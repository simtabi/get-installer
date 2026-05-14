# Local `*.test` development domain

For testing the bootstrap one-liner against a local container instead
of `get.simtabi.com`. Pairs with `mkcert` for trusted local TLS.

## Setup

### 1. Install dnsmasq + mkcert

macOS (Homebrew):
```bash
brew install dnsmasq mkcert
mkcert -install
```

Ubuntu:
```bash
sudo apt-get install -y dnsmasq libnss3-tools
curl -fsSL https://github.com/FiloSottile/mkcert/releases/latest/download/mkcert-v1.4.4-linux-amd64 \
    -o /tmp/mkcert
sudo install /tmp/mkcert /usr/local/bin/mkcert
mkcert -install
```

### 2. Point `*.test` at localhost via dnsmasq

```bash
# macOS
echo 'address=/.test/127.0.0.1' | sudo tee -a /usr/local/etc/dnsmasq.conf
sudo brew services restart dnsmasq
echo 'nameserver 127.0.0.1' | sudo tee /etc/resolver/test

# Linux
echo 'address=/.test/127.0.0.1' | sudo tee /etc/dnsmasq.d/test.conf
sudo systemctl restart dnsmasq
```

### 3. Generate a local TLS cert for `get.test`

```bash
mkdir -p deploy/certs
mkcert -cert-file deploy/certs/get.test.pem -key-file deploy/certs/get.test-key.pem 'get.test' '*.get.test'
```

### 4. Add a TLS-terminating reverse proxy locally

Cheapest option: Caddy in front of the container.

```yaml
# docker-compose.override.yml — gitignored
services:
  caddy:
    image: caddy:2
    container_name: get-installer-caddy
    restart: unless-stopped
    ports:
      - "443:443"
    volumes:
      - ./deploy/certs:/etc/caddy/certs:ro
      - ./deploy/Caddyfile:/etc/caddy/Caddyfile:ro
    networks:
      - getnet
    depends_on:
      - get
```

```caddy
# deploy/Caddyfile
get.test {
    tls /etc/caddy/certs/get.test.pem /etc/caddy/certs/get.test-key.pem
    reverse_proxy get:80
}
```

### 5. Test

```bash
docker compose up -d
curl -fsSL https://get.test/install.sh | head -1
```

## When to use this

- Smoke-testing the bootstrap launchers + signed-bundle pipeline end-to-end.
- Demoing to a customer without exposing the dev tunnel.
- Reproducing a "behind the corporate DNS" test scenario.

## Tear-down

```bash
docker compose down
# Optional: rm the mkcert root from your system trust store
mkcert -uninstall
```
