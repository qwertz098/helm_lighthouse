#!/bin/bash
set -e -x

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
