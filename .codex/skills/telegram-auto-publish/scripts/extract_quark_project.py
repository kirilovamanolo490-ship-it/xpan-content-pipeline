#!/usr/bin/env python3
"""Collect a Quark project tree and prepare publishable project media."""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import time
import zipfile
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))
from xpan_auto.runtime import cjk_font_candidates, find_media_tool, resolve_project_path


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv", ".m4v"}
PDF_EXTENSIONS = {".pdf"}
DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".doc",
    ".pptx",
    ".ppt",
    ".xlsx",
    ".xlsm",
    ".xls",
    ".odt",
    ".ods",
    ".odp",
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".html",
    ".htm",
    ".rtf",
    ".xml",
    ".yaml",
    ".yml",
    ".log",
    ".ini",
    ".sql",
}
DOCUMENT_EXTENSION_PRIORITY = {
    ".pdf": 0,
    ".pptx": 1,
    ".ppt": 2,
    ".docx": 3,
    ".doc": 4,
    ".xlsx": 5,
    ".xlsm": 5,
    ".xls": 6,
    ".odt": 7,
    ".ods": 7,
    ".odp": 7,
    ".html": 8,
    ".htm": 8,
    ".md": 9,
    ".txt": 10,
    ".csv": 11,
    ".json": 12,
    ".xml": 13,
    ".yaml": 14,
    ".yml": 14,
    ".rtf": 15,
    ".log": 16,
    ".ini": 17,
    ".sql": 18,
}
MAX_IMAGE_MEDIA_ATTEMPTS = 5
MAX_VIDEO_MEDIA_ATTEMPTS = 3
MAX_DOCUMENT_MEDIA_ATTEMPTS = 5
# Kept as a compatibility alias for callers and tests that used the old
# PDF-only limit. Documents now share one bounded preview budget.
MAX_PDF_MEDIA_ATTEMPTS = MAX_DOCUMENT_MEDIA_ATTEMPTS
VIDEO_FRAME_TIMEOUT_SECONDS = 45
PDF_PREVIEW_TIMEOUT_SECONDS = 90
DOCUMENT_PREVIEW_TIMEOUT_SECONDS = 90
MEDIA_POLICY_VERSION = 6
PUBLISH_MEDIA_POLICY_VERSION = 10
TELEGRAM_BOT_API_MAX_MEDIA_BYTES = 50_000_000
MIN_VIDEO_FRAME_SCORE = 24.0
EXISTING_SOURCE_NAMES = (
    "source-preview.webp",
    "source-preview.png",
    "source-preview.jpg",
    "source-image.webp",
    "source-image.png",
    "source-image.jpg",
    "cover.jpg",
    "cover.jpeg",
    "cover.png",
)


def project_root() -> Path:
    # .../<project>/.codex/skills/telegram-auto-publish/scripts/<file>
    return Path(__file__).resolve().parents[4]


def resolve_path(value: str | Path) -> Path:
    return resolve_project_path(value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    location = parser.add_mutually_exclusive_group(required=True)
    location.add_argument("--row-index", type=int, help="1-based Excel data row index")
    location.add_argument("--asset-dir", type=Path, help="explicit numbered asset directory")
    parser.add_argument("--share-link", default="", help="validated Quark share link for this row")
    parser.add_argument("--db", default="output/quark_state.sqlite3")
    parser.add_argument("--cookie-file", default="config/quark-storage.json")
    parser.add_argument("--asset-root", default="output/assets")
    parser.add_argument("--title", default="", help="fallback title when the state store has no title")
    parser.add_argument("--details-name", default="telegram-project-details.json")
    parser.add_argument(
        "--media-name",
        default="source-preview",
        help="stable basename for the fallback image or document preview",
    )
    parser.add_argument(
        "--video-name",
        default="project-video",
        help="stable basename for the preferred publishable MP4",
    )
    parser.add_argument("--max-depth", type=int, default=32)
    parser.add_argument("--max-items", type=int, default=20000)
    parser.add_argument("--timeout", type=float, default=45.0, help="Quark API timeout in seconds")
    parser.add_argument(
        "--quark-auto-save-dir",
        "--quark-skill-dir",
        dest="quark_auto_save_dir",
        default=os.environ.get(
            "QUARK_AUTO_SAVE_DIR",
            str(project_root() / "work" / "quark-auto-save"),
        ),
        help="deployed quark-auto-save directory (the old --quark-skill-dir name is accepted for compatibility)",
    )
    return parser.parse_args()


def _load_job_metadata(
    db_path: Path,
    *,
    row_index: int | None,
    share_link: str,
) -> tuple[dict[str, Any], str]:
    if not db_path.is_file():
        return {}, ""

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        rows = list(connection.execute("SELECT * FROM jobs ORDER BY created_at"))
    finally:
        connection.close()

    selected: sqlite3.Row | None = None
    if share_link:
        for row in rows:
            if str(row["source_url"] or "") == share_link:
                selected = row
                break
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except json.JSONDecodeError:
                metadata = {}
            if any(str(share.get("url") or "") == share_link for share in metadata.get("new_shares") or []):
                selected = row
                break
    elif row_index is not None and 1 <= row_index <= len(rows):
        selected = rows[row_index - 1]

    if selected is None:
        return {}, ""
    try:
        metadata = json.loads(selected["metadata_json"] or "{}")
    except json.JSONDecodeError:
        metadata = {}
    return metadata if isinstance(metadata, dict) else {}, str(selected["source_url"] or "")


def _target_from_metadata(metadata: dict[str, Any]) -> tuple[str, str]:
    target_id = str(metadata.get("target_folder_id") or "")
    target_root = str(metadata.get("target_root") or "")
    if target_id:
        return target_id, target_root.rsplit("/", 1)[-1] or "项目资料"

    for item in metadata.get("saved_items") or ():
        if item.get("is_dir") and item.get("fid"):
            return str(item["fid"]), str(item.get("name") or "项目资料")
    return "", target_root.rsplit("/", 1)[-1] or "项目资料"


def _normalized_name(value: str) -> str:
    value = re.sub(r"^\d{4}[_-]?", "", str(value or "").strip()).casefold()
    return re.sub(r"[^\w]+", "", value)


def _item_record(item: Any, *, path: str, depth: int) -> dict[str, Any]:
    name = str(item.name or "")
    suffix = Path(name).suffix.lower()
    return {
        "fid": str(item.fid),
        "parent_id": str(item.pdir_fid or "0"),
        "name": name,
        "path": path,
        "type": "folder" if item.is_dir else "file",
        "extension": suffix,
        "depth": depth,
        "include_items": item.include_items,
        "size_bytes": getattr(item, "size_bytes", None),
        "share_fid_token": str(getattr(item, "share_fid_token", "") or ""),
    }


def _collect_tree(adapter: Any, root_id: str, root_name: str, *, max_depth: int, max_items: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    visited: set[str] = set()

    def visit(folder_id: str, parent_path: str, depth: int) -> None:
        if folder_id in visited:
            return
        visited.add(folder_id)
        children = adapter.list_folder(folder_id)
        for item in children:
            if len(records) >= max_items:
                return
            path = f"{parent_path}/{item.name}" if parent_path else item.name
            record = _item_record(item, path=path, depth=depth)
            records.append(record)
            if item.is_dir:
                if depth >= max_depth:
                    raise RuntimeError(f"夸克目录达到递归深度上限 {max_depth} 层，无法证明文件树完整")
                visit(item.fid, path, depth + 1)

    visit(root_id, root_name, 0)
    return records


def _collect_share_tree(
    adapter: Any,
    share_link: str,
    root_name: str,
    *,
    max_depth: int,
    max_items: int,
) -> list[dict[str, Any]]:
    """Collect the project tree through the share-page API.

    The collector preserves the complete share-page response order for
    structure and fallback evidence. Publish selection happens only after the
    complete tree is collected, using explicit lesson/sequence markers from
    video filenames when available.
    """
    records: list[dict[str, Any]] = []
    visited: set[str] = set()
    pwd_id = adapter._pwd_id(share_link)
    stoken = adapter._get_stoken(pwd_id, adapter._passcode(share_link))

    def visit(pdir_fid: str, parent_path: str, depth: int) -> None:
        if pdir_fid in visited:
            return
        visited.add(pdir_fid)
        _is_owner, items = adapter._share_detail(pwd_id, stoken, pdir_fid)
        for item in items:
            if len(records) >= max_items:
                return
            path = f"{parent_path}/{item.name}" if parent_path else item.name
            record = _item_record(item, path=path, depth=depth)
            records.append(record)
            if item.is_dir:
                if depth >= max_depth:
                    raise RuntimeError(f"夸克目录达到递归深度上限 {max_depth} 层，无法证明文件树完整")
                visit(item.fid, path, depth + 1)

    visit("0", root_name, 0)
    return records


def _existing_media(asset_dir: Path) -> dict[str, Any] | None:
    for name in EXISTING_SOURCE_NAMES:
        candidate = asset_dir / name
        if candidate.is_file() and candidate.stat().st_size > 0:
            try:
                with Image.open(candidate) as image:
                    image.verify()
            except (OSError, ValueError):
                candidate.unlink(missing_ok=True)
                continue
            return {
                "kind": "existing-local",
                "source_name": candidate.name,
                "source_path": str(candidate),
            }
    return None


def _media_candidates(records: list[dict[str, Any]], extension_set: set[str]) -> list[dict[str, Any]]:
    candidates = [record for record in records if record["type"] == "file" and record["extension"] in extension_set]
    preferred_words = ("cover", "封面", "海报", "banner", "preview", "截图", "首页")
    return sorted(
        candidates,
        key=lambda record: (
            0 if any(word in str(record.get("name") or "").casefold() for word in preferred_words) else 1,
            int(record.get("depth") or 0),
            str(record.get("path") or ""),
        ),
    )


def _download_metadata(adapter: Any, fid: str) -> dict[str, Any]:
    response = adapter._request(
        "POST",
        "/1/clouddrive/file/download",
        payload={"fids": [fid]},
    )
    data = response.get("data") or []
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise RuntimeError("夸克没有返回可用的项目媒体信息")
    return data[0]


def _media_headers(adapter: Any) -> dict[str, str]:
    return {
        key: value
        for key, value in adapter.headers.items()
        if key.lower() in {"user-agent", "cookie", "origin", "referer", "accept-language"}
    }


def _public_media_headers(adapter: Any) -> dict[str, str]:
    """Headers for signed public-share media URLs; never pass account cookies to ffmpeg."""
    return {
        key: value
        for key, value in adapter.headers.items()
        if key.lower() in {"user-agent", "origin", "referer", "accept-language"}
    }


def _sanitise_media_error(exc: BaseException) -> str:
    message = re.sub(r"https?://\S+", "[URL]", str(exc))
    message = re.sub(
        r"(?i)\b(cookie|authorization|stoken|token|fid_token)\s*[:=]\s*[^\s,;]+",
        r"\1=[REDACTED]",
        message,
    )
    return message[:240]


def _walk_mappings(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_mappings(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk_mappings(child)


def _first_nested_url(payload: Any, keys: tuple[str, ...]) -> str:
    for mapping in _walk_mappings(payload):
        for key in keys:
            value = mapping.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return value
    return ""


def _first_nested_number(payload: Any, keys: tuple[str, ...]) -> float:
    for mapping in _walk_mappings(payload):
        for key in keys:
            try:
                value = float(mapping.get(key))
            except (TypeError, ValueError):
                continue
            if value > 0:
                return value / 1000.0 if value > 10000 else value
    return 0.0


def _public_video_metadata(
    adapter: Any,
    share_link: str,
    record: dict[str, Any],
    cache: dict[str, Any],
) -> dict[str, Any]:
    """Resolve a video poster and HLS URL from the public Quark share itself."""
    if not share_link:
        raise RuntimeError("缺少公开分享链接")
    if not cache.get("initialised"):
        cache["initialised"] = True
        pwd_id = adapter._pwd_id(share_link)
        cache["pwd_id"] = pwd_id
        cache["stoken"] = adapter._get_stoken(pwd_id, adapter._passcode(share_link))
        cache["parents"] = {}

    fid = str(record.get("fid") or "")
    fid_token = str(record.get("share_fid_token") or "")
    if not fid_token:
        parent_id = str(record.get("parent_id") or "0")
        parent_cache = cache["parents"]
        if parent_id not in parent_cache:
            _is_owner, items = adapter._share_detail(cache["pwd_id"], cache["stoken"], parent_id)
            parent_cache[parent_id] = {str(item.fid): str(item.share_fid_token or "") for item in items}
        fid_token = str(parent_cache[parent_id].get(fid) or "")
    if not fid_token:
        raise RuntimeError("公开分享中没有找到视频预览令牌")

    response = adapter._request(
        "GET",
        "/1/clouddrive/share/sharepage/video_preview",
        params={
            "pwd_id": cache["pwd_id"],
            "stoken": cache["stoken"],
            "fid": fid,
            "fid_token": fid_token,
            "format": "png",
            "__dt": str(random.randint(200, 9999)),
            "__t": str(int(time.time() * 1000)),
        },
    )
    data = response.get("data") or {}
    preview_url = _first_nested_url(
        data,
        ("preview_url", "image_url", "big_thumbnail", "thumbnail"),
    )
    play_url = ""
    for mapping in _walk_mappings(data):
        play_info = mapping.get("play_info")
        if isinstance(play_info, dict):
            candidate = str(play_info.get("url") or "")
            if candidate.startswith(("http://", "https://")):
                play_url = candidate
                break
    if not play_url:
        play_url = _first_nested_url(data, ("play_url", "m3u8_url"))
    if not preview_url and not play_url:
        raise RuntimeError("公开分享没有返回可用的视频预览")
    return {
        "preview_url": preview_url,
        "play_url": play_url,
        "duration": _first_nested_number(data, ("duration", "video_duration")),
    }


def _video_frame_quality(path: Path) -> tuple[float, dict[str, float]]:
    """Score detail and spatial activity so blank/error/transition frames lose."""
    with Image.open(path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
    width, height = image.size
    if width < 320 or height < 180:
        return 0.0, {"detail": 0.0, "activity": 0.0, "extreme": 1.0}
    image.thumbnail((480, 270), Image.Resampling.LANCZOS)
    gray = ImageOps.grayscale(image)
    detail = float(ImageStat.Stat(gray).stddev[0])
    edges = gray.filter(ImageFilter.FIND_EDGES)
    if edges.width > 4 and edges.height > 4:
        edges = edges.crop((2, 2, edges.width - 2, edges.height - 2))
    edge_mean = float(ImageStat.Stat(edges).mean[0])

    histogram = gray.histogram()
    pixel_count = max(1, sum(histogram))
    extreme = (sum(histogram[:10]) + sum(histogram[246:])) / pixel_count
    active_cells = 0
    total_cells = 24
    for row in range(4):
        for column in range(6):
            box = (
                column * gray.width // 6,
                row * gray.height // 4,
                (column + 1) * gray.width // 6,
                (row + 1) * gray.height // 4,
            )
            cell = gray.crop(box)
            cell_detail = float(ImageStat.Stat(cell).stddev[0])
            cell_edges = cell.filter(ImageFilter.FIND_EDGES)
            cell_edge_mean = float(ImageStat.Stat(cell_edges).mean[0])
            if cell_detail >= 12.0 or cell_edge_mean >= 12.0:
                active_cells += 1
    activity = active_cells / total_cells
    score = detail * 0.72 + edge_mean * 0.90 + activity * 32.0 - max(0.0, extreme - 0.82) * 120.0
    if detail < 10.0 or activity < 0.25:
        score *= 0.35
    return round(max(0.0, score), 3), {
        "detail": round(detail, 3),
        "edge": round(edge_mean, 3),
        "activity": round(activity, 3),
        "extreme": round(extreme, 3),
    }


def _save_bytes(output: Path, content: bytes) -> None:
    if not content:
        raise RuntimeError("媒体响应为空")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=output.parent,
            prefix=f".{output.stem}.",
            suffix=output.suffix or ".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        temporary.replace(output)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _save_png_atomically(image: Image.Image, output: Path) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=output.parent,
            prefix=f".{output.stem}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
        image.save(temporary, format="PNG", optimize=True)
        temporary.replace(output)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _fetch_image(url: str, output: Path, headers: dict[str, str]) -> None:
    request = Request(url, headers=headers)
    with urlopen(request, timeout=45) as response:
        content = response.read()
    _save_bytes(output, content)
    try:
        with Image.open(output) as image:
            image.verify()
    except Exception:
        output.unlink(missing_ok=True)
        raise RuntimeError(f"下载的媒体不是可识别图片：{output.name}")


def _download_file(
    url: str,
    output: Path,
    headers: dict[str, str],
    *,
    timeout: float = 45,
) -> None:
    request = Request(url, headers=headers)
    temporary: Path | None = None
    try:
        with urlopen(request, timeout=timeout) as response:
            with tempfile.NamedTemporaryFile(
                dir=output.parent,
                prefix=f".{output.stem}.",
                suffix=output.suffix or ".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
        if temporary.stat().st_size <= 0:
            raise RuntimeError("媒体下载为空")
        temporary.replace(output)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _render_pdf_page(
    pdf_path: Path,
    output: Path,
    *,
    timeout: float = PDF_PREVIEW_TIMEOUT_SECONDS,
) -> None:
    renderer = shutil.which("pdftoppm")
    if not renderer:
        raise RuntimeError("系统未找到 pdftoppm，无法把 PDF 首页渲染为封面")

    prefix = output.with_suffix("")
    rendered = prefix.with_suffix(".png")
    rendered.unlink(missing_ok=True)
    output.unlink(missing_ok=True)
    try:
        subprocess.run(
            [
                renderer,
                "-f",
                "1",
                "-l",
                "1",
                "-singlefile",
                "-png",
                "-r",
                "120",
                str(pdf_path),
                str(prefix),
            ],
            check=True,
            timeout=timeout,
            capture_output=True,
        )
        if not rendered.is_file() or rendered.stat().st_size <= 0:
            raise RuntimeError("pdftoppm 没有生成 PDF 首页截图")
        if rendered.resolve() != output.resolve():
            rendered.replace(output)
        with Image.open(output) as image:
            image.verify()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
        rendered.unlink(missing_ok=True)
        output.unlink(missing_ok=True)
        raise


class _PreviewTextParser(HTMLParser):
    """Collect readable text from HTML without carrying markup into a card."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = re.sub(r"\s+", " ", data).strip()
        if value:
            self.parts.append(value)


def _document_candidates(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = _media_candidates(records, DOCUMENT_EXTENSIONS)
    preferred_words = ("cover", "封面", "海报", "banner", "preview", "截图", "首页")
    return sorted(
        candidates,
        key=lambda record: (
            DOCUMENT_EXTENSION_PRIORITY.get(str(record.get("extension") or ""), 99),
            0 if any(word in str(record.get("name") or "").casefold() for word in preferred_words) else 1,
            int(record.get("depth") or 0),
            str(record.get("path") or ""),
        ),
    )


def _decode_document_bytes(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _normalise_document_lines(lines: Any, *, limit: int = 80) -> list[str]:
    result: list[str] = []
    for raw_line in lines:
        line = re.sub(r"\s+", " ", str(raw_line or "")).strip()
        if not line:
            continue
        result.append(line[:240])
        if len(result) >= limit:
            break
    return result


def _extract_document_lines(path: Path, extension: str) -> list[str]:
    """Extract real first-content lines for common document formats."""
    extension = extension.lower()

    if extension == ".docx":
        from docx import Document

        document = Document(path)
        lines = [paragraph.text for paragraph in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                lines.append(" | ".join(cell.text for cell in row.cells))
        return _normalise_document_lines(lines)

    if extension == ".pptx":
        from pptx import Presentation

        presentation = Presentation(path)
        if not presentation.slides:
            return []
        lines: list[str] = []
        for shape in presentation.slides[0].shapes:
            value = getattr(shape, "text", "")
            if value:
                lines.extend(str(value).splitlines())
        return _normalise_document_lines(lines)

    if extension in {".xlsx", ".xlsm"}:
        from openpyxl import load_workbook

        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            sheet = workbook.active
            lines = []
            for row in sheet.iter_rows(max_row=24, max_col=12, values_only=True):
                values = [str(value).strip() for value in row if value is not None and str(value).strip()]
                if values:
                    lines.append(" | ".join(values))
            return _normalise_document_lines(lines)
        finally:
            workbook.close()

    if extension == ".xls":
        try:
            import xlrd
        except ImportError as exc:
            raise RuntimeError("当前环境没有安装 xlrd，无法读取旧版 XLS") from exc
        workbook = xlrd.open_workbook(path, on_demand=True)
        try:
            sheet = workbook.sheet_by_index(0)
            lines = []
            for row_index in range(min(sheet.nrows, 24)):
                values = [str(value).strip() for value in sheet.row_values(row_index) if str(value).strip()]
                if values:
                    lines.append(" | ".join(values))
            return _normalise_document_lines(lines)
        finally:
            workbook.release_resources()

    if extension == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("当前环境没有安装 pypdf，无法提取 PDF 文本") from exc
        reader = PdfReader(str(path))
        if not reader.pages:
            return []
        return _normalise_document_lines((reader.pages[0].extract_text() or "").splitlines())

    if extension in {".doc", ".ppt"}:
        converter = "antiword" if extension == ".doc" else "catppt"
        executable = shutil.which(converter)
        if not executable:
            raise RuntimeError(f"当前环境没有 {converter}，无法读取旧版 {extension} 文件")
        result = subprocess.run(
            [executable, str(path)],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=DOCUMENT_PREVIEW_TIMEOUT_SECONDS,
        )
        return _normalise_document_lines(result.stdout.splitlines())

    if extension in {".odt", ".ods", ".odp"}:
        with zipfile.ZipFile(path) as archive:
            xml_parts = []
            for name in archive.namelist():
                if name.endswith(".xml"):
                    xml_parts.append(archive.read(name).decode("utf-8", errors="replace"))
        text = re.sub(r"<[^>]+>", " ", " ".join(xml_parts))
        return _normalise_document_lines(text.splitlines())

    raw_text = _decode_document_bytes(path)
    if extension in {".html", ".htm"}:
        parser = _PreviewTextParser()
        parser.feed(raw_text)
        parser.close()
        return _normalise_document_lines(parser.parts)
    if extension == ".rtf":
        raw_text = re.sub(r"\\[a-z]+\d* ?", " ", raw_text, flags=re.IGNORECASE)
        raw_text = raw_text.replace("{", " ").replace("}", " ")
    if extension == ".json":
        try:
            raw_text = json.dumps(json.loads(raw_text), ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            pass
    if extension == ".csv":
        rows = csv.reader(raw_text.splitlines())
        return _normalise_document_lines(" | ".join(row) for row in rows)
    if extension == ".zip":
        with zipfile.ZipFile(path) as archive:
            return _normalise_document_lines(
                (f"{index + 1}. {name}" for index, name in enumerate(archive.namelist())),
                limit=40,
            )
    return _normalise_document_lines(raw_text.splitlines())


def _preview_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\NotoSansSC-VF.ttf",
    ) if bold else (
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\NotoSansSC-VF.ttf",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except (OSError, ValueError):
            continue
    for candidate in cjk_font_candidates(bold=bold):
        try:
            font = ImageFont.truetype(candidate, size=size)
            masks = [font.getmask(char) for char in ("永", "诗", "国")]
            if all(mask.getbbox() for mask in masks) and len({bytes(mask) for mask in masks}) == 3:
                return font
        except (OSError, ValueError):
            continue
    raise RuntimeError("没有可用的中文字体，请配置 XPAN_CJK_FONT / XPAN_CJK_FONT_BOLD")


def _wrap_preview_line(line: str, *, width: int = 42) -> list[str]:
    return textwrap.wrap(
        line,
        width=width,
        break_long_words=True,
        break_on_hyphens=False,
    ) or [line]


def _render_document_content_preview(
    path: Path,
    output: Path,
    record: dict[str, Any],
) -> list[str]:
    """Render extracted source content, never a directory-summary substitute."""
    extension = str(record.get("extension") or path.suffix).lower()
    lines = _extract_document_lines(path, extension)
    if not lines:
        raise RuntimeError(f"{record.get('name') or path.name} 没有可提取的预览内容")

    width, height = 1280, 720
    canvas = Image.new("RGB", (width, height), (20, 27, 45))
    draw = ImageDraw.Draw(canvas)
    accent = (70, 218, 164)
    secondary = (246, 191, 77)
    heading_font = _preview_font(30, bold=True)
    body_font = _preview_font(23)
    small_font = _preview_font(18)
    draw.rounded_rectangle((24, 24, width - 24, height - 24), radius=22, outline=accent, width=3)
    draw.text((54, 48), "文件预览", font=heading_font, fill=(242, 247, 255))
    file_name = str(record.get("name") or path.name)
    file_label = f"{file_name}  ·  {extension.lstrip('.').upper() or 'FILE'}"
    draw.text((54, 96), file_label[:72], font=small_font, fill=secondary)
    draw.line((54, 132, width - 54, 132), fill=(62, 91, 113), width=2)

    wrapped: list[str] = []
    for line in lines:
        wrapped.extend(_wrap_preview_line(line))
    line_height = 32
    y = 164
    rendered = 0
    for line in wrapped:
        if y + line_height > height - 56:
            break
        draw.text((58, y), line, font=body_font, fill=(233, 239, 247))
        y += line_height
        rendered += 1
    if rendered == 0:
        raise RuntimeError(f"{file_name} 的预览内容无法放入预览画布")
    draw.text((58, height - 48), "显示文件开头的完整内容行", font=small_font, fill=(155, 177, 191))
    output.parent.mkdir(parents=True, exist_ok=True)
    _save_png_atomically(canvas, output)
    return lines


def _extract_video_frame(
    url: str,
    output: Path,
    headers: dict[str, str],
    *,
    timestamp_seconds: float = 10.0,
    timeout: float = VIDEO_FRAME_TIMEOUT_SECONDS,
) -> None:
    ffmpeg = find_media_tool("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("系统未找到 ffmpeg，无法从视频截取封面")
    header_text = "".join(f"{key}: {value}\r\n" for key, value in headers.items())
    try:
        subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                f"{max(0.0, timestamp_seconds):.3f}",
                "-headers",
                header_text,
                "-i",
                url,
                "-frames:v",
                "1",
                "-vf",
                "scale=1280:-2",
                str(output),
            ],
            check=True,
            timeout=timeout,
            capture_output=True,
        )
        if not output.is_file() or output.stat().st_size == 0:
            raise RuntimeError("ffmpeg 没有生成视频截图")
        with Image.open(output) as image:
            image.verify()
    except subprocess.SubprocessError as exc:
        output.unlink(missing_ok=True)
        raise RuntimeError("ffmpeg 无法提取该视频的可用关键帧") from None
    except (OSError, RuntimeError, ValueError):
        output.unlink(missing_ok=True)
        raise


def _publish_video_candidates(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select videos by explicit lesson sequence after the full tree is known."""

    from xpan_auto.media_selection import order_video_records, selection_basis

    return order_video_records(records)


def _store_original_video(
    source: Path,
    asset_dir: Path,
    *,
    video_name: str,
) -> Path:
    """Atomically preserve the complete Quark download before platform checks."""

    asset_dir.mkdir(parents=True, exist_ok=True)
    if not source.is_file() or source.stat().st_size <= 0:
        raise RuntimeError("quark-auto-save 没有返回可用的本地原视频")
    suffix = source.suffix or ".video"
    original = asset_dir / f"{video_name}-original{suffix or '.video'}"
    for old_original in asset_dir.glob(f"{video_name}-original.*"):
        if old_original.resolve() != source.resolve():
            old_original.unlink(missing_ok=True)

    temporary = original.with_name(f".{original.stem}.part{original.suffix}")
    temporary.unlink(missing_ok=True)
    if source.resolve() != original.resolve():
        shutil.move(str(source), temporary)
        temporary.replace(original)
        if source.parent.name == ".quark-download":
            shutil.rmtree(source.parent)
    return original


def _quark_auto_save_download(
    fid: str,
    asset_dir: Path,
    *,
    auto_save_dir: Path,
    config_file: Path,
    file_name: str,
    expected_size: int | None,
    cloud_path: str,
    timeout: float = 7200.0,
) -> Path:
    """Download one selected FID through the deployed quark-auto-save helper."""

    downloader = auto_save_dir / "download_first_video.py"
    if not downloader.is_file():
        raise RuntimeError(f"quark-auto-save 部署不完整，缺少下载脚本：{downloader}")
    if not config_file.is_file():
        raise RuntimeError(f"夸克登录状态文件不存在：{config_file}")

    download_dir = asset_dir / ".quark-download"
    # Local resilience patch (2026-08-14): keep existing .part files so an
    # interrupted download resumes from its checkpoint instead of starting
    # over (download_first_video.py picks the largest valid partial).
    download_dir.mkdir(parents=True, exist_ok=True)

    python = auto_save_dir / ".venv" / ("Scripts" if os.name == "nt" else "bin") / (
        "python.exe" if os.name == "nt" else "python"
    )
    if not python.is_file():
        python = Path(sys.executable)
    command = [
        str(python),
        str(downloader),
        cloud_path or file_name,
        str(download_dir),
        "--config",
        str(config_file),
        "--fid",
        fid,
        "--file-name",
        file_name,
    ]
    if expected_size and expected_size > 0:
        command.extend(["--expected-size", str(expected_size)])
    try:
        result = subprocess.run(
            command,
            cwd=auto_save_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip().splitlines()
            detail_text = detail[-1] if detail else "quark-auto-save 下载命令失败"
            raise RuntimeError(
                "夸克原视频下载阶段失败（尚未执行 Telegram 媒体路由）："
                f"{detail_text}"
            )
        files = [
            path
            for path in download_dir.iterdir()
            if path.is_file() and path.stat().st_size > 0
        ]
        if len(files) != 1:
            raise RuntimeError("quark-auto-save 下载成功但未返回唯一的本地视频路径")
        downloaded = files[0]
        if downloaded.name != Path(file_name).name:
            raise RuntimeError(
                f"quark-auto-save 返回文件名与首个视频不一致：{downloaded.name}"
            )
        return downloaded
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"quark-auto-save 下载执行失败：{_sanitise_media_error(exc)}") from None


def _prepare_publish_video(
    adapter: Any,
    records: list[dict[str, Any]],
    asset_dir: Path,
    *,
    share_link: str,
    video_name: str,
    quark_auto_save_dir: Path,
    quark_cookie_file: Path,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Download the first complete video and prepare one bounded publishable prefix."""

    from xpan_auto.media_selection import selection_basis

    candidates = _publish_video_candidates(records)
    if not candidates:
        raise RuntimeError("项目清单中没有视频")

    quality_path = asset_dir / "video-quality.json"
    src_dir = project_root() / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    from xpan_auto.video_quality import inspect_publish_video, prepare_publish_video

    record = candidates[0]
    errors: list[str] = []
    stage = "quark-original-download"
    try:
        suffix = Path(str(record["name"])).suffix or ".video"
        existing_original = asset_dir / f"{video_name}-original{suffix}"
        expected_size = int(record.get("size_bytes") or 0)
        can_reuse = (
            not force_refresh
            and existing_original.is_file()
            and existing_original.stat().st_size > 0
            and (expected_size <= 0 or existing_original.stat().st_size == expected_size)
        )
        if can_reuse:
            stage = "reuse-complete-original"
            original_path = existing_original
        else:
            downloaded = _quark_auto_save_download(
                str(record["fid"]),
                asset_dir,
                auto_save_dir=quark_auto_save_dir,
                config_file=quark_cookie_file,
                file_name=str(record["name"]),
                expected_size=record.get("size_bytes"),
                cloud_path=str(record.get("path") or record["name"]),
            )
            stage = "store-complete-original"
            original_path = _store_original_video(
                downloaded,
                asset_dir,
                video_name=video_name,
            )
        stage = "original-quality"
        original_report = inspect_publish_video(original_path, max_size_bytes=2**63 - 1)
        if not original_report.passed:
            quality_path.write_text(
                json.dumps(
                    {"passed": False, "stage": stage, "original": original_report.__dict__},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            raise RuntimeError(f"original: {'；'.join(original_report.issues)}")
        stage = "publish-video-limits"
        preparation = prepare_publish_video(
            original_path,
            source_report=original_report,
            max_duration_seconds=600.0,
            max_size_bytes=TELEGRAM_BOT_API_MAX_MEDIA_BYTES,
            target_size_bytes=49_000_000,
        )
        original_path = Path(preparation.final.path)
        for stale in (
            asset_dir / f"{video_name}.mp4",
            asset_dir / f"{video_name}-x.mp4",
            asset_dir / f"{video_name}-telegram.mp4",
        ):
            stale.unlink(missing_ok=True)
        size_bytes = original_path.stat().st_size
        if size_bytes >= TELEGRAM_BOT_API_MAX_MEDIA_BYTES:
            raise RuntimeError(
                "最终发布视频没有严格小于 50,000,000 bytes，禁止进入上传阶段"
            )
        telegram_route = "bot-api"
        preparation_payload = asdict(preparation)
        quality_path.write_text(
            json.dumps(
                {
                    "passed": preparation.passed,
                    "telegram_route": telegram_route,
                    "preparation": preparation_payload,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return {
            "kind": "project-video",
            "source_name": record["name"],
            "source_path": str(original_path),
            "original_path": str(original_path),
            "publish_path": str(original_path),
            "size_bytes": size_bytes,
            "source_size_bytes": preparation.source.size_bytes,
            "duration_seconds": preparation.final.duration_seconds,
            "source_duration_seconds": preparation.source.duration_seconds,
            "duration_trimmed": preparation.duration_trimmed,
            "size_trimmed": preparation.size_trimmed,
            "container_remuxed": preparation.container_remuxed,
            "telegram_route": telegram_route,
            "source_fid": record["fid"],
            "selection_basis": selection_basis(record),
            "source_url_type": "quark-auto-save",
            "download_provider": "quark-auto-save",
            "saved_as_original_mp4": original_path.suffix.lower() == ".mp4",
            "quality": preparation_payload,
        }
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        (asset_dir / f"{video_name}-x.mp4").unlink(missing_ok=True)
        (asset_dir / f"{video_name}-telegram.mp4").unlink(missing_ok=True)
        errors.append(
            f"{stage}:{record.get('name')}: {_sanitise_media_error(exc)}"
        )

    raise RuntimeError(
        "项目存在视频，但目录首个视频未能完成完整下载、源质检和发布视频截断；"
        "禁止尝试后续视频或静默降级为图片。"
        + (f" 最近错误：{' | '.join(errors[-4:])}" if errors else "")
    )


def _select_public_video_frame(
    adapter: Any,
    share_link: str,
    records: list[dict[str, Any]],
    asset_dir: Path,
    *,
    media_name: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Compare real public-share frames and keep the strongest usable candidate."""
    cache: dict[str, Any] = {}
    headers = _public_media_headers(adapter)
    errors: list[str] = []
    samples: list[dict[str, Any]] = []
    temporary_paths: list[Path] = []

    try:
        for candidate_index, record in enumerate(records[:MAX_VIDEO_MEDIA_ATTEMPTS]):
            try:
                metadata = _public_video_metadata(adapter, share_link, record, cache)
            except (OSError, RuntimeError, ValueError) as exc:
                errors.append(f"public-video:{record.get('name')}: {_sanitise_media_error(exc)}")
                continue

            preview_url = str(metadata.get("preview_url") or "")
            if preview_url:
                preview_path = asset_dir / f".{media_name}.public-{candidate_index}-poster.png"
                temporary_paths.append(preview_path)
                try:
                    _fetch_image(preview_url, preview_path, headers)
                    score, metrics = _video_frame_quality(preview_path)
                    samples.append(
                        {
                            "path": preview_path,
                            "record": record,
                            "score": score,
                            "metrics": metrics,
                            "sample": "share-poster",
                            "timestamp_seconds": None,
                        }
                    )
                except (OSError, RuntimeError, ValueError) as exc:
                    errors.append(f"public-poster:{record.get('name')}: {_sanitise_media_error(exc)}")

            play_url = str(metadata.get("play_url") or "")
            if candidate_index == 0 and play_url:
                duration = float(metadata.get("duration") or 0.0)
                later_sample = min(180.0, max(60.0, duration * 0.35 if duration else 60.0))
                for sample_index, timestamp_seconds in enumerate((10.0, later_sample)):
                    frame_path = asset_dir / f".{media_name}.public-{candidate_index}-frame-{sample_index}.png"
                    temporary_paths.append(frame_path)
                    try:
                        _extract_video_frame(
                            play_url,
                            frame_path,
                            headers,
                            timestamp_seconds=timestamp_seconds,
                            timeout=VIDEO_FRAME_TIMEOUT_SECONDS,
                        )
                        score, metrics = _video_frame_quality(frame_path)
                        samples.append(
                            {
                                "path": frame_path,
                                "record": record,
                                "score": score,
                                "metrics": metrics,
                                "sample": "share-keyframe",
                                "timestamp_seconds": round(timestamp_seconds, 3),
                            }
                        )
                    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
                        errors.append(f"public-frame:{record.get('name')}: {_sanitise_media_error(exc)}")

        if not samples:
            return None, errors
        best = max(samples, key=lambda sample: float(sample["score"]))
        if float(best["score"]) < MIN_VIDEO_FRAME_SCORE:
            errors.append(
                f"public-video-quality: best={float(best['score']):.2f}, minimum={MIN_VIDEO_FRAME_SCORE:.2f}"
            )
            return None, errors

        output = asset_dir / f"{media_name}.png"
        with Image.open(best["path"]) as opened:
            selected = ImageOps.exif_transpose(opened).convert("RGB")
            _save_png_atomically(selected, output)
        record = best["record"]
        return {
            "kind": "video-frame",
            "source_name": record["name"],
            "source_path": str(output),
            "source_fid": record["fid"],
            "source_url_type": str(best["sample"]),
            "frame_timestamp_seconds": best["timestamp_seconds"],
            "frame_quality_score": best["score"],
            "frame_quality": best["metrics"],
            "evaluated_frames": len(samples),
            "evaluated_videos": min(len(records), MAX_VIDEO_MEDIA_ATTEMPTS),
        }, errors
    finally:
        for path in temporary_paths:
            path.unlink(missing_ok=True)


def _prepare_media(
    adapter: Any,
    records: list[dict[str, Any]],
    asset_dir: Path,
    *,
    media_name: str,
    share_link: str = "",
    force_refresh: bool = False,
) -> dict[str, Any]:
    if not force_refresh:
        existing = _existing_media(asset_dir)
        if existing is not None:
            return existing

    def finish(result: dict[str, Any]) -> dict[str, Any]:
        source_path = Path(str(result.get("source_path") or ""))
        if source_path.is_file():
            for suffix in (".webp", ".png", ".jpg", ".jpeg"):
                stale = asset_dir / f"{media_name}{suffix}"
                if stale.exists() and stale.resolve() != source_path.resolve():
                    stale.unlink(missing_ok=True)
        return result

    headers = _media_headers(adapter)
    errors: list[str] = []
    image_candidates = _media_candidates(records, IMAGE_EXTENSIONS)
    for record in image_candidates[:MAX_IMAGE_MEDIA_ATTEMPTS]:
        try:
            metadata = _download_metadata(adapter, str(record["fid"]))
            url = str(metadata.get("download_url") or metadata.get("preview_url") or metadata.get("thumbnail") or "")
            if not url:
                raise RuntimeError("项目图片没有可下载地址")
            output = asset_dir / f"{media_name}{record['extension'] or '.png'}"
            _fetch_image(url, output, headers)
            return finish({
                "kind": "project-image",
                "source_name": record["name"],
                "source_path": str(output),
                "source_fid": record["fid"],
                "source_url_type": "download_url" if metadata.get("download_url") else "preview_url",
            })
        except (OSError, RuntimeError, ValueError) as exc:
            errors.append(f"image:{record.get('name')}: {_sanitise_media_error(exc)}")

    video_candidates = _media_candidates(records, VIDEO_EXTENSIONS)
    if share_link and video_candidates:
        public_result, public_errors = _select_public_video_frame(
            adapter,
            share_link,
            video_candidates,
            asset_dir,
            media_name=media_name,
        )
        errors.extend(public_errors)
        if public_result is not None:
            return finish(public_result)

    for record in video_candidates[:MAX_VIDEO_MEDIA_ATTEMPTS]:
        try:
            metadata = _download_metadata(adapter, str(record["fid"]))
            output = asset_dir / f"{media_name}.png"
            for source_key in ("big_thumbnail", "thumbnail", "thumbnail_url"):
                preview_url = str(metadata.get(source_key) or "")
                if not preview_url:
                    continue
                try:
                    _fetch_image(preview_url, output, headers)
                    score, metrics = _video_frame_quality(output)
                    if score < MIN_VIDEO_FRAME_SCORE:
                        raise RuntimeError(f"视频缩略图质量不足：{score:.2f}")
                    return finish({
                        "kind": "video-frame",
                        "source_name": record["name"],
                        "source_path": str(output),
                        "source_fid": record["fid"],
                        "source_url_type": source_key,
                        "frame_timestamp_seconds": None,
                        "frame_quality_score": score,
                        "frame_quality": metrics,
                        "evaluated_frames": 1,
                        "evaluated_videos": 1,
                    })
                except (OSError, RuntimeError, ValueError) as exc:
                    errors.append(f"video-{source_key}:{record.get('name')}: {_sanitise_media_error(exc)}")
                    output.unlink(missing_ok=True)

            download_url = str(metadata.get("download_url") or "")
            if download_url:
                _extract_video_frame(
                    download_url,
                    output,
                    headers,
                    timestamp_seconds=10.0,
                    timeout=VIDEO_FRAME_TIMEOUT_SECONDS,
                )
                score, metrics = _video_frame_quality(output)
                if score < MIN_VIDEO_FRAME_SCORE:
                    raise RuntimeError(f"视频关键帧质量不足：{score:.2f}")
                return finish({
                    "kind": "video-frame",
                    "source_name": record["name"],
                    "source_path": str(output),
                    "source_fid": record["fid"],
                    "source_url_type": "download_url",
                    "frame_timestamp_seconds": 10.0,
                    "frame_quality_score": score,
                    "frame_quality": metrics,
                    "evaluated_frames": 1,
                    "evaluated_videos": 1,
                })
            raise RuntimeError("项目视频没有可用缩略图或下载地址")
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            errors.append(f"video:{record.get('name')}: {_sanitise_media_error(exc)}")

    document_candidates = _document_candidates(records)
    for record in document_candidates[:MAX_DOCUMENT_MEDIA_ATTEMPTS]:
        temporary_document: Path | None = None
        extension = str(record.get("extension") or "").lower()
        try:
            metadata = _download_metadata(adapter, str(record["fid"]))
            download_url = str(metadata.get("download_url") or "")
            preview_url = str(metadata.get("preview_url") or metadata.get("thumbnail") or "")
            output = asset_dir / f"{media_name}.png"
            source_url_type = ""
            preview_method = ""
            if preview_url:
                try:
                    _fetch_image(preview_url, output, headers)
                    source_url_type = "preview_url"
                    preview_method = "preview-url"
                except (OSError, RuntimeError, ValueError):
                    if not download_url:
                        raise
            if not source_url_type and download_url:
                with tempfile.NamedTemporaryFile(
                    dir=asset_dir,
                    prefix=f".{media_name}.",
                    suffix=extension or ".bin",
                    delete=False,
                ) as handle:
                    temporary_document = Path(handle.name)
                _download_file(download_url, temporary_document, headers)
                if extension == ".pdf":
                    try:
                        _render_pdf_page(temporary_document, output)
                        preview_method = "pdf-page"
                    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
                        _render_document_content_preview(temporary_document, output, record)
                        preview_method = "content-render"
                else:
                    _render_document_content_preview(temporary_document, output, record)
                    preview_method = "content-render"
                source_url_type = "download_url"
            if not source_url_type:
                raise RuntimeError("项目文件没有可下载或预览地址")
            return finish({
                "kind": "document-preview",
                "document_type": extension.lstrip(".") or "file",
                "preview_method": preview_method,
                "source_name": record["name"],
                "source_path": str(output),
                "source_fid": record["fid"],
                "source_url_type": source_url_type,
            })
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            errors.append(f"document:{record.get('name')}: {_sanitise_media_error(exc)}")
        finally:
            if temporary_document is not None and temporary_document.exists():
                temporary_document.unlink()

    attempted = (
        len(image_candidates[:MAX_IMAGE_MEDIA_ATTEMPTS])
        + len(video_candidates[:MAX_VIDEO_MEDIA_ATTEMPTS])
        + len(document_candidates[:MAX_DOCUMENT_MEDIA_ATTEMPTS])
    )
    candidate_counts = {
        "images": len(image_candidates),
        "videos": len(video_candidates),
        "documents": len(document_candidates),
    }
    if any(candidate_counts.values()):
        return {
            "kind": "media-preview-required",
            "source_path": None,
            "error": "项目含可预览文件，但真实预览全部失败；必须恢复预览后才能生成和发布",
            "diagnostics": errors[-6:],
            "attempted_candidates": attempted,
            "candidate_counts": candidate_counts,
        }
    return {
        "kind": "no-project-media",
        "source_path": None,
        "error": "项目清单中没有图片、视频或可预览文档",
        "attempted_candidates": 0,
        "candidate_counts": candidate_counts,
    }


def _write_details(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    if args.row_index is not None and args.row_index < 1:
        raise RuntimeError("--row-index must be at least 1")
    if args.max_depth < 0 or args.max_items < 1:
        raise RuntimeError("--max-depth must be non-negative and --max-items must be positive")
    if args.timeout <= 0:
        raise RuntimeError("--timeout must be positive")
    if args.asset_dir is not None:
        asset_dir = resolve_path(args.asset_dir)
        row_index = args.row_index
    else:
        if args.row_index is None:
            raise RuntimeError("--row-index is required when --asset-dir is omitted")
        asset_dir = resolve_path(args.asset_root) / f"{args.row_index:04d}"
        row_index = args.row_index
    asset_dir.mkdir(parents=True, exist_ok=True)

    metadata, stored_source_url = _load_job_metadata(
        resolve_path(args.db), row_index=row_index, share_link=args.share_link.strip()
    )
    share_link = args.share_link.strip() or stored_source_url
    root_id, root_name = _target_from_metadata(metadata)
    title = args.title.strip()

    src_dir = project_root() / "src"
    sys.path.insert(0, str(src_dir))
    from xpan_auto.quark_adapter import QuarkAdapter

    cookie_file = resolve_path(args.cookie_file)
    if not cookie_file.is_file():
        raise RuntimeError(f"Quark cookie file not found: {cookie_file}")
    adapter = QuarkAdapter(cookie_file=cookie_file, timeout=args.timeout)

    fallback_items: list[Any] = []
    if not root_id:
        if not share_link:
            raise RuntimeError("No target folder or share link found for this row")
        inspected = adapter.inspect_share(share_link)
        fallback_items = list(inspected.items)
        root_name = root_name or title
        root_id = next((item.fid for item in fallback_items if item.is_dir), "")

    if root_id:
        children = adapter.list_folder(root_id)
        wrapper = next(
            (
                item
                for item in children
                if item.is_dir and _normalized_name(item.name) == _normalized_name(root_name)
            ),
            None,
        )
        if wrapper is not None:
            root_id = wrapper.fid
            root_name = wrapper.name
        title = title or root_name
        if share_link:
            records = _collect_share_tree(
                adapter,
                share_link,
                root_name or title,
                max_depth=args.max_depth,
                max_items=args.max_items,
            )
        else:
            records = _collect_tree(
                adapter,
                root_id,
                root_name or title,
                max_depth=args.max_depth,
                max_items=args.max_items,
            )
    else:
        records = [_item_record(item, path=item.name, depth=0) for item in fallback_items]
        title = title or root_name

    if not records:
        raise RuntimeError("Quark project returned no visible files or folders; refusing to create empty details")
    if len(records) >= args.max_items:
        raise RuntimeError(
            f"夸克目录达到递归上限 {args.max_items} 项，无法证明已读取完整文件树，禁止准备发布媒体"
        )

    details_path = asset_dir / args.details_name
    prior_policy_version = 0
    prior_publish_policy_version = 0
    if details_path.is_file():
        try:
            prior_payload = json.loads(details_path.read_text(encoding="utf-8"))
            prior_policy_version = int(prior_payload.get("media_policy_version") or 0)
            prior_publish_policy_version = int(prior_payload.get("publish_media_policy_version") or 0)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            prior_policy_version = 0
            prior_publish_policy_version = 0

    video_candidates = _publish_video_candidates(records)
    if video_candidates:
        media = _prepare_publish_video(
            adapter,
            records,
            asset_dir,
            share_link=share_link,
            video_name=args.video_name,
            quark_auto_save_dir=resolve_path(args.quark_auto_save_dir),
            quark_cookie_file=cookie_file,
            force_refresh=prior_publish_policy_version != PUBLISH_MEDIA_POLICY_VERSION,
        )
    else:
        for old_original in asset_dir.glob(f"{args.video_name}-original.*"):
            old_original.unlink(missing_ok=True)
        for stale in (
            asset_dir / f"{args.video_name}.mp4",
            asset_dir / f"{args.video_name}-x.mp4",
            asset_dir / f"{args.video_name}-telegram.mp4",
        ):
            stale.unlink(missing_ok=True)
        (asset_dir / "video-quality.json").unlink(missing_ok=True)
        media = _prepare_media(
            adapter,
            records,
            asset_dir,
            media_name=args.media_name,
            share_link=share_link,
            force_refresh=(
                prior_policy_version != MEDIA_POLICY_VERSION
                or prior_publish_policy_version != PUBLISH_MEDIA_POLICY_VERSION
            ),
        )
    folder_records = [record for record in records if record["type"] == "folder"]
    file_records = [record for record in records if record["type"] == "file"]
    extension_counts = Counter(record["extension"] or "(no extension)" for record in file_records)
    top_level = [record for record in records if int(record.get("depth") or 0) == 0]
    representative_files = file_records[:20]
    summary = {
        "folder_count": len(folder_records),
        "file_count": len(file_records),
        "extension_count": len(extension_counts),
        "extension_counts": dict(extension_counts.most_common()),
        "truncated": len(records) >= args.max_items,
    }
    payload = {
        "row_index": row_index,
        "media_policy_version": MEDIA_POLICY_VERSION,
        "publish_media_policy_version": PUBLISH_MEDIA_POLICY_VERSION,
        "publish_media_strategy": "first-video-prefix-max-600s-under-50mb-typefully-mp4-image-fallback",
        "title": title,
        "source_share_link": share_link,
        "target_root": str(metadata.get("target_root") or root_name),
        "root_folder_id": root_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "media": media,
        "top_level": top_level,
        "representative_files": representative_files,
        "items": records,
    }

    _write_details(details_path, payload)
    print(
        json.dumps(
            {
                "action": "created",
                "details": str(details_path),
                "row_index": row_index,
                "title": title,
                "summary": summary,
                "media": media,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
