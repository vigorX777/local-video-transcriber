#!/usr/bin/env python3
"""Validate the final transcript schema and its source-segment coverage."""
import argparse
import json
import sys
from pathlib import Path


def require(value, message):
    if not value:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("final_json", type=Path)
    parser.add_argument("--whisper-json", type=Path, required=True)
    args = parser.parse_args()
    final = json.loads(args.final_json.read_text(encoding="utf-8"))
    whisper = json.loads(args.whisper_json.read_text(encoding="utf-8"))
    expected_ids = list(range(len(whisper["transcription"])))
    require(final.get("schema_version") == "1.0", "schema_version 必须为 1.0")
    require(isinstance(final.get("title"), str) and final["title"].strip(), "缺少总标题")
    require(isinstance(final.get("summary"), str) and final["summary"].strip(), "缺少总摘要")
    require(isinstance(final.get("sections"), list) and final["sections"], "缺少章节")
    duration_ms = round(float(final["source"]["duration_seconds"]) * 1000)
    covered = []
    previous_start = -1
    for expected_section_id, section in enumerate(final["sections"], start=1):
        require(section.get("id") == expected_section_id, "章节 ID 必须连续")
        require(isinstance(section.get("title"), str) and section["title"].strip(), "章节标题为空")
        paragraphs = section.get("paragraphs")
        require(isinstance(paragraphs, list) and paragraphs, "章节缺少段落")
        section_ids = []
        for paragraph in paragraphs:
            ids = paragraph.get("source_segment_ids")
            require(isinstance(ids, list) and ids, "段落缺少来源 ID")
            require(isinstance(paragraph.get("text"), str) and paragraph["text"].strip(), "段落文本为空")
            start, end = paragraph.get("start_ms"), paragraph.get("end_ms")
            require(isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= duration_ms, "段落时间非法")
            require(start >= previous_start, "段落时间未单调递增")
            previous_start = start
            source_start = whisper["transcription"][ids[0]]["offsets"]["from"]
            source_end = whisper["transcription"][ids[-1]]["offsets"]["to"]
            require((start, end) == (source_start, source_end), "段落时间不等于来源分段范围")
            section_ids.extend(ids)
            covered.extend(ids)
        require((section["start_ms"], section["end_ms"]) == (
            whisper["transcription"][section_ids[0]]["offsets"]["from"],
            whisper["transcription"][section_ids[-1]]["offsets"]["to"],
        ), "章节时间不等于段落范围")
    require(covered == expected_ids, "来源分段必须按原顺序恰好引用一次")
    print(json.dumps({"status": "ok", "segments": len(expected_ids), "sections": len(final["sections"])}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"最终 JSON 验证失败：{error}", file=sys.stderr)
        sys.exit(1)
