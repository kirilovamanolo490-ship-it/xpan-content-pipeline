import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from xpan_auto.video_quality import VideoQualityReport, inspect_publish_video, prepare_publish_video


class VideoQualityTests(unittest.TestCase):
    def _report(self, path: Path, *, size: int, duration: float) -> VideoQualityReport:
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

    def test_accepts_decodable_h264_video_with_publishable_dimensions(self):
        payload = {
            "format": {"duration": "60.5"},
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1280, "height": 720},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "project-video.mp4"
            video.write_bytes(b"video")
            completed = subprocess.CompletedProcess([], 0, stdout=json.dumps(payload), stderr="")
            with patch("xpan_auto.video_quality.shutil.which", return_value="ffprobe"), patch(
                "xpan_auto.video_quality.subprocess.run", return_value=completed
            ):
                report = inspect_publish_video(video)

        self.assertTrue(report.passed)
        self.assertEqual(report.duration_seconds, 60.5)
        self.assertEqual(report.video_codec, "h264")

    def test_rejects_audio_only_or_too_short_media(self):
        payload = {
            "format": {"duration": "1.0"},
            "streams": [{"codec_type": "audio", "codec_name": "aac"}],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "project-video.mp4"
            video.write_bytes(b"audio-only")
            completed = subprocess.CompletedProcess([], 0, stdout=json.dumps(payload), stderr="")
            with patch("xpan_auto.video_quality.shutil.which", return_value="ffprobe"), patch(
                "xpan_auto.video_quality.subprocess.run", return_value=completed
            ):
                report = inspect_publish_video(video)

        self.assertFalse(report.passed)
        self.assertIn("文件中没有视频轨道", report.issues)

    def test_rejects_video_longer_than_the_publish_limit(self):
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
                report = inspect_publish_video(video, max_duration_seconds=600)

        self.assertFalse(report.passed)
        self.assertTrue(any("超过发布上限" in issue for issue in report.issues))

    def test_publish_video_within_both_limits_is_not_rewritten(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "project-video-original.mp4"
            video.write_bytes(b"small")
            source = self._report(video, size=5, duration=120.0)
            with patch(
                "xpan_auto.video_quality.inspect_publish_video", return_value=source
            ), patch("xpan_auto.video_quality._copy_video_prefix") as copy_prefix:
                result = prepare_publish_video(
                    video,
                    source_report=source,
                    max_size_bytes=50,
                    target_size_bytes=49,
                )

            self.assertFalse(result.duration_trimmed)
            self.assertFalse(result.size_trimmed)
            self.assertEqual(video.read_bytes(), b"small")
            copy_prefix.assert_not_called()

    def test_publish_video_limits_duration_before_checking_size(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "project-video-original.mp4"
            video.write_bytes(b"o" * 100)
            source = self._report(video, size=100, duration=700.0)
            duration_report = self._report(video, size=60, duration=600.0)
            final_report = self._report(video, size=49, duration=480.0)

            def copy_prefix(source_path, output_path, **kwargs):
                if "duration-limit" in output_path.name:
                    output_path.write_bytes(b"d" * 60)
                else:
                    output_path.write_bytes(b"s" * 49)

            with patch(
                "xpan_auto.video_quality.inspect_publish_video",
                side_effect=[duration_report, final_report, final_report],
            ), patch(
                "xpan_auto.video_quality._copy_video_prefix", side_effect=copy_prefix
            ) as copy_video:
                result = prepare_publish_video(
                    video,
                    source_report=source,
                    max_size_bytes=50,
                    target_size_bytes=49,
                )

            self.assertTrue(result.duration_trimmed)
            self.assertTrue(result.size_trimmed)
            self.assertEqual(video.stat().st_size, 49)
            self.assertEqual(copy_video.call_count, 2)
            self.assertEqual(copy_video.call_args_list[0].kwargs["duration_seconds"], 600.0)
            self.assertLess(copy_video.call_args_list[1].kwargs["duration_seconds"], 600.0)

    def test_video_exactly_at_size_limit_is_shortened(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "project-video-original.mp4"
            video.write_bytes(b"o" * 50)
            source = self._report(video, size=50, duration=300.0)
            final_report = self._report(video, size=49, duration=294.0)

            def copy_prefix(source_path, output_path, **kwargs):
                output_path.write_bytes(b"s" * 49)

            with patch(
                "xpan_auto.video_quality.inspect_publish_video", return_value=final_report
            ), patch(
                "xpan_auto.video_quality._copy_video_prefix", side_effect=copy_prefix
            ):
                result = prepare_publish_video(
                    video,
                    source_report=source,
                    max_size_bytes=50,
                    target_size_bytes=49,
                )

            self.assertFalse(result.duration_trimmed)
            self.assertTrue(result.size_trimmed)
            self.assertLess(video.stat().st_size, 50)

    def test_typefully_incompatible_container_is_remuxed_to_mp4(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "project-video-original.mkv"
            video.write_bytes(b"mkv-video")
            source = self._report(video, size=9, duration=120.0)
            before_remux = self._report(video, size=9, duration=120.0)
            remuxed = self._report(video.with_suffix(".mp4"), size=8, duration=120.0)

            def remux(source_path, output_path):
                output_path.write_bytes(b"mp4-file")

            with patch(
                "xpan_auto.video_quality.inspect_publish_video",
                side_effect=[before_remux, remuxed],
            ), patch(
                "xpan_auto.video_quality._remux_video_to_mp4", side_effect=remux
            ):
                result = prepare_publish_video(
                    video,
                    source_report=source,
                    max_size_bytes=50,
                    target_size_bytes=49,
                )

            final_path = Path(result.final.path)
            self.assertTrue(result.container_remuxed)
            self.assertEqual(final_path.suffix, ".mp4")
            self.assertTrue(final_path.is_file())
            self.assertFalse(video.exists())

    def test_duration_limit_retries_one_second_shorter_when_timestamps_overshoot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "project-video-original.mp4"
            video.write_bytes(b"o" * 100)
            source = self._report(video, size=100, duration=700.0)
            overshoot = VideoQualityReport(
                False,
                ("视频时长超过发布上限",),
                str(video),
                60,
                600.04,
                1280,
                720,
                "h264",
                "aac",
            )
            bounded = self._report(video, size=60, duration=599.04)

            def copy_prefix(source_path, output_path, **kwargs):
                output_path.write_bytes(b"d" * 60)

            with patch(
                "xpan_auto.video_quality.inspect_publish_video",
                side_effect=[overshoot, bounded, bounded],
            ), patch(
                "xpan_auto.video_quality._copy_video_prefix", side_effect=copy_prefix
            ) as copy_video:
                result = prepare_publish_video(
                    video,
                    source_report=source,
                    max_size_bytes=1000,
                    target_size_bytes=900,
                )

            self.assertTrue(result.passed)
            self.assertEqual(
                [call.kwargs["duration_seconds"] for call in copy_video.call_args_list],
                [600.0, 599.0],
            )
            self.assertLessEqual(result.final.duration_seconds, 600.0)

    def test_failed_trim_keeps_complete_download_for_retry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "project-video-original.mp4"
            original = b"o" * 100
            video.write_bytes(original)
            source = self._report(video, size=100, duration=700.0)
            with patch(
                "xpan_auto.video_quality._copy_video_prefix",
                side_effect=RuntimeError("ffmpeg failed"),
            ):
                with self.assertRaisesRegex(RuntimeError, "ffmpeg failed"):
                    prepare_publish_video(
                        video,
                        source_report=source,
                        max_size_bytes=50,
                        target_size_bytes=49,
                    )

            self.assertEqual(video.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
