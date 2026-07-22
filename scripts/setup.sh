#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
model_dir="$project_root/models"
model_name="ggml-large-v3-turbo.bin"
model_path="$model_dir/$model_name"
model_url="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/$model_name?download=true"
tool_dir="$project_root/tools"
yt_dlp_path="$tool_dir/yt-dlp_macos"
yt_dlp_url="https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos"
yt_dlp_checksums_url="https://github.com/yt-dlp/yt-dlp/releases/latest/download/SHA2-256SUMS"

mkdir -p "$model_dir" "$tool_dir"

for command_name in brew curl shasum npm; do
  command -v "$command_name" >/dev/null || {
    echo "缺少命令：$command_name" >&2
    exit 1
  }
done

python3 -m pip install --user --requirement "$project_root/requirements.txt"
(cd "$project_root/web" && npm install)

if [[ -x "$yt_dlp_path" ]]; then
  yt_dlp_version="$($yt_dlp_path --version)"
  echo "yt-dlp 已存在：$yt_dlp_version"
else
  yt_dlp_download="$tool_dir/yt-dlp_macos.download"
  checksums_download="$tool_dir/SHA2-256SUMS.download"
  rm -f "$yt_dlp_download" "$checksums_download"
  echo "下载官方 yt-dlp macOS 独立程序..."
  curl --fail --location --retry 3 --retry-delay 2 --output "$yt_dlp_download" "$yt_dlp_url"
  curl --fail --location --retry 3 --retry-delay 2 --output "$checksums_download" "$yt_dlp_checksums_url"
  expected_sha256="$(awk '$2 == "yt-dlp_macos" {print $1; exit}' "$checksums_download")"
  actual_sha256="$(shasum -a 256 "$yt_dlp_download" | awk '{print $1}')"
  [[ -n "$expected_sha256" && "$actual_sha256" == "$expected_sha256" ]] || {
    echo "yt-dlp SHA-256 校验失败" >&2
    exit 1
  }
  chmod +x "$yt_dlp_download"
  mv "$yt_dlp_download" "$yt_dlp_path"
  rm -f "$checksums_download"
  yt_dlp_version="$($yt_dlp_path --version)"
  echo "yt-dlp 已验证：$yt_dlp_version"
fi
printf '%s\n' "$yt_dlp_version" > "$tool_dir/yt-dlp.version"

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
