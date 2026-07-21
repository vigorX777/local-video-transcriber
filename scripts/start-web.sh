#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
web_root="$project_root/web"

python3 -c 'import fastapi, uvicorn' >/dev/null 2>&1 || {
  echo "缺少 Web 依赖，请先运行 scripts/setup.sh" >&2
  exit 1
}
[[ -d "$web_root/node_modules" ]] || {
  echo "缺少前端依赖，请在 web/ 目录运行 npm install" >&2
  exit 1
}
(cd "$web_root" && npm run build >/dev/null)
exec python3 -m uvicorn app.server:app --host 127.0.0.1 --port "${PORT:-8765}"
