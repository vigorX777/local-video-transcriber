#!/usr/bin/env python3
"""Validate SRT structure and optionally ensure two files share their timeline."""
import argparse
import json
import re
import sys
from pathlib import Path

TIMESTAMP = re.compile(r"^(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})$")


def milliseconds(value: str) -> int:
    hours, minutes, seconds_millis = value.split(":")
    seconds, millis = seconds_millis.split(",")
    return ((int(hours) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + int(millis)


def parse_srt(path: Path) -> list[dict[str, object]]:
    raw = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").strip()
    if not raw:
        raise ValueError(f"{path} 为空")
    entries = []
    for position, block in enumerate(re.split(r"\n{2,}", raw), start=1):
        lines = block.split("\n")
        if len(lines) < 3:
            raise ValueError(f"{path} 第 {position} 块不完整")
        try:
            sequence = int(lines[0].strip())
        except ValueError as error:
            raise ValueError(f"{path} 第 {position} 块序号无效") from error
        match = TIMESTAMP.fullmatch(lines[1].strip())
        if not match:
            raise ValueError(f"{path} 第 {position} 块时间轴无效：{lines[1]}")
        start, end = match.groups()
        if milliseconds(start) >= milliseconds(end):
            raise ValueError(f"{path} 第 {position} 块开始时间不早于结束时间")
        text = "\n".join(lines[2:]).strip()
        if not text:
            raise ValueError(f"{path} 第 {position} 块字幕为空")
        entries.append({"id": sequence, "start": start, "end": end, "text": text})
    previous_start = -1
    for expected_id, entry in enumerate(entries, start=1):
        if entry["id"] != expected_id:
            raise ValueError(f"{path} 序号不连续：期望 {expected_id}，实际 {entry['id']}")
        current_start = milliseconds(str(entry["start"]))
        if current_start < previous_start:
            raise ValueError(f"{path} 时间轴未单调递增：第 {expected_id} 块")
        previous_start = current_start
    return entries


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("srt", type=Path)
    parser.add_argument("--reference", type=Path)
    args = parser.parse_args()
    entries = parse_srt(args.srt)
    if args.reference:
        reference = parse_srt(args.reference)
        if len(entries) != len(reference):
            raise ValueError("翻译前后字幕块数量不一致")
        for translated, original in zip(entries, reference):
            if tuple(translated[key] for key in ("id", "start", "end")) != tuple(
                original[key] for key in ("id", "start", "end")
            ):
                raise ValueError(f"第 {original['id']} 块序号或时间轴被修改")
    print(json.dumps({"status": "ok", "blocks": len(entries), "file": str(args.srt)}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        print(f"SRT 验证失败：{error}", file=sys.stderr)
        sys.exit(1)
