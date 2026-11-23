"""Revisions of one site: saved, validated states that can be compared and restored.

    sites/local/<site>/
        site.yaml, library/         the working files (a draft while they differ from a revision)
        revisions/0001/             site.yaml, library/..., manifest.json
        revisions/applied           the number of the revision the hub is running

A revision holds the site file and the site's own library, nothing else: never secrets,
logins or broker files. A revision is only saved if it validates, so anything in the store
can be handed to a hub. Applying one to a running hub is a later phase; this module keeps
the record that applying will need (which revision is applied, and what each was based on).
"""

from __future__ import annotations

import difflib
import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fsf_core import Catalog, ConfigError, load_site

TRACKED = ("site.yaml", "library")      # everything else in the site folder is left alone


class RevisionError(Exception):
    pass


@dataclass
class Revision:
    number: int
    parent: int | None
    created: str
    by: str
    message: str
    files: dict[str, str]           # relative path -> sha256
    warnings: list[str]

    @property
    def name(self) -> str:
        return f"{self.number:04d}"


def _files(folder: Path) -> dict[str, Path]:
    """Tracked files below a folder, by relative path with forward slashes."""
    found: dict[str, Path] = {}
    site_file = folder / "site.yaml"
    if site_file.is_file():
        found["site.yaml"] = site_file
    library = folder / "library"
    if library.is_dir():
        for path in sorted(library.rglob("*.yaml")):
            found[path.relative_to(folder).as_posix()] = path
    return found


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RevisionStore:
    def __init__(self, site_dir: Path, catalog: Catalog):
        self.site_dir, self.catalog = Path(site_dir), catalog
        self.root = self.site_dir / "revisions"

    # ------------------------------------------------------------------ reading

    def list(self) -> list[Revision]:
        if not self.root.is_dir():
            return []
        out = []
        for folder in sorted(p for p in self.root.iterdir() if p.is_dir() and p.name.isdigit()):
            data = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            out.append(Revision(**data))
        return out

    def get(self, number: int) -> Revision:
        for revision in self.list():
            if revision.number == number:
                return revision
        raise RevisionError(f"there is no revision {number}")

    def latest(self) -> Revision | None:
        revisions = self.list()
        return revisions[-1] if revisions else None

    def applied(self) -> int | None:
        marker = self.root / "applied"
        return int(marker.read_text(encoding="utf-8").strip()) if marker.exists() else None

    def _folder(self, number: int) -> Path:
        return self.root / f"{number:04d}"

    def changed(self) -> list[str]:
        """Working files that differ from the latest revision: this is what makes the folder a draft."""
        latest = self.latest()
        saved = latest.files if latest else {}
        working = {name: _digest(path) for name, path in _files(self.site_dir).items()}
        return sorted(name for name in set(saved) | set(working) if saved.get(name) != working.get(name))

    # ------------------------------------------------------------------ writing

    def validate(self) -> list[str]:
        """Load the working files exactly as a hub would. Returns warnings; raises ConfigError with every problem."""
        return load_site(self.site_dir, self.catalog).warnings

    def save(self, by: str, message: str, based_on: int | None = None, now: datetime | None = None) -> Revision:
        """Snapshot the working files as the next revision.

        based_on: the revision the editor started from. If someone else saved in between,
        the save is refused instead of silently overwriting their work.
        """
        latest = self.latest()
        head = latest.number if latest else None
        if based_on is not None and based_on != head:
            raise RevisionError(f"this draft was based on revision {based_on}, but the newest is {head}; "
                                "take the newest revision and redo the change")
        if latest and not self.changed():
            raise RevisionError(f"nothing has changed since revision {latest.number}")
        try:
            warnings = self.validate()
        except ConfigError as err:
            raise RevisionError("the draft does not validate, so it was not saved:\n  " + "\n  ".join(err.problems)) from None
        number = (head or 0) + 1
        folder = self._folder(number)
        folder.mkdir(parents=True)
        files = {}
        for name, path in _files(self.site_dir).items():
            target = folder / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            files[name] = _digest(path)
        revision = Revision(number=number, parent=head, created=(now or datetime.now(timezone.utc)).isoformat(),
                            by=by, message=message, files=files, warnings=warnings)
        (folder / "manifest.json").write_text(json.dumps(revision.__dict__, indent=1) + "\n", encoding="utf-8", newline="\n")
        return revision

    def restore(self, number: int) -> list[str]:
        """Make the working files equal to a revision. Returns what changed. Nothing outside TRACKED is touched."""
        revision = self.get(number)
        before = _files(self.site_dir)
        source = self._folder(number)
        changed = []
        for name in sorted(set(before) | set(revision.files)):
            target = self.site_dir / name
            if name not in revision.files:
                target.unlink()
                changed.append(name)
            elif name not in before or _digest(target) != revision.files[name]:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / name, target)
                changed.append(name)
        return changed

    def mark_applied(self, number: int) -> None:
        self.get(number)
        (self.root / "applied").write_text(f"{number}\n", encoding="utf-8", newline="\n")

    # ------------------------------------------------------------------ comparing

    def diff(self, old: int | None, new: int | None = None) -> list[dict]:
        """File by file, what differs between two revisions (None for `new` means the working files)."""
        def read(number: int | None) -> dict[str, str]:
            folder = self.site_dir if number is None else self._folder(self.get(number).number)
            return {name: path.read_text(encoding="utf-8") for name, path in _files(folder).items()}

        before = read(old) if old is not None else {}
        after = read(new)
        out = []
        for name in sorted(set(before) | set(after)):
            a, b = before.get(name), after.get(name)
            if a == b:
                continue
            change = "added" if a is None else "removed" if b is None else "changed"
            lines = difflib.unified_diff((a or "").splitlines(), (b or "").splitlines(), lineterm="", n=2,
                                         fromfile=f"{name} (revision {old})" if old else name,
                                         tofile=f"{name} (revision {new})" if new else f"{name} (draft)")
            out.append({"file": name, "change": change, "diff": "\n".join(lines)})
        return out
