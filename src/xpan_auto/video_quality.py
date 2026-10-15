from __future__ import annotations

import json
import shutil
import subprocess
from .runtime import find_media_tool
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class VideoQualityReport:
    passed: bool
    issues: tuple[str, ...]
    path: str
    size_bytes: int
    duration_seconds: float
    width: int
    height: int
    video_codec: str
    audio_codec: str


@dataclass(frozen=True)
class VideoPreparationReport:
    passed: bool
    source: VideoQualityReport
    final: VideoQualityReport
    duration_trimmed: bool
    size_trimmed: bool
    container_remuxed: bool
    max_duration_seconds: float
    max_size_bytes: int
    target_size_bytes: int


def inspect_publish_video(
    path: str | Path,
    *,
    min_duration_seconds: float = 3.0,
    max_duration_seconds: float | None = None,
    max_size_bytes: int = 2 * 1024 * 1024 * 1024,
) -> VideoQualityReport:
    video = Path(path)
    issues: list[str] = []
    if not video.is_file():
        return VideoQualityReport(False, ("视频文件不存在",), str(video), 0, 0.0, 0, 0, "", "")

    size_bytes = video.stat().st_size
    if size_bytes <= 0:
        issues.append("视频文件为空")
    if size_bytes > max_size_bytes:
        issues.append(f"视频超过发布上限：{size_bytes} > {max_size_bytes} bytes")

    ffprobe = find_media_tool("ffprobe")
    if not ffprobe:
        issues.append("系统未找到 ffprobe，无法完成视频质检")
        return VideoQualityReport(False, tuple(issues), str(video), size_bytes, 0.0, 0, 0, "", "")

    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=codec_type,codec_name,width,height",
                "-of",
                "json",
                str(video),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        issues.append(f"ffprobe 执行失败：{exc}")
        return VideoQualityReport(False, tuple(issues), str(video), size_bytes, 0.0, 0, 0, "", "")

    if result.returncode != 0:
        issues.append(f"视频无法解码：{(result.stderr or '').strip()[-240:]}")
        return VideoQualityReport(False, tuple(issues), str(video), size_bytes, 0.0, 0, 0, "", "")

    try:
        payload: dict[str, Any] = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        issues.append("ffprobe 返回了无效结果")
        payload = {}

    streams = payload.get("streams") if isinstance(payload.get("streams"), list) else []
    video_stream = next(
        (stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "video"),
        {},
    )
    audio_stream = next(
        (stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "audio"),
        {},
    )
    try:
        duration = float((payload.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)
    video_codec = str(video_stream.get("codec_name") or "")
    audio_codec = str(audio_stream.get("codec_name") or "")

    if not video_stream:
        issues.append("文件中没有视频轨道")
    if duration < min_duration_seconds:
        issues.append(f"视频时长不足 {min_duration_seconds:g} 秒")
    if max_duration_seconds is not None and duration > max_duration_seconds:
        issues.append(f"视频时长超过发布上限：{duration:.1f} > {max_duration_seconds:g} 秒")
    if width < 320 or height < 180:
        issues.append(f"视频分辨率过低：{width}x{height}")
    if video_codec not in {"h264", "hevc"}:
        issues.append(f"视频编码不适合通用发布：{video_codec or 'unknown'}")

    return VideoQualityReport(
        not issues,
        tuple(issues),
        str(video),
        size_bytes,
        duration,
        width,
        height,
        video_codec,
        audio_codec,
    )


def _copy_video_prefix(
    source: Path,
    output: Path,
    *,
    duration_seconds: float,
) -> None:
    ffmpeg = find_media_tool("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("系统未找到 ffmpeg，无法截断发布视频")

    output.unlink(missing_ok=True)
    command = [
        ffmpeg,
        "-v",
        "error",
        "-y",
        "-i",
        str(source),
        "-map",
        "0",
        "-c",
        "copy",
    ]
    command.extend(["-t", f"{duration_seconds:g}"])
    command.append(str(output))

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"ffmpeg 截断发布视频失败：{exc}") from None
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[-500:]
        raise RuntimeError(f"ffmpeg 截断发布视频失败：{detail or 'unknown error'}")
    if not output.is_file() or output.stat().st_size <= 0:
        raise RuntimeError("ffmpeg 没有生成可用的发布视频")


def _remux_video_to_mp4(source: Path, output: Path) -> None:
    ffmpeg = find_media_tool("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("系统未找到 ffmpeg，无法为 Typefully 封装 MP4")

    output.unlink(missing_ok=True)
    try:
        result = subprocess.run(
            [
                ffmpeg,
                "-v",
                "error",
                "-y",
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-c",
                "copy",
                str(output),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"ffmpeg 无损封装 MP4 失败：{exc}") from None
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[-500:]
        raise RuntimeError(f"ffmpeg 无损封装 MP4 失败：{detail or 'unknown error'}")
    if not output.is_file() or output.stat().st_size <= 0:
        raise RuntimeError("ffmpeg 没有生成可用的 Typefully MP4")


def prepare_publish_video(
    path: str | Path,
    *,
    source_report: VideoQualityReport | None = None,
    max_duration_seconds: float = 600.0,
    max_size_bytes: int = 50_000_000,
    target_size_bytes: int = 49_000_000,
) -> VideoPreparationReport:
    """Keep the leading <=10 minutes, then trim the tail until it is under 50 MB."""

    video = Path(path)
    if max_duration_seconds <= 3:
        raise ValueError("max_duration_seconds must be greater than the three-second QA minimum")
    if max_size_bytes <= 1:
        raise ValueError("max_size_bytes must be greater than one byte")
    if target_size_bytes <= 0 or target_size_bytes >= max_size_bytes:
        raise ValueError("target_size_bytes must be positive and smaller than max_size_bytes")

    source = source_report or inspect_publish_video(video, max_size_bytes=2**63 - 1)
    if not source.passed:
        raise RuntimeError(f"源视频质检未通过：{'；'.join(source.issues)}")

    duration_output = video.with_name(f".{video.stem}.duration-limit.part{video.suffix}")
    size_output = video.with_name(f".{video.stem}.size-limit.part{video.suffix}")
    container_output = video.with_name(f".{video.stem}.typefully.part.mp4")
    temporary_outputs = (duration_output, size_output, container_output)
    duration_trimmed = source.duration_seconds > max_duration_seconds
    size_trimmed = False
    container_remuxed = video.suffix.lower() not in {".mp4", ".mov"}
    candidate = video
    candidate_report = source

    try:
        if duration_trimmed:
            duration_report: VideoQualityReport | None = None
            retry_duration = max_duration_seconds - 1.0
            for duration_target in (max_duration_seconds, retry_duration):
                _copy_video_prefix(
                    video,
                    duration_output,
                    duration_seconds=duration_target,
                )
                duration_report = inspect_publish_video(
                    duration_output,
                    max_duration_seconds=max_duration_seconds,
                    max_size_bytes=2**63 - 1,
                )
                if duration_report.passed:
                    break
                if duration_report.duration_seconds <= max_duration_seconds:
                    break
            if duration_report is None:
                raise RuntimeError("十分钟截断没有生成质检结果")
            if not duration_report.passed:
                raise RuntimeError(f"十分钟截断后质检未通过：{'；'.join(duration_report.issues)}")
            candidate = duration_output
            candidate_report = duration_report

        size_trimmed = candidate.stat().st_size >= max_size_bytes
        if size_trimmed:
            size_report: VideoQualityReport | None = None
            trim_duration = (
                candidate_report.duration_seconds
                * target_size_bytes
                / candidate.stat().st_size
                * 0.98
            )
            for _ in range(4):
                if trim_duration < 3.0:
                    raise RuntimeError(
                        "仅靠截断无法同时满足三秒时长下限和 50,000,000 bytes 大小上限"
                    )
                _copy_video_prefix(
                    candidate,
                    size_output,
                    duration_seconds=trim_duration,
                )
                size_report = inspect_publish_video(
                    size_output,
                    max_duration_seconds=max_duration_seconds,
                    max_size_bytes=max_size_bytes - 1,
                )
                if size_report.passed:
                    break
                actual_size = size_output.stat().st_size
                if actual_size < max_size_bytes:
                    break
                trim_duration *= target_size_bytes / actual_size * 0.98
            if size_report is None:
                raise RuntimeError("大小截断没有生成质检结果")
            if not size_report.passed:
                raise RuntimeError(f"大小截断后质检未通过：{'；'.join(size_report.issues)}")
            candidate = size_output

        final_report = inspect_publish_video(
            candidate,
            max_duration_seconds=max_duration_seconds,
            max_size_bytes=max_size_bytes - 1,
        )
        if not final_report.passed:
            raise RuntimeError(f"最终发布视频质检未通过：{'；'.join(final_report.issues)}")

        final_target = video
        if container_remuxed:
            _remux_video_to_mp4(candidate, container_output)
            final_report = inspect_publish_video(
                container_output,
                max_duration_seconds=max_duration_seconds,
                max_size_bytes=max_size_bytes - 1,
            )
            if not final_report.passed:
                raise RuntimeError(
                    f"Typefully MP4 封装后质检未通过：{'；'.join(final_report.issues)}"
                )
            candidate = container_output
            final_target = video.with_suffix(".mp4")

        if candidate.resolve() != final_target.resolve():
            candidate.replace(final_target)
        if final_target.resolve() != video.resolve():
            video.unlink(missing_ok=True)
        final_report = replace(final_report, path=str(final_target))

        return VideoPreparationReport(
            passed=True,
            source=source,
            final=final_report,
            duration_trimmed=duration_trimmed,
            size_trimmed=size_trimmed,
            container_remuxed=container_remuxed,
            max_duration_seconds=max_duration_seconds,
            max_size_bytes=max_size_bytes,
            target_size_bytes=target_size_bytes,
        )
    finally:
        for temporary in temporary_outputs:
            temporary.unlink(missing_ok=True)


def write_video_quality_report(path: str | Path, report: VideoQualityReport) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")
