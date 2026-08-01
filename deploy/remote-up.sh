#!/usr/bin/env bash
# 在服务器 /opt/photorestore：镜像加速 → pull → up（GitHub Actions deploy.yml 调用）
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/photorestore}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:18183/healthz}"
cd "$APP_DIR"

if [[ ! -f docker-compose.yml ]]; then
  echo "ERROR: missing docker-compose.yml in $APP_DIR"
  ls -la || true
  exit 1
fi
if [[ ! -f .env ]]; then
  echo "ERROR: missing .env"
  exit 1
fi

get_env() {
  local line
  line="$(grep -E "^${1}=" .env | tail -n1 || true)"
  echo "${line#*=}"
}

DOCKER_USERNAME="$(get_env DOCKER_USERNAME)"
IMAGE_TAG="$(get_env IMAGE_TAG)"
IMAGE_TAG="${IMAGE_TAG:-latest}"
HTTP_PORT="$(get_env HTTP_PORT)"
HTTP_PORT="${HTTP_PORT:-18183}"

if [[ -z "$DOCKER_USERNAME" ]]; then
  echo "ERROR: DOCKER_USERNAME empty in .env"
  exit 1
fi

run_root() {
  if [[ "$(id -u)" -eq 0 ]]; then "$@"
  elif command -v sudo >/dev/null 2>&1; then sudo "$@"
  else "$@"; fi
}

force_registry_mirrors() {
  echo "==> Configure registry-mirrors"
  run_root mkdir -p /etc/docker
  [[ -f /etc/docker/daemon.json ]] && run_root cp /etc/docker/daemon.json "/etc/docker/daemon.json.bak.$(date +%s)" || true
  run_root tee /etc/docker/daemon.json >/dev/null <<'EOF'
{
  "registry-mirrors": [
    "https://mirror.ccs.tencentyun.com",
    "https://docker.m.daocloud.io",
    "https://docker.1ms.run"
  ],
  "max-concurrent-downloads": 3
}
EOF
  run_root systemctl daemon-reload 2>/dev/null || true
  run_root systemctl restart docker 2>/dev/null || true
  sleep 4
  for _ in $(seq 1 20); do docker info >/dev/null 2>&1 && break; sleep 2; done
}

hub_reachable() {
  timeout 5 bash -c 'echo >/dev/tcp/registry-1.docker.io/443' 2>/dev/null \
    || curl -fsS -m 5 -o /dev/null https://registry-1.docker.io/v2/ 2>/dev/null
}

docker_login_optional() {
  if ! hub_reachable; then
    echo "==> Skip docker login (Hub unreachable; pull via mirrors)"
    rm -f .docker_password 2>/dev/null || true
    return 0
  fi
  if [[ -f .docker_password ]]; then
    cat .docker_password | docker login -u "$DOCKER_USERNAME" --password-stdin || true
  elif [[ -n "${DOCKER_PASSWORD:-}" ]]; then
    echo "$DOCKER_PASSWORD" | docker login -u "$DOCKER_USERNAME" --password-stdin || true
  fi
  rm -f .docker_password 2>/dev/null || true
}

force_registry_mirrors
docker_login_optional

IMAGE="${DOCKER_USERNAME}/photorestore-frontend:${IMAGE_TAG}"
echo "==> Pull $IMAGE"
for i in 1 2 3 4 5; do
  if docker compose pull; then break; fi
  if docker pull "$IMAGE"; then break; fi
  echo "pull fail $i/5"; sleep $((i * 6))
  [[ "$i" -eq 2 ]] && force_registry_mirrors
  [[ "$i" -eq 5 ]] && exit 1
done
echo "==> Try model download (non-blocking; restore has classic fallback)"
docker compose exec -T backend python scripts/download_models.py || true

echo "==> Up"
docker compose up -d --remove-orphans
docker compose ps

echo "==> Health $HEALTH_URL (port ${HTTP_PORT})"
ok=0
for i in $(seq 1 24); do
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1 \
    || curl -fsS "http://127.0.0.1:${HTTP_PORT}/healthz" >/dev/null 2>&1 \
    || curl -fsS "http://127.0.0.1:${HTTP_PORT}/" >/dev/null 2>&1; then
    echo "healthy attempt $i"
    ok=1
    break
  fi
  sleep 3
done
[[ "$ok" -ne 1 ]] && docker compose logs --tail=40 || true
docker image prune -f >/dev/null 2>&1 || true
echo "Deploy finished $(date -Is)"