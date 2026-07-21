#!/usr/bin/env bash
set -euo pipefail

if (($# != 1)); then
  echo "用法：$0 <视频路径>" >&2
  exit 2
fi

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
input="$1"
[[ -f "$input" ]] || { echo "输入不是普通文件：$input" >&2; exit 1; }
provider="${TRANSCRIPT_PROVIDER:-gemini}"
case "$provider" in
  gemini) [[ -n "${GEMINI_API_KEY:-}" ]] || { echo "缺少 GEMINI_API_KEY；默认 Gemini 模式无法启动" >&2; exit 1; } ;;
  ollama) ;;
  *) echo "TRANSCRIPT_PROVIDER 仅支持 gemini 或 ollama" >&2; exit 2 ;;
esac
model="$project_root/models/ggml-large-v3-turbo.bin"
[[ -s "$model" ]] || { echo "模型不存在，请先运行 scripts/setup.sh" >&2; exit 1; }

task_name="$(basename "${input%.*}")"
work_dir="$project_root/work/$task_name"
output_dir="$project_root/outputs/$task_name"
sample_wav="$work_dir/sample-60s.wav"
sample_prefix="$work_dir/sample.transcript.whisper"
sample_json="$sample_prefix.json"
sample_final="$work_dir/sample.transcript.final.json"
sample_candidate="$work_dir/sample.transcript.${provider}.candidate.json"
legacy_sample_json="$output_dir/sample.transcript.original.json"
mkdir -p "$work_dir" "$output_dir"

if [[ ! -s "$sample_wav" ]]; then
  ffmpeg -nostdin -hide_banner -loglevel error -ss 0 -t 60 -i "$input" -vn -ac 1 -ar 16000 -c:a pcm_s16le -n "$sample_wav"
fi
if [[ ! -s "$sample_json" && -s "$legacy_sample_json" ]]; then
  cp -p "$legacy_sample_json" "$sample_json"
fi
if [[ ! -s "$sample_json" ]]; then
  whisper-cli -m "$model" -f "$sample_wav" -l auto -fa -ojf -of "$sample_prefix" || \
    whisper-cli -m "$model" -f "$sample_wav" -l auto -ojf -of "$sample_prefix"
fi
python3 "$project_root/scripts/process-transcript.py" "$sample_json" "$sample_candidate" \
  --source "$input" --duration-seconds 60 --cache-dir "$work_dir/sample-transcript-cache"
python3 "$project_root/scripts/validate-transcript-json.py" "$sample_candidate" --whisper-json "$sample_json"
mv -f "$sample_candidate" "$sample_final"
echo "60 秒 JSON 样本通过：$sample_final"
