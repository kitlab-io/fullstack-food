#!/usr/bin/env bash
# Prepare a fresh Debian-based single-board computer to run the hub.
# Targets: Raspberry Pi OS (Bookworm, 64-bit) and Armbian (Bookworm) on an Orange Pi Zero 2W.
#
#   sudo ./provision.sh --hostname growhub --timezone Europe/Berlin
#
# It installs Docker, creates the `fsf` user, sets the hostname and timezone, and enables
# mDNS so the hub answers at <hostname>.local. It does not touch I2C, 1-Wire or GPIO:
# sensors wired to the hub itself are not supported yet.
#
# NOT YET RUN ON EITHER TARGET. Read it before you run it.
set -euo pipefail

HOSTNAME_WANTED=""
TIMEZONE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --hostname) HOSTNAME_WANTED="$2"; shift 2 ;;
    --timezone) TIMEZONE="$2"; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

if [ "$(id -u)" -ne 0 ]; then
  echo "run this with sudo" >&2
  exit 1
fi
if ! grep -qi 'bookworm' /etc/os-release; then
  echo "this script expects Debian Bookworm (Raspberry Pi OS or Armbian); found:" >&2
  grep PRETTY_NAME /etc/os-release >&2
  exit 1
fi

echo "== packages"
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl git avahi-daemon

echo "== docker"
if ! command -v docker >/dev/null 2>&1; then
  # Docker's own convenience script; it adds Docker's apt repository for this distribution.
  curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
  sh /tmp/get-docker.sh
  rm -f /tmp/get-docker.sh
fi
docker compose version >/dev/null 2>&1 || { echo "docker compose plugin is missing after install" >&2; exit 1; }
systemctl enable --now docker

echo "== user"
if ! id fsf >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash fsf
fi
usermod -aG docker fsf

if [ -n "$HOSTNAME_WANTED" ]; then
  echo "== hostname $HOSTNAME_WANTED"
  hostnamectl set-hostname "$HOSTNAME_WANTED"
  if grep -q '^127\.0\.1\.1' /etc/hosts; then
    sed -i "s/^127\.0\.1\.1.*/127.0.1.1\t$HOSTNAME_WANTED/" /etc/hosts
  else
    printf '127.0.1.1\t%s\n' "$HOSTNAME_WANTED" >> /etc/hosts
  fi
fi
systemctl enable --now avahi-daemon

if [ -n "$TIMEZONE" ]; then
  echo "== timezone $TIMEZONE"
  timedatectl set-timezone "$TIMEZONE"
fi
timedatectl set-ntp true || true

cat <<EOF

Done. Next, as the fsf user:

  sudo -iu fsf
  git clone <this repository> fullstack-food && cd fullstack-food
  pip install --user -e .                     # for the fsf command line, or use: docker compose run --rm hub fsf ...
  fsf init my-site --from sites/examples/houseplants
  # edit sites/local/my-site/site.yaml and secrets.yaml, set the dashboard password hash in web.env
  FSF_SITE=my-site docker compose -f deploy/compose/base.yaml -f deploy/compose/sbc.yaml up -d --build
  fsf doctor --site sites/local/my-site

The hub will answer at http://$(hostname).local:8080 on the local network.
EOF
