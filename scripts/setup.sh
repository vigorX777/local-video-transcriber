#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
model_dir="$project_root/models"
model_name="ggml-large-v3-turbo.bin"
model_path="$model_dir/$model_name"
model_url="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/$model_name?download=true"

mkdir -p "$model_dir"

for command_name in brew curl shasum npm; do
  command -v "$command_name" >/dev/null || {
    echo "缺少命令：$command_name" >&2
    exit 1
  }
done

python3 -m pip install --user --requirement "$project_root/requirements.txt"
(cd "$project_root/web" && npm install)

missing_formulae=()
command -v ffmpeg >/dev/null || missing_formulae+=(ffmpeg)
command -v whisper-cli >/dev/null || missing_formulae+=(whisper-cpp)
if ((${#missing_formulae[@]})); then
  brew install "${missing_formulae[@]}"
fi

if [[ -s "$model_path" ]]; then
  echo "Whisper 模型已存在：$model_path"
else
  temporary_path="$model_path.download"
  rm -f "$temporary_path"
  echo "下载 Whisper Large v3 Turbo 模型（约 1.6 GB）..."
  curl --fail --location --retry 3 --retry-delay 2 --output "$temporary_path" "$model_url"
  mv "$temporary_path" "$model_path"
fi

model_bytes="$(stat -f '%z' "$model_path")"
if ((model_bytes < 1000000000)); then
  echo "模型文件大小异常：$model_bytes bytes" >&2
  exit 1
fi

model_sha256="$(shasum -a 256 "$model_path" | awk '{print $1}')"
printf 'source=%s\nbytes=%s\nsha256=%s\n' "$model_url" "$model_bytes" "$model_sha256" \
  > "$model_dir/$model_name.metadata"
echo "模型已验证：$model_path"
echo "SHA-256：$model_sha256"
