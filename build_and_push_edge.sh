#!/bin/bash
set -e -x

cd "$(dirname "$0")"

# Aktuelle Version aus Git holen (Abbruch bei Fehler, damit nichts Veraltetes gebaut wird).
# Danach Neustart, weil bash die laufende Datei stueckweise liest und das Update sie veraendert haben kann.
if [ -z "$HELM_PULLED" ] && [ -d .git ] && command -v git >/dev/null 2>&1; then
  git pull --ff-only
  HELM_PULLED=1 exec bash "$(basename "$0")" "$@"
fi

EDGE_IP="${EDGE_IP:-192.168.140.1}"
IMAGE_NAME="${IMAGE_NAME:-helm}"
IMAGE_TAG="${IMAGE_TAG:-latest}"

docker buildx inspect secure-edge-pro >/dev/null 2>&1 || \
  docker buildx create --name secure-edge-pro \
                        --config buildkitd-secure-edge-pro.toml

docker buildx use secure-edge-pro

# Release shown on the settings page, e.g. v1.0.0 or v1.0.0-3-gabc1234
APP_RELEASE="$(git describe --tags --always --dirty 2>/dev/null || echo dev)"

docker buildx build --platform linux/arm64/v8 \
                    --build-arg APP_RELEASE="${APP_RELEASE}" \
                    --tag ${EDGE_IP}:5000/${IMAGE_NAME}:${IMAGE_TAG} \
                    --push .
