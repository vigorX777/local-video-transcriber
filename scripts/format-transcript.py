#!/usr/bin/env python3
"""Turn whisper TXT fragments into readable Markdown without changing source words."""
import argparse
import json
import re
import sys
import unicodedata
import urllib.request
from pathlib import Path

API_URL = "http://127.0.0.1:11434/api/chat"
MODEL = "qwen2.5:14b-instruct"


def call(messages: list[dict[str, str]]) -> str:
    request = urllib.request.Request(
        API_URL,
        data=json.dumps({"model": MODEL, "stream": False, "options": {"temperature": 0}, "messages": messages}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=600) as response:
        return json.loads(response.read().decode())["message"]["content"].strip()


def chunks(lines: list[str], maximum_chars: int = 6500) -> list[list[str]]:
    output, current, size = [], [], 0
    for line in lines:
        if current and size + len(line) > maximum_chars:
            output.append(current)
            current, size = [], 0
        current.append(line)
        size += len(line)
    if current:
        output.append(current)
    return output


def normalize(value: str) -> str:
    return "".join(
        character for character in value
        if not character.isspace() and not unicodedata.category(character).startswith("P")
    )


def title_for(chunk: list[str]) -> tuple[str, str]:
    prompt = "\n".join(chunk)
    response = call([
        {"role": "system", "content": "你是中文视频编辑。仅返回 JSON：{\"chapter\":\"不超过14字的主题\",\"section\":\"不超过18字的本段标题\"}。标题必须忠实概括给定原文，不补充事实。"},
        {"role": "user", "content": prompt},
    ])
    response = re.sub(r"^```(?:json)?\s*|\s*```$", "", response, flags=re.I)
    value = json.loads(response)
    return str(value["chapter"]).strip(), str(value["section"]).strip()


def format_body(chunk: list[str]) -> str:
    # Whisper TXT has no punctuation.  Keep every source fragment untouched and
    # add sentence marks only between fragments; this is mechanically verifiable.
    sentences, fragments, length = [], [], 0
    for fragment in chunk:
        fragments.append(fragment)
        length += len(fragment)
        if length >= 36 or fragment.endswith(("吗", "呢", "了", "吧", "。", "？", "！")):
            sentences.append("".join(fragments).rstrip("。！？") + "。")
            fragments, length = [], 0
    if fragments:
        sentences.append("".join(fragments).rstrip("。！？") + "。")
    paragraphs = ["".join(sentences[index:index + 3]) for index in range(0, len(sentences), 3)]
    body = "\n\n".join(paragraphs)
    source = "\n".join(chunk)
    if normalize(body) != normalize(source):
        raise ValueError("内部逐字校验失败")
    return body


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-video", required=True)
    args = parser.parse_args()
    lines = [line.strip() for line in args.input.read_text(encoding="utf-8").splitlines() if line.strip()]
    sections = chunks(lines)
    markdown = ["# 视频字幕整理稿", "", f"> 源视频：{args.source_video}", ""]
    last_chapter = ""
    chapter_number = section_number = 0
    for index, chunk in enumerate(sections, start=1):
        chapter, section = title_for(chunk)
        if chapter != last_chapter:
            chapter_number += 1
            section_number = 0
            markdown.extend([f"## {chapter_number}. {chapter}", ""])
            last_chapter = chapter
        section_number += 1
        markdown.extend([f"### {chapter_number}.{section_number} {section}", "", format_body(chunk), ""])
        print(f"已整理第 {index}/{len(sections)} 段", file=sys.stderr)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(markdown).rstrip() + "\n", encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"整理失败：{error}", file=sys.stderr)
        sys.exit(1)
