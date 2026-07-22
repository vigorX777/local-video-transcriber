"""Safe yt-dlp integration for public single-video imports."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLATFORM_DOMAINS = {
    "youtube": ("youtube.com", "youtu.be"),
    "bilibili": ("bilibili.com", "b23.tv"),
    "douyin": ("douyin.com", "iesdouyin.com"),
}
MEDIA_SUFFIXES = {
    ".mp4", ".m4v", ".mov", ".mkv", ".webm", ".m4a", ".mp3", ".opus",
    ".ogg", ".aac", ".flac", ".wav",
}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


class NetworkMediaError(RuntimeError):
    def __init__(self, message: str, code: str = "download_failed"):
        super().__init__(message)
        self.code = code


def _platform_for_host(host: str) -> Optional[str]:
    normalized = host.lower().rstrip(".")
    for platform, domains in PLATFORM_DOMAINS.items():
        if any(normalized == domain or normalized.endswith("." + domain) for domain in domains):
            return platform
    return None


def validate_public_media_url(value: str) -> Tuple[str, str]:
    value = value.strip()
    if len(value) > 2048:
        raise NetworkMediaError("链接过长，请检查后重试。", "invalid_url")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise NetworkMediaError("请输入完整的公开视频链接。", "invalid_url")
    host = parsed.hostname.lower().rstrip(".")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise NetworkMediaError("不支持 IP 地址形式的视频链接。", "unsupported_site")
    platform = _platform_for_host(host)
    if not platform:
        raise NetworkMediaError("第一版仅支持 YouTube、B站和抖音的公开单视频链接。", "unsupported_site")
    normalized = urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))
    return platform, normalized


def yt_dlp_path() -> Path:
    override = os.environ.get("YTDLP_BINARY", "").strip()
    candidates = [Path(override)] if override else []
    candidates.append(PROJECT_ROOT / "tools" / "yt-dlp_macos")
    discovered = shutil.which("yt-dlp")
    if discovered:
        candidates.append(Path(discovered))
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise NetworkMediaError("网络下载组件尚未安装，请先运行 ./scripts/setup.sh。", "downloader_missing")


def _safe_text(value: Any, limit: int) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", "", str(value or "")).strip()[:limit]


def _safe_id(value: Any, url: str) -> str:
    candidate = re.sub(r"[^A-Za-z0-9_-]", "-", _safe_text(value, 120)).strip("-")
    return candidate or hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def inspect_network_url(url: str, timeout: int = 75) -> Dict[str, Any]:
    initial_platform, normalized = validate_public_media_url(url)
    command = [
        str(yt_dlp_path()), "--ignore-config", "--no-playlist", "--skip-download",
        "--dump-single-json", "--no-warnings", "--", normalized,
    ]
    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise NetworkMediaError("链接验证超时，请检查网络后重试。", "inspect_timeout") from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).lower()
        if "unsupported url" in detail:
            code, message = "unsupported_site", "暂时无法识别这个链接。"
        elif "private" in detail or "login" in detail or "sign in" in detail or "cookie" in detail:
            code, message = "login_required", "该内容需要登录或 Cookie，第一版暂不支持。"
        elif "not available" in detail or "removed" in detail:
            code, message = "unavailable", "该视频当前不可访问。"
        else:
            code, message = "inspect_failed", "链接验证失败，请确认视频公开可访问后重试。"
        raise NetworkMediaError(message, code)
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise NetworkMediaError("下载组件返回了无法识别的结果。", "inspect_failed") from error
    if data.get("entries") or data.get("_type") in {"playlist", "multi_video"}:
        raise NetworkMediaError("第一版仅支持单视频或单作品链接。", "playlist_unsupported")
    if data.get("is_live") or data.get("live_status") in {"is_live", "is_upcoming", "post_live"}:
        raise NetworkMediaError("第一版暂不支持直播和直播回放。", "live_unsupported")
    webpage_url = _safe_text(data.get("webpage_url") or normalized, 2048)
    resolved_platform, webpage_url = validate_public_media_url(webpage_url)
    platform = resolved_platform or initial_platform
    content_id = _safe_id(data.get("id"), webpage_url)
    if platform == "youtube":
        webpage_url = "https://www.youtube.com/watch?v={}".format(content_id)
    elif platform == "bilibili":
        webpage_url = "https://www.bilibili.com/video/{}".format(content_id)
    else:
        parsed_webpage = urlsplit(webpage_url)
        webpage_url = urlunsplit((parsed_webpage.scheme, parsed_webpage.netloc, parsed_webpage.path, "", ""))
    thumbnail = _safe_text(data.get("thumbnail"), 2048)
    if thumbnail and urlsplit(thumbnail).scheme not in {"http", "https"}:
        thumbnail = ""
    duration = data.get("duration")
    try:
        duration = round(float(duration), 2) if duration is not None else None
    except (TypeError, ValueError):
        duration = None
    return {
        "platform": platform,
        "platform_label": {"youtube": "YouTube", "bilibili": "B站", "douyin": "抖音"}[platform],
        "content_id": content_id,
        "title": _safe_text(data.get("title"), 300) or "未命名视频",
        "author": _safe_text(data.get("uploader") or data.get("channel") or data.get("creator"), 200) or "作者未知",
        "duration_seconds": duration,
        "thumbnail_url": thumbnail,
        "source_url": webpage_url,
    }


def task_id_for(media: Dict[str, Any]) -> str:
    return "network-{}-{}".format(media["platform"], _safe_id(media["content_id"], media["source_url"]))


def _float(value: str) -> Optional[float]:
    match = re.search(r"-?\d+(?:\.\d+)?", value or "")
    return float(match.group()) if match else None


def download_network_media(
    media: Dict[str, Any],
    mode: str,
    download_root: Path,
    progress: Callable[[Dict[str, Any]], None],
) -> Dict[str, Any]:
    if mode not in {"transcribe_only", "keep_video"}:
        raise NetworkMediaError("下载模式无效。", "invalid_mode")
    task_id = task_id_for(media)
    target_dir = download_root / task_id
    target_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = target_dir / "source-manifest.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            cached = Path(manifest["local_media_path"])
            if cached.is_file() and manifest.get("download_mode") == mode:
                manifest["reused"] = True
                return manifest
        except (OSError, KeyError, TypeError, json.JSONDecodeError):
            pass
    prefix = "{}-{}".format(task_id, "video" if mode == "keep_video" else "audio")
    output_template = str(target_dir / (prefix + ".%(ext)s"))
    format_selector = "bv*[height<=1080]+ba/b[height<=1080]" if mode == "keep_video" else "bestaudio/best"
    command = [
        str(yt_dlp_path()), "--ignore-config", "--no-playlist", "--continue", "--newline", "--progress",
        "--write-thumbnail", "--convert-thumbnails", "jpg", "--no-write-info-json",
        "--format", format_selector, "--output", output_template,
        "--progress-template", "download:@@download|%(progress._percent_str)s|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s",
        "--print", "after_move:@@result|%(filepath)s",
    ]
    if mode == "keep_video":
        command.extend(["--merge-output-format", "mp4"])
    command.extend(["--", media["source_url"]])
    process = subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1)
    result_path = None
    tail = []
    for raw in iter(process.stdout.readline, ""):
        line = raw.strip()
        if not line:
            continue
        tail.append(line)
        tail = tail[-15:]
        if line.startswith("@@download|"):
            values = (line.split("|", 6) + [""] * 7)[:7]
            total = _float(values[3]) or _float(values[4])
            progress({
                "percent": _float(values[1]) or 0,
                "downloaded_bytes": int(_float(values[2]) or 0),
                "total_bytes": int(total or 0),
                "speed_bytes": _float(values[5]),
                "eta_seconds": _float(values[6]),
            })
        elif line.startswith("@@result|"):
            result_path = Path(line.split("|", 1)[1])
    return_code = process.wait()
    if return_code != 0:
        raise NetworkMediaError("视频下载未完成，可稍后从下载阶段继续。", "download_failed")
    if not result_path or not result_path.is_file():
        candidates = [path for path in target_dir.glob(prefix + ".*") if path.suffix.lower() in MEDIA_SUFFIXES]
        result_path = max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None
    if not result_path or not result_path.is_file():
        raise NetworkMediaError("下载完成后未找到可转写的媒体文件。", "download_missing")
    covers = [path for path in target_dir.glob(prefix + ".*") if path.suffix.lower() in IMAGE_SUFFIXES]
    cover_path = max(covers, key=lambda path: path.stat().st_mtime) if covers else None
    manifest = {
        **media,
        "kind": "network",
        "download_mode": mode,
        "local_media_path": str(result_path.resolve()),
        "local_cover_path": str(cover_path.resolve()) if cover_path else "",
        "reused": False,
    }
    temporary = manifest_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, manifest_path)
    return manifest
