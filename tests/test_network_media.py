import json
import subprocess
import unittest
from unittest.mock import patch

from app.network_media import NetworkMediaError, inspect_network_url, task_id_for, validate_public_media_url


class NetworkMediaTests(unittest.TestCase):
    def test_url_allowlist_accepts_supported_sites_and_rejects_local_targets(self):
        self.assertEqual(validate_public_media_url("https://www.youtube.com/watch?v=abc")[0], "youtube")
        self.assertEqual(validate_public_media_url("https://www.bilibili.com/video/BV1abc")[0], "bilibili")
        self.assertEqual(validate_public_media_url("https://v.douyin.com/example/")[0], "douyin")
        with self.assertRaises(NetworkMediaError):
            validate_public_media_url("http://127.0.0.1:8765/private")
        with self.assertRaises(NetworkMediaError):
            validate_public_media_url("https://example.com/video")

    @patch("app.network_media.yt_dlp_path")
    @patch("app.network_media.subprocess.run")
    def test_inspect_returns_only_sanitized_single_video_metadata(self, run, binary):
        binary.return_value = "/tmp/yt-dlp"
        run.return_value = subprocess.CompletedProcess([], 0, stdout=json.dumps({
            "id": "BaW_jenozKc",
            "title": "Test\u0000 Video",
            "uploader": "yt-dlp",
            "duration": 10.0,
            "thumbnail": "https://i.ytimg.com/example.jpg",
            "webpage_url": "https://www.youtube.com/watch?v=BaW_jenozKc",
        }), stderr="")
        result = inspect_network_url("https://youtu.be/BaW_jenozKc")
        self.assertEqual(result["platform"], "youtube")
        self.assertEqual(result["title"], "Test Video")
        self.assertNotIn("path", result)
        self.assertEqual(task_id_for(result), "network-youtube-BaW_jenozKc")

    @patch("app.network_media.yt_dlp_path")
    @patch("app.network_media.subprocess.run")
    def test_inspect_rejects_playlists(self, run, binary):
        binary.return_value = "/tmp/yt-dlp"
        run.return_value = subprocess.CompletedProcess([], 0, stdout=json.dumps({
            "_type": "playlist", "entries": [{"id": "one"}],
        }), stderr="")
        with self.assertRaisesRegex(NetworkMediaError, "单视频"):
            inspect_network_url("https://www.youtube.com/playlist?list=test")


if __name__ == "__main__":
    unittest.main()
