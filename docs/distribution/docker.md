# Docker distribution

`get-installer` ships a static-content container that serves
`install.sh`, `install.ps1`, `installer.py`, and `registry.json` over
HTTP, suitable for fronting with a CDN. This page covers:

- Build + run on macOS / Windows (no UID/GID issue)
- Build + run on Linux (the classic UID/GID issue and the
  PUID/PGID convention that fixes it)
- The `entrypoint.sh` privilege-drop pattern
- Common failure modes + diagnostics

## Why Linux needs special handling

Docker on macOS and Windows uses a Linux VM (Docker Desktop) that
translates file ownership between the host filesystem and the
container's view. Files written by container UID 0 (root) appear in
the host filesystem owned by your host user. The translation is
implicit; users almost never hit ownership issues there.

On **Linux**, the kernel is shared between host and container.
Numeric UIDs are the only currency. Files written inside the
container by UID 0 appear on the host as owned by UID 0 (root).
Files written by UID 33 (the conventional `www-data`) appear as
owned by UID 33. Your host user is typically UID 1000.

Two common failure modes:

1. **"Permission denied" when mounted volume is read by container.**
   Host file owned by 1000:1000 with mode 0640. Container's nginx
   runs as UID 33 (`www-data`). The "group" octet doesn't grant
   read to `www-data`. nginx returns 403.

2. **"Cannot edit file" after container writes to mounted volume.**
   Container writes as UID 0. Host file is now owned by root.
   Host user (UID 1000) gets `EACCES` on next `vim`.

The LinuxServer.io community settled on a convention for this:
ship images that accept `PUID` and `PGID` env vars and re-number an
in-container "app" user to match at start time. We adopt the same
convention.

## Quick reference

| Scenario | Run command |
|---|---|
| macOS / Windows desktop dev | `docker compose up` (defaults are fine) |
| Linux dev, host user is 1000:1000 | `docker compose up` (defaults match) |
| Linux dev, host user is *not* 1000:1000 | `PUID=$(id -u) PGID=$(id -g) docker compose up --build` |
| CI: per-job user | `docker run -e PUID=$UID -e PGID=$GID ...` |
| Air-gapped: prove no root execution | `docker run --user 1000:1000 --entrypoint /usr/local/bin/entrypoint ...` |

## Build args

The `Dockerfile` declares:

```dockerfile
ARG PUID=1000
ARG PGID=1000

RUN groupadd -g "$PGID" installer \
 && useradd -m -u "$PUID" -g "$PGID" -s /bin/bash installer
```

These are **build-time** defaults. The resulting image has an
`installer:installer` user at the configured numeric IDs. Override
per-build with:

```bash
docker buildx build \
  --build-arg PUID=$(id -u) \
  --build-arg PGID=$(id -g) \
  -t my/get-installer:dev .
```

Or via `docker-compose.yml::build.args` (already wired to read
`PUID` / `PGID` from your `.env`).

## Runtime env vars

The entrypoint (`docker/entrypoint.sh`) re-numbers the `installer`
user on start. This is the per-run override that doesn't need a
rebuild:

| Env var | Default | Purpose |
|---|---|---|
| `PUID` | `1000` | Numeric UID for the `installer` user. |
| `PGID` | `1000` | Numeric GID for the `installer` group. |
| `CHOWN_PATHS` | (empty) | Colon-separated paths the entrypoint chowns to `PUID:PGID` before exec. Use when mounting writable host volumes. |

The entrypoint refuses `PUID=0` / `PGID=0` because that would be
running as root (use `docker run --user 0:0 --entrypoint <cmd>` to
opt in explicitly).

## How privileges drop

The default `CMD` is `tini -> supervisord` running as root. This is
required to bind port 80 inside the container and to fork nginx
under the `www-data` user (per `deploy/nginx.conf`).

For a fully-non-root container, override the entrypoint:

```bash
docker run \
  --user $(id -u):$(id -g) \
  --entrypoint /usr/local/bin/entrypoint \
  -e PUID=$(id -u) -e PGID=$(id -g) \
  simtabi/get-installer:dev \
  <your-non-port-80-command>
```

This drops privileges via `gosu` and exec's whatever command you
pass, with the container's filesystem visible at `installer`'s UID.

## Diagnosing "Permission denied"

Order of checks:

1. **Is the file present in the mounted volume on the host?**
   ```bash
   ls -la ./<mounted-path>
   ```

2. **What UID/GID does the container see?**
   ```bash
   docker compose exec get id
   docker compose exec get ls -la /srv/www | head
   ```

3. **What user is nginx actually running as inside the container?**
   ```bash
   docker compose exec get ps -eo user,pid,cmd | grep nginx
   ```

4. **If the file's host UID/GID doesn't match the container's
   `installer` user, restart with matching `PUID`/`PGID`:**
   ```bash
   echo "PUID=$(id -u)" >> .env
   echo "PGID=$(id -g)" >> .env
   docker compose down && docker compose up --build
   ```

5. **If the issue is a read-only mount + restrictive host modes,
   widen on the host:**
   ```bash
   chmod -R a+rX ./<mounted-path>
   ```

## Common pitfalls

- **Forgetting `--build` after changing `PUID` / `PGID`.** Build
  args only take effect during `docker build`. Runtime env vars
  cover most of the gap, but new file creates by the entrypoint
  use the build-time UID. Run with `docker compose up --build`
  after changing the args.

- **CHOWN_PATHS that traverse symlinks.** `chown -R` follows
  symlinks by default. If a mounted volume contains a symlink to a
  host path you didn't intend to chown, you'll surprise yourself.
  Mitigate: don't symlink across volume boundaries.

- **Read-only filesystems.** If `chown` fails because the mount is
  read-only, the entrypoint emits a warning to stderr and
  continues; nginx still serves whatever is readable.

- **WSL2 inside Windows.** WSL2 is a Linux kernel; the same UID/GID
  rules apply. Use the Linux PUID/PGID flow, not the macOS one.

## See also

- [`../../Dockerfile`](../../Dockerfile)
- [`../../docker/entrypoint.sh`](../../docker/entrypoint.sh)
- [`../../docker-compose.yml`](../../docker-compose.yml)
- [LinuxServer.io PUID/PGID convention](https://docs.linuxserver.io/general/understanding-puid-and-pgid)
