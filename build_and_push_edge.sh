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

docker buildx build --platform linux/arm64/v8 \
                    --tag ${EDGE_IP}:5000/${IMAGE_NAME}:${IMAGE_TAG} \
                    --push .
