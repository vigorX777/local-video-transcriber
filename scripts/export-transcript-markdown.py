#!/usr/bin/env python3
"""Export a validated final transcript JSON as readable Markdown."""
import argparse
import json
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started = time.perf_counter()
    transcript = json.loads(args.input.read_text(encoding="utf-8"))
    lines = [f"# {transcript['title']}", "", f"> 源视频：{Path(transcript['source']['path']).name}", "", "## 内容摘要", "", transcript["summary"].strip(), ""]
    paragraphs = 0
    for section in transcript["sections"]:
        lines.extend([f"## {section['id']}. {section['title']}", ""])
        for paragraph in section["paragraphs"]:
            lines.extend([paragraph["text"].strip(), ""])
            paragraphs += 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "sections": len(transcript["sections"]), "paragraphs": paragraphs, "elapsed_ms": round((time.perf_counter() - started) * 1000, 2)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
