#!/usr/bin/env python3
"""Run a cache-free full-video benchmark and record stage timings."""
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


def run(command, log):
    started = time.perf_counter()
    subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT)
    return round(time.perf_counter() - started, 3)


def main():
    if len(sys.argv) != 2:
        raise SystemExit(f"用法：{Path(sys.argv[0]).name} <视频路径>")
    root = Path(__file__).resolve().parent.parent
    video = Path(sys.argv[1]).resolve()
    if not video.is_file():
        raise SystemExit(f"输入不是普通文件：{video}")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"{video.stem}-benchmark-{stamp}"
    work = root / "work" / name
    output = root / "outputs" / name
    work.mkdir(parents=True)
    output.mkdir(parents=True)
    log_path = output / "run.log"
    probe = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(video)], text=True)
    duration = float(json.loads(probe)["format"]["duration"])
    audio = work / "audio.wav"
    whisper_prefix = work / "transcript.whisper"
    whisper_json = work / "transcript.whisper.json"
    final_json = output / "transcript.final.json"
    final_markdown = output / "transcript.final.md"
    timings = {}
    overall = time.perf_counter()
    with log_path.open("w", encoding="utf-8") as log:
        timings["audio_extract_seconds"] = run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-n", str(audio)], log)
        timings["whisper_seconds"] = run(["whisper-cli", "-m", str(root / "models" / "ggml-large-v3-turbo.bin"), "-f", str(audio), "-l", "auto", "-fa", "-ojf", "-of", str(whisper_prefix)], log)
        timings["qwen_seconds"] = run([sys.executable, str(root / "scripts" / "process-transcript.py"), str(whisper_json), str(final_json), "--source", str(video), "--duration-seconds", str(duration), "--cache-dir", str(work / "qwen-cache")], log)
        timings["json_validation_seconds"] = run([sys.executable, str(root / "scripts" / "validate-transcript-json.py"), str(final_json), "--whisper-json", str(whisper_json)], log)
        timings["markdown_export_seconds"] = run([sys.executable, str(root / "scripts" / "export-transcript-markdown.py"), str(final_json), str(final_markdown)], log)
    timings["total_seconds"] = round(time.perf_counter() - overall, 3)
    result = {"source": str(video), "duration_seconds": duration, "work_dir": str(work), "output_dir": str(output), "timings": timings}
    (output / "benchmark.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
