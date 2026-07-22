#!/usr/bin/env bash
set -euo pipefail

if (($# != 1)); then
  echo "用法：$0 <视频路径>" >&2
  exit 2
fi

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
input="$1"
[[ -f "$input" ]] || { echo "输入不是普通文件：$input" >&2; exit 1; }

progress() {
  printf '@@progress {"stage":"%s","percent":%s,"message":"%s"}\n' "$1" "$2" "$3"
}

provider="${TRANSCRIPT_PROVIDER:-gemini}"
case "$provider" in
  gemini)
    [[ -n "${GEMINI_API_KEY:-}" ]] || { echo "缺少 GEMINI_API_KEY；默认 Gemini 模式无法启动" >&2; exit 1; }
    ;;
  ollama)
    for command_name in curl ollama; do
      command -v "$command_name" >/dev/null || { echo "缺少命令：$command_name" >&2; exit 1; }
    done
    curl --connect-timeout 3 --max-time 10 --fail --silent http://127.0.0.1:11434/api/tags >/dev/null
    ollama list | awk 'NR > 1 {print $1}' | grep -Fxq "${OLLAMA_MODEL:-qwen2.5:14b-instruct}" || {
      echo "本地 Ollama 缺少 ${OLLAMA_MODEL:-qwen2.5:14b-instruct}" >&2
      exit 1
    }
    ;;
  *)
    echo "TRANSCRIPT_PROVIDER 仅支持 gemini 或 ollama" >&2
    exit 2
    ;;
esac
for command_name in ffmpeg ffprobe whisper-cli python3; do
  command -v "$command_name" >/dev/null || { echo "缺少命令：$command_name，请先运行 scripts/setup.sh" >&2; exit 1; }
done
model="$project_root/models/ggml-large-v3-turbo.bin"
[[ -s "$model" ]] || { echo "模型不存在，请先运行 scripts/setup.sh" >&2; exit 1; }

task_name="${TRANSCRIPT_TASK_NAME:-$(basename "${input%.*}")}"
[[ "$task_name" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "任务名称包含不安全字符" >&2; exit 2; }
work_dir="$project_root/work/$task_name"
output_dir="$project_root/outputs/$task_name"
audio="$work_dir/audio.wav"
whisper_prefix="$work_dir/transcript.whisper"
whisper_json="$whisper_prefix.json"
legacy_whisper_json="$output_dir/transcript.original.json"
final_json="$output_dir/transcript.final.json"
final_markdown="$output_dir/transcript.final.md"
candidate_json="$output_dir/transcript.${provider}.candidate.json"
qwen_backup="$output_dir/transcript.qwen.json"
log="$output_dir/run.log"
probe="$output_dir/input-probe.json"
mkdir -p "$work_dir" "$output_dir"
exec > >(tee -a "$log") 2>&1

progress "准备开始" 1 "正在检查本机依赖和已有结果。"

ffprobe -v error -show_entries format=duration,size:stream=codec_type,codec_name,width,height,sample_rate,channels -of json "$input" > "$probe"
duration_seconds="$(python3 - "$probe" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding='utf-8'))['format']['duration'])
PY
)"

if [[ ! -s "$audio" ]]; then
  progress "音频提取" 5 "正在从视频提取音频。"
  ffmpeg -nostdin -hide_banner -loglevel error -i "$input" -vn -ac 1 -ar 16000 -c:a pcm_s16le -n "$audio"
else
  progress "音频提取" 12 "已复用已有音频。"
fi
if [[ ! -s "$whisper_json" && -s "$legacy_whisper_json" ]]; then
  cp -p "$legacy_whisper_json" "$whisper_json"
  echo "已复用旧版 Whisper JSON：$legacy_whisper_json"
fi
if [[ ! -s "$whisper_json" ]]; then
  progress "Whisper 识别" 15 "正在本机识别视频语音。"
  whisper-cli -m "$model" -f "$audio" -l auto -fa -ojf -of "$whisper_prefix" || \
    whisper-cli -m "$model" -f "$audio" -l auto -ojf -of "$whisper_prefix"
else
  progress "Whisper 识别" 32 "已复用已有 Whisper 结果。"
fi
python3 -m json.tool "$whisper_json" >/dev/null

if [[ "$provider" == "gemini" && -s "$final_json" && ! -e "$qwen_backup" ]]; then
  if python3 - "$final_json" <<'PY'
import json
import sys
editor = json.load(open(sys.argv[1], encoding="utf-8")).get("models", {}).get("editor", "")
raise SystemExit(0 if "qwen" in editor.lower() else 1)
PY
  then
    cp -p "$final_json" "$qwen_backup"
    echo "已备份 Qwen 最终结果：$qwen_backup"
  fi
fi

progress "文本整理" 34 "正在准备带来源映射的文本块。"
process_args=(
  "$whisper_json" "$candidate_json"
  --source "$input"
  --duration-seconds "$duration_seconds"
  --cache-dir "$work_dir/transcript-cache"
)
if [[ -n "${TRANSCRIPT_SOURCE_MANIFEST:-}" ]]; then
  process_args+=(--source-manifest "$TRANSCRIPT_SOURCE_MANIFEST")
fi
python3 "$project_root/scripts/process-transcript.py" "${process_args[@]}"
progress "结构校验" 94 "正在验证时间范围和来源映射。"
python3 "$project_root/scripts/validate-transcript-json.py" "$candidate_json" --whisper-json "$whisper_json"
mv -f "$candidate_json" "$final_json"
progress "生成 Markdown" 97 "正在生成阅读版 Markdown。"
python3 "$project_root/scripts/export-transcript-markdown.py" "$final_json" "$final_markdown"
progress "已完成" 100 "Markdown 已生成，可以阅读和导出。"
echo "完成：$final_json"
