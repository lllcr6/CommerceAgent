#!/usr/bin/env bash

set -euo pipefail
cd "$(dirname "$0")/.."



export PYTHONUTF8=1

if [ ! -f .env ]; then
  echo "Missing .env. Copy .env.example to .env and configure provider credentials." >&2
  exit 1
fi
set -a; source .env; set +a




if command -v colima >/dev/null 2>&1; then
  if ! colima status >/dev/null 2>&1; then
    echo "Colima is stopped; starting it (30-60 seconds)..."
    colima start
  fi
fi

echo "Starting infrastructure containers (MySQL, etcd, MinIO, Milvus)..."
docker compose up -d mysql etcd minio milvus-standalone

echo "Waiting for Milvus health check..."
MILVUS_READY=0
for _ in $(seq 1 60); do
  if curl -sf "http://localhost:${MILVUS_HEALTH_PORT:-9091}/healthz" >/dev/null 2>&1; then
    MILVUS_READY=1
    break
  fi
  sleep 3
done
if [ "$MILVUS_READY" -ne 1 ]; then
  echo "Milvus did not become ready after 180 seconds; stopping startup." >&2
  exit 1
fi
echo "Milvus OK"

make mcp-up

uv run uvicorn app.main:app --port 8000
