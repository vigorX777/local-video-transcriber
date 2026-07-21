#!/usr/bin/env python3
"""Create a source-traceable Chinese transcript JSON with Gemini or Ollama."""
import argparse
import json
import os
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import warnings
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore", message="You are using a Python version 3.9 past its end of life", category=FutureWarning)
warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL", category=Warning)

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

PROVIDER = os.environ.get("TRANSCRIPT_PROVIDER", "gemini").lower()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:14b-instruct")
MODEL = GEMINI_MODEL if PROVIDER == "gemini" else OLLAMA_MODEL
GEMINI_THINKING_BUDGET = int(os.environ.get("GEMINI_THINKING_BUDGET", "0"))
GEMINI_TEMPERATURE = float(os.environ.get("GEMINI_TEMPERATURE", "0"))
OLLAMA_API_URL = "http://127.0.0.1:11434/api/chat"
NUM_CTX = os.environ.get("OLLAMA_NUM_CTX")
MAX_CHARS = 6000
CACHE_VERSION = "v11-" + re.sub(r"[^a-z0-9]+", "-", f"{PROVIDER}-{MODEL}".lower()).strip("-")
MIN_PARAGRAPH_CHARS = 80
MAX_PARAGRAPH_CHARS = 260
TARGET_GROUP_CHARS = 160
MAX_GEMINI_GROUPS_PER_BLOCK = 4
GEMINI_CONNECT_TIMEOUT_SECONDS = 8
GEMINI_WRITE_TIMEOUT_SECONDS = 30
GEMINI_READ_TIMEOUT_SECONDS = 120
GEMINI_HEARTBEAT_SECONDS = 5
GEMINI_MAX_ATTEMPTS = 4
_gemini_client = None
_gemini_httpx_client = None


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean_json(text):
    return json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I))


def emit_progress(stage, percent, message, **extra):
    event = {"stage": stage, "percent": percent, "message": message, **extra}
    print("@@progress " + json.dumps(event, ensure_ascii=False), file=sys.stderr, flush=True)


def gemini_contents(messages):
    system_parts, contents = [], []
    for message in messages:
        content = message["content"]
        if message["role"] == "system":
            system_parts.append(content)
        else:
            role = "model" if message["role"] == "assistant" else "user"
            contents.append(genai_types.Content(role=role, parts=[genai_types.Part.from_text(text=content)]))
    return "\n\n".join(system_parts), contents


def gemini_client(api_key):
    global _gemini_client, _gemini_httpx_client
    if _gemini_client is None:
        client_options = {
            "timeout": httpx.Timeout(
                connect=GEMINI_CONNECT_TIMEOUT_SECONDS,
                write=GEMINI_WRITE_TIMEOUT_SECONDS,
                read=GEMINI_READ_TIMEOUT_SECONDS,
                pool=GEMINI_CONNECT_TIMEOUT_SECONDS,
            ),
            "trust_env": True,
        }
        proxies = urllib.request.getproxies()
        proxy = proxies.get("https") or proxies.get("all")
        if proxy:
            client_options["proxy"] = proxy
        else:
            client_options["transport"] = httpx.HTTPTransport(local_address="0.0.0.0", retries=0)
        _gemini_httpx_client = httpx.Client(**client_options)
        _gemini_client = genai.Client(
            api_key=api_key,
            http_options=genai_types.HttpOptions(
                api_version="v1beta",
                httpx_client=_gemini_httpx_client,
                retry_options=genai_types.HttpRetryOptions(attempts=1),
            ),
        )
    return _gemini_client


def close_gemini_client():
    global _gemini_client, _gemini_httpx_client
    if _gemini_client is not None:
        _gemini_client.close()
    _gemini_client = None
    _gemini_httpx_client = None


def retryable_gemini_error(error):
    if isinstance(error, (httpx.TimeoutException, httpx.NetworkError)):
        return True
    return isinstance(error, genai_errors.APIError) and (error.code in (408, 429) or 500 <= error.code <= 599)


def gemini_error_message(error):
    if isinstance(error, genai_errors.APIError):
        if error.code in (401, 403):
            return f"Gemini API Key 无效或无权限（HTTP {error.code}）"
        return f"Gemini API 请求失败（HTTP {error.code}）"
    if isinstance(error, httpx.TimeoutException):
        return "Gemini API 请求超时"
    return "Gemini API 网络请求失败"


def request_with_heartbeat(request, progress, attempt):
    result, failure = {}, {}
    finished = threading.Event()

    def run_request():
        try:
            result["value"] = request()
        except BaseException as error:  # Re-raised in the main thread below.
            failure["error"] = error
        finally:
            finished.set()

    thread = threading.Thread(target=run_request, daemon=True)
    started = time.monotonic()
    thread.start()
    while not finished.wait(GEMINI_HEARTBEAT_SECONDS):
        waited_seconds = int(time.monotonic() - started)
        emit_progress(
            progress["stage"],
            progress["percent"],
            f"正在请求第 {progress['request_block_index']} / {progress['block_total']} 组，已等待 {waited_seconds} 秒。",
            block_index=progress["block_index"],
            block_total=progress["block_total"],
            request_block_index=progress["request_block_index"],
            attempt=attempt,
            waited_seconds=waited_seconds,
        )
    thread.join()
    if "error" in failure:
        raise failure["error"]
    return result["value"]


def gemini_chat(messages, response_format, progress=None):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("缺少 GEMINI_API_KEY；默认 Gemini 模式无法调用 API")
    system_instruction, contents = gemini_contents(messages)
    config = genai_types.GenerateContentConfig(
        system_instruction=system_instruction or None,
        temperature=GEMINI_TEMPERATURE,
        thinking_config=genai_types.ThinkingConfig(thinking_budget=GEMINI_THINKING_BUDGET),
    )
    if response_format is not None:
        config.response_mime_type = "application/json"
        config.response_json_schema = response_format
    client = gemini_client(api_key)
    for attempt in range(1, GEMINI_MAX_ATTEMPTS + 1):
        if progress is not None:
            emit_progress(
                progress["stage"],
                progress["percent"],
                f"正在请求第 {progress['request_block_index']} / {progress['block_total']} 组（第 {attempt} 次尝试）。",
                block_index=progress["block_index"],
                block_total=progress["block_total"],
                request_block_index=progress["request_block_index"],
                attempt=attempt,
                waited_seconds=0,
            )
        try:
            request = lambda: client.models.generate_content(model=MODEL, contents=contents, config=config)
            response = request_with_heartbeat(request, progress, attempt) if progress is not None else request()
            text = response.text or ""
            if not text.strip():
                raise ValueError("Gemini 响应不含文本")
            return clean_json(text) if response_format is not None else text
        except (httpx.RequestError, genai_errors.APIError) as error:
            if not retryable_gemini_error(error):
                raise RuntimeError(gemini_error_message(error)) from error
            if attempt == GEMINI_MAX_ATTEMPTS:
                raise RuntimeError(f"{gemini_error_message(error)}（已重试 {GEMINI_MAX_ATTEMPTS} 次）") from error
            delay = min(2 ** (attempt - 1), 20) + random.uniform(0, 0.5)
            if progress is not None:
                emit_progress(
                    progress["stage"],
                    progress["percent"],
                    f"第 {progress['request_block_index']} / {progress['block_total']} 组请求失败，{delay:.1f} 秒后进行第 {attempt + 1} 次尝试。",
                    block_index=progress["block_index"],
                    block_total=progress["block_total"],
                    request_block_index=progress["request_block_index"],
                    attempt=attempt,
                    retry_in_seconds=round(delay, 1),
                )
            time.sleep(delay)


def ollama_chat(messages, response_format):
    payload = {"model": MODEL, "stream": False, "options": {"temperature": 0}, "messages": messages}
    if NUM_CTX:
        payload["options"]["num_ctx"] = int(NUM_CTX)
    if response_format is not None:
        payload["format"] = response_format
    request = urllib.request.Request(
        OLLAMA_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            return clean_json(json.loads(response.read().decode("utf-8"))["message"]["content"])
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace").strip()
        raise urllib.error.URLError(f"Ollama HTTP {error.code}: {detail}") from error


def chat(messages, response_format=None, progress=None):
    if PROVIDER == "gemini":
        return gemini_chat(messages, response_format, progress)
    if PROVIDER == "ollama":
        return ollama_chat(messages, response_format)
    raise RuntimeError("TRANSCRIPT_PROVIDER 仅支持 gemini 或 ollama")


def source_segments(whisper):
    segments = []
    for identifier, item in enumerate(whisper["transcription"]):
        text = str(item.get("text", "")).strip()
        start, end = item["offsets"]["from"], item["offsets"]["to"]
        if not text or not isinstance(start, int) or not isinstance(end, int) or start >= end:
            raise ValueError(f"Whisper 第 {identifier} 段无效")
        segments.append({"id": identifier, "text": text, "start_ms": start, "end_ms": end})
    if not segments:
        raise ValueError("Whisper JSON 不含有效分段")
    return segments


def make_source_groups(segments):
    groups, current, size = [], [], 0
    for segment in segments:
        if current and size >= TARGET_GROUP_CHARS:
            groups.append({"id": len(groups), "segments": current, "text": "".join(item["text"] for item in current)})
            current, size = [], 0
        current.append(segment)
        size += len(segment["text"])
    if current:
        tail = {"segments": current, "text": "".join(item["text"] for item in current)}
        if groups and len(tail["text"]) < MIN_PARAGRAPH_CHARS:
            groups[-1]["segments"].extend(tail["segments"])
            groups[-1]["text"] += tail["text"]
        else:
            tail["id"] = len(groups)
            groups.append(tail)
    return groups


def make_blocks(groups):
    blocks, current, size = [], [], 0
    for group in groups:
        addition = len(group["text"])
        if current and (size + addition > MAX_CHARS or (PROVIDER == "gemini" and len(current) >= MAX_GEMINI_GROUPS_PER_BLOCK)):
            blocks.append(current)
            current, size = [], 0
        current.append(group)
        size += addition
    if current:
        blocks.append(current)
    return blocks


def validate_block(value, expected_group_ids):
    if not isinstance(value, dict) or not str(value.get("title", "")).strip() or not str(value.get("summary", "")).strip():
        raise ValueError("模型未返回标题或摘要")
    paragraphs = value.get("paragraphs")
    if not isinstance(paragraphs, list) or not paragraphs:
        raise ValueError("模型未返回段落数组")
    actual_group_ids = []
    for paragraph in paragraphs:
        group_id = paragraph.get("source_group_id") if isinstance(paragraph, dict) else None
        text = paragraph.get("text") if isinstance(paragraph, dict) else None
        if not isinstance(group_id, int):
            raise ValueError("模型段落来源组 ID 无效")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("模型段落格式无效")
        length = len(text.strip())
        sentence_count = len(re.findall(r"[。！？]", text))
        if not MIN_PARAGRAPH_CHARS <= length <= MAX_PARAGRAPH_CHARS:
            raise ValueError(f"段落长度必须在 {MIN_PARAGRAPH_CHARS}–{MAX_PARAGRAPH_CHARS} 字之间")
        if not 2 <= sentence_count <= 3:
            raise ValueError("每段必须包含 2–3 句")
        actual_group_ids.append(group_id)
    if actual_group_ids != expected_group_ids:
        raise ValueError("模型段落来源组 ID 存在遗漏、重复或乱序")


def normalize_block(value):
    if not isinstance(value, dict) or not isinstance(value.get("paragraphs"), list):
        return value
    normalized = dict(value)
    paragraphs = []
    for paragraph in value["paragraphs"]:
        if not isinstance(paragraph, dict):
            paragraphs.append(paragraph)
            continue
        item = dict(paragraph)
        if "sentences" in item:
            sentences = item.pop("sentences")
            if not isinstance(sentences, list) or not all(isinstance(sentence, str) and sentence.strip() for sentence in sentences):
                raise ValueError("模型句子数组格式无效")
            item["text"] = "".join(sentence.strip() for sentence in sentences)
        if isinstance(item.get("text"), str):
            item["text"] = normalize_sentence_count(item["text"])
        paragraphs.append(item)
    normalized["paragraphs"] = paragraphs
    return normalized


def normalize_sentence_count(text):
    text = re.sub(r"[。！？]+", "。", text.strip())
    marks = [index for index, char in enumerate(text) if char == "。"]
    target_count = 3 if len(text) >= 180 else 2
    if len(marks) > target_count:
        keep = {marks[-1]}
        for target in (len(text) * index // target_count for index in range(1, target_count)):
            keep.add(min(marks, key=lambda position: abs(position - target)))
        text = "".join("。" if index in keep else "，" if char == "。" else char for index, char in enumerate(text))
        marks = [index for index, char in enumerate(text) if char == "。"]
    while len(marks) < 2:
        target = len(text) * (len(marks) + 1) // 2
        boundaries = [index for index, char in enumerate(text) if char in "，、；："]
        position = min(boundaries, key=lambda index: abs(index - target)) if boundaries else target
        if position < len(text) and text[position] in "，、；：":
            text = text[:position] + "。" + text[position + 1:]
        else:
            text = text[:position] + "。" + text[position:]
        marks = [index for index, char in enumerate(text) if char == "。"]
    return text if text.endswith("。") else text + "。"


def block_prompt(block):
    return {
        "role": "user",
        "content": json.dumps({"groups": [{"id": item["id"], "start_id": item["segments"][0]["id"], "end_id": item["segments"][-1]["id"], "text": item["text"]} for item in block]}, ensure_ascii=False),
    }


def block_format(group_count):
    return {
        "type": "object",
        "required": ["title", "summary", "paragraphs"],
        "additionalProperties": False,
        "properties": {
            "title": {"type": "string", "minLength": 1},
            "summary": {"type": "string", "minLength": 1},
            "paragraphs": {
                "type": "array",
                "minItems": group_count,
                "maxItems": group_count,
                "items": {
                    "type": "object",
                    "required": ["source_group_id", "text"],
                    "additionalProperties": False,
                    "properties": {
                        "source_group_id": {"type": "integer"},
                        "text": {"type": "string"},
                    },
                },
            },
        },
    }


def process_block(block, cache_path, progress):
    expected_group_ids = [item["id"] for item in block]
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        validate_block(cached, expected_group_ids)
        emit_progress(
            progress["stage"],
            progress["percent"],
            f"已复用第 {progress['request_block_index']} / {progress['block_total']} 组缓存。",
            block_index=progress["block_index"],
            block_total=progress["block_total"],
            request_block_index=progress["request_block_index"],
            cached=True,
        )
        return cached
    system = """你是严谨的中文视频编辑。输入是按时间排序的 Whisper 分段。返回且只返回 JSON 对象：
{"title":"本块章节标题","summary":"本块两三句摘要","paragraphs":[{"source_group_id":整数,"text":"整理后的简体中文段落"}]}。
输入 groups 已按时间排序，每个 group 都包含固定且连续的 Whisper 来源范围。每个 group 必须返回恰好一个段落，source_group_id 必须按输入顺序完整出现一次；不得合并、拆分、遗漏或调换 group。
每个 text 必须为 80–260 个汉字或字符、表达 2 或 3 句完整语义。句末标点由本地程序统一处理。不要输出时间戳、Markdown、解释或代码围栏。
中文分段请修正明显 ASR 错字、标点和不影响语义的口语冗余，但必须保留每个来源组的全部事实、观点、问题和例子；禁止摘要、缩写、省略或将内容移到其他来源组。英文分段翻译为简体中文。对不确定的人名、术语或数字使用【待核对】标记。"""
    last_error = None
    previous_value = None
    for attempt in range(2):
        response_value = None
        try:
            messages = [{"role": "system", "content": system}, block_prompt(block)]
            if previous_value is not None:
                messages.extend([
                    {"role": "assistant", "content": json.dumps(previous_value, ensure_ascii=False)},
                    {"role": "user", "content": f"上一版 JSON 未通过本地验收：{last_error}。请只返回修正后的完整 JSON；每个来源组仍须恰好一个段落，严格满足 80–260 字和 2–3 个中文句末标点。"},
                ])
            response_value = chat(messages, block_format(len(block)), progress)
            value = normalize_block(response_value)
            validate_block(value, expected_group_ids)
            temporary = cache_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(temporary, cache_path)
            return value
        except (urllib.error.URLError, TimeoutError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            last_error = error
            if response_value is not None:
                previous_value = response_value
            time.sleep(1)
    raise RuntimeError(f"来源组 {expected_group_ids[0]}–{expected_group_ids[-1]} 处理失败：{last_error}")


def overview(blocks):
    outline = [{"id": index + 1, "title": block["title"], "summary": block["summary"]} for index, block in enumerate(blocks)]
    system = """你是严谨的中文视频编辑。根据给定章节提纲，返回且只返回 JSON：
{"title":"视频总标题","summary":"两三句总摘要","section_titles":[{"id":1,"title":"章节标题"}]}。
section_titles 必须覆盖每一个输入 id 一次且仅一次，按原顺序。不要编造事实、不要输出 Markdown 或解释。"""
    value = chat(
        [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(outline, ensure_ascii=False)}],
        overview_format(len(blocks)),
        {"stage": "生成结构", "percent": 92, "block_index": len(blocks), "block_total": len(blocks), "request_block_index": len(blocks)},
    )
    titles = value.get("section_titles") if isinstance(value, dict) else None
    if not isinstance(value.get("title"), str) or not value["title"].strip() or not isinstance(value.get("summary"), str) or not value["summary"].strip():
        raise ValueError("总览缺少标题或摘要")
    if not isinstance(titles, list) or [item.get("id") for item in titles if isinstance(item, dict)] != list(range(1, len(blocks) + 1)):
        raise ValueError("总览章节 ID 无效")
    if any(not isinstance(item.get("title"), str) or not item["title"].strip() for item in titles):
        raise ValueError("总览章节标题为空")
    return value


def overview_format(section_count):
    return {
        "type": "object",
        "required": ["title", "summary", "section_titles"],
        "additionalProperties": False,
        "properties": {
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "section_titles": {
                "type": "array",
                "minItems": section_count,
                "maxItems": section_count,
                "items": {
                    "type": "object",
                    "required": ["id", "title"],
                    "additionalProperties": False,
                    "properties": {"id": {"type": "integer"}, "title": {"type": "string"}},
                },
            },
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("whisper_json", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source", required=True)
    parser.add_argument("--duration-seconds", required=True, type=float)
    parser.add_argument("--cache-dir", type=Path, required=True)
    args = parser.parse_args()
    if PROVIDER not in ("gemini", "ollama"):
        raise ValueError("TRANSCRIPT_PROVIDER 仅支持 gemini 或 ollama")
    started = now()
    whisper = json.loads(args.whisper_json.read_text(encoding="utf-8"))
    segments = source_segments(whisper)
    source_groups = make_source_groups(segments)
    blocks = make_blocks(source_groups)
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    processed = []
    editor_stage = "Gemini 整理" if PROVIDER == "gemini" else "Ollama 整理"
    emit_progress(editor_stage, 35, "正在按时间范围整理文字。", block_index=0, block_total=len(blocks))
    for index, block in enumerate(blocks, start=1):
        progress = {
            "stage": editor_stage,
            "percent": 35 + round((index - 1) / len(blocks) * 55),
            "block_index": index - 1,
            "block_total": len(blocks),
            "request_block_index": index,
        }
        processed.append(process_block(block, args.cache_dir / f"{CACHE_VERSION}-block-{index:03d}.json", progress))
        print(f"已处理第 {index} 块", file=sys.stderr)
        emit_progress(editor_stage, 35 + round(index / len(blocks) * 55), f"正在整理第 {index} / {len(blocks)} 组。", block_index=index, block_total=len(blocks))
    emit_progress("生成结构", 92, "正在汇总标题、摘要与章节。", block_index=len(blocks), block_total=len(blocks))
    meta = overview(processed)
    sections = []
    for index, (block, result) in enumerate(zip(blocks, processed), start=1):
        by_group_id = {item["id"]: item for item in block}
        paragraphs = []
        for item in result["paragraphs"]:
            group = by_group_id[item["source_group_id"]]
            ids = [segment["id"] for segment in group["segments"]]
            paragraphs.append({"start_ms": group["segments"][0]["start_ms"], "end_ms": group["segments"][-1]["end_ms"], "source_segment_ids": ids, "text": item["text"].strip()})
        sections.append({"id": index, "title": meta["section_titles"][index - 1]["title"].strip(), "start_ms": paragraphs[0]["start_ms"], "end_ms": paragraphs[-1]["end_ms"], "paragraphs": paragraphs})
    finished = now()
    result = {"schema_version": "1.0", "source": {"path": str(Path(args.source).resolve()), "duration_seconds": args.duration_seconds, "detected_language": whisper.get("result", {}).get("language", "unknown")}, "models": {"asr": "whisper-large-v3-turbo", "editor": MODEL}, "title": meta["title"].strip(), "summary": meta["summary"].strip(), "sections": sections, "run": {"started_at": started, "finished_at": finished, "elapsed_seconds": max(0, int(datetime.fromisoformat(finished.replace("Z", "+00:00")).timestamp() - datetime.fromisoformat(started.replace("Z", "+00:00")).timestamp()))}}
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, args.output)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(f"JSON 文本处理失败：{error}", file=sys.stderr)
        sys.exit(1)
    finally:
        close_gemini_client()
