#! /usr/bin/env sh

# 任一步失败就立即停止，避免残留不完整的测试环境。
set -e
set -x

docker compose build
docker compose down -v --remove-orphans
docker compose up -d
docker compose exec -T backend bash scripts/tests-start.sh "$@"
docker compose down -v --remove-orphans
