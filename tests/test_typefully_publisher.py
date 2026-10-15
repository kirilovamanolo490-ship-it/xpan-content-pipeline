import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from urllib.request import Request
from unittest.mock import patch

from xpan_auto.typefully_cli import (
    KNOWLEDGE_GROUP_URL,
    _load_dotenv,
    build_post_text,
    prepare_x_post_text,
    resolve_image_path,
    resolve_media_path,
    validate_typefully_media,
)
from xpan_auto.typefully_publisher import TypefullyClient


class FakeResponse:
    def __init__(self, payload=None, status=200):
        self.status = status
        self._payload = payload

    def read(self):
        if isinstance(self._payload, bytes):
            return self._payload
        if self._payload is None:
            return b""
        return json.dumps(self._payload).encode("utf-8")


class TypefullyPublisherTests(unittest.TestCase):
    def test_loads_dotenv_without_overriding_explicit_environment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            dotenv = Path(temp_dir) / ".env"
            dotenv.write_text(
                'TYPEFULLY_API_KEY="from-file"\nTYPEFULLY_SOCIAL_SET_ID=12345\n',
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"TYPEFULLY_API_KEY": "from-process"}, clear=False):
                os.environ.pop("TYPEFULLY_SOCIAL_SET_ID", None)
                _load_dotenv(dotenv)
                self.assertEqual(os.environ["TYPEFULLY_API_KEY"], "from-process")
                self.assertEqual(os.environ["TYPEFULLY_SOCIAL_SET_ID"], "12345")
                os.environ.pop("TYPEFULLY_SOCIAL_SET_ID", None)

    def test_reuses_x_sidecar_before_legacy_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "assets"
            asset_dir = root / "0001"
            asset_dir.mkdir(parents=True)
            (asset_dir / "x.txt").write_text("X 专用文案\n\nhttps://pan.quark.cn/s/demo", encoding="utf-8")

            text = build_post_text(
                {"资料标题": "旧标题", "文字介绍": "旧介绍"},
                data_index=1,
                asset_root=root,
                workbook_path=Path(temp_dir) / "prepared.xlsx",
            )

        self.assertIn("X 专用文案", text)
        self.assertIn("https://pan.quark.cn/s/demo", text)
        self.assertIn(KNOWLEDGE_GROUP_URL, text)

    def test_prefers_telegram_final_cover_over_source_cover(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "assets"
            asset_dir = root / "0001"
            asset_dir.mkdir(parents=True)
            (asset_dir / "cover.jpg").write_bytes(b"source")
            final_cover = asset_dir / "cover-v1-information-card.png"
            final_cover.write_bytes(b"telegram-final")

            image = resolve_image_path(
                {},
                data_index=1,
                workbook_path=Path(temp_dir) / "prepared.xlsx",
                image_root=root,
            )

        self.assertEqual(image, final_cover.resolve())

    def test_publish_media_prefers_the_typefully_specific_video(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "assets"
            asset_dir = root / "0001"
            asset_dir.mkdir(parents=True)
            original = asset_dir / "project-video-original.mp4"
            original.write_bytes(b"original")
            video = asset_dir / "project-video-x.mp4"
            video.write_bytes(b"x-video")
            (asset_dir / "cover-v1-information-card.png").write_bytes(b"fallback")

            media = resolve_media_path(
                {},
                data_index=1,
                workbook_path=Path(temp_dir) / "prepared.xlsx",
                asset_root=root,
            )

        self.assertEqual(media, video.resolve())

    def test_explicit_typefully_path_wins_over_original_video_column(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "assets"
            asset_dir = root / "0001"
            asset_dir.mkdir(parents=True)
            original = asset_dir / "project-video-original.mp4"
            x_video = asset_dir / "project-video-x.mp4"
            original.write_bytes(b"original")
            x_video.write_bytes(b"x-video")

            media = resolve_media_path(
                {"视频": str(original), "Typefully媒体路径": str(x_video)},
                data_index=1,
                workbook_path=Path(temp_dir) / "prepared.xlsx",
                asset_root=root,
            )

        self.assertEqual(media, x_video.resolve())

    def test_typefully_video_limit_is_channel_specific(self):
        payload = {
            "format": {"duration": "601.0"},
            "streams": [{"codec_type": "video", "codec_name": "h264", "width": 1280, "height": 720}],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "project-video.mp4"
            video.write_bytes(b"video")
            completed = subprocess.CompletedProcess([], 0, stdout=json.dumps(payload), stderr="")
            with patch("xpan_auto.video_quality.shutil.which", return_value="ffprobe"), patch(
                "xpan_auto.video_quality.subprocess.run", return_value=completed
            ):
                error = validate_typefully_media(video)

        self.assertIn("Typefully 视频不符合 X 发布限制", error or "")

    def test_reuses_telegram_caption_without_telegram_inline_links(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "assets"
            asset_dir = root / "0001"
            asset_dir.mkdir(parents=True)
            (asset_dir / "telegram-caption.html").write_text(
                "标题\n\n介绍\n\n🔗 https://pan.quark.cn/s/demo\n\n#标签\n\n"
                '🔔<a href="https://x.com/example">Twitter</a>  '
                '<a href="https://t.me/example">频道</a>\n',
                encoding="utf-8",
            )

            text = build_post_text(
                {"资料标题": "旧标题", "文字介绍": "旧介绍"},
                data_index=1,
                asset_root=root,
                workbook_path=Path(temp_dir) / "prepared.xlsx",
            )

        self.assertIn("#标签", text)
        self.assertNotIn("Twitter", text)
        self.assertNotIn("<a", text)
        self.assertIn(KNOWLEDGE_GROUP_URL, text)

    def test_preserves_standard_chinese_hashtags(self):
        text = prepare_x_post_text("内容\n\n#PPT设计 #课程分享")

        self.assertIn("#PPT设计", text)
        self.assertIn("#课程分享", text)
        self.assertNotIn("\u200c", text)
        self.assertEqual(text.count(KNOWLEDGE_GROUP_URL), 1)

    def test_create_draft_includes_media_and_keeps_draft_mode(self):
        requests = []

        def transport(request: Request, timeout: float):
            requests.append(request)
            return FakeResponse({"id": 123, "status": "draft", "private_url": "https://typefully.com/?d=123"}, 201)

        client = TypefullyClient("secret", base_url="https://example.test", transport=transport)
        draft = client.create_draft("456", text="hello", media_ids=("media-1",))

        self.assertEqual(draft.draft_id, "123")
        self.assertEqual(requests[0].full_url, "https://example.test/v2/social-sets/456/drafts")
        payload = json.loads(requests[0].data.decode("utf-8"))
        self.assertEqual(payload["platforms"]["x"]["posts"][0]["media_ids"], ["media-1"])
        self.assertNotIn("publish_at", payload)

    def test_lists_social_sets_for_configuration(self):
        requests = []

        def transport(request: Request, timeout: float):
            requests.append(request)
            return FakeResponse({"results": [{"id": 123, "name": "X account", "username": "example"}]})

        client = TypefullyClient("secret", base_url="https://example.test", transport=transport)
        response = client.list_social_sets()

        self.assertEqual(requests[0].method, "GET")
        self.assertEqual(requests[0].full_url, "https://example.test/v2/social-sets")
        self.assertEqual(response["results"][0]["id"], 123)

    def test_create_x_draft_uploads_local_media_then_creates_draft(self):
        requests = []

        def transport(request: Request, timeout: float):
            requests.append(request)
            if request.method == "POST" and request.full_url.endswith("/media/upload"):
                return FakeResponse({"media_id": "media-1", "upload_url": "https://upload.test/media-1"}, 201)
            if request.full_url == "https://upload.test/media-1":
                return FakeResponse(None, 200)
            if request.method == "GET" and "/media/media-1" in request.full_url:
                return FakeResponse({"media_id": "media-1", "status": "ready"}, 200)
            return FakeResponse({"id": 123, "status": "draft"}, 201)

        with tempfile.TemporaryDirectory() as temp_dir:
            image = Path(temp_dir) / "cover.jpg"
            image.write_bytes(b"image")
            client = TypefullyClient(
                "secret",
                base_url="https://example.test",
                transport=transport,
                sleeper=lambda _: None,
            )
            draft = client.create_x_draft("456", text="hello", image_path=image)

        self.assertEqual(draft.draft_id, "123")
        self.assertEqual(requests[1].full_url, "https://upload.test/media-1")
        self.assertEqual(requests[1].data, b"image")

    def test_create_x_draft_accepts_video_through_generic_media_path(self):
        requests = []

        def transport(request: Request, timeout: float):
            requests.append(request)
            if request.method == "POST" and request.full_url.endswith("/media/upload"):
                return FakeResponse({"media_id": "video-1", "upload_url": "https://upload.test/video-1"}, 201)
            if request.full_url == "https://upload.test/video-1":
                return FakeResponse(None, 200)
            if request.method == "GET" and "/media/video-1" in request.full_url:
                return FakeResponse({"media_id": "video-1", "status": "ready"}, 200)
            return FakeResponse({"id": 124, "status": "draft"}, 201)

        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "project-video.mp4"
            video.write_bytes(b"video-bytes")
            client = TypefullyClient(
                "secret",
                base_url="https://example.test",
                transport=transport,
                sleeper=lambda _: None,
            )
            draft = client.create_x_draft("456", text="hello", media_path=video)

        self.assertEqual(draft.draft_id, "124")
        self.assertEqual(requests[1].data, b"video-bytes")


if __name__ == "__main__":
    unittest.main()
