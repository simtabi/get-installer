# VPS deployment

The "I have one $5 VPS" path. Single Ubuntu 26.04 (or 24.04) host,
Docker, Cloudflare Tunnel for ingress. Setup in ~10 minutes.

## Provision

1. Boot a fresh Ubuntu 26.04 LTS droplet / instance (1 vCPU / 1 GB RAM
   is enough for the static channel; bump to 2 GB if you also run the
   API container in Phase M).
2. SSH in as a non-root user with passwordless sudo.

## Install Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker
```

## Clone + configure

```bash
git clone https://github.com/simtabi/get-installer.git
cd get-installer

cp .env.example .env
# Edit .env — set PG_PASSWORD, GET_INSTALLER_TOKEN_SECRET,
# CLOUDFLARE_TUNNEL_TOKEN

python3 scripts/bundle.py             # builds dist/installer.py
```

## Bring up

```bash
# Static-only (no DB / API):
docker compose up -d get

# Static + Cloudflare Tunnel:
docker compose --profile tunnel up -d

# Full stack (static + DB; the API service ships in Phase M):
docker compose up -d
```

## Verify

```bash
curl -fsS http://localhost:8080/healthz       # local
curl -fsSL https://get.simtabi.com/install.sh | head -1   # public, via CF tunnel
```

## Upgrades

```bash
git pull
python3 scripts/bundle.py
docker compose pull
docker compose up -d --build
```

## Operational notes

- **Logs**: `docker compose logs -f get` for nginx, ditto for
  `cloudflared`. The container streams everything to stdout/stderr —
  no log files to rotate inside.
- **Backups**: only `postgres` carries state. `docker compose exec
  postgres pg_dump -U $PG_USER $PG_DB > backup.sql` on a cron.
- **Monitoring**: the `healthz` endpoint + the `HEALTHCHECK` directive
  in the Dockerfile mean `docker compose ps` already shows green/red.
  For external monitoring, point UptimeRobot / Better Stack at
  `https://get.<domain>/healthz`.
- **Resource limits**: add `deploy.resources.limits.memory` /
  `cpus` to each service in `docker-compose.prod.yml` if you're sharing
  the box with other workloads.

## When to outgrow this

A single $5 VPS handles ~1k installs/day without breaking a sweat,
because the workload is "serve static bytes". When you exceed that,
or need multi-region, switch to the AWS deployment in
[`deploy/aws.md`](aws.md).
