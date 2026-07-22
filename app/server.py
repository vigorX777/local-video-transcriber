"""Loopback-only API and task runner for the local browser workbench."""
import asyncio
import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_SUPPORT = Path.home() / "Library" / "Application Support" / "Local Video Transcriber"
SETTINGS_PATH = APP_SUPPORT / "settings.json"
KEYCHAIN_SERVICE = "local-video-transcriber"
KEYCHAIN_ACCOUNT = "gemini-api-key"
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
GEMINI_MODELS = ("gemini-2.5-flash", "gemini-2.5-flash-lite")
DEFAULT_SETTINGS = {
    "provider": "gemini",
    "gemini_model": "gemini-2.5-flash",
    "gemini_thinking_budget": 0,
    "gemini_temperature": 0,
    "ollama_model": "qwen2.5:14b-instruct",
    "obsidian_vault": "",
    "obsidian_subdir": "",
}
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def load_settings() -> Dict[str, Any]:
    if not SETTINGS_PATH.exists():
        return dict(DEFAULT_SETTINGS)
    try:
        saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_SETTINGS)
    if not isinstance(saved, dict):
        return dict(DEFAULT_SETTINGS)
    settings = dict(DEFAULT_SETTINGS)
    settings.update({key: saved[key] for key in DEFAULT_SETTINGS if key in saved})
    return validate_settings(settings)


def validate_settings(value: Dict[str, Any]) -> Dict[str, Any]:
    provider = value.get("provider")
    model = str(value.get("gemini_model", ""))
    ollama_model = str(value.get("ollama_model", "")).strip()
    thinking_budget = value.get("gemini_thinking_budget")
    temperature = value.get("gemini_temperature")
    vault = str(value.get("obsidian_vault", "")).strip()
    subdir = str(value.get("obsidian_subdir", "")).strip().strip("/")
    if provider not in {"gemini", "ollama"}:
        raise ValueError("模型提供方仅支持 Gemini 或 Ollama")
    if model not in GEMINI_MODELS:
        raise ValueError("Gemini 模型不在受支持列表中")
    if not ollama_model or len(ollama_model) > 120:
        raise ValueError("Ollama 模型名称无效")
    if not isinstance(thinking_budget, int) or not 0 <= thinking_budget <= 24576:
        raise ValueError("思考预算必须在 0–24576 之间")
    if not isinstance(temperature, (int, float)) or not 0 <= float(temperature) <= 1:
        raise ValueError("温度必须在 0–1 之间")
    if vault and not Path(vault).is_dir():
        raise ValueError("Obsidian Vault 目录不存在")
    if subdir and (Path(subdir).is_absolute() or ".." in Path(subdir).parts):
        raise ValueError("Obsidian 子目录无效")
    return {
        "provider": provider,
        "gemini_model": model,
        "gemini_thinking_budget": thinking_budget,
        "gemini_temperature": float(temperature),
        "ollama_model": ollama_model,
        "obsidian_vault": vault,
        "obsidian_subdir": subdir,
    }


def save_settings(value: Dict[str, Any]) -> Dict[str, Any]:
    settings = validate_settings(value)
    APP_SUPPORT.mkdir(parents=True, exist_ok=True)
    temporary = SETTINGS_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, SETTINGS_PATH)
    return settings


def run_security(args, *, input_text: Optional[str] = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["security", *args],
        input=input_text,
        text=True,
        capture_output=True,
        check=check,
    )


def key_is_configured() -> bool:
    result = run_security(["find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT, "-w"], check=False)
    return result.returncode == 0 and bool(result.stdout.strip())


def read_api_key() -> str:
    result = run_security(["find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT, "-w"], check=False)
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError("尚未在 macOS Keychain 配置 Gemini API Key")
    return result.stdout.strip()


def store_api_key(api_key: str) -> None:
    if not api_key.strip():
        raise ValueError("API Key 不能为空")
    run_security(["add-generic-password", "-U", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT, "-w", api_key.strip()])


def delete_api_key() -> None:
    run_security(["delete-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT], check=False)


def choose_video() -> Optional[Path]:
    result = subprocess.run(
        ["osascript", "-e", 'POSIX path of (choose file with prompt "选择要转写的视频")'],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip())


def choose_directory() -> Optional[Path]:
    result = subprocess.run(
        ["osascript", "-e", 'POSIX path of (choose folder with prompt "选择 Obsidian Vault")'],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip())


def video_metadata(path: Path) -> Dict[str, Any]:
    if not path.is_file() or path.suffix.lower() not in VIDEO_SUFFIXES:
        raise ValueError("请选择常见格式的本地视频文件")
    metadata = {"path": str(path.resolve()), "name": path.name, "size_bytes": path.stat().st_size, "duration_seconds": None}
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        text=True,
        capture_output=True,
    )
    if result.returncode == 0:
        try:
            metadata["duration_seconds"] = round(float(json.loads(result.stdout)["format"]["duration"]), 2)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            pass
    return metadata


def cover_seek_seconds(duration_seconds: Optional[float]) -> float:
    duration = float(duration_seconds or 0)
    return min(60.0, max(8.0, duration * 0.1))


def extract_cover(source: Path, output_dir: Path, duration_seconds: Optional[float]) -> Optional[Path]:
    cover = output_dir / "cover.jpg"
    if cover.is_file():
        return cover
    if not source.is_file() or source.suffix.lower() not in VIDEO_SUFFIXES:
        return None
    output_dir.mkdir(parents=True, exist_ok=True)
    temporary = output_dir / "cover.tmp.jpg"
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-ss", f"{cover_seek_seconds(duration_seconds):.2f}", "-i", str(source),
            "-frames:v", "1", "-q:v", "3", str(temporary),
        ],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0 or not temporary.is_file():
        temporary.unlink(missing_ok=True)
        return None
    os.replace(temporary, cover)
    return cover


def task_output_dir(source: Path) -> Path:
    return PROJECT_ROOT / "outputs" / source.stem


def task_state_path(source: Path) -> Path:
    return task_output_dir(source) / "web-task.json"


def redacted(value: str, source: Optional[str] = None) -> str:
    result = value.replace(str(PROJECT_ROOT), "[项目目录]")
    if source:
        result = result.replace(source, "[源视频]")
    result = re.sub(r"/(?:Users|Library|private|var|System|Applications|opt|tmp)(?:/[^\s'\"(),:]+)+", "[本机路径]", result)
    return result.replace("GEMINI_API_KEY", "Gemini API Key")


class SettingsPayload(BaseModel):
    provider: str
    gemini_model: str
    gemini_thinking_budget: int
    gemini_temperature: float
    ollama_model: str
    obsidian_vault: str = ""
    obsidian_subdir: str = ""


class KeyPayload(BaseModel):
    api_key: str


class TaskPayload(BaseModel):
    source: str


class LocalTask:
    def __init__(self, source: Path, metadata: Dict[str, Any], settings: Dict[str, Any], output_dir: Optional[Path] = None):
        self.id = output_dir.name if output_dir else source.stem
        self.source = source
        self.metadata = metadata
        self.settings = settings
        self._output_dir = output_dir
        self.status = "queued"
        self.stage = "准备开始"
        self.percent = 0
        self.message = "任务已创建，等待启动。"
        self.block_index = 0
        self.block_total = 0
        self.error = ""
        self.logs = []
        self.started_at = ""
        self.finished_at = ""
        self.version = 0
        self.lock = threading.Lock()

    @property
    def output_dir(self) -> Path:
        return self._output_dir or task_output_dir(self.source)

    @property
    def markdown_path(self) -> Path:
        return self.output_dir / "transcript.final.md"

    @property
    def state_path(self) -> Path:
        return task_state_path(self.source)

    def public(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source": {key: self.metadata.get(key) for key in ("name", "size_bytes", "duration_seconds")},
            "status": self.status,
            "stage": self.stage,
            "percent": self.percent,
            "message": self.message,
            "block_index": self.block_index,
            "block_total": self.block_total,
            "error": self.error,
            "logs": self.logs[-80:],
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "has_markdown": self.markdown_path.is_file(),
            "cover_url": f"/api/tasks/{self.id}/cover" if self.source.is_file() or (self.output_dir / "cover.jpg").is_file() else "",
            "model": self.settings["gemini_model"] if self.settings["provider"] == "gemini" else self.settings["ollama_model"],
            "provider": self.settings["provider"],
            "can_retry": self.status in {"failed", "interrupted"},
        }

    def persist(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        payload = self.public()
        payload["source_path"] = str(self.source)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self.state_path)

    def update(self, **changes: Any) -> None:
        with self.lock:
            for key, value in changes.items():
                setattr(self, key, value)
            self.version += 1
            self.persist()

    def append_log(self, line: str) -> None:
        with self.lock:
            self.logs.append(line)
            self.logs = self.logs[-120:]
            self.version += 1
            self.persist()


class TaskManager:
    def __init__(self):
        self.current: Optional[LocalTask] = None
        self.lock = threading.Lock()
        self._recover_latest()

    def _recover_latest(self) -> None:
        candidates = []
        for final_json in (PROJECT_ROOT / "outputs").glob("*/transcript.final.json"):
            try:
                transcript = json.loads(final_json.read_text(encoding="utf-8"))
                source = Path(transcript["source"]["path"])
                candidates.append((final_json.stat().st_mtime, final_json, transcript, source))
            except (OSError, KeyError, TypeError, json.JSONDecodeError):
                continue
        if not candidates:
            return
        _, final_json, transcript, source = max(candidates, key=lambda item: item[0])
        metadata = {
            "name": source.name,
            "size_bytes": source.stat().st_size if source.is_file() else None,
            "duration_seconds": transcript.get("source", {}).get("duration_seconds"),
        }
        task = LocalTask(source, metadata, load_settings(), final_json.parent)
        if not task.markdown_path.is_file():
            return
        task.status = "completed"
        task.stage = "已完成"
        task.percent = 100
        task.message = "已恢复最近一次通过校验的 Markdown。"
        task.finished_at = transcript.get("run", {}).get("finished_at", "")
        self.current = task

    def get_current(self) -> Optional[LocalTask]:
        return self.current

    def start(self, source: Path) -> LocalTask:
        with self.lock:
            if self.current and self.current.status in {"queued", "running"}:
                raise RuntimeError("已有转写任务正在运行，请等待它完成")
            metadata = video_metadata(source)
            settings = load_settings()
            if settings["provider"] == "gemini" and not key_is_configured():
                raise RuntimeError("请先在设置中保存 Gemini API Key")
            task = LocalTask(source, metadata, settings)
            extract_cover(source, task.output_dir, metadata.get("duration_seconds"))
            self.current = task
            task.persist()
            runner = threading.Thread(target=self._run, args=(task,), daemon=True)
            try:
                runner.start()
            except RuntimeError as error:
                task.update(
                    status="failed",
                    stage="无法启动",
                    error="后台转写任务未能启动，请重试。",
                    finished_at=utc_now(),
                )
                raise RuntimeError("后台转写任务未能启动，请重试") from error
            return task

    def retry(self, task_id: str) -> LocalTask:
        with self.lock:
            if not self.current or self.current.id != task_id or self.current.status not in {"failed", "interrupted"}:
                raise RuntimeError("当前任务无法重试")
            source = self.current.source
        return self.start(source)

    def _run(self, task: LocalTask) -> None:
        task.update(status="running", stage="准备开始", message="正在检查本机依赖。", started_at=utc_now())
        env = os.environ.copy()
        env.update({
            "TRANSCRIPT_PROVIDER": task.settings["provider"],
            "GEMINI_MODEL": task.settings["gemini_model"],
            "GEMINI_THINKING_BUDGET": str(task.settings["gemini_thinking_budget"]),
            "GEMINI_TEMPERATURE": str(task.settings["gemini_temperature"]),
            "OLLAMA_MODEL": task.settings["ollama_model"],
        })
        if task.settings["provider"] == "gemini":
            try:
                env["GEMINI_API_KEY"] = read_api_key()
            except RuntimeError as error:
                task.update(status="failed", stage="无法启动", error=str(error), finished_at=utc_now())
                return
        process = subprocess.Popen(
            [str(PROJECT_ROOT / "scripts" / "transcribe-video.sh"), str(task.source)],
            cwd=PROJECT_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for raw_line in iter(process.stdout.readline, ""):
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("@@progress "):
                try:
                    event = json.loads(line[len("@@progress "):])
                    task.update(
                        stage=str(event.get("stage", task.stage)),
                        percent=max(0, min(100, int(event.get("percent", task.percent)))),
                        message=str(event.get("message", task.message)),
                        block_index=int(event.get("block_index", task.block_index or 0)),
                        block_total=int(event.get("block_total", task.block_total or 0)),
                    )
                    continue
                except (TypeError, ValueError, json.JSONDecodeError):
                    pass
            task.append_log(redacted(line, str(task.source)))
        result = process.wait()
        if result == 0 and task.markdown_path.is_file():
            task.update(status="completed", stage="已完成", percent=100, message="Markdown 已生成，可以阅读和导出。", finished_at=utc_now())
        else:
            task.update(status="failed", stage="运行失败", error="转写流程未成功完成，请查看运行日志。", finished_at=utc_now())


manager = TaskManager()
app = FastAPI(title="Local Video Transcriber", docs_url=None, redoc_url=None)


def history_output_dir(record_id: str) -> Path:
    if not record_id or Path(record_id).name != record_id or record_id in {".", ".."}:
        raise HTTPException(status_code=404, detail="历史记录不存在")
    output_dir = PROJECT_ROOT / "outputs" / record_id
    try:
        output_dir.resolve().relative_to((PROJECT_ROOT / "outputs").resolve())
    except ValueError as error:
        raise HTTPException(status_code=404, detail="历史记录不存在") from error
    return output_dir


def load_history_transcript(record_id: str) -> tuple[Path, Dict[str, Any]]:
    output_dir = history_output_dir(record_id)
    final_json = output_dir / "transcript.final.json"
    try:
        transcript = json.loads(final_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=404, detail="历史记录不存在") from error
    if not isinstance(transcript, dict):
        raise HTTPException(status_code=404, detail="历史记录不存在")
    return output_dir, transcript


def history_sort_timestamp(transcript: Dict[str, Any], final_json: Path) -> float:
    finished_at = transcript.get("run", {}).get("finished_at", "")
    if isinstance(finished_at, str):
        try:
            return datetime.fromisoformat(finished_at.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return final_json.stat().st_mtime


def history_record(output_dir: Path, transcript: Dict[str, Any]) -> Dict[str, Any]:
    source = transcript.get("source", {}) if isinstance(transcript.get("source"), dict) else {}
    models = transcript.get("models", {}) if isinstance(transcript.get("models"), dict) else {}
    source_value = source.get("path", "")
    source_path = Path(source_value) if isinstance(source_value, str) and source_value else None
    completed_at = transcript.get("run", {}).get("finished_at", "") if isinstance(transcript.get("run"), dict) else ""
    if not isinstance(completed_at, str) or not completed_at:
        completed_at = datetime.fromtimestamp((output_dir / "transcript.final.json").stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    cover_available = (output_dir / "cover.jpg").is_file() or bool(source_path and source_path.is_file())
    return {
        "id": output_dir.name,
        "title": str(transcript.get("title") or output_dir.name),
        "source_name": source_path.name if source_path else "原始视频",
        "duration_seconds": source.get("duration_seconds"),
        "model": str(models.get("editor") or "未知模型"),
        "completed_at": completed_at,
        "has_markdown": (output_dir / "transcript.final.md").is_file(),
        "cover_url": f"/api/history/{output_dir.name}/cover" if cover_available else "",
    }


def list_history_records() -> list[Dict[str, Any]]:
    records = []
    for final_json in (PROJECT_ROOT / "outputs").glob("*/transcript.final.json"):
        try:
            transcript = json.loads(final_json.read_text(encoding="utf-8"))
            if not isinstance(transcript, dict):
                continue
            records.append((history_sort_timestamp(transcript, final_json), history_record(final_json.parent, transcript)))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return [record for _, record in sorted(records, key=lambda item: item[0], reverse=True)]


def dashboard_summary() -> Dict[str, Any]:
    records = list_history_records()
    now = datetime.now(SHANGHAI_TZ)
    month_seconds = 0.0
    month_count = 0
    for record in records:
        completed_at = record.get("completed_at")
        if not isinstance(completed_at, str):
            continue
        try:
            completed = datetime.fromisoformat(completed_at.replace("Z", "+00:00")).astimezone(SHANGHAI_TZ)
        except ValueError:
            continue
        if (completed.year, completed.month) != (now.year, now.month):
            continue
        month_count += 1
        duration = record.get("duration_seconds")
        if isinstance(duration, (int, float)) and duration >= 0:
            month_seconds += float(duration)
    task = manager.get_current()
    return {
        "current_task": task.public() if task else None,
        "recent_records": records[:4],
        "month": {
            "year_month": now.strftime("%Y-%m"),
            "completed_count": month_count,
            "duration_seconds": round(month_seconds, 2),
        },
    }


def ensure_history_markdown(output_dir: Path) -> Path:
    markdown_path = output_dir / "transcript.final.md"
    if markdown_path.is_file():
        return markdown_path
    result = subprocess.run(
        ["python3", str(PROJECT_ROOT / "scripts" / "export-transcript-markdown.py"), str(output_dir / "transcript.final.json"), str(markdown_path)],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0 or not markdown_path.is_file():
        raise HTTPException(status_code=500, detail="无法从已验证 JSON 生成 Markdown")
    return markdown_path


def settings_response() -> Dict[str, Any]:
    result = load_settings()
    result["gemini_key_configured"] = key_is_configured()
    result["gemini_models"] = GEMINI_MODELS
    return result


@app.get("/api/settings")
def get_settings():
    return settings_response()


@app.put("/api/settings")
def put_settings(payload: SettingsPayload):
    try:
        save_settings(payload.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return settings_response()


@app.put("/api/settings/gemini-key")
def put_key(payload: KeyPayload):
    try:
        store_api_key(payload.api_key)
    except (ValueError, subprocess.SubprocessError) as error:
        raise HTTPException(status_code=400, detail="无法保存 Gemini API Key") from error
    return {"configured": True}


@app.delete("/api/settings/gemini-key")
def remove_key():
    delete_api_key()
    return {"configured": False}


@app.get("/api/models/ollama")
def ollama_models():
    try:
        from urllib.request import urlopen
        with urlopen("http://127.0.0.1:11434/api/tags", timeout=3) as response:
            values = json.loads(response.read().decode("utf-8"))
        return {"models": [item["name"] for item in values.get("models", []) if isinstance(item, dict) and item.get("name")]}
    except Exception:
        return {"models": [], "error": "本机 Ollama 当前不可用"}


@app.post("/api/picker/video")
def pick_video():
    path = choose_video()
    if path is None:
        return {"cancelled": True}
    try:
        return {"cancelled": False, "video": video_metadata(path)}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/picker/vault")
def pick_vault():
    path = choose_directory()
    return {"cancelled": path is None, "path": str(path.resolve()) if path else ""}


@app.post("/api/tasks")
def create_task(payload: TaskPayload):
    source = Path(payload.source).expanduser().resolve()
    try:
        return manager.start(source).public()
    except (RuntimeError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/tasks/current")
def current_task():
    task = manager.get_current()
    return task.public() if task else None


@app.get("/api/dashboard")
def dashboard():
    return dashboard_summary()


@app.post("/api/tasks/{task_id}/retry")
def retry_task(task_id: str):
    try:
        return manager.retry(task_id).public()
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/tasks/{task_id}")
def task_detail(task_id: str):
    task = manager.get_current()
    if not task or task.id != task_id:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task.public()


@app.get("/api/tasks/{task_id}/cover")
def task_cover(task_id: str):
    task = manager.get_current()
    if not task or task.id != task_id:
        raise HTTPException(status_code=404, detail="封面不存在")
    cover = extract_cover(task.source, task.output_dir, task.metadata.get("duration_seconds"))
    if not cover:
        raise HTTPException(status_code=404, detail="封面不存在")
    return FileResponse(cover, media_type="image/jpeg")


@app.get("/api/tasks/{task_id}/events")
async def task_events(task_id: str):
    task = manager.get_current()
    if not task or task.id != task_id:
        raise HTTPException(status_code=404, detail="任务不存在")

    async def stream():
        version = -1
        while True:
            if task.version != version:
                version = task.version
                yield f"event: task\ndata: {safe_json(task.public())}\n\n"
            if task.status in {"completed", "failed"}:
                return
            await asyncio.sleep(0.4)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def locate_task_markdown(task_id: str) -> Path:
    task = manager.get_current()
    if not task or task.id != task_id or not task.markdown_path.is_file():
        raise HTTPException(status_code=404, detail="Markdown 尚未生成")
    return task.markdown_path


@app.get("/api/tasks/{task_id}/markdown")
def markdown(task_id: str):
    path = locate_task_markdown(task_id)
    return FileResponse(path, media_type="text/markdown; charset=utf-8", filename=path.name)


@app.get("/api/tasks/{task_id}/download")
def download_markdown(task_id: str):
    path = locate_task_markdown(task_id)
    task = manager.get_current()
    return FileResponse(
        path,
        media_type="text/markdown; charset=utf-8",
        filename=markdown_download_filename(task.source.name, task.finished_at, path),
    )


@app.get("/api/history")
def history():
    return {"records": list_history_records()}


@app.get("/api/history/{record_id}/cover")
def history_cover(record_id: str):
    output_dir, transcript = load_history_transcript(record_id)
    source = transcript.get("source", {}) if isinstance(transcript.get("source"), dict) else {}
    source_value = source.get("path", "")
    source_path = Path(source_value) if isinstance(source_value, str) and source_value else Path()
    cover = extract_cover(source_path, output_dir, source.get("duration_seconds"))
    if not cover:
        raise HTTPException(status_code=404, detail="封面不存在")
    return FileResponse(cover, media_type="image/jpeg")


def locate_history_markdown(record_id: str) -> Path:
    output_dir, _ = load_history_transcript(record_id)
    return ensure_history_markdown(output_dir)


@app.get("/api/history/{record_id}/markdown")
def history_markdown(record_id: str):
    path = locate_history_markdown(record_id)
    return FileResponse(path, media_type="text/markdown; charset=utf-8", filename=path.name)


@app.get("/api/history/{record_id}/download")
def history_download(record_id: str):
    output_dir, transcript = load_history_transcript(record_id)
    path = ensure_history_markdown(output_dir)
    source = transcript.get("source", {}) if isinstance(transcript.get("source"), dict) else {}
    source_name = source.get("path", "") if isinstance(source.get("path"), str) else ""
    completed_at = transcript.get("run", {}).get("finished_at", "") if isinstance(transcript.get("run"), dict) else ""
    return FileResponse(
        path,
        media_type="text/markdown; charset=utf-8",
        filename=markdown_download_filename(source_name, completed_at, path),
    )


def safe_note_name(value: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]+', "-", value).strip().strip(".")
    return name[:120] or "视频转写稿"


def markdown_download_filename(source_name: str, completed_at: str, markdown_path: Path) -> str:
    try:
        completed = datetime.fromisoformat(completed_at.replace("Z", "+00:00")).astimezone()
    except (AttributeError, ValueError):
        completed = datetime.fromtimestamp(markdown_path.stat().st_mtime)
    return f"{safe_note_name(Path(source_name).stem)}-{completed.strftime('%Y-%m-%d')}.md"


def import_markdown_to_obsidian(source_markdown: Path):
    settings = load_settings()
    vault = Path(settings["obsidian_vault"]).expanduser()
    if not vault.is_dir():
        raise HTTPException(status_code=400, detail="请先在设置中选择 Obsidian Vault")
    target_dir = (vault / settings["obsidian_subdir"]).resolve()
    try:
        target_dir.relative_to(vault.resolve())
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Obsidian 子目录无效") from error
    target_dir.mkdir(parents=True, exist_ok=True)
    raw_title = source_markdown.read_text(encoding="utf-8").splitlines()[0].lstrip("# ").strip()
    basename = safe_note_name(raw_title)
    destination = target_dir / f"{basename}.md"
    sequence = 2
    while destination.exists():
        destination = target_dir / f"{basename} ({sequence}).md"
        sequence += 1
    destination.write_text(source_markdown.read_text(encoding="utf-8"), encoding="utf-8")
    return {"path": str(destination), "name": destination.name}


@app.post("/api/tasks/{task_id}/obsidian")
def import_obsidian(task_id: str):
    return import_markdown_to_obsidian(locate_task_markdown(task_id))


@app.post("/api/history/{record_id}/obsidian")
def import_history_obsidian(record_id: str):
    return import_markdown_to_obsidian(locate_history_markdown(record_id))


STATIC_ROOT = PROJECT_ROOT / "web" / "dist"
if STATIC_ROOT.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_ROOT, html=True), name="web")
