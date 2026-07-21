#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
port="${PORT:-8765}"
url="http://127.0.0.1:${port}"
health_url="${url}/api/settings"
log_path="${project_root}/work/web-server-${port}.log"

[[ "$port" =~ ^[0-9]{2,5}$ ]] || { echo "PORT 必须是有效端口号：${port}" >&2; exit 2; }

is_workbench_running() {
  curl --fail --silent --max-time 1 "$health_url" >/dev/null 2>&1
}

open_workbench() {
  open "$url"
  echo "已打开本机工作台：${url}"
}

if is_workbench_running; then
  echo "本机工作台已在运行，直接打开现有服务。"
  open_workbench
  exit 0
fi

if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "端口 ${port} 已被其他进程占用，且不是本项目工作台；未做任何停止操作。" >&2
  exit 1
fi

mkdir -p "${project_root}/work"
echo "正在启动本机工作台…"
nohup "${project_root}/scripts/start-web.sh" >"$log_path" 2>&1 &
server_pid=$!

for _ in {1..80}; do
  if is_workbench_running; then
    open_workbench
    exit 0
  fi
  if ! kill -0 "$server_pid" >/dev/null 2>&1; then
    echo "工作台启动失败；日志：${log_path}" >&2
    tail -n 40 "$log_path" >&2 || true
    exit 1
  fi
  sleep 0.25
done

kill -TERM "$server_pid" >/dev/null 2>&1 || true
echo "工作台在 20 秒内未就绪，已停止本次启动进程；日志：${log_path}" >&2
tail -n 40 "$log_path" >&2 || true
exit 1
