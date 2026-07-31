#!/usr/bin/env bash
# PhotoRestore 数据管理：清理 data/（SQLite、uploads、outputs、tmp）与可选 models/
# 用法：
#   scripts/docker_cleanup.sh          # 清理数据（保留模型）
#   scripts/docker_cleanup.sh --all    # 数据 + 模型一起清理
set -euo pipefail

cd "$(dirname "$0")/.."

ALL="${1:-}"
if [[ "$ALL" == "--all" ]]; then
  echo "将清理 data/ 与 models/ 下所有内容"
else
  echo "将清理 data/ 下所有内容（模型保留）"
fi

# 停止并移除容器，避免文件占用
if docker compose ps -q >/dev/null 2>&1 && [[ -n "$(docker compose ps -q)" ]]; then
  echo "==> 停止服务: docker compose down"
  docker compose down
fi

echo "==> 清理 data/"
rm -rf data/*
mkdir -p data/uploads data/outputs data/tmp

if [[ "$ALL" == "--all" ]]; then
  echo "==> 清理 models/"
  rm -rf models/*
fi

echo "==> 完成。重启: docker compose up -d --build（数据库与目录会在后端启动时自动重建）"
