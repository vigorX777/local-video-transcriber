#!/usr/bin/env python3
"""Translate SRT text through loopback-only Ollama without exposing its timeline."""
import argparse
import importlib.util
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

VERIFIER_PATH = Path(__file__).with_name("verify-srt.py")
VERIFIER_SPEC = importlib.util.spec_from_file_location("verify_srt", VERIFIER_PATH)
if VERIFIER_SPEC is None or VERIFIER_SPEC.loader is None:
    raise RuntimeError(f"无法加载 SRT 校验器：{VERIFIER_PATH}")
VERIFIER_MODULE = importlib.util.module_from_spec(VERIFIER_SPEC)
VERIFIER_SPEC.loader.exec_module(VERIFIER_MODULE)
parse_srt = VERIFIER_MODULE.parse_srt

API_URL = "http://127.0.0.1:11434/api/chat"
SYSTEM_PROMPT = """You translate English subtitles into concise natural Simplified Chinese.
Return only a JSON array. Each item must be {\"id\": integer, \"text\": string}.
Keep exactly the supplied ids. Translate only the subtitle text; no notes, Markdown, or timestamps."""


def batches(entries: list[dict[str, object]], maximum_chars: int = 9000):
    batch, size = [], 0
    for entry in entries:
        addition = len(str(entry["text"])) + 32
        if batch and size + addition > maximum_chars:
            yield batch
            batch, size = [], 0
        batch.append(entry)
        size += addition
    if batch:
        yield batch


def clean_json(content: str) -> object:
    content = content.strip()
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.IGNORECASE)
    return json.loads(content)


def translate(batch: list[dict[str, object]], model: str) -> dict[int, str]:
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    [{"id": item["id"], "text": item["text"]} for item in batch],
                    ensure_ascii=False,
                ),
            },
        ],
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        body = json.loads(response.read().decode("utf-8"))
    result = clean_json(body["message"]["content"])
    if not isinstance(result, list):
        raise ValueError("模型未返回 JSON 数组")
    translated = {item.get("id"): str(item.get("text", "")).strip() for item in result if isinstance(item, dict)}
    expected = {item["id"] for item in batch}
    if set(translated) != expected or any(not translated[item_id] for item_id in expected):
        raise ValueError("模型返回的字幕 ID 或文本不完整")
    return {int(item_id): text for item_id, text in translated.items()}


def write_srt(entries: list[dict[str, object]], translated: dict[int, str], output: Path) -> None:
    blocks = []
    for entry in entries:
        blocks.append(f"{entry['id']}\n{entry['start']} --> {entry['end']}\n{translated[int(entry['id'])]}")
    output.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", default="qwen2.5:14b-instruct")
    args = parser.parse_args()
    entries = parse_srt(args.input)
    translations: dict[int, str] = {}
    for index, batch in enumerate(batches(entries), start=1):
        for attempt in range(2):
            try:
                translations.update(translate(batch, args.model))
                print(f"已翻译第 {index} 批，共 {len(batch)} 条", file=sys.stderr)
                break
            except (urllib.error.URLError, TimeoutError, KeyError, ValueError, json.JSONDecodeError) as error:
                if attempt:
                    raise RuntimeError(f"第 {index} 批翻译失败：{error}") from error
                print(f"第 {index} 批返回无效，重试一次：{error}", file=sys.stderr)
                time.sleep(1)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_srt(entries, translations, args.output)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError) as error:
        print(f"翻译失败：{error}", file=sys.stderr)
        sys.exit(1)
