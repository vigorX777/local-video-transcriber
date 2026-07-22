import importlib.util
import time
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "process-transcript.py"
SPEC = importlib.util.spec_from_file_location("process_transcript", MODULE_PATH)
process_transcript = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(process_transcript)


class ProcessTranscriptTests(unittest.TestCase):
    def tearDown(self):
        process_transcript.close_gemini_client()

    def test_gemini_client_uses_ipv4_and_split_timeouts(self):
        with patch.object(process_transcript.urllib.request, "getproxies", return_value={}):
            process_transcript.gemini_client("test-key")
        http_client = process_transcript._gemini_httpx_client
        self.assertEqual(http_client._transport._pool._local_address, "0.0.0.0")
        self.assertEqual(http_client._timeout.connect, 8)
        self.assertEqual(http_client._timeout.write, 30)
        self.assertEqual(http_client._timeout.read, 120)

    def test_heartbeat_reports_waiting_request(self):
        progress = {
            "stage": "Gemini 整理",
            "percent": 39,
            "block_index": 1,
            "block_total": 13,
            "request_block_index": 2,
        }
        original_interval = process_transcript.GEMINI_HEARTBEAT_SECONDS
        process_transcript.GEMINI_HEARTBEAT_SECONDS = 0.01
        try:
            with patch.object(process_transcript, "emit_progress") as emit:
                result = process_transcript.request_with_heartbeat(
                    lambda: (time.sleep(0.03), "ok")[1], progress, 1
                )
            self.assertEqual(result, "ok")
            self.assertTrue(any(call.kwargs.get("waited_seconds", 0) >= 0 for call in emit.call_args_list))
        finally:
            process_transcript.GEMINI_HEARTBEAT_SECONDS = original_interval

    def test_retry_policy_only_includes_transient_http_statuses(self):
        self.assertTrue(process_transcript.retryable_gemini_error(process_transcript.httpx.ConnectTimeout("timeout")))
        self.assertFalse(process_transcript.retryable_gemini_error(process_transcript.genai_errors.ClientError(403, {})))
        self.assertTrue(process_transcript.retryable_gemini_error(process_transcript.genai_errors.ServerError(503, {})))

    def test_source_segments_excludes_zero_duration_artifacts(self):
        segments, excluded = process_transcript.source_segments({"transcription": [
            {"text": "有效分段", "offsets": {"from": 0, "to": 500}},
            {"text": "重复重复", "offsets": {"from": 500, "to": 500}},
            {"text": "后续分段", "offsets": {"from": 500, "to": 900}},
        ]})
        self.assertEqual([item["id"] for item in segments], [0, 2])
        self.assertEqual(excluded, [{"id": 1, "reason": "non_positive_duration", "start_ms": 500, "end_ms": 500}])

    def test_source_segments_rejects_excessive_invalid_data(self):
        with self.assertRaisesRegex(ValueError, "无效分段过多"):
            process_transcript.source_segments({"transcription": [
                {"text": "无效", "offsets": {"from": 0, "to": 0}}
                for _ in range(11)
            ]})


if __name__ == "__main__":
    unittest.main()
