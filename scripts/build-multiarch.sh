#!/usr/bin/env bash
# Build the get-installer container for both linux/amd64 and linux/arm64.
#
# Requirements:
#   - Docker Desktop 4+ OR docker-ce with buildx plugin
#   - QEMU emulation registered (one-time): `docker run --privileged --rm \
#       tonistiigi/binfmt --install all`
#
# Usage:
#   ./scripts/build-multiarch.sh                # build for host arch + load
#   ./scripts/build-multiarch.sh --push         # build both arches + push
#   IMAGE=ghcr.io/myorg/get-installer ./scripts/build-multiarch.sh

set -euo pipefail

IMAGE="${IMAGE:-simtabi/get-installer}"
TAG="${TAG:-dev}"
PLATFORMS="${PLATFORMS:-linux/amd64,linux/arm64}"

PUSH=0
LOAD=1
case "${1:-}" in
    --push) PUSH=1; LOAD=0 ;;
    --load) PUSH=0; LOAD=1 ;;
    "") ;;
    *) echo "unknown flag: $1" >&2; exit 1 ;;
esac

# Bundle must be built before the image is built. Idempotent.
if [ -f scripts/bundle.py ]; then
    python3 scripts/bundle.py
fi

# Set up the buildx builder if it doesn't exist
if ! docker buildx inspect get-installer-builder >/dev/null 2>&1; then
    docker buildx create --name get-installer-builder --driver docker-container --use
else
    docker buildx use get-installer-builder
fi

if [ "$PUSH" = 1 ]; then
    echo "==> Building + pushing $IMAGE:$TAG for $PLATFORMS"
    docker buildx build \
        --platform "$PLATFORMS" \
        --tag "$IMAGE:$TAG" \
        --push \
        .
else
    if [ "$LOAD" = 1 ]; then
        # `--load` exports a single-platform image. Detect host arch.
        host_arch="$(uname -m)"
        case "$host_arch" in
            x86_64|amd64) host_platform=linux/amd64 ;;
            aarch64|arm64) host_platform=linux/arm64 ;;
            *) echo "unknown host arch: $host_arch" >&2; exit 1 ;;
        esac
        echo "==> Building $IMAGE:$TAG for $host_platform (host) and loading"
        docker buildx build \
            --platform "$host_platform" \
            --tag "$IMAGE:$TAG" \
            --load \
            .
        echo "  Note: --push or running on each arch will exercise both arches."
    else
        echo "==> Building $IMAGE:$TAG for $PLATFORMS (no load, no push)"
        docker buildx build \
            --platform "$PLATFORMS" \
            --tag "$IMAGE:$TAG" \
            .
    fi
fi

echo
echo "Smoke-check: docker run --rm $IMAGE:$TAG curl -fsS http://127.0.0.1/healthz"
