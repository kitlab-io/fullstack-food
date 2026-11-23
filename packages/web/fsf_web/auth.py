"""Shared logins for the dashboard: one password per role, not per person.

    viewer     reads the dashboard
    operator   also acts: advance, water, pause, override, test pulse
    admin      also changes the site itself (the studio)

A password is never stored: the service is given a salted scrypt hash per role, made with

    python -m fsf_web hash-password

and kept in the environment (FSF_WEB_PASSWORD_HASH for the operator, and
FSF_WEB_VIEWER_PASSWORD_HASH and FSF_WEB_ADMIN_PASSWORD_HASH) or a gitignored file. A role
without a hash cannot be logged in to. A session is a random token in an HttpOnly,
SameSite=Strict cookie; every state-changing request must also carry the session's CSRF
token in a header.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from typing import Callable

COOKIE = "fsf_session"
SESSION_S = 12 * 3600
MAX_FAILURES = 5
LOCKOUT_S = 60
N, R, P = 2 ** 14, 8, 1
ROLES = ("viewer", "operator", "admin")     # each includes the ones before it


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=N, r=R, p=P, dklen=32)
    return ":".join(["scrypt", str(N), str(R), str(P), base64.urlsafe_b64encode(salt).decode(),
                     base64.urlsafe_b64encode(digest).decode()])


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split(":")
        if scheme != "scrypt":
            return False
        expected = base64.urlsafe_b64decode(digest)
        got = hashlib.scrypt(password.encode(), salt=base64.urlsafe_b64decode(salt), n=int(n), r=int(r), p=int(p),
                             dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, expected)


class LoginError(Exception):
    pass


class Auth:
    """Who may read and who may act.

    no_login: no authentication at all, for the mock stack on a port published on this
    machine only. read_without_login: pages can be read by anyone who can reach the
    service; actions still need the login.
    """

    def __init__(self, password_hash: str | None = None, read_without_login: bool = False, no_login: bool = False,
                 clock: Callable[[], float] = time.monotonic, viewer_hash: str | None = None, admin_hash: str | None = None):
        """password_hash is the operator's."""
        self.hashes = {role: value for role, value in (("viewer", viewer_hash), ("operator", password_hash), ("admin", admin_hash))
                       if value}
        self.read_without_login, self.no_login, self._clock = read_without_login, no_login, clock
        self._sessions: dict[str, dict] = {}
        self._failures = 0
        self._locked_until = 0.0

    def login(self, password: str, name: str | None) -> tuple[str, dict]:
        now = self._clock()
        if not self.hashes:
            raise LoginError("no password is configured; set FSF_WEB_PASSWORD_HASH (python -m fsf_web hash-password)")
        if now < self._locked_until:
            raise LoginError(f"too many wrong passwords; try again in {int(self._locked_until - now) + 1} s")
        # Every hash is checked every time, so the answer takes as long whichever role matches.
        matches = [role for role in ROLES if role in self.hashes and verify_password(password, self.hashes[role])]
        if not matches:
            self._failures += 1
            if self._failures >= MAX_FAILURES:
                self._failures, self._locked_until = 0, now + LOCKOUT_S
            raise LoginError("wrong password")
        self._failures = 0
        token = secrets.token_urlsafe(32)
        clean = "".join(ch for ch in (name or "").strip() if ch.isprintable())[:40]
        self._sessions[token] = {"name": clean or "someone", "csrf": secrets.token_urlsafe(24), "expires": now + SESSION_S,
                                 "role": matches[-1]}
        return token, self._sessions[token]

    def session(self, token: str | None) -> dict | None:
        found = self._sessions.get(token or "")
        if found and self._clock() >= found["expires"]:
            del self._sessions[token]
            return None
        return found

    def logout(self, token: str | None) -> None:
        self._sessions.pop(token or "", None)

    def role(self, session: dict | None) -> str | None:
        """The visitor's role. Without any login configured to be needed, everyone is an admin (the mock stack)."""
        if self.no_login:
            return "admin"
        if session is not None:
            return session["role"]
        return "viewer" if self.read_without_login else None

    def allows(self, session: dict | None, needed: str) -> bool:
        role = self.role(session)
        return role is not None and ROLES.index(role) >= ROLES.index(needed)

    def describe(self, session: dict | None) -> dict:
        """What the frontend needs to know about this visitor."""
        return {"login_required": not self.no_login, "authenticated": session is not None, "role": self.role(session),
                "can_read": self.allows(session, "viewer"), "can_act": self.allows(session, "operator"),
                "can_admin": self.allows(session, "admin"),
                "name": session["name"] if session else None, "csrf": session["csrf"] if session else None,
                "password_configured": bool(self.hashes)}
