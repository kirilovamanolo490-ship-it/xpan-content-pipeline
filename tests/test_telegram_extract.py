import io
import importlib.util
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image, ImageDraw


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from xpan_auto.telegram_quality import measure_cover_activity
from xpan_auto.video_quality import VideoPreparationReport, VideoQualityReport


def _video_report(path: Path, *, size: int, duration: float) -> VideoQualityReport:
    return VideoQualityReport(
        True,
        (),
        str(path),
        size,
        duration,
        1280,
        720,
        "h264",
        "aac",
    )


def _load_script_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load script module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXTRACT = _load_script_module(
    "telegram_extract_under_test",
    PROJECT_ROOT / ".codex/skills/telegram-auto-publish/scripts/extract_quark_project.py",
)
PREPARE = _load_script_module(
    "telegram_prepare_under_test",
    PROJECT_ROOT / ".codex/skills/telegram-auto-publish/scripts/prepare_telegram_asset.py",
)


def _item(fid: str, name: str, *, is_dir: bool = False, parent: str = "0") -> SimpleNamespace:
    return SimpleNamespace(
        fid=fid,
        name=name,
        is_dir=is_dir,
        pdir_fid=parent,
        include_items=[],
    )


def _write_detailed_frame(path: Path) -> None:
    image = Image.new("RGB", (640, 360), (24, 34, 48))
    draw = ImageDraw.Draw(image)
    for x in range(0, 640, 32):
        draw.line((x, 0, 640 - x // 2, 359), fill=(70 + x % 150, 180, 210), width=3)
    draw.ellipse((250, 70, 410, 300), fill=(214, 156, 112), outline=(250, 230, 190), width=5)
    image.save(path, format="PNG")


class TelegramExtractTests(unittest.TestCase):
    def test_quark_auto_save_download_runs_exact_file_download_command(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            auto_save_dir = root / "quark-auto-save"
            auto_save_dir.mkdir()
            (auto_save_dir / "download_first_video.py").write_text("# helper\n", encoding="utf-8")
            config_file = root / "quark-storage.json"
            config_file.write_text("{}", encoding="utf-8")
            asset_dir = root / "assets"
            asset_dir.mkdir()
            calls = []

            def run(command, **_kwargs):
                calls.append(command)
                output_dir = Path(command[3])
                downloaded = output_dir / "导学.mp4"
                downloaded.write_bytes(b"video")
                return SimpleNamespace(returncode=0, stdout="Downloaded 5 bytes", stderr="")

            with patch.object(EXTRACT.subprocess, "run", side_effect=run):
                downloaded = EXTRACT._quark_auto_save_download(
                    "video-fid",
                    asset_dir,
                    auto_save_dir=auto_save_dir,
                    config_file=config_file,
                    file_name="导学.mp4",
                    expected_size=5,
                    cloud_path="课程/导学.mp4",
                )

            self.assertEqual(downloaded.name, "导学.mp4")
            command = calls[-1]
            self.assertEqual(Path(command[0]), Path(sys.executable))
            self.assertEqual(command[2], "课程/导学.mp4")
            self.assertEqual(command[3], str(asset_dir / ".quark-download"))
            self.assertEqual(command[command.index("--fid") + 1], "video-fid")
            self.assertEqual(command[command.index("--file-name") + 1], "导学.mp4")
            self.assertEqual(command[command.index("--expected-size") + 1], "5")
            self.assertEqual(command[command.index("--config") + 1], str(config_file))

    def test_publish_video_keeps_only_original_from_exactly_the_first_video(self):
        records = [
            {
                "type": "file",
                "extension": ".mp4",
                "name": "第二课.mp4",
                "fid": "video-2",
                "depth": 0,
                "path": "第二课.mp4",
                "size_bytes": 20,
            },
            {
                "type": "file",
                "extension": ".mp4",
                "name": "导学试看.mp4",
                "fid": "video-1",
                "depth": 0,
                "path": "导学试看.mp4",
                "size_bytes": 30,
            },
        ]
        adapter = SimpleNamespace(headers={})
        with tempfile.TemporaryDirectory() as temp_dir:
            asset_dir = Path(temp_dir)
            for stale_name in ("project-video.mp4", "project-video-x.mp4", "project-video-telegram.mp4"):
                (asset_dir / stale_name).write_bytes(b"stale")
            downloaded = asset_dir / ".quark-download" / "第二课.mp4"
            downloaded.parent.mkdir()
            downloaded.write_bytes(b"downloaded")
            final_path = asset_dir / "project-video-original.mp4"
            report = _video_report(final_path, size=len(b"downloaded"), duration=60.0)
            preparation = VideoPreparationReport(
                True, report, report, False, False, False, 600.0, 50_000_000, 49_000_000
            )
            with patch.object(
                EXTRACT, "_quark_auto_save_download", return_value=downloaded
            ) as quark_download, patch(
                "xpan_auto.video_quality.inspect_publish_video", return_value=report
            ), patch(
                "xpan_auto.video_quality.prepare_publish_video", return_value=preparation
            ):
                result = EXTRACT._prepare_publish_video(
                    adapter,
                    records,
                    asset_dir,
                    share_link="",
                    video_name="project-video",
                    quark_auto_save_dir=Path("C:/quark-auto-save"),
                    quark_cookie_file=Path("C:/quark-storage.json"),
                    force_refresh=True,
                )

            self.assertEqual(result["kind"], "project-video")
            self.assertEqual(result["source_name"], "第二课.mp4")
            self.assertEqual(Path(result["original_path"]), asset_dir / "project-video-original.mp4")
            self.assertEqual(Path(result["source_path"]), asset_dir / "project-video-original.mp4")
            self.assertEqual(result["telegram_route"], "bot-api")
            self.assertNotIn("typefully_path", result)
            self.assertNotIn("telegram_path", result)
            self.assertEqual(
                sorted(path.name for path in asset_dir.glob("*.mp4")),
                ["project-video-original.mp4"],
            )
            quark_download.assert_called_once_with(
                "video-2",
                asset_dir,
                auto_save_dir=Path("C:/quark-auto-save"),
                config_file=Path("C:/quark-storage.json"),
                file_name="第二课.mp4",
                expected_size=20,
                cloud_path="第二课.mp4",
            )

    def test_publish_video_uses_typefully_remuxed_mp4_path(self):
        records = [
            {
                "type": "file",
                "extension": ".mkv",
                "name": "第一课.mkv",
                "fid": "video-1",
                "depth": 0,
                "path": "第一课.mkv",
                "size_bytes": 9,
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            asset_dir = Path(temp_dir)
            downloaded = asset_dir / ".quark-download" / "第一课.mkv"
            downloaded.parent.mkdir()
            downloaded.write_bytes(b"mkv-video")
            source_path = asset_dir / "project-video-original.mkv"
            final_path = asset_dir / "project-video-original.mp4"
            source_report = _video_report(source_path, size=9, duration=60.0)
            final_report = _video_report(final_path, size=8, duration=60.0)

            def prepare(path, **kwargs):
                final_path.write_bytes(b"mp4-file")
                Path(path).unlink(missing_ok=True)
                return VideoPreparationReport(
                    True,
                    source_report,
                    final_report,
                    False,
                    False,
                    True,
                    600.0,
                    50_000_000,
                    49_000_000,
                )

            with patch.object(
                EXTRACT, "_quark_auto_save_download", return_value=downloaded
            ), patch(
                "xpan_auto.video_quality.inspect_publish_video", return_value=source_report
            ), patch(
                "xpan_auto.video_quality.prepare_publish_video", side_effect=prepare
            ):
                result = EXTRACT._prepare_publish_video(
                    SimpleNamespace(headers={}),
                    records,
                    asset_dir,
                    share_link="",
                    video_name="project-video",
                    quark_auto_save_dir=Path("C:/quark-auto-save"),
                    quark_cookie_file=Path("C:/quark-storage.json"),
                    force_refresh=True,
                )

            self.assertEqual(Path(result["publish_path"]), final_path)
            self.assertTrue(result["container_remuxed"])
            self.assertTrue(final_path.is_file())
            self.assertFalse(source_path.exists())

    def test_117mb_source_is_reduced_and_routed_to_bot_api(self):
        records = [
            {
                "type": "file",
                "extension": ".mp4",
                "name": "1.为什么要使用QEMU学习嵌入式开发.mp4",
                "fid": "first-video",
                "depth": 0,
                "path": "1.为什么要使用QEMU学习嵌入式开发.mp4",
                "size": 117_657_722,
            }
        ]
        events = []

        with tempfile.TemporaryDirectory() as temp_dir:
            asset_dir = Path(temp_dir)
            downloaded = asset_dir / ".quark-download" / records[0]["name"]
            downloaded.parent.mkdir()
            with downloaded.open("wb") as handle:
                handle.truncate(117_657_722)

            final_path = asset_dir / "project-video-original.mp4"
            source_report = _video_report(final_path, size=117_657_722, duration=700.0)
            final_report = _video_report(final_path, size=49_000_000, duration=580.0)

            def inspect(path, **kwargs):
                events.append(("inspect", Path(path).name, kwargs.get("max_size_bytes")))
                return source_report

            def prepare(path, **kwargs):
                events.append(("prepare", Path(path).name, kwargs.get("max_duration_seconds")))
                with Path(path).open("wb") as handle:
                    handle.truncate(49_000_000)
                return VideoPreparationReport(
                    True,
                    source_report,
                    final_report,
                    True,
                    True,
                    False,
                    600.0,
                    50_000_000,
                    49_000_000,
                )

            with patch.object(EXTRACT, "_quark_auto_save_download", return_value=downloaded), patch(
                "xpan_auto.video_quality.inspect_publish_video", side_effect=inspect
            ), patch(
                "xpan_auto.video_quality.prepare_publish_video", side_effect=prepare
            ):
                result = EXTRACT._prepare_publish_video(
                    SimpleNamespace(headers={}),
                    records,
                    asset_dir,
                    share_link="https://pan.quark.cn/s/example",
                    video_name="project-video",
                    quark_auto_save_dir=Path("C:/quark-auto-save"),
                    quark_cookie_file=Path("C:/quark-storage.json"),
                    force_refresh=True,
                )

            self.assertEqual(Path(result["original_path"]).stat().st_size, 49_000_000)
            self.assertEqual(
                events,
                [
                    ("inspect", "project-video-original.mp4", 2**63 - 1),
                    ("prepare", "project-video-original.mp4", 600.0),
                ],
            )
            self.assertTrue(result["duration_trimmed"])
            self.assertTrue(result["size_trimmed"])
            self.assertEqual(result["telegram_route"], "bot-api")
            self.assertEqual(list(asset_dir.glob("project-video*.mp4")), [asset_dir / "project-video-original.mp4"])

    def test_original_download_failure_never_creates_platform_derivatives(self):
        records = [
            {
                "type": "file",
                "extension": ".mp4",
                "name": "首课.mp4",
                "fid": "first-video",
                "depth": 0,
                "path": "首课.mp4",
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            EXTRACT,
            "_quark_auto_save_download",
            side_effect=RuntimeError("夸克原视频下载阶段失败：服务端拒绝"),
        ):
            with self.assertRaisesRegex(RuntimeError, "完整下载、源质检和发布视频截断"):
                EXTRACT._prepare_publish_video(
                    SimpleNamespace(headers={}),
                    records,
                    Path(temp_dir),
                    share_link="https://pan.quark.cn/s/example",
                    video_name="project-video",
                    quark_auto_save_dir=Path("C:/quark-auto-save"),
                    quark_cookie_file=Path("C:/quark-storage.json"),
                    force_refresh=True,
                )
            self.assertFalse(any(Path(temp_dir).glob("project-video*.mp4")))

    def test_publish_video_does_not_fall_back_when_video_candidates_fail(self):
        records = [
            {
                "type": "file",
                "extension": ".mp4",
                "name": "课程.mp4",
                "fid": "video-1",
                "depth": 0,
                "path": "课程.mp4",
            },
            {
                "type": "file",
                "extension": ".png",
                "name": "封面.png",
                "fid": "image-1",
                "depth": 0,
                "path": "封面.png",
            },
            {
                "type": "file",
                "extension": ".mp4",
                "name": "备用课程.mp4",
                "fid": "video-2",
                "depth": 0,
                "path": "备用课程.mp4",
            },
        ]
        adapter = SimpleNamespace(headers={})
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(
                EXTRACT, "_quark_auto_save_download", side_effect=RuntimeError("download failed")
            ) as download, patch.object(EXTRACT, "_public_video_metadata") as public_video:
                with self.assertRaisesRegex(RuntimeError, "禁止尝试后续视频"):
                    EXTRACT._prepare_publish_video(
                        adapter,
                        records,
                        Path(temp_dir),
                        share_link="https://pan.quark.cn/s/example",
                        video_name="project-video",
                        quark_auto_save_dir=Path("C:/quark-auto-save"),
                        quark_cookie_file=Path("C:/quark-storage.json"),
                        force_refresh=True,
                    )
            public_video.assert_not_called()
            download.assert_called_once_with(
                "video-1",
                Path(temp_dir),
                auto_save_dir=Path("C:/quark-auto-save"),
                config_file=Path("C:/quark-storage.json"),
                file_name="课程.mp4",
                expected_size=None,
                cloud_path="课程.mp4",
            )

    def test_extract_writes_details_without_project_preview_image(self):
        class FakeAdapter:
            def __init__(self, **kwargs):
                self.headers = {}

            def inspect_share(self, share_link):
                return SimpleNamespace(
                    items=[
                        _item("root", "课程资料", is_dir=True),
                        _item("lesson", "01 _ 哲学入门.pdf", parent="root"),
                    ]
                )

            def list_folder(self, folder_id):
                if folder_id == "root":
                    return [_item("lesson", "01 _ 哲学入门.pdf", parent="root")]
                return []

            def _pwd_id(self, share_link):
                return "pwd"

            def _passcode(self, share_link):
                return ""

            def _get_stoken(self, pwd_id, passcode):
                return "stoken"

            def _share_detail(self, pwd_id, stoken, folder_id):
                if folder_id == "0":
                    return False, [_item("root", "课程资料", is_dir=True)]
                if folder_id == "root":
                    return False, [_item("lesson", "01 _ 哲学入门.pdf", parent="root")]
                return False, []

            def _request(self, *args, **kwargs):
                return {"data": []}

        with tempfile.TemporaryDirectory() as temp_dir:
            asset_dir = Path(temp_dir) / "0001"
            cookie_file = Path(temp_dir) / "cookie.json"
            cookie_file.write_text("{}", encoding="utf-8")
            argv = [
                "extract_quark_project.py",
                "--asset-dir",
                str(asset_dir),
                "--share-link",
                "https://pan.quark.cn/s/example",
                "--title",
                "哲学课程",
                "--cookie-file",
                str(cookie_file),
            ]
            output = io.StringIO()
            with patch.object(sys, "argv", argv), patch("xpan_auto.quark_adapter.QuarkAdapter", FakeAdapter):
                with redirect_stdout(output):
                    result = EXTRACT.main()

            self.assertEqual(result, 0)
            details_path = asset_dir / "telegram-project-details.json"
            self.assertTrue(details_path.is_file())
            self.assertEqual(json.loads(details_path.read_text(encoding="utf-8"))["media_policy_version"], 6)
            self.assertFalse((asset_dir / "project-preview.png").exists())
            self.assertNotIn("preview", json.loads(output.getvalue()))

    def test_local_cover_does_not_reuse_legacy_project_preview(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            asset_dir = Path(temp_dir)
            legacy_preview = asset_dir / "project-preview.png"
            legacy_preview.write_bytes(b"not a source asset")

            source = PREPARE._find_source(asset_dir, None, asset_dir / "cover-v1-information-card.png")

            self.assertIsNone(source)

    def test_media_selection_prefers_project_image_over_video(self):
        records = [
            {
                "type": "file",
                "extension": ".png",
                "name": "封面.png",
                "fid": "image-fid",
                "depth": 0,
                "path": "封面.png",
            },
            {
                "type": "file",
                "extension": ".mp4",
                "name": "课程.mp4",
                "fid": "video-fid",
                "depth": 0,
                "path": "课程.mp4",
            },
        ]
        adapter = SimpleNamespace(headers={})

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(EXTRACT, "_download_metadata", return_value={"download_url": "https://image"}), patch.object(
                EXTRACT, "_fetch_image"
            ) as fetch_image, patch.object(EXTRACT, "_extract_video_frame") as extract_frame:
                result = EXTRACT._prepare_media(adapter, records, Path(temp_dir), media_name="source-preview")

        self.assertEqual(result["kind"], "project-image")
        fetch_image.assert_called_once()
        extract_frame.assert_not_called()

    def test_video_without_preview_uses_a_bounded_keyframe_attempt(self):
        records = [
            {
                "type": "file",
                "extension": ".mp4",
                "name": "课程.mp4",
                "fid": "video-fid",
                "depth": 0,
                "path": "课程.mp4",
            }
        ]
        adapter = SimpleNamespace(headers={})

        def extract_frame(_url, output, _headers, **_kwargs):
            _write_detailed_frame(output)

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(EXTRACT, "_download_metadata", return_value={"download_url": "https://video"}), patch.object(
                EXTRACT, "_extract_video_frame", side_effect=extract_frame
            ) as extract_frame:
                result = EXTRACT._prepare_media(adapter, records, Path(temp_dir), media_name="source-preview")

        self.assertEqual(result["kind"], "video-frame")
        extract_frame.assert_called_once()
        self.assertEqual(extract_frame.call_args.kwargs["timeout"], EXTRACT.VIDEO_FRAME_TIMEOUT_SECONDS)
        self.assertEqual(extract_frame.call_args.kwargs["timestamp_seconds"], 10.0)

    def test_video_preview_endpoint_is_not_mistaken_for_a_static_image(self):
        records = [
            {
                "type": "file",
                "extension": ".mp4",
                "name": "课程.mp4",
                "fid": "video-fid",
                "depth": 0,
                "path": "课程.mp4",
            }
        ]
        adapter = SimpleNamespace(headers={})

        def extract_frame(_url, output, _headers, **_kwargs):
            _write_detailed_frame(output)

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(
                EXTRACT,
                "_download_metadata",
                return_value={"preview_url": "https://api/video-preview", "download_url": "https://video"},
            ), patch.object(EXTRACT, "_fetch_image") as fetch_image, patch.object(
                EXTRACT, "_extract_video_frame", side_effect=extract_frame
            ) as extract:
                result = EXTRACT._prepare_media(adapter, records, Path(temp_dir), media_name="source-preview")

        self.assertEqual(result["kind"], "video-frame")
        fetch_image.assert_not_called()
        extract.assert_called_once()

    def test_public_share_compares_multiple_real_video_frames(self):
        records = [
            {
                "type": "file",
                "extension": ".mp4",
                "name": f"课程-{index}.mp4",
                "fid": f"video-{index}",
                "parent_id": "root",
                "depth": 0,
                "path": f"课程-{index}.mp4",
            }
            for index in range(3)
        ]
        adapter = SimpleNamespace(headers={})

        def fetch_image(_url, output, _headers):
            _write_detailed_frame(output)

        def extract_frame(_url, output, _headers, **_kwargs):
            _write_detailed_frame(output)

        def quality(path):
            name = path.name
            score = 96.0 if "public-1-poster" in name else (72.0 if "frame-0" in name else 40.0)
            return score, {"detail": score, "edge": 10.0, "activity": 1.0, "extreme": 0.0}

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(
                EXTRACT,
                "_public_video_metadata",
                return_value={"preview_url": "https://poster", "play_url": "https://video.m3u8", "duration": 570},
            ), patch.object(EXTRACT, "_fetch_image", side_effect=fetch_image), patch.object(
                EXTRACT, "_extract_video_frame", side_effect=extract_frame
            ), patch.object(EXTRACT, "_video_frame_quality", side_effect=quality):
                result, errors = EXTRACT._select_public_video_frame(
                    adapter,
                    "https://pan.quark.cn/s/example",
                    records,
                    Path(temp_dir),
                    media_name="source-preview",
                )

            self.assertEqual(errors, [])
            self.assertIsNotNone(result)
            self.assertEqual(result["source_name"], "课程-1.mp4")
            self.assertEqual(result["evaluated_frames"], 5)
            self.assertTrue(Path(result["source_path"]).is_file())

    def test_video_failures_do_not_try_the_entire_project(self):
        records = [
            {
                "type": "file",
                "extension": ".mp4",
                "name": f"课程-{index}.mp4",
                "fid": f"video-{index}",
                "depth": 0,
                "path": f"课程-{index}.mp4",
            }
            for index in range(8)
        ]
        adapter = SimpleNamespace(headers={})

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(EXTRACT, "_download_metadata", side_effect=RuntimeError("unavailable")) as download:
                result = EXTRACT._prepare_media(adapter, records, Path(temp_dir), media_name="source-preview")

        self.assertEqual(result["kind"], "media-preview-required")
        self.assertEqual(download.call_count, EXTRACT.MAX_VIDEO_MEDIA_ATTEMPTS)
        self.assertEqual(result["attempted_candidates"], EXTRACT.MAX_VIDEO_MEDIA_ATTEMPTS)

    def test_pdf_is_used_after_image_and_video_candidates(self):
        records = [
            {
                "type": "file",
                "extension": ".pdf",
                "name": "课程讲义.pdf",
                "fid": "pdf-fid",
                "depth": 0,
                "path": "课程讲义.pdf",
            }
        ]
        adapter = SimpleNamespace(headers={})

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(EXTRACT, "_download_metadata", return_value={"download_url": "https://pdf"}), patch.object(
                EXTRACT, "_download_file"
            ) as download_file, patch.object(EXTRACT, "_render_pdf_page") as render_pdf:
                result = EXTRACT._prepare_media(adapter, records, Path(temp_dir), media_name="source-preview")

        self.assertEqual(result["kind"], "document-preview")
        self.assertEqual(result["document_type"], "pdf")
        download_file.assert_called_once()
        render_pdf.assert_called_once()

    def test_pdf_preview_is_preferred_before_downloading_the_document(self):
        records = [
            {
                "type": "file",
                "extension": ".pdf",
                "name": "课程讲义.pdf",
                "fid": "pdf-fid",
                "depth": 0,
                "path": "课程讲义.pdf",
            }
        ]
        adapter = SimpleNamespace(headers={})

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(
                EXTRACT,
                "_download_metadata",
                return_value={"download_url": "https://pdf", "preview_url": "https://preview"},
            ), patch.object(EXTRACT, "_fetch_image") as fetch_image, patch.object(
                EXTRACT, "_download_file"
            ) as download_file, patch.object(EXTRACT, "_render_pdf_page") as render_pdf:
                result = EXTRACT._prepare_media(adapter, records, Path(temp_dir), media_name="source-preview")

        self.assertEqual(result["kind"], "document-preview")
        self.assertEqual(result["source_url_type"], "preview_url")
        fetch_image.assert_called_once()
        download_file.assert_not_called()
        render_pdf.assert_not_called()

    def test_docx_uses_content_preview_when_no_preview_url_exists(self):
        records = [
            {
                "type": "file",
                "extension": ".docx",
                "name": "课程讲义.docx",
                "fid": "docx-fid",
                "depth": 0,
                "path": "课程讲义.docx",
            }
        ]
        adapter = SimpleNamespace(headers={})

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(EXTRACT, "_download_metadata", return_value={"download_url": "https://docx"}), patch.object(
                EXTRACT, "_download_file"
            ) as download_file, patch.object(EXTRACT, "_render_document_content_preview") as render_preview:
                result = EXTRACT._prepare_media(adapter, records, Path(temp_dir), media_name="source-preview")

        self.assertEqual(result["kind"], "document-preview")
        self.assertEqual(result["document_type"], "docx")
        self.assertEqual(result["preview_method"], "content-render")
        download_file.assert_called_once()
        render_preview.assert_called_once()
        self.assertEqual(render_preview.call_args.args[2]["name"], "课程讲义.docx")

    def test_text_document_preview_contains_real_file_content(self):
        records = [
            {
                "type": "file",
                "extension": ".txt",
                "name": "课程说明.txt",
                "fid": "text-fid",
                "depth": 0,
                "path": "课程说明.txt",
            }
        ]
        adapter = SimpleNamespace(headers={})

        def download_text(_url, output, _headers):
            output.write_text("真实标题\n这是文件里的第一段内容。", encoding="utf-8")

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(EXTRACT, "_download_metadata", return_value={"download_url": "https://text"}), patch.object(
                EXTRACT, "_download_file", side_effect=download_text
            ):
                result = EXTRACT._prepare_media(adapter, records, Path(temp_dir), media_name="source-preview")

            self.assertEqual(result["kind"], "document-preview")
            self.assertEqual(result["document_type"], "txt")
            self.assertTrue(Path(result["source_path"]).is_file())
            with Image.open(result["source_path"]) as preview:
                self.assertEqual(preview.size, (1280, 720))

    def test_cover_design_uses_project_semantics_and_complete_information_hierarchy(self):
        details = {
            "summary": {
                "file_count": 82,
                "folder_count": 0,
                "extension_counts": {".mp3": 41, ".pdf": 41},
            },
            "items": [{"type": "file", "name": "01 品读古诗词.pdf"}],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source-preview.png"
            Image.new("RGB", (1000, 5000), (244, 221, 188)).save(source, format="PNG")

            image, design = PREPARE._render_local_card(
                title="跟杨雨品读古诗词，腹有诗书气自华",
                description="古诗词品读与传统文化课程",
                source_path=source,
                source_kind="document-preview",
                file_names=("01 品读古诗词.pdf",),
                details=details,
                width=1672,
                height=941,
            )

        self.assertEqual(image.size, (1672, 941))
        self.assertEqual(design["visual_profile"], "literary")
        self.assertEqual(design["composition"], "asymmetric-split")
        self.assertEqual(design["layout_strategy"], "asymmetric-split")
        self.assertGreaterEqual(design["fullness"]["occupied_ratio"], 0.72)
        self.assertEqual(design["information_tiers"], ["topic", "title", "support", "keywords", "metrics"])
        self.assertIn("古诗词", design["topic_text"])
        self.assertEqual(
            design["metrics"],
            [{"label": "音频", "count": 41}, {"label": "PDF讲义", "count": 41}],
        )
        self.assertTrue(PREPARE._font_has_cjk_glyphs(PREPARE._font(48, bold=True, family="editorial")))

    def test_semantic_profiles_change_style_by_project_content(self):
        literary = PREPARE._semantic_profile("古诗词与传统文化", "", ())
        digital = PREPARE._semantic_profile("AI绘画电商设计", "", ())
        friendly = PREPARE._semantic_profile("幽默表达与社交沟通", "", ())
        growth = PREPARE._semantic_profile("古典·《超级个体》", "", ())
        learning = PREPARE._semantic_profile("超新概念语法写作训练营", "", ())
        finance = PREPARE._semantic_profile("红心买点系统课", "", ())
        mixed_digital, scores, signals = PREPARE._semantic_decision(
            "299.PPT 从视觉到观点（完结）",
            "PPT模板制作、视觉表达、案例拆解与素材整理。",
            (),
        )

        self.assertEqual(literary, "literary")
        self.assertEqual(digital, "digital")
        self.assertEqual(friendly, "friendly")
        self.assertEqual(growth, "growth")
        self.assertEqual(learning, "learning")
        self.assertEqual(finance, "finance")
        self.assertEqual(mixed_digital, "digital")
        self.assertGreater(scores["digital"], scores["friendly"])
        self.assertIn("title:ppt", signals)
        self.assertNotEqual(PREPARE.SEMANTIC_PALETTES[literary], PREPARE.SEMANTIC_PALETTES[digital])

    def test_video_projects_use_distinct_dense_content_driven_layouts(self):
        details = {
            "media": {"kind": "video-frame", "source_name": "第一节课程.mp4"},
            "summary": {"file_count": 19, "extension_counts": {".mp4": 19}},
            "top_level": [
                {"name": "01 先导篇 什么是天道鬼谷.mp4"},
                {"name": "02 第一场直播答疑.mp4"},
                {"name": "03 人性规律与实战.mp4"},
            ],
            "items": [
                {"type": "file", "name": "01 先导篇 什么是天道鬼谷.mp4"},
                {"type": "file", "name": "02 第一场直播答疑.mp4"},
                {"type": "file", "name": "03 人性规律与实战.mp4"},
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source-preview.png"
            _write_detailed_frame(source)
            literary_image, literary = PREPARE._render_local_card(
                title="大齐老师—天道鬼谷训练营",
                description="天道、鬼谷与人性洞察课程。",
                source_path=source,
                source_kind="video-frame",
                file_names=tuple(item["name"] for item in details["items"]),
                details=details,
                width=1672,
                height=941,
            )
            digital_image, digital = PREPARE._render_local_card(
                title="短视频带货课，零基础详解流量成果",
                description="短视频、流量运营与带货实战。",
                source_path=source,
                source_kind="video-frame",
                file_names=tuple(item["name"] for item in details["items"]),
                details=details,
                width=1672,
                height=941,
            )

        self.assertEqual(literary["layout_strategy"], "media-editorial-split")
        self.assertEqual(digital["layout_strategy"], "media-focus-split")
        self.assertNotEqual(literary["composition"], digital["composition"])
        for image, design in ((literary_image, literary), (digital_image, digital)):
            activity = measure_cover_activity(image)
            self.assertGreaterEqual(activity["activity_ratio"], 0.60)
            self.assertGreaterEqual(activity["left_activity_ratio"], 0.50)
            self.assertGreaterEqual(activity["right_activity_ratio"], 0.40)
            self.assertIn("support", design["information_tiers"])
            self.assertEqual(design["overlay_mode"], "separate-zones")
            self.assertGreaterEqual(design["layout_geometry"]["minimum_gap"], 24)
            self.assertGreaterEqual(design["layout_geometry"]["title_support_gap"], 28)
            self.assertFalse(design["layout_geometry"]["text_over_source"])
            self.assertEqual(design["metric_presentation"], "support-inline")
            self.assertEqual(design["metrics"], [{"label": "视频", "count": 19}])
            left_region = next(region for region in design["content_regions"] if region["name"] == "left-rail")
            self.assertEqual(len(left_region["indices"]), 3)

    def test_growth_video_uses_book_typography_and_a_non_overlapping_single_spine(self):
        details = {
            "media": {"kind": "video-frame", "source_name": "超级个体课程.mp4"},
            "summary": {
                "file_count": 490,
                "extension_counts": {".mp4": 7, ".mp3": 203, ".pdf": 274},
            },
            "top_level": [
                {"name": "课前必读(共2讲-含加餐1讲)"},
                {"name": "趋势机会(共3讲-含加餐3讲)"},
                {"name": "第一模块求职转型(共23讲-含加餐1讲)"},
                {"name": "第二模块底层逻辑(共28讲-含加餐2讲)"},
                {"name": "第三模块核心竞争力(共30讲-含加餐3讲)"},
            ],
            "items": [{"type": "file", "name": "52次加速，助你成为超级个体.pdf"}],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source-preview.png"
            _write_detailed_frame(source)
            image, design = PREPARE._render_local_card(
                title="古典·《超级个体》",
                description="职业成长与个人进阶课程",
                source_path=source,
                source_kind="video-frame",
                file_names=("52次加速，助你成为超级个体.pdf",),
                details=details,
                width=1672,
                height=941,
            )

        self.assertEqual(image.size, (1672, 941))
        self.assertEqual(design["layout_strategy"], "media-focus-split")
        self.assertEqual(design["typography_basis"]["title_family"], "editorial")
        self.assertEqual(design["title_lines"], ["古典", "《超级个体》"])
        self.assertEqual(design["support_text"], "7 节视频课程")
        self.assertEqual(design["metric_presentation"], "compact-strip")
        self.assertGreaterEqual(design["layout_geometry"]["minimum_gap"], 24)
        self.assertGreaterEqual(design["layout_geometry"]["title_support_gap"], 28)
        self.assertEqual(
            [metric["label"] for metric in design["metrics"]],
            ["视频", "音频", "PDF讲义"],
        )

    def test_single_real_metric_does_not_gain_a_fake_format_metric(self):
        metrics = PREPARE._project_metrics({"summary": {"extension_counts": {".mp4": 19}}})
        self.assertEqual(metrics, [("视频", 19)])
        self.assertEqual(
            PREPARE._clean_spine_label("第一模块求职转型(共23讲-含加餐1讲)"),
            "第一模块 · 求职转型",
        )

    def test_title_layout_uses_phrase_boundaries_and_moves_status_out_of_the_headline(self):
        image, design = PREPARE._render_local_card(
            title="肌筋膜链康复技术大汇总（康复师必备掌握）",
            description="肌筋膜理论、疼痛康复、评估训练与医师培训资料。",
            source_path=None,
            details={"summary": {"extension_counts": {".mp4": 184, ".pdf": 9}}},
            width=1672,
            height=941,
        )
        status_title, status = PREPARE._display_title_and_status("299.PPT 从视觉到观点（完结）")

        self.assertEqual(image.size, (1672, 941))
        self.assertEqual(
            design["title_lines"],
            ["肌筋膜链康复", "技术大汇总", "康复师必备掌握"],
        )
        self.assertEqual(status_title, "299.PPT 从视觉到观点")
        self.assertEqual(status, "完结")
        sharing_title, sharing_status = PREPARE._display_title_and_status(
            "传智播客网络营销课程 价值16000元【共享完毕】 14.32G"
        )
        self.assertEqual(sharing_title, "传智播客网络营销课程")
        self.assertEqual(sharing_status, "共享完毕")
        listing_title, listing_status = PREPARE._display_title_and_status(
            "WorkBuddy多场景AI办公实战，系统提升职场效率(3)"
        )
        self.assertEqual(listing_title, "WorkBuddy多场景AI办公实战，系统提升职场效率")
        self.assertEqual(listing_status, "")
        self.assertEqual(PREPARE._title_phrases("古典·《超级个体》"), ["古典·", "《超级个体》"])

        _, book_design = PREPARE._render_local_card(
            title="古典·《超级个体》",
            description="逻辑思辨与人生哲学课程。",
            source_path=None,
            details={"summary": {"extension_counts": {".pdf": 1}}},
            width=1672,
            height=941,
        )
        self.assertFalse(PREPARE._has_title_orphans(book_design["title_lines"]))

    def test_course_spine_labels_remove_file_noise_and_keep_mixed_terms_whole(self):
        self.assertEqual(
            PREPARE._clean_spine_label("1-1认识workbuddy-AI办公新范式，使用场景.mp4"),
            "认识WorkBuddy AI办公新范式，使用场景",
        )
        self.assertEqual(
            PREPARE._clean_spine_label("1-第1节：自媒体发展现状与趋势_1.mp4"),
            "自媒体发展现状与趋势",
        )
        image = Image.new("RGB", (600, 300), (0, 0, 0))
        draw = ImageDraw.Draw(image)
        lines = PREPARE._wrap_content_spine_label(
            draw,
            "认识WorkBuddy AI办公新范式，使用场景与传统AI工具的区别",
            PREPARE._font(24, bold=True),
            220,
            max_lines=3,
        )
        self.assertFalse(any(line.endswith("WorkBudd") or line == "y" for line in lines))
        self.assertFalse(
            any(line.endswith("A") and next_line.startswith("I") for line, next_line in zip(lines, lines[1:]))
        )

    def test_long_titles_reduce_size_before_breaking_protected_terms(self):
        image, design = PREPARE._render_local_card(
            title="传智播客网络营销课程SEO SEM 社会化媒体 新媒体运营 电商网络营销",
            description="SEO、SEM、社会化媒体和电商网络营销课程。",
            source_path=None,
            details={"summary": {"extension_counts": {".mp4": 208}}},
            width=1672,
            height=941,
        )

        self.assertEqual(image.size, (1672, 941))
        self.assertFalse(PREPARE._has_protected_title_breaks(design["title_lines"]))

        _, finance_design = PREPARE._render_local_card(
            title="股道九杨红心买点系统课买点的底层根基",
            description="买点系统、量能与主升浪的交易课程。",
            source_path=None,
            details={"summary": {"extension_counts": {".mp4": 32}}},
            width=1672,
            height=941,
        )
        self.assertFalse(PREPARE._has_protected_title_breaks(finance_design["title_lines"]))

    def test_prepare_requires_imagegen_when_no_real_preview_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            asset_dir = Path(temp_dir) / "0001"
            details = asset_dir / "telegram-project-details.json"
            asset_dir.mkdir(parents=True)
            details.write_text(
                json.dumps(
                    {
                        "media": {"kind": "no-project-media", "source_path": None},
                        "summary": {
                            "file_count": 2,
                            "folder_count": 1,
                            "extension_counts": {".bin": 2},
                        },
                        "items": [{"type": "file", "name": "课程.bin"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            argv = [
                "prepare_telegram_asset.py",
                "--asset-dir",
                str(asset_dir),
                "--title",
                "课程资料",
                "--details-file",
                str(details),
            ]
            with patch.object(sys, "argv", argv):
                with self.assertRaisesRegex(RuntimeError, "必须先调用 imagegen"):
                    PREPARE.main()

    def test_prepare_accepts_reviewed_imagegen_cover_with_clinical_semantics(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            asset_dir = Path(temp_dir) / "0134"
            details = asset_dir / "telegram-project-details.json"
            generated = asset_dir / "imagegen-source.png"
            review = asset_dir / "imagegen-review.json"
            asset_dir.mkdir(parents=True)
            Image.new("RGB", (1672, 941), (35, 12, 50)).save(
                asset_dir / "cover-v1-information-card.png",
                format="PNG",
            )
            Image.new("RGB", (1672, 941), (11, 31, 51)).save(generated, format="PNG")
            details.write_text(
                json.dumps(
                    {
                        "media_policy_version": 6,
                        "media": {"kind": "no-project-media", "source_path": None},
                        "summary": {"file_count": 3, "extension_counts": {".bin": 3}},
                        "items": [
                            {"type": "file", "name": "电子病历大数据与临床科研.bin"},
                            {"type": "file", "name": "R语言基本操作.bin"},
                            {"type": "file", "name": "临床预测模型.bin"},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            review.write_text(
                json.dumps(
                    {
                        "tool": "imagegen",
                        "prompt_contract": "factual-social-cover-v1",
                        "displayed_title": "临床大数据：分析与处理实操课",
                        "content_anchors": ["电子病历", "R语言", "临床预测模型"],
                        "visual_direction": "医学研究期刊式的信息视觉，把电子病历和统计模型组织为一个连贯研究场景。",
                        "palette_reason": "根据临床科研的可信、克制和分析属性选择低饱和深色与少量暖色强调。",
                        "prompt": "医学编辑风，深海军蓝与低饱和青绿色，展示电子病历和临床统计建模。",
                        "checks": {
                            "subject_relevant": True,
                            "palette_compliant": True,
                            "text_readable": True,
                            "uncluttered_composition": True,
                            "no_fabricated_content": True,
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            argv = [
                "prepare_telegram_asset.py",
                "--asset-dir",
                str(asset_dir),
                "--title",
                "临床大数据、分析与处理实操课（共27节）",
                "--description",
                "电子病历、R语言与临床预测模型。",
                "--details-file",
                str(details),
                "--generated-image",
                str(generated),
                "--generated-review",
                str(review),
                "--output-name",
                "cover-v2-final.png",
            ]
            with patch.object(sys, "argv", argv):
                result = PREPARE.main()

            self.assertEqual(result, 0)
            metadata = json.loads((asset_dir / "telegram-asset.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["method"], "image-gen-output")
            self.assertEqual(metadata["layout"], "image-gen")
            self.assertEqual(metadata["design"]["visual_profile"], "clinical")
            self.assertEqual(metadata["design"]["generation"]["tool"], "imagegen")
            self.assertEqual(metadata["design"]["metrics"], [])
            self.assertEqual(Path(metadata["source_image"]), generated)

    def test_imagegen_review_requires_project_specific_visual_direction(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            review_path = Path(temp_dir) / "imagegen-review.json"
            review_path.write_text(
                json.dumps(
                    {
                        "tool": "imagegen",
                        "prompt_contract": "factual-social-cover-v1",
                        "displayed_title": "临床大数据",
                        "content_anchors": ["电子病历", "临床预测模型"],
                        "prompt": "临床科研课程封面",
                        "checks": {
                            "subject_relevant": True,
                            "palette_compliant": True,
                            "text_readable": True,
                            "uncluttered_composition": True,
                            "no_fabricated_content": True,
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "visual direction and palette reason"):
                PREPARE._load_imagegen_review(
                    review_path,
                    title="临床大数据",
                    description="电子病历与临床预测模型",
                    file_names=("电子病历", "临床预测模型"),
                )

    def test_prepare_renders_landscape_document_preview_as_16_by_9_cover(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            asset_dir = Path(temp_dir) / "0001"
            details = asset_dir / "telegram-project-details.json"
            source = asset_dir / "source-preview.png"
            asset_dir.mkdir(parents=True)
            preview = Image.new("RGB", (1000, 550), (244, 246, 249))
            draw = ImageDraw.Draw(preview)
            draw.rectangle((40, 40, 960, 510), outline=(32, 72, 115), width=8)
            draw.line((80, 140, 920, 140), fill=(50, 50, 50), width=8)
            draw.line((80, 220, 920, 220), fill=(90, 90, 90), width=6)
            preview.save(source, format="PNG")
            details.write_text(
                json.dumps(
                    {
                        "media_policy_version": 6,
                        "media": {
                            "kind": "document-preview",
                            "source_name": "讲义.pdf",
                            "source_path": str(source),
                        },
                        "summary": {"file_count": 1, "extension_counts": {".pdf": 1}},
                        "items": [{"type": "file", "name": "讲义.pdf", "extension": ".pdf"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            argv = [
                "prepare_telegram_asset.py",
                "--asset-dir",
                str(asset_dir),
                "--title",
                "课程讲义",
                "--details-file",
                str(details),
            ]
            with patch.object(sys, "argv", argv):
                result = PREPARE.main()

            output = asset_dir / "cover-v1-information-card.png"
            metadata = json.loads((asset_dir / "telegram-asset.json").read_text(encoding="utf-8"))
            self.assertEqual(result, 0)
            with Image.open(output) as image:
                self.assertEqual(image.size, (1920, 1080))
            self.assertEqual(metadata["quality_version"], 12)
            self.assertEqual(metadata["method"], "document-cover-adaptive")
            self.assertEqual(metadata["layout"], "document-cover-adaptive")
            self.assertEqual(metadata["source_render_mode"], "fit-document-page")
            self.assertEqual(metadata["font_files"], [])
            self.assertFalse(metadata["design"]["overlay_text"])
            self.assertEqual(metadata["design"]["canvas_size"], [1920, 1080])
            self.assertEqual(metadata["design"]["orientation"], "landscape")
            self.assertEqual(metadata["design"]["aspect_ratio"], "16:9")

    def test_document_cover_uses_9_by_16_for_a_tall_preview(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source-preview.png"
            Image.new("RGB", (800, 1400), (20, 55, 90)).save(source, format="PNG")

            image, design = PREPARE._render_document_cover_adaptive(
                source,
                source_kind="document-preview",
                details={"summary": {"extension_counts": {".pdf": 1}}},
            )

        self.assertEqual(image.size, (1080, 1920))
        self.assertEqual(design["canvas_size"], [1080, 1920])
        self.assertEqual(design["orientation"], "portrait")
        self.assertEqual(design["aspect_ratio"], "9:16")

    def test_prepare_blocks_text_cover_when_video_preview_is_not_ready(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            asset_dir = Path(temp_dir) / "0001"
            details = asset_dir / "telegram-project-details.json"
            asset_dir.mkdir(parents=True)
            details.write_text(
                json.dumps(
                    {
                        "media_policy_version": 6,
                        "media": {"kind": "media-preview-required", "source_path": None},
                        "summary": {"file_count": 19, "extension_counts": {".mp4": 19}},
                        "items": [{"type": "file", "name": "课程.mp4", "extension": ".mp4"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            argv = [
                "prepare_telegram_asset.py",
                "--asset-dir",
                str(asset_dir),
                "--title",
                "课程资料",
                "--details-file",
                str(details),
            ]
            with patch.object(sys, "argv", argv):
                with self.assertRaisesRegex(RuntimeError, "禁止生成纯文字目录封面"):
                    PREPARE.main()

    def test_short_growth_project_uses_a_full_source_dominant_poster(self):
        details = {
            "media": {
                "kind": "document-preview",
                "source_name": "发刊词丨52次加速，助你成为超级个体.pdf",
            },
            "summary": {
                "file_count": 490,
                "folder_count": 10,
                "extension_counts": {".pdf": 274, ".mp3": 203, ".mp4": 7},
            },
            "items": [
                {"type": "file", "name": "让我们一起职业重启.mp3"},
                {"type": "file", "name": "自我效能与领导力.pdf"},
                {"type": "file", "name": "副业发展.pdf"},
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source-preview.png"
            Image.new("RGB", (900, 1800), (211, 62, 48)).save(source, format="PNG")

            image, design = PREPARE._render_local_card(
                title="古典·《超级个体》",
                description="职业成长与个人进阶课程",
                source_path=source,
                source_kind="document-preview",
                file_names=tuple(item["name"] for item in details["items"]),
                details=details,
                width=1672,
                height=941,
            )

        self.assertEqual(image.size, (1672, 941))
        self.assertEqual(design["visual_profile"], "growth")
        self.assertEqual(design["layout_strategy"], "source-dominant-poster")
        self.assertEqual(design["composition"], "source-dominant-poster")
        self.assertEqual(design["overlay_mode"], "solid-stage")
        self.assertIn("52次加速", design["support_text"])
        self.assertIn("support", design["information_tiers"])
        self.assertGreaterEqual(design["fullness"]["source_coverage"], 0.72)
        self.assertGreaterEqual(design["fullness"]["occupied_ratio"], 0.72)

    def test_short_document_uses_a_real_filename_as_poster_support(self):
        details = {
            "media": {
                "kind": "document-preview",
                "source_name": "学习技巧.pdf",
            },
            "summary": {
                "file_count": 1,
                "folder_count": 1,
                "extension_counts": {".pdf": 1},
            },
            "top_level": [{"name": "学习技巧.pdf"}],
            "items": [{"type": "file", "name": "学习技巧.pdf", "extension": ".pdf"}],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source-preview.png"
            Image.new("RGB", (1000, 1414), (18, 36, 58)).save(source, format="PNG")

            image, design = PREPARE._render_local_card(
                title="男同学持久技巧指南",
                description="一份真实资料",
                source_path=source,
                source_kind="document-preview",
                file_names=("学习技巧.pdf",),
                details=details,
                width=1672,
                height=941,
            )

        self.assertEqual(image.size, (1672, 941))
        self.assertEqual(design["layout_strategy"], "source-dominant-poster")
        self.assertEqual(design["support_text"], "学习技巧")
        self.assertEqual(design["support_source"], "project.files")

    def test_text_only_course_uses_a_real_content_timeline_instead_of_empty_summary(self):
        details = {
            "media": {"kind": "no-project-media", "source_path": None},
            "summary": {
                "file_count": 19,
                "folder_count": 0,
                "extension_counts": {".mp4": 19},
            },
            "top_level": [
                {"name": "001.先导篇 什么是天道鬼谷？.mp4"},
                {"name": "002.第一场直播答疑-大齐老师.mp4"},
                {"name": "008.拆解顶级做局者的手段.mp4"},
                {"name": "009.商君书驭民术及破解之道.mp4"},
            ],
            "items": [
                {"type": "file", "name": "001.先导篇 什么是天道鬼谷？.mp4"},
                {"type": "file", "name": "002.第一场直播答疑-大齐老师.mp4"},
                {"type": "file", "name": "008.拆解顶级做局者的手段.mp4"},
                {"type": "file", "name": "009.商君书驭民术及破解之道.mp4"},
            ],
        }
        image, design = PREPARE._render_local_card(
            title="大齐老师—天道鬼谷训练营",
            description="天道、鬼谷与人性洞察课程。",
            source_path=None,
            source_kind="no-project-media",
            file_names=tuple(item["name"] for item in details["items"]),
            details=details,
            width=1672,
            height=941,
        )

        self.assertEqual(image.size, (1672, 941))
        self.assertEqual(design["visual_profile"], "literary")
        self.assertEqual(design["layout_strategy"], "semantic-timeline")
        self.assertEqual(design["composition"], "semantic-timeline")
        self.assertEqual(design["support_text"], "19 节视频课程")
        self.assertEqual(design["support_source"], "project.summary")
        self.assertGreaterEqual(len(design["content_spine"]), 3)
        self.assertEqual(design["content_spine_source"], "project.top_level")
        self.assertIn("support", design["information_tiers"])
        self.assertGreaterEqual(design["fullness"]["occupied_ratio"], 0.72)

    def test_document_cover_uses_a_readable_top_slice(self):
        source = Image.new("RGB", (100, 800), "white")
        draw = ImageDraw.Draw(source)
        draw.rectangle((0, 0, 99, 38), fill="red")
        draw.rectangle((0, 120, 99, 799), fill="blue")

        cropped = PREPARE._top_safe_document_crop(source, (200, 100))

        self.assertEqual(cropped.size, (200, 100))
        self.assertGreater(cropped.getpixel((100, 10))[0], 180)
        self.assertGreater(cropped.getpixel((100, 90))[0], 180)


if __name__ == "__main__":
    unittest.main()
