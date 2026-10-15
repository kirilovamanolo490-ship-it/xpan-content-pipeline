import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / ".codex/skills/telegram-auto-publish/scripts/send_telegram.py"
SPEC = importlib.util.spec_from_file_location("send_telegram_under_test", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load {SCRIPT_PATH}")
SEND = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SEND)


class SendTelegramTests(unittest.TestCase):
    def _environment(self):
        return {"TELEGRAM_BOT_TOKEN": "secret-token", "TELEGRAM_CHAT_ID": "-100123"}

    def test_check_verifies_bot_channel_membership(self):
        responses = {
            "getMe": {"ok": True, "result": {"id": 88, "username": "publisher_bot"}},
            "getChat": {
                "ok": True,
                "result": {"id": -100123, "type": "channel", "username": "channel"},
            },
            "getChatMember": {
                "ok": True,
                "result": {"status": "administrator", "can_post_messages": True},
            },
        }

        def api_response(**kwargs):
            return responses[kwargs["method"]]

        output = StringIO()
        with patch.object(sys, "argv", ["send_telegram.py", "--check"]), patch.dict(
            os.environ, self._environment(), clear=False
        ), patch.object(SEND, "api_call", side_effect=api_response) as api_call, redirect_stdout(output):
            self.assertEqual(SEND.main(), 0)

        self.assertEqual(
            [call.kwargs["method"] for call in api_call.call_args_list],
            ["getMe", "getChat", "getChatMember"],
        )
        self.assertTrue(json.loads(output.getvalue())["membership"]["can_post_messages"])

    def test_environment_proxy_takes_precedence_over_macos_proxy(self):
        with patch.object(
            SEND.urllib.request,
            "getproxies",
            return_value={"https": "http://proxy.example:8443"},
        ), patch.object(SEND.subprocess, "run") as run:
            proxy_map, network_route = SEND.telegram_proxy_config()

        self.assertEqual(network_route, "environment-proxy")
        self.assertEqual(proxy_map["https"], "http://proxy.example:8443")
        self.assertEqual(proxy_map["http"], "http://proxy.example:8443")
        run.assert_not_called()

    def test_macos_system_proxy_is_used_when_proxy_environment_is_missing(self):
        proxy_output = """
<dictionary> {
  HTTPEnable : 1
  HTTPPort : 7897
  HTTPProxy : 127.0.0.1
  HTTPSEnable : 1
  HTTPSPort : 7897
  HTTPSProxy : 127.0.0.1
}
"""
        completed = subprocess.CompletedProcess(
            ["/usr/sbin/scutil", "--proxy"], 0, stdout=proxy_output, stderr=""
        )
        with patch.object(
            SEND.urllib.request, "getproxies", return_value={"no": "localhost"}
        ), patch.object(SEND.sys, "platform", "darwin"), patch.object(
            SEND.subprocess, "run", return_value=completed
        ):
            proxy_map, network_route = SEND.telegram_proxy_config()

        self.assertEqual(network_route, "macos-system-proxy")
        self.assertEqual(
            proxy_map,
            {
                "http": "http://127.0.0.1:7897",
                "https": "http://127.0.0.1:7897",
            },
        )

    def test_non_macos_without_proxy_environment_uses_direct_route(self):
        with patch.object(SEND.urllib.request, "getproxies", return_value={}), patch.object(
            SEND.sys, "platform", "linux"
        ), patch.object(SEND.subprocess, "run") as run:
            proxy_map, network_route = SEND.telegram_proxy_config()

        self.assertEqual(proxy_map, {})
        self.assertEqual(network_route, "direct")
        run.assert_not_called()

    def test_check_rejects_bot_without_channel_post_permission(self):
        responses = {
            "getMe": {"ok": True, "result": {"id": 88}},
            "getChat": {"ok": True, "result": {"id": -100123, "type": "channel"}},
            "getChatMember": {
                "ok": True,
                "result": {"status": "administrator", "can_post_messages": False},
            },
        }

        with patch.object(sys, "argv", ["send_telegram.py", "--check"]), patch.dict(
            os.environ, self._environment(), clear=False
        ), patch.object(
            SEND,
            "api_call",
            side_effect=lambda **kwargs: responses[kwargs["method"]],
        ):
            with self.assertRaisesRegex(RuntimeError, "not allowed to post"):
                SEND.main()

    def test_small_original_non_mp4_video_uses_bot_api_send_video(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "project-video-original.mkv"
            caption = Path(temp_dir) / "telegram-caption.html"
            video.write_bytes(b"video")
            caption.write_text("高冲击力文案", encoding="utf-8")
            argv = [
                "send_telegram.py", "--video", str(video),
                "--caption-file", str(caption), "--send",
            ]
            with patch.object(sys, "argv", argv), patch.dict(
                os.environ, self._environment(), clear=False
            ), patch.object(
                SEND, "api_call", return_value={"ok": True, "result": {"message_id": 88}}
            ) as api_call:
                self.assertEqual(SEND.main(), 0)

        self.assertEqual(api_call.call_args.kwargs["method"], "sendVideo")
        self.assertEqual(api_call.call_args.kwargs["file_field"], ("video", video))
        self.assertEqual(api_call.call_args.kwargs["fields"]["supports_streaming"], "true")

    def test_small_image_uses_bot_api_send_photo(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image = Path(temp_dir) / "cover.png"
            caption = Path(temp_dir) / "telegram-caption.html"
            image.write_bytes(b"image")
            caption.write_text("图片文案", encoding="utf-8")
            argv = [
                "send_telegram.py", "--image", str(image),
                "--caption-file", str(caption), "--send",
            ]
            with patch.object(sys, "argv", argv), patch.dict(
                os.environ, self._environment(), clear=False
            ), patch.object(
                SEND, "api_call", return_value={"ok": True, "result": {"message_id": 89}}
            ) as api_call:
                self.assertEqual(SEND.main(), 0)

        self.assertEqual(api_call.call_args.kwargs["method"], "sendPhoto")
        self.assertEqual(api_call.call_args.kwargs["file_field"], ("photo", image))

    def test_edit_caption_uses_bot_api_without_media_upload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            caption = Path(temp_dir) / "telegram-caption.html"
            caption.write_text("卧槽，终于改好了！🔥", encoding="utf-8")
            argv = [
                "send_telegram.py", "--edit", "--message-id", "132",
                "--caption-file", str(caption),
            ]
            with patch.object(sys, "argv", argv), patch.dict(
                os.environ, self._environment(), clear=False
            ), patch.object(
                SEND, "api_call", return_value={"ok": True, "result": {"message_id": 132}}
            ) as api_call:
                self.assertEqual(SEND.main(), 0)

        self.assertEqual(api_call.call_args.kwargs["method"], "editMessageCaption")
        self.assertIsNone(api_call.call_args.kwargs.get("file_field"))
        self.assertEqual(api_call.call_args.kwargs["fields"]["message_id"], "132")
        self.assertEqual(api_call.call_args.kwargs["fields"]["parse_mode"], "HTML")

    def test_edit_caption_treats_not_modified_as_idempotent_success(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            caption = Path(temp_dir) / "telegram-caption.html"
            caption.write_text("目标文案🔥", encoding="utf-8")
            argv = [
                "send_telegram.py", "--edit", "--message-id", "132",
                "--caption-file", str(caption),
            ]
            with patch.object(sys, "argv", argv), patch.dict(
                os.environ, self._environment(), clear=False
            ), patch.object(
                SEND,
                "api_call",
                side_effect=RuntimeError(
                    "Telegram API 400: Bad Request: message is not modified: specified new message content"
                ),
            ) as api_call, redirect_stdout(StringIO()) as output:
                self.assertEqual(SEND.main(), 0)

        payload = json.loads(output.getvalue())
        self.assertEqual(payload["mode"], "unchanged")
        self.assertEqual(payload["message_id"], 132)
        api_call.assert_called_once()

    def test_exactly_50mb_video_is_rejected_for_tail_trimming(self):
        self._assert_threshold_rejected("--video", "project-video-original.mp4")

    def test_exactly_50mb_image_is_rejected_for_local_reduction(self):
        self._assert_threshold_rejected("--image", "cover.png")

    def _assert_threshold_rejected(self, media_arg: str, filename: str):
        with tempfile.TemporaryDirectory() as temp_dir:
            media = Path(temp_dir) / filename
            caption = Path(temp_dir) / "telegram-caption.html"
            with media.open("wb") as handle:
                handle.truncate(SEND.BOT_API_MAX_MEDIA_BYTES)
            caption.write_text("边界文案", encoding="utf-8")
            argv = [
                "send_telegram.py", media_arg, str(media),
                "--caption-file", str(caption), "--send",
            ]
            with patch.object(sys, "argv", argv), patch.dict(
                os.environ, self._environment(), clear=False
            ), patch.object(SEND, "api_call") as api_call:
                with self.assertRaisesRegex(RuntimeError, "smaller than 50,000,000 bytes"):
                    SEND.main()
            api_call.assert_not_called()

    def test_dry_run_does_not_send(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image = Path(temp_dir) / "cover.png"
            caption = Path(temp_dir) / "telegram-caption.html"
            image.write_bytes(b"image")
            caption.write_text("预演文案", encoding="utf-8")
            argv = ["send_telegram.py", "--image", str(image), "--caption-file", str(caption)]
            output = StringIO()
            with patch.object(sys, "argv", argv), patch.dict(
                os.environ, self._environment(), clear=False
            ), patch.object(SEND, "api_call") as api_call, redirect_stdout(output):
                self.assertEqual(SEND.main(), 0)

        api_call.assert_not_called()
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["mode"], "dry-run")
        self.assertEqual(payload["transport"], "bot-api")


if __name__ == "__main__":
    unittest.main()
