import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app.server as server


class ServerTests(unittest.TestCase):
    def test_settings_reject_remote_provider(self):
        with self.assertRaises(ValueError):
            server.validate_settings({**server.DEFAULT_SETTINGS, "provider": "remote"})

    def test_note_name_removes_unsafe_characters(self):
        self.assertEqual(server.safe_note_name('a/b:c?d*e'), "a-b-c-d-e")

    def test_markdown_download_name_uses_video_name_and_completion_date(self):
        filename = server.markdown_download_filename(
            '有的“天才文学少女”才9岁就是老登了.mp4',
            "2026-07-21T14:49:32Z",
            Path(__file__),
        )
        self.assertEqual(filename, '有的“天才文学少女”才9岁就是老登了-2026-07-21.md')

    def test_task_payload_never_exposes_source_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "private-video.mp4"
            source.touch()
            task = server.LocalTask(source, {"name": source.name, "size_bytes": 1, "duration_seconds": 1}, server.DEFAULT_SETTINGS)
            self.assertNotIn("source_path", task.public())
            self.assertNotIn(str(source), str(task.public()))

    def test_log_redaction_hides_other_absolute_paths(self):
        value = server.redacted("warning from /Users/example/Library/Python/site-packages/module.py")
        self.assertNotIn("/Users/example", value)
        self.assertIn("[本机路径]", value)

    def test_processing_failure_detail_exposes_only_the_safe_validation_reason(self):
        detail = server.processing_failure_detail([
            "已复用已有 Whisper 结果。",
            "JSON 文本处理失败：来源组 0–3 处理失败：来源组 0 段落长度为 278，必须在 60–320 字之间",
        ])
        self.assertEqual(detail, "来源组 0–3 处理失败：来源组 0 段落长度为 278，必须在 60–320 字之间")

    def test_network_retry_reuses_persisted_source_manifest_without_preflight(self):
        manager = server.TaskManager()
        task = server.LocalTask(
            Path("/tmp/network-bilibili-BVtest"),
            {"name": "公开单视频", "size_bytes": None, "duration_seconds": 60},
            server.DEFAULT_SETTINGS,
            Path("/tmp/network-bilibili-BVtest-output"),
            {"platform": "bilibili", "content_id": "BVtest", "source_url": "https://www.bilibili.com/video/BVtest"},
            "keep_video",
        )
        task.status = "failed"
        manager.current = task
        with patch.object(manager, "start_network", return_value=task) as start_network:
            self.assertIs(manager.retry(task.id), task)
        start_network.assert_called_once_with(task.origin, "keep_video", resume=True)

    def test_cover_seek_time_is_bounded_and_uses_video_progress(self):
        self.assertEqual(server.cover_seek_seconds(None), 8)
        self.assertEqual(server.cover_seek_seconds(20), 8)
        self.assertEqual(server.cover_seek_seconds(580), 58)
        self.assertEqual(server.cover_seek_seconds(3600), 60)

    def test_history_records_are_sorted_and_hide_source_paths(self):
        original_root = server.PROJECT_ROOT
        try:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                server.PROJECT_ROOT = root
                source = root / "private" / "source.mp4"
                for record_id, finished_at, title in [
                    ("older-run", "2026-07-20T10:00:00Z", "较早的文稿"),
                    ("same-name-benchmark", "2026-07-21T10:00:00Z", "较新的文稿"),
                ]:
                    output = root / "outputs" / record_id
                    output.mkdir(parents=True)
                    (output / "transcript.final.json").write_text(
                        server.json.dumps({
                            "source": {"path": str(source), "duration_seconds": 60},
                            "models": {"editor": "gemini-2.5-flash"},
                            "title": title,
                            "run": {"finished_at": finished_at},
                        }, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    (output / "transcript.final.md").write_text(f"# {title}\n", encoding="utf-8")
                records = server.list_history_records()
                self.assertEqual([record["id"] for record in records], ["same-name-benchmark", "older-run"])
                self.assertEqual(records[0]["source_name"], "source.mp4")
                self.assertNotIn(str(source), server.json.dumps(records, ensure_ascii=False))
        finally:
            server.PROJECT_ROOT = original_root

    def test_dashboard_uses_verified_history_without_source_paths(self):
        original_root = server.PROJECT_ROOT
        original_task = server.manager.current
        try:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                output = root / "outputs" / "verified-run"
                output.mkdir(parents=True)
                source = root / "private" / "video.mp4"
                now = server.datetime.now(server.SHANGHAI_TZ).replace(microsecond=0)
                (output / "transcript.final.json").write_text(
                    server.json.dumps({
                        "source": {"path": str(source), "duration_seconds": 95},
                        "models": {"editor": "gemini-2.5-flash"},
                        "title": "首页统计测试",
                        "run": {"finished_at": now.isoformat()},
                    }, ensure_ascii=False),
                    encoding="utf-8",
                )
                server.PROJECT_ROOT = root
                server.manager.current = None
                summary = server.dashboard_summary()
                self.assertEqual(summary["month"]["completed_count"], 1)
                self.assertEqual(summary["month"]["duration_seconds"], 95)
                self.assertEqual(summary["recent_records"][0]["title"], "首页统计测试")
                self.assertNotIn(str(source), server.json.dumps(summary, ensure_ascii=False))
        finally:
            server.PROJECT_ROOT = original_root
            server.manager.current = original_task

    def test_task_starts_in_a_background_thread(self):
        original_root = server.PROJECT_ROOT
        original_task = server.manager.current
        try:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / "input.mp4"
                source.touch()
                server.PROJECT_ROOT = root
                server.manager.current = None
                metadata = {"name": source.name, "size_bytes": 1, "duration_seconds": 60}
                with patch.object(server, "video_metadata", return_value=metadata), patch.object(server, "load_settings", return_value=server.DEFAULT_SETTINGS), patch.object(server, "key_is_configured", return_value=True), patch.object(server, "extract_cover", return_value=None), patch.object(server.threading, "Thread") as create_thread:
                    task = server.manager.start(source)
                create_thread.assert_called_once()
                create_thread.return_value.start.assert_called_once()
                self.assertEqual(task.status, "queued")
        finally:
            server.PROJECT_ROOT = original_root
            server.manager.current = original_task

    def test_completed_network_task_keeps_network_metadata_after_restart(self):
        original_root = server.PROJECT_ROOT
        try:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                output = root / "outputs" / "network-bilibili-BVtest"
                media = root / "downloads" / "network-bilibili-BVtest-video.mp4"
                output.mkdir(parents=True)
                media.parent.mkdir(parents=True)
                media.touch()
                (output / "transcript.final.json").write_text(server.json.dumps({
                    "source": {"path": str(media), "duration_seconds": 55},
                    "title": "测试文稿",
                    "run": {"finished_at": "2026-07-22T09:00:00Z"},
                }), encoding="utf-8")
                (output / "transcript.final.md").write_text("# 测试文稿\n", encoding="utf-8")
                (output / "web-task.json").write_text(server.json.dumps({
                    "source_kind": "network",
                    "status": "completed",
                    "stage": "已完成",
                    "percent": 100,
                    "message": "已补齐原视频，已有文稿未重复转写。",
                    "source_path": str(media),
                    "download_mode": "keep_video",
                    "source": {
                        "name": "公开单视频",
                        "size_bytes": 3,
                        "duration_seconds": 55,
                    },
                    "origin": {
                        "platform": "bilibili",
                        "platform_label": "B站",
                        "content_id": "BVtest",
                        "title": "公开单视频",
                        "author": "作者",
                        "duration_seconds": 55,
                        "source_url": "https://www.bilibili.com/video/BVtest",
                    },
                }), encoding="utf-8")
                server.PROJECT_ROOT = root
                with patch.object(server, "load_settings", return_value=server.DEFAULT_SETTINGS):
                    recovered = server.TaskManager().current
                self.assertEqual(recovered.status, "completed")
                self.assertEqual(recovered.source_kind, "network")
                self.assertEqual(recovered.origin["platform_label"], "B站")
                self.assertEqual(recovered.metadata["name"], "公开单视频")
                self.assertEqual(len(recovered.public()["stages"]), 7)
        finally:
            server.PROJECT_ROOT = original_root

    def test_obsidian_import_keeps_existing_note(self):
        original_root = server.PROJECT_ROOT
        original_task = server.manager.current
        try:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / "input.mp4"
                source.touch()
                server.PROJECT_ROOT = root
                task = server.LocalTask(source, {"name": source.name, "size_bytes": 1, "duration_seconds": 1}, server.DEFAULT_SETTINGS)
                task.markdown_path.parent.mkdir(parents=True)
                task.markdown_path.write_text("# 测试文稿\n\n正文。\n", encoding="utf-8")
                server.manager.current = task
                vault = root / "vault"
                vault.mkdir()
                settings = {**server.DEFAULT_SETTINGS, "obsidian_vault": str(vault), "obsidian_subdir": "收件箱"}
                with patch.object(server, "load_settings", return_value=settings):
                    first = server.import_obsidian(task.id)
                    second = server.import_obsidian(task.id)
                first_path = Path(first["path"])
                second_path = Path(second["path"])
                self.assertTrue(first_path.is_file())
                self.assertTrue(second_path.is_file())
                self.assertNotEqual(first_path, second_path)
                self.assertEqual(first_path.read_text(encoding="utf-8"), second_path.read_text(encoding="utf-8"))
        finally:
            server.PROJECT_ROOT = original_root
            server.manager.current = original_task


if __name__ == "__main__":
    unittest.main()
