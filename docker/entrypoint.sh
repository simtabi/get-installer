#!/usr/bin/env bash
# Entrypoint: LinuxServer.io-style PUID/PGID handling.
#
# Why this exists: on Linux, file ownership inside a container is just
# numeric (UID/GID), so a container that writes as UID 33 (www-data)
# produces files unreadable by the host's UID 1000 user, and vice
# versa. This script adjusts the in-container "installer" user's
# numeric IDs at start time so they match the host, then drops
# privileges via gosu before exec'ing the real CMD.
#
# Environment variables (runtime):
#   PUID    -- numeric UID for the installer user. Default 1000.
#   PGID    -- numeric GID for the installer group. Default 1000.
#   CHOWN_PATHS -- colon-separated list of paths to chown to PUID:PGID
#                  before dropping privileges. Default: empty.
#
# If PUID == 0 or PGID == 0, the script refuses to "drop" to root
# (that's a no-op pretending to be a safety feature). To intentionally
# run as root, pass `--user 0:0` to docker run and skip this script.
#
# Usage in Dockerfile:
#   COPY docker/entrypoint.sh /usr/local/bin/entrypoint
#   RUN chmod +x /usr/local/bin/entrypoint
#   ENTRYPOINT ["/usr/local/bin/entrypoint"]
#   CMD ["supervisord", "-c", "/etc/supervisor/supervisord.conf"]

set -euo pipefail

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

# Refuse to assist root-spoofing. If the caller really wants root,
# they can `docker run --user 0:0 --entrypoint <cmd>`.
if [ "$PUID" = "0" ] || [ "$PGID" = "0" ]; then
    echo "entrypoint: refusing PUID=0 / PGID=0 (running as root is fine; bypass this entrypoint instead)" >&2
    exit 1
fi

# Adjust the installer group/user numerically. -o allows duplicate
# IDs (so if PUID happens to match an existing user like www-data,
# we don't conflict).
if [ "$(id -g installer 2>/dev/null || echo "")" != "$PGID" ]; then
    groupmod -o -g "$PGID" installer
fi
if [ "$(id -u installer 2>/dev/null || echo "")" != "$PUID" ]; then
    usermod -o -u "$PUID" installer
fi

# Optionally chown a list of paths before dropping privileges. This
# is the "self-heal" step that fixes the classic mounted-volume
# ownership mismatch.
if [ -n "${CHOWN_PATHS:-}" ]; then
    IFS=':'
    for p in $CHOWN_PATHS; do
        if [ -e "$p" ]; then
            chown -R installer:installer "$p" || \
                echo "entrypoint: warning: chown $p failed (read-only mount?)" >&2
        fi
    done
    unset IFS
fi

# If no command was passed, default to a shell so users can debug.
if [ "$#" -eq 0 ]; then
    set -- /bin/bash
fi

# Drop privileges and exec the real command. We use gosu (small,
# well-audited) over su or sudo because it doesn't fork an extra
# process and forwards signals correctly.
exec gosu installer "$@"
