# Cloudflare Tunnel deployment

Zero-trust ingress: the container sits behind a Cloudflare Tunnel and
needs **no inbound ports** open on the host. Public TLS is terminated
at the Cloudflare edge; the tunnel carries the request to the
container over an outbound mTLS connection.

## One-time setup

1. **Create the tunnel** in your Cloudflare dashboard
   (Zero Trust → Networks → Tunnels → Create tunnel):
   - Name it `get-installer`.
   - Copy the **token** Cloudflare shows you.
2. **Add a public-hostname route** on the tunnel pointing to
   `http://get:80` (the `get` service name inside our docker network):
   - Subdomain: `get`
   - Domain: `simtabi.com` (or your domain)
   - Service: `HTTP` → `get:80`
3. **Save**: Cloudflare auto-provisions DNS + the TLS cert.

## `.env` entry

```bash
CLOUDFLARE_TUNNEL_TOKEN=<the long token Cloudflare gave you>
```

## Bring up the stack

```bash
docker compose --profile tunnel up -d
```

The `cloudflared` sidecar in `docker-compose.yml` reads the token,
connects out to Cloudflare, and starts routing.

## Verifying

```bash
curl -fsSL https://get.simtabi.com/install.sh | head -1
```

Should return the script's shebang line. From inside the host:

```bash
docker compose logs --tail=20 cloudflared
docker compose logs --tail=20 get
```

## Why this is the recommended ingress

- No firewall rules to maintain.
- No port-forwarding through home / corporate NAT.
- TLS terminated and DDoS-filtered at Cloudflare's edge.
- The `User-Agent`-parity guarantee (see `docs/security.md`) is easier
  to verify because the edge serves identical bytes: Cloudflare's
  cache doesn't vary on UA by default.
- The token can be rotated from the dashboard without touching the
  host.

## Rotating the token

1. In the Cloudflare dashboard, generate a new connector token on the
   same tunnel.
2. Update `CLOUDFLARE_TUNNEL_TOKEN` in `.env`.
3. `docker compose up -d cloudflared` (re-pulls + reconnects).
4. Revoke the old token after the new connection is healthy.
