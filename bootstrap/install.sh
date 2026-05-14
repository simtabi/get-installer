#!/usr/bin/env sh
# Simtabi installer — POSIX bootstrap (sh-compatible, runs on bash/dash/zsh).
#
# Usage (one-liner):
#   sh -c "$(curl -fsSL https://get.simtabi.com/install.sh)"
#
# Or with flags:
#   curl -fsSL https://get.simtabi.com/install.sh \
#     | sh -s -- --product claude-configurator --version 0.2.0 --yes
#
# Everything happens via Python — this shell layer only:
#   1. Verifies Python >= 3.10 is on PATH.
#   2. Downloads installer.py + registry.json into a private temp dir.
#   3. Verifies the SHA256 of installer.py against INSTALLER_SHA256 below.
#   4. Hands off to ``python3 installer.py``, passing through CLI args.

set -eu

VERSION="1.0.0"; export VERSION
# Surface in any error / debug log even if not directly referenced below.

# ----- defaults ------------------------------------------------------------ #
INSTALLER_BASE_URL="${INSTALLER_BASE_URL:-https://get.simtabi.com}"
INSTALLER_SHA256="${INSTALLER_SHA256:-}"          # set to pin a specific installer.py
REGISTRY_URL="${REGISTRY_URL:-${INSTALLER_BASE_URL}/registry.json}"
INSTALLER_URL="${INSTALLER_URL:-${INSTALLER_BASE_URL}/installer.py}"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=10

# ----- output ------------------------------------------------------------- #
say()  { printf '%s\n' "$*"; }
info() { printf '\033[36m[info]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[warn]\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[31m[fail]\033[0m %s\n' "$*" >&2; exit 1; }

# Disable colour if not a tty
if [ ! -t 1 ]; then
  info() { printf '[info] %s\n' "$*"; }
  warn() { printf '[warn] %s\n' "$*" >&2; }
  fail() { printf '[fail] %s\n' "$*" >&2; exit 1; }
fi

# ----- safety -------------------------------------------------------------- #
if [ "$(id -u)" = "0" ]; then
  case " $* " in
    *" --allow-root "*) : ;;
    *) fail "refusing to run as root. Pass --allow-root if you really mean it." ;;
  esac
fi

# Don't execute under unfamiliar shells silently
if [ -z "${SHELL_OK:-}" ]; then
  case "$0" in
    -*|sh|/bin/sh|*/sh|bash|/bin/bash|*/bash|zsh|/bin/zsh|*/zsh|dash|/bin/dash|*/dash) : ;;
    *) info "running under $0" ;;
  esac
fi

# ----- find Python --------------------------------------------------------- #
find_python() {
  for cand in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then
      ver=$("$cand" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || echo "0.0")
      maj=$(printf '%s' "$ver" | cut -d. -f1)
      min=$(printf '%s' "$ver" | cut -d. -f2)
      if [ "$maj" -ge "$MIN_PYTHON_MAJOR" ] 2>/dev/null \
         && { [ "$maj" -gt "$MIN_PYTHON_MAJOR" ] || [ "$min" -ge "$MIN_PYTHON_MINOR" ]; }; then
        PYTHON_BIN="$cand"
        PYTHON_VERSION="$ver"
        return 0
      fi
    fi
  done
  return 1
}

if ! find_python; then
  fail "Python ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+ not found on PATH.
       Install Python first (https://www.python.org/downloads/) or via your
       package manager, then re-run this installer.
       (If you have uv installed, you can also pass --with-python so the
       Python-side installer bootstraps a userspace Python.)"
fi
info "Python ${PYTHON_VERSION} at $(command -v "$PYTHON_BIN")"

# ----- find a downloader --------------------------------------------------- #
# By default, curl restricts to HTTPS + TLS 1.2+. The
# ``INSTALLER_PROTO_OVERRIDE`` env var exists ONLY for the test suite,
# which serves the artefacts from a local HTTP server. Setting this in
# production removes the security guarantee — don't.
PROTO_OVERRIDE="${INSTALLER_PROTO_OVERRIDE:-}"
if [ -n "$PROTO_OVERRIDE" ]; then
  warn "INSTALLER_PROTO_OVERRIDE set — bypassing HTTPS-only guard (test-mode)"
fi

if command -v curl >/dev/null 2>&1; then
  if [ -n "$PROTO_OVERRIDE" ]; then
    DL="curl -fsSL --proto $PROTO_OVERRIDE --max-time 30 -o"
  else
    DL="curl -fsSL --proto =https --tlsv1.2 --max-time 30 -o"
  fi
elif command -v wget >/dev/null 2>&1; then
  DL="wget -q -O"
else
  fail "neither curl nor wget on PATH; one is required."
fi

# ----- private temp dir ---------------------------------------------------- #
umask 077
TMP="$(mktemp -d 2>/dev/null || mktemp -d -t simtabi-installer)" || fail "mktemp failed"
trap 'rm -rf "$TMP"' EXIT INT TERM
chmod 700 "$TMP"

# ----- download core + registry ------------------------------------------- #
info "downloading installer.py + registry.json"
$DL "$TMP/installer.py" "$INSTALLER_URL"   || fail "download installer.py failed ($INSTALLER_URL)"
$DL "$TMP/registry.json" "$REGISTRY_URL"   || fail "download registry.json failed ($REGISTRY_URL)"
chmod 600 "$TMP/installer.py" "$TMP/registry.json"

# ----- verify checksum (if pinned) ---------------------------------------- #
if [ -n "$INSTALLER_SHA256" ]; then
  if command -v sha256sum >/dev/null 2>&1; then
    actual=$(sha256sum "$TMP/installer.py" | awk '{print $1}')
  elif command -v shasum >/dev/null 2>&1; then
    actual=$(shasum -a 256 "$TMP/installer.py" | awk '{print $1}')
  else
    fail "neither sha256sum nor shasum available; cannot verify INSTALLER_SHA256"
  fi
  if [ "$actual" != "$INSTALLER_SHA256" ]; then
    fail "sha256 mismatch: expected $INSTALLER_SHA256, got $actual"
  fi
  info "installer.py sha256 verified"
else
  warn "no INSTALLER_SHA256 pin — proceeding without integrity check"
fi

# ----- execute ------------------------------------------------------------- #
info "handing off to installer.py"
"$PYTHON_BIN" "$TMP/installer.py" --registry "$TMP/registry.json" "$@"
