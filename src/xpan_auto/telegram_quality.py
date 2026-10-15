from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from PIL import Image, ImageFilter, ImageOps, ImageStat
from .runtime import resolve_project_path
from .telegram_formatter import TELEGRAM_CHANNEL_URL


TELEGRAM_QUALITY_VERSION = 12
EXPECTED_MEDIA_POLICY_VERSION = 6
EXPECTED_IMAGE_SIZE = (1672, 941)
DOCUMENT_COVER_LANDSCAPE_SIZE = (1920, 1080)
DOCUMENT_COVER_PORTRAIT_SIZE = (1080, 1920)
DOCUMENT_COVER_IMAGE_SIZES = {DOCUMENT_COVER_LANDSCAPE_SIZE, DOCUMENT_COVER_PORTRAIT_SIZE}
DOCUMENT_LANDSCAPE_ASPECT_THRESHOLD = 1.10
MIN_RENDERED_ACTIVITY = 0.60
MIN_IMAGEGEN_ACTIVITY = 0.45
MIN_LEFT_ACTIVITY = 0.50
MIN_TEXT_ONLY_LEFT_ACTIVITY = 0.58
MIN_SOURCE_SIDE_ACTIVITY = 0.40
MIN_TITLE_SUPPORT_GAP = 28
MIN_TITLE_FONT_SIZE = 96
PREVIEWABLE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp",
    ".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv", ".m4v",
    ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx",
    ".txt", ".md", ".csv", ".json", ".html", ".htm", ".rtf",
    ".xml", ".yaml", ".yml", ".log", ".ini", ".sql",
}
DOCUMENT_COVER_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".odt", ".rtf",
    ".ppt", ".pptx", ".odp",
    ".xls", ".xlsx", ".ods", ".csv",
    ".epub", ".mobi", ".azw3",
    ".txt", ".md", ".json", ".html", ".htm",
    ".xml", ".yaml", ".yml", ".sql", ".log", ".ini",
}
GENERIC_SPINE_LABELS = {"资料", "视频", "课程", "推广", "课件", "文档", "音频", "素材", "文件", "其他", "讲义"}
GENERIC_METRIC_LABELS = {"格式", "文件类型", "类型"}
DESCRIPTION_PLACEHOLDERS = (
    "来源飞书页面已识别",
    "待转存后补充",
    "项目内容待补充",
)
IMAGE_PLACEHOLDERS = ("项目主题", "Telegram Knowledge Share")
TAG_PATTERN = re.compile(r"#[A-Za-z0-9_\u3400-\u9fff]+")


class _HTMLAudit(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.errors: list[str] = []
        self.stack: list[str] = []

    def error(self, message: str) -> None:  # pragma: no cover - kept for older parser versions
        self.errors.append(message)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() not in {"br", "hr", "img", "meta", "link", "input"}:
            self.stack.append(tag.lower())

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        return

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if not self.stack:
            self.errors.append(f"unexpected closing tag: {tag}")
            return
        if self.stack[-1] != normalized:
            self.errors.append(f"mismatched closing tag: {tag}")
            return
        self.stack.pop()


@dataclass(frozen=True)
class TelegramQualityReport:
    passed: bool
    issues: tuple[str, ...]
    checks: dict[str, bool]

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "issues": list(self.issues),
            "checks": dict(self.checks),
            "quality_version": TELEGRAM_QUALITY_VERSION,
        }


def _load_json(path: Path, issues: list[str], label: str) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size <= 0:
        issues.append(f"{label}不存在或为空：{path}")
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        issues.append(f"{label}无法读取：{exc}")
        return {}
    if not isinstance(payload, dict):
        issues.append(f"{label}必须是 JSON 对象：{path}")
        return {}
    return payload


def _is_quark_link(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and parsed.netloc == "pan.quark.cn" and parsed.path.startswith("/s/")


def measure_cover_activity(image_or_path: Image.Image | Path) -> dict[str, Any]:
    """Measure spatially distributed visual activity in the rendered cover."""
    if isinstance(image_or_path, Image.Image):
        image = image_or_path.copy().convert("RGB")
    else:
        with Image.open(image_or_path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")

    columns, rows = 12, 7
    grid: list[list[bool]] = []
    row_ratios: list[float] = []
    for row in range(rows):
        row_values: list[bool] = []
        for column in range(columns):
            box = (
                column * image.width // columns,
                row * image.height // rows,
                (column + 1) * image.width // columns,
                (row + 1) * image.height // rows,
            )
            cell = image.crop(box)
            gray = ImageOps.grayscale(cell)
            rgb_std = sum(float(value) for value in ImageStat.Stat(cell).stddev) / 3.0
            gray_std = float(ImageStat.Stat(gray).stddev[0])
            edges = gray.filter(ImageFilter.FIND_EDGES)
            if edges.width > 4 and edges.height > 4:
                edges = edges.crop((2, 2, edges.width - 2, edges.height - 2))
            histogram = edges.histogram()
            pixels = max(1, sum(histogram))
            edge_ratio = sum(histogram[25:]) / pixels
            row_values.append(edge_ratio >= 0.055 or gray_std >= 18.0 or rgb_std >= 18.0)
        grid.append(row_values)
        row_ratios.append(sum(row_values) / columns)

    total_active = sum(sum(row) for row in grid)
    left_active = sum(sum(row[:6]) for row in grid)
    right_active = sum(sum(row[6:]) for row in grid)
    consecutive_sparse = any(
        row_ratios[index] < 0.34 and row_ratios[index + 1] < 0.34
        for index in range(1, rows - 2)
    )
    return {
        "activity_ratio": round(total_active / (columns * rows), 4),
        "left_activity_ratio": round(left_active / (6 * rows), 4),
        "right_activity_ratio": round(right_active / (6 * rows), 4),
        "row_activity_ratios": [round(value, 4) for value in row_ratios],
        "consecutive_sparse_bands": consecutive_sparse,
    }


def _check_image(
    image_path: Path,
    issues: list[str],
    checks: dict[str, bool],
    *,
    expected_size: tuple[int, int] = EXPECTED_IMAGE_SIZE,
) -> None:
    exists = image_path.is_file() and image_path.stat().st_size > 0
    checks["image_file"] = exists
    if not exists:
        issues.append(f"封面不存在或为空：{image_path}")
        return

    try:
        with Image.open(image_path) as image:
            checks["image_png"] = image.format == "PNG"
            checks["image_dimensions"] = image.size == expected_size
            checks["image_color_mode"] = image.mode in {"RGB", "RGBA"}
            if image.format != "PNG":
                issues.append(f"封面必须是 PNG：{image.format}")
            if image.size != expected_size:
                issues.append(f"封面尺寸不符合标准：{image.size}，应为 {expected_size}")
            if image.mode not in {"RGB", "RGBA"}:
                issues.append(f"封面颜色模式不符合标准：{image.mode}")
            alpha_extrema = ImageStat.Stat(image.getchannel("A")).extrema if image.mode == "RGBA" else None
            if alpha_extrema is not None and alpha_extrema[1] == 0:
                checks["image_visible"] = False
                issues.append("封面完全透明")
            else:
                visible = ImageStat.Stat(image.convert("RGB"))
                spread = max(high - low for low, high in visible.extrema)
                checks["image_visible"] = spread >= 12 and sum(visible.stddev) >= 12
                if not checks["image_visible"]:
                    issues.append("封面疑似空白或对比度不足")
    except (OSError, ValueError) as exc:
        checks["image_decodable"] = False
        issues.append(f"封面无法解码：{exc}")
    else:
        checks["image_decodable"] = True


def _check_rendered_activity(
    image_path: Path,
    metadata: dict[str, Any],
    issues: list[str],
    checks: dict[str, bool],
) -> None:
    if not image_path.is_file():
        checks["rendered_activity"] = False
        return
    try:
        measured = measure_cover_activity(image_path)
    except (OSError, ValueError) as exc:
        checks["rendered_activity"] = False
        issues.append(f"无法测量最终封面的真实饱满度：{exc}")
        return

    activity = float(measured["activity_ratio"])
    left_activity = float(measured["left_activity_ratio"])
    right_activity = float(measured["right_activity_ratio"])
    layout = str(metadata.get("layout") or "")
    design = metadata.get("design") if isinstance(metadata.get("design"), dict) else {}
    fullness = design.get("fullness") if isinstance(design.get("fullness"), dict) else {}

    if layout == "document-cover-adaptive":
        declared = fullness.get("rendered_activity_ratio")
        declared_matches = isinstance(declared, (int, float)) and not isinstance(declared, bool) and abs(
            float(declared) - activity
        ) <= 0.015
        checks["rendered_activity"] = True
        checks["rendered_left_activity"] = True
        checks["rendered_source_side_activity"] = True
        checks["no_consecutive_sparse_bands"] = True
        checks["measured_activity_matches_metadata"] = declared_matches
        if not declared_matches:
            issues.append("文档封面元数据中的成图活跃度缺失或与最终图片实测结果不一致")
        return

    if layout == "image-gen":
        declared = fullness.get("rendered_activity_ratio")
        declared_matches = isinstance(declared, (int, float)) and not isinstance(declared, bool) and abs(
            float(declared) - activity
        ) <= 0.015
        checks["rendered_activity"] = activity >= MIN_IMAGEGEN_ACTIVITY
        checks["rendered_left_activity"] = True
        checks["rendered_source_side_activity"] = True
        checks["no_consecutive_sparse_bands"] = True
        checks["measured_activity_matches_metadata"] = declared_matches
        if not checks["rendered_activity"]:
            issues.append(
                f"ImageGen 成图视觉内容不足：{activity:.3f}，最低要求为 {MIN_IMAGEGEN_ACTIVITY:.2f}"
            )
        if not declared_matches:
            issues.append("ImageGen 封面元数据中的成图活跃度缺失或与最终图片实测结果不一致")
        return

    checks["rendered_activity"] = activity >= MIN_RENDERED_ACTIVITY
    if not checks["rendered_activity"]:
        issues.append(
            f"最终成图真实饱满度不足：{activity:.3f}，最低要求为 {MIN_RENDERED_ACTIVITY:.2f}；不能用自报数值代替成图检测"
        )
    required_left_activity = MIN_LEFT_ACTIVITY if layout == "source-image" else MIN_TEXT_ONLY_LEFT_ACTIVITY
    checks["rendered_left_activity"] = left_activity >= required_left_activity
    if not checks["rendered_left_activity"]:
        issues.append(
            f"左侧信息区不够饱满：{left_activity:.3f}，最低要求为 {required_left_activity:.2f}"
        )
    source_side_ok = layout != "source-image" or right_activity >= MIN_SOURCE_SIDE_ACTIVITY
    checks["rendered_source_side_activity"] = source_side_ok
    if not source_side_ok:
        issues.append(
            f"真实素材区域过空或利用不足：{right_activity:.3f}，最低要求为 {MIN_SOURCE_SIDE_ACTIVITY:.2f}"
        )
    no_sparse_bands = not bool(measured["consecutive_sparse_bands"])
    checks["no_consecutive_sparse_bands"] = no_sparse_bands
    if not no_sparse_bands:
        issues.append("最终成图存在连续两条大面积无功能空白带，信息层级没有形成连续视觉结构")

    declared = fullness.get("rendered_activity_ratio")
    declared_matches = isinstance(declared, (int, float)) and not isinstance(declared, bool) and abs(
        float(declared) - activity
    ) <= 0.015
    checks["measured_activity_matches_metadata"] = declared_matches
    if not declared_matches:
        issues.append("封面元数据中的成图饱满度缺失或与最终图片实测结果不一致")


def _check_asset_metadata(metadata: dict[str, Any], issues: list[str], checks: dict[str, bool]) -> None:
    current = metadata.get("quality_version") == TELEGRAM_QUALITY_VERSION
    checks["asset_quality_metadata"] = current
    if not current:
        issues.append("封面缺少当前版本的质量元数据，视为旧版或未质检产物")

    layout = str(metadata.get("layout") or "")
    if layout == "document-cover-adaptive":
        checks["font_no_fallback"] = metadata.get("font_fallback") is False
        if not checks["font_no_fallback"]:
            issues.append("文档封面字体状态异常")

        font_files = metadata.get("font_files")
        checks["font_files"] = isinstance(font_files, list) and not font_files
        if not checks["font_files"]:
            issues.append("无文字叠加的文档封面不应声明渲染字体")

        checks["layout"] = True
        placeholders = metadata.get("placeholder_texts")
        checks["no_image_placeholders"] = isinstance(placeholders, list) and not placeholders
        if not checks["no_image_placeholders"]:
            issues.append(f"文档封面包含占位文案：{placeholders}")

        checks["source_render_mode"] = metadata.get("source_render_mode") == "fit-document-page"
        if not checks["source_render_mode"]:
            issues.append("文档封面必须完整适配真实页面，不能使用信息卡裁切模式")

        checks["document_cover_method"] = metadata.get("method") == "document-cover-adaptive"
        if not checks["document_cover_method"]:
            issues.append("文档封面没有记录自适应横竖版渲染方法")

        design = metadata.get("design")
        valid_design = isinstance(design, dict)
        checks["semantic_design_metadata"] = valid_design
        if not valid_design:
            issues.append("文档封面缺少来源与版式元数据")
            return

        checks["document_cover_layout_strategy"] = (
            design.get("layout_strategy") == "document-cover-adaptive"
            and design.get("composition") == "document-cover-adaptive"
        )
        if not checks["document_cover_layout_strategy"]:
            issues.append("文档封面的构图记录不是自适应真实页面")

        checks["document_cover_no_overlay_text"] = design.get("overlay_text") is False
        if not checks["document_cover_no_overlay_text"]:
            issues.append("文档封面禁止叠加标题、营销文案或统计信息")

        original_size = design.get("original_size")
        source_dimensions_valid = bool(
            isinstance(original_size, list)
            and len(original_size) == 2
            and all(isinstance(value, int) and not isinstance(value, bool) and value > 0 for value in original_size)
        )
        checks["document_cover_source_dimensions"] = source_dimensions_valid
        if not checks["document_cover_source_dimensions"]:
            issues.append("文档封面缺少真实预览页的原始尺寸")

        source_aspect_ratio = (
            float(original_size[0]) / float(original_size[1])
            if source_dimensions_valid
            else 0.0
        )
        landscape = source_aspect_ratio >= DOCUMENT_LANDSCAPE_ASPECT_THRESHOLD
        expected_canvas = DOCUMENT_COVER_LANDSCAPE_SIZE if landscape else DOCUMENT_COVER_PORTRAIT_SIZE
        expected_orientation = "landscape" if landscape else "portrait"
        expected_aspect_ratio = "16:9" if landscape else "9:16"

        canvas_size = design.get("canvas_size")
        checks["document_cover_canvas"] = canvas_size == list(expected_canvas)
        if not checks["document_cover_canvas"]:
            issues.append(
                f"文档封面方向与真实预览页不匹配：应使用 {expected_aspect_ratio} 画布 {expected_canvas}"
            )

        checks["document_cover_orientation"] = (
            design.get("orientation") == expected_orientation
            and design.get("aspect_ratio") == expected_aspect_ratio
        )
        if not checks["document_cover_orientation"]:
            issues.append("文档封面没有按真实页面横竖方向选择 16:9 或 9:16")

        declared_source_aspect = design.get("source_aspect_ratio")
        checks["document_cover_source_aspect"] = bool(
            isinstance(declared_source_aspect, (int, float))
            and not isinstance(declared_source_aspect, bool)
            and abs(float(declared_source_aspect) - source_aspect_ratio) <= 0.01
        )
        if not checks["document_cover_source_aspect"]:
            issues.append("文档封面记录的源页面比例与真实尺寸不一致")

        content_box = design.get("content_box")
        checks["document_cover_content_box"] = bool(
            isinstance(content_box, list)
            and len(content_box) == 4
            and all(isinstance(value, int) and not isinstance(value, bool) for value in content_box)
            and 0 <= content_box[0] < content_box[2] <= expected_canvas[0]
            and 0 <= content_box[1] < content_box[3] <= expected_canvas[1]
        )
        if not checks["document_cover_content_box"]:
            issues.append("文档预览页没有完整放入所选横版或竖版画布")

        inventory_count = design.get("document_inventory_count")
        checks["document_cover_inventory"] = bool(
            isinstance(inventory_count, int) and not isinstance(inventory_count, bool) and inventory_count > 0
        )
        if not checks["document_cover_inventory"]:
            issues.append("自适应文档封面缺少真实文档清单依据")
        return

    if layout == "image-gen":
        checks["font_no_fallback"] = metadata.get("font_fallback") is False
        if not checks["font_no_fallback"]:
            issues.append("ImageGen 封面的字体状态异常")
        checks["font_files"] = isinstance(metadata.get("font_files"), list) and not metadata.get("font_files")
        if not checks["font_files"]:
            issues.append("ImageGen 封面不应声明本地渲染字体")
        checks["layout"] = metadata.get("method") == "image-gen-output"
        if not checks["layout"]:
            issues.append("ImageGen 封面没有记录正确的生成方法")
        placeholders = metadata.get("placeholder_texts")
        checks["no_image_placeholders"] = isinstance(placeholders, list) and not placeholders
        if not checks["no_image_placeholders"]:
            issues.append(f"ImageGen 封面包含占位文案：{placeholders}")

        design = metadata.get("design")
        checks["semantic_design_metadata"] = isinstance(design, dict)
        if not checks["semantic_design_metadata"]:
            issues.append("ImageGen 封面缺少设计与视觉验收元数据")
            return
        profile = str(design.get("visual_profile") or "")
        checks["semantic_visual_profile"] = profile in {
            "clinical", "literary", "learning", "wellness", "cinematic",
            "growth", "finance", "friendly", "digital", "modern",
        }
        if not checks["semantic_visual_profile"]:
            issues.append("ImageGen 封面没有记录由项目内容决定的视觉主题")
        semantic_basis = design.get("semantic_basis")
        checks["semantic_style_evidence"] = bool(
            isinstance(semantic_basis, dict)
            and semantic_basis.get("selected_profile") == profile
            and isinstance(semantic_basis.get("scores"), dict)
            and isinstance(semantic_basis.get("matched_signals"), list)
        )
        if not checks["semantic_style_evidence"]:
            issues.append("ImageGen 封面缺少项目语义选择依据")
        palette = design.get("palette")
        checks["semantic_palette"] = bool(
            isinstance(palette, dict)
            and {"background", "accent", "secondary"}.issubset(palette)
            and palette.get("basis") == "imagegen-project-derived"
        )
        if not checks["semantic_palette"]:
            issues.append("ImageGen 封面缺少成图与语义配色记录")
        generation = design.get("generation")
        generation_checks = generation.get("checks") if isinstance(generation, dict) else None
        required_review_checks = {
            "subject_relevant",
            "palette_compliant",
            "text_readable",
            "uncluttered_composition",
            "no_fabricated_content",
        }
        checks["imagegen_visual_review"] = bool(
            isinstance(generation, dict)
            and generation.get("tool") == "imagegen"
            and generation.get("prompt_contract") == "factual-social-cover-v1"
            and bool(str(generation.get("prompt") or "").strip())
            and bool(str(generation.get("visual_direction") or "").strip())
            and bool(str(generation.get("palette_reason") or "").strip())
            and isinstance(generation_checks, dict)
            and all(generation_checks.get(name) is True for name in required_review_checks)
        )
        if not checks["imagegen_visual_review"]:
            issues.append("ImageGen 封面没有通过主题、配色、文字、构图和事实五项视觉验收")
        anchors = design.get("content_anchors")
        checks["imagegen_content_fields"] = bool(
            str(design.get("title_display") or "").strip()
            and isinstance(anchors, list)
            and 2 <= len(anchors) <= 4
            and all(str(anchor).strip() for anchor in anchors)
        )
        if not checks["imagegen_content_fields"]:
            issues.append("ImageGen 封面缺少标题或 2-4 个真实内容锚点")
        checks["imagegen_no_inventory_metrics"] = design.get("metrics") == []
        if not checks["imagegen_no_inventory_metrics"]:
            issues.append("ImageGen 封面禁止使用文件数、文件夹数等库存指标")
        return

    fallback = metadata.get("font_fallback")
    checks["font_no_fallback"] = fallback is False
    if fallback is not False:
        issues.append("封面存在字体回退风险，可能产生方框乱码")

    font_files = metadata.get("font_files")
    valid_fonts = isinstance(font_files, list) and bool(font_files) and all(Path(str(item)).is_file() for item in font_files)
    checks["font_files"] = valid_fonts
    if not valid_fonts:
        issues.append("封面没有记录可验证的中文字体文件")

    valid_layout = layout in {"source-image", "text-only-summary"}
    checks["layout"] = valid_layout
    if not valid_layout:
        issues.append("封面使用旧版或未知布局，禁止发布")

    placeholders = metadata.get("placeholder_texts")
    clean_placeholders = isinstance(placeholders, list) and not placeholders
    checks["no_image_placeholders"] = clean_placeholders
    if not clean_placeholders:
        issues.append(f"封面包含占位文案：{placeholders}")

    render_mode = metadata.get("source_render_mode")
    if layout == "source-image":
        valid_render_mode = render_mode in {"fit-media", "top-safe-crop"}
        checks["source_render_mode"] = valid_render_mode
        if not valid_render_mode:
            issues.append("文档或媒体源图缺少可验证的裁切模式")

    design = metadata.get("design")
    valid_design = isinstance(design, dict)
    checks["semantic_design_metadata"] = valid_design
    if not valid_design:
        issues.append("封面缺少语义化设计元数据")
        return

    profile = str(design.get("visual_profile") or "")
    valid_profile = profile in {
        "literary",
        "learning",
        "wellness",
        "cinematic",
        "growth",
        "finance",
        "friendly",
        "digital",
        "modern",
    }
    checks["semantic_visual_profile"] = valid_profile
    if not valid_profile:
        issues.append("封面没有记录由项目内容决定的字体与配色风格")

    semantic_basis = design.get("semantic_basis")
    valid_semantic_basis = (
        isinstance(semantic_basis, dict)
        and semantic_basis.get("selected_profile") == profile
        and isinstance(semantic_basis.get("scores"), dict)
        and isinstance(semantic_basis.get("matched_signals"), list)
    )
    checks["semantic_style_evidence"] = valid_semantic_basis
    if not valid_semantic_basis:
        issues.append("封面没有记录字体与配色如何由当前项目内容推导")

    palette = design.get("palette")
    valid_palette = isinstance(palette, dict) and {"background", "accent", "secondary"}.issubset(palette)
    checks["semantic_palette"] = valid_palette
    if not valid_palette:
        issues.append("封面缺少当前项目的语义配色记录")
    else:
        semantic_palette = palette.get("semantic_palette")
        semantic_palette_evidence = (
            bool(str(palette.get("semantic_reason") or "").strip())
            and isinstance(semantic_palette, dict)
            and {"background", "accent", "secondary"}.issubset(semantic_palette)
        )
        checks["semantic_palette_evidence"] = semantic_palette_evidence
        if not semantic_palette_evidence:
            issues.append("封面没有记录项目语义基础色及其选择依据")
        palette_basis = str(palette.get("basis") or "")
        source_palette = palette.get("source_palette")
        source_weight = palette.get("source_weight")
        source_palette_valid = layout != "source-image" or (
            palette_basis in {"project-media-dominant", "semantic-with-low-chroma-media"}
            and isinstance(source_palette, dict)
            and {"background", "accent", "secondary"}.issubset(source_palette)
            and isinstance(source_weight, (int, float))
            and not isinstance(source_weight, bool)
            and 0.35 <= float(source_weight) <= 0.85
        )
        checks["project_palette_evidence"] = source_palette_valid
        if not source_palette_valid:
            issues.append("封面没有记录当前真实素材的调色证据或有效混合权重")

    typography = design.get("typography_basis")
    valid_typography = (
        isinstance(typography, dict)
        and all(bool(str(typography.get(key) or "").strip()) for key in ("title_family", "eyebrow_family", "body_family"))
        and bool(str(typography.get("reason") or "").strip())
    )
    checks["semantic_typography"] = valid_typography
    if not valid_typography:
        issues.append("封面没有记录字体如何根据当前项目内容选择")

    valid_title_display_evidence = all(
        bool(str(design.get(key) or "").strip())
        for key in ("title_display", "title_display_source", "title_display_basis")
    )
    checks["title_display_evidence"] = valid_title_display_evidence
    if not valid_title_display_evidence:
        issues.append("封面没有记录主标题从完整项目标题提取或保留的依据")

    layout_strategy = str(design.get("layout_strategy") or "")
    expected_strategies = (
        {"source-dominant-poster", "asymmetric-split", "media-editorial-split", "media-focus-split"}
        if layout == "source-image"
        else {"semantic-summary", "semantic-timeline", "semantic-grid", "semantic-guide"}
    )
    valid_strategy = layout_strategy in expected_strategies
    checks["dynamic_layout_strategy"] = valid_strategy
    if not valid_strategy:
        issues.append("封面没有根据标题长度和真实素材选择有效的动态构图")

    valid_composition = design.get("composition") == layout_strategy
    checks["dynamic_composition"] = valid_composition
    if not valid_composition:
        issues.append("封面构图与记录的动态布局策略不一致")

    layout_basis = design.get("layout_basis")
    valid_layout_basis = (
        isinstance(layout_basis, dict)
        and layout_basis.get("title_length_class") in {"short", "medium", "long"}
        and "source_aspect_ratio" in layout_basis
        and isinstance(layout_basis.get("metric_count"), int)
        and not isinstance(layout_basis.get("metric_count"), bool)
        and bool(str(layout_basis.get("reason") or "").strip())
    )
    checks["layout_selection_evidence"] = valid_layout_basis
    if not valid_layout_basis:
        issues.append("封面缺少标题长度、素材比例、指标数量或构图理由")

    fullness = design.get("fullness")
    numeric_fullness = isinstance(fullness, dict) and all(
        isinstance(fullness.get(key), (int, float)) and not isinstance(fullness.get(key), bool)
        for key in (
            "source_coverage",
            "occupied_ratio",
            "rendered_activity_ratio",
            "rendered_left_activity_ratio",
            "rendered_right_activity_ratio",
        )
    )
    line_fullness = isinstance(fullness, dict) and all(
        isinstance(fullness.get(key), int) and not isinstance(fullness.get(key), bool)
        for key in ("title_line_count", "support_line_count", "keyword_line_count", "metric_count")
    )
    valid_fullness = numeric_fullness and line_fullness
    checks["fullness_metadata"] = valid_fullness
    if not valid_fullness:
        issues.append("封面缺少可质检的素材覆盖率、内容占用率或文字行数")

    occupied_ratio = float(fullness.get("rendered_activity_ratio") or 0) if isinstance(fullness, dict) else 0.0
    adequate_fullness = valid_fullness and MIN_RENDERED_ACTIVITY <= occupied_ratio <= 1.0
    checks["adequate_visual_fullness"] = adequate_fullness
    if not adequate_fullness:
        issues.append(
            f"封面记录的最终成图饱满度不足：{occupied_ratio:.2f}，最低要求为 {MIN_RENDERED_ACTIVITY:.2f}"
        )

    title_length_class = str(layout_basis.get("title_length_class") or "") if isinstance(layout_basis, dict) else ""
    selected_source_kind = str(layout_basis.get("source_kind") or "") if isinstance(layout_basis, dict) else ""
    is_video_source = selected_source_kind in {"video-preview", "video-frame", "video-contact-sheet"}
    short_title_layout = not (
        layout == "source-image"
        and title_length_class == "short"
        and not is_video_source
        and layout_strategy != "source-dominant-poster"
    )
    checks["short_title_uses_poster"] = short_title_layout
    if not short_title_layout:
        issues.append("短标题仍在使用长标题分栏，容易产生大面积无效空白")

    source_coverage = float(fullness.get("source_coverage") or 0) if isinstance(fullness, dict) else 0.0
    poster_source_coverage = layout_strategy != "source-dominant-poster" or source_coverage >= 0.72
    checks["poster_source_coverage"] = poster_source_coverage
    if not poster_source_coverage:
        issues.append(f"素材主导封面的真实素材覆盖率不足：{source_coverage:.2f}，最低要求为 0.72")

    overlay_mode = str(design.get("overlay_mode") or "")
    expected_overlay = {
        "source-dominant-poster": "solid-stage",
        "asymmetric-split": "localized-fade",
        "media-editorial-split": "separate-zones",
        "media-focus-split": "separate-zones",
        "semantic-summary": "none",
        "semantic-timeline": "none",
        "semantic-grid": "none",
        "semantic-guide": "none",
    }.get(layout_strategy)
    valid_overlay = bool(expected_overlay) and overlay_mode == expected_overlay
    checks["intentional_overlay_mode"] = valid_overlay
    if not valid_overlay:
        issues.append("封面覆盖方式与当前构图不匹配，禁止无条件套用渐变")

    media_split = layout_strategy in {"media-editorial-split", "media-focus-split"}
    geometry = design.get("layout_geometry")
    title_font_size = geometry.get("title_font_size_px") if isinstance(geometry, dict) else None
    valid_title_scale = not media_split or (
        isinstance(title_font_size, (int, float))
        and not isinstance(title_font_size, bool)
        and float(title_font_size) >= MIN_TITLE_FONT_SIZE
    )
    checks["title_scale"] = valid_title_scale
    if not valid_title_scale:
        actual_size = f"{float(title_font_size):.0f}px" if isinstance(title_font_size, (int, float)) else "缺失"
        issues.append(
            f"视频分区主标题视觉权重不足：实际字号 {actual_size}，最低要求为 {MIN_TITLE_FONT_SIZE}px"
        )
    valid_separation = True
    if media_split:
        text_zone = geometry.get("text_zone") if isinstance(geometry, dict) else None
        source_zone = geometry.get("source_zone") if isinstance(geometry, dict) else None
        valid_rectangles = all(
            isinstance(rect, list)
            and len(rect) == 4
            and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in rect)
            for rect in (text_zone, source_zone)
        )
        valid_separation = bool(
            valid_rectangles
            and text_zone[2] + 24 <= source_zone[0]
            and float(geometry.get("minimum_gap") or 0) >= 24
            and geometry.get("text_over_source") is False
        )
    checks["text_source_separation"] = valid_separation
    if not valid_separation:
        issues.append("视频封面的文字区与真实画面没有保留安全间距，文字可能遮挡素材")

    title_support_gap = geometry.get("title_support_gap") if isinstance(geometry, dict) else None
    valid_title_support_spacing = not media_split or bool(
        isinstance(title_support_gap, (int, float))
        and not isinstance(title_support_gap, bool)
        and float(title_support_gap) >= MIN_TITLE_SUPPORT_GAP
    )
    checks["title_support_spacing"] = valid_title_support_spacing
    if not valid_title_support_spacing:
        issues.append(
            f"主标题与课程数量信息间距不足：至少需要 {MIN_TITLE_SUPPORT_GAP}px 的实际字形间距"
        )

    tiers = design.get("information_tiers")
    required_tiers = {"topic", "title", "keywords", "metrics"}
    valid_tiers = isinstance(tiers, list) and required_tiers.issubset(set(map(str, tiers)))
    checks["information_hierarchy"] = valid_tiers
    if not valid_tiers:
        issues.append("封面信息层级不完整，必须包含主题、标题、关键词和资料规模")

    valid_content_fields = all(
        bool(str(design.get(field) or "").strip())
        for field in ("topic_text", "title_display", "keyword_text")
    )
    checks["cover_content_fields"] = valid_content_fields
    if not valid_content_fields:
        issues.append("封面缺少可质检的主题、主标题或内容关键词")

    support_text = str(design.get("support_text") or "").strip()
    support_source = str(design.get("support_source") or "").strip()
    valid_poster_support = layout_strategy != "source-dominant-poster" or (
        bool(support_text)
        and support_source in {"media.source_name", "project.files"}
        and isinstance(tiers, list)
        and "support" in tiers
    )
    checks["poster_support_metadata"] = valid_poster_support
    if not valid_poster_support:
        issues.append("短标题素材海报缺少来自真实资料的支持信息及来源")

    title_lines = design.get("title_lines")
    valid_title_lines = (
        isinstance(title_lines, list)
        and bool(title_lines)
        and all(isinstance(line, str) and line.strip() for line in title_lines)
    )
    checks["title_line_layout"] = valid_title_lines
    if not valid_title_lines:
        issues.append("封面没有记录可质检的标题断行")
    elif len(title_lines) > 1:
        displayed_title_for_lines = str(design.get("title_display") or "").strip()
        book_author_match = re.match(r"^(.+?)[·•\s]*《", displayed_title_for_lines)
        allowed_book_author = book_author_match.group(1).strip() if book_author_match else ""
        short_cjk_lines = [
            line
            for index, line in enumerate(title_lines)
            if 0 < len(re.findall(r"[\u3400-\u9fff]", line)) < 3
            and re.search(r"[A-Za-z0-9]", line) is None
            and not (index == 0 and allowed_book_author and line.strip(" ·•") == allowed_book_author)
        ]
        checks["title_no_cjk_orphans"] = not short_cjk_lines
        if short_cjk_lines:
            issues.append(f"封面标题存在一至两个汉字的孤行：{short_cjk_lines}")

        nonspace_positions = [
            index for index, character in enumerate(displayed_title_for_lines) if not character.isspace()
        ]
        ascii_breaks = []
        for left, right in zip(title_lines, title_lines[1:]):
            if not re.search(r"[A-Za-z]$", left) or not re.match(r"^[A-Za-z]", right):
                continue
            boundary = len(left)
            has_explicit_space = False
            if 0 < boundary < len(nonspace_positions):
                left_position = nonspace_positions[boundary - 1]
                right_position = nonspace_positions[boundary]
                has_explicit_space = right_position > left_position + 1
            if not has_explicit_space:
                ascii_breaks.append(f"{left}|{right}")
        checks["title_no_ascii_word_breaks"] = not ascii_breaks
        if ascii_breaks:
            issues.append(f"封面标题拆开了英文缩写或单词：{ascii_breaks}")

    display_title = str(design.get("title_display") or "").strip()
    title_has_listing_suffix = bool(re.search(r"[（(]\s*\d{1,3}\s*[）)]$", display_title))
    checks["title_no_listing_suffix"] = not title_has_listing_suffix
    if title_has_listing_suffix:
        issues.append("封面主标题残留列表序号，必须在渲染前清理")

    spine = design.get("content_spine")
    if isinstance(spine, list):
        dirty_spine = [
            str(label)
            for label in spine
            if re.search(r"(?:[_\-]\s*|\s)\d{1,3}$", str(label))
            or str(label).rstrip().endswith(("，", "、", "；", "：", "【", "】"))
            or bool(re.match(r"^\s*\d{6,}", str(label)))
            or re.sub(r"[\s_·•]+", "", str(label)).casefold() in GENERIC_SPINE_LABELS
        ]
        checks["content_spine_clean_labels"] = not dirty_spine
        if dirty_spine:
            issues.append(f"课程脉络残留编号或截断标点：{dirty_spine}")

    regions = design.get("content_regions")
    valid_content_regions = True
    if media_split and isinstance(spine, list) and len(spine) >= 3:
        valid_region_list = isinstance(regions, list) and bool(regions)
        indexed_regions = [region for region in regions if isinstance(region, dict)] if valid_region_list else []
        left_region = next((region for region in indexed_regions if region.get("name") == "left-rail"), None)
        all_indices = [
            index
            for region in indexed_regions
            for index in (region.get("indices") if isinstance(region.get("indices"), list) else [])
        ]
        left_indices = left_region.get("indices") if isinstance(left_region, dict) else None
        valid_content_regions = bool(
            valid_region_list
            and isinstance(left_indices, list)
            and len(left_indices) >= min(3, len(spine))
            and all(isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(spine) for index in all_indices)
            and len(all_indices) == len(set(all_indices))
            and len(set(all_indices)) >= min(3, len(spine))
        )
    checks["content_spine_distribution"] = valid_content_regions
    if not valid_content_regions:
        issues.append("视频封面的课程线索没有填满左侧信息区，或同一课程条目被重复塞进多个框")

    metrics = design.get("metrics")
    valid_metrics = isinstance(metrics, list) and bool(metrics)
    checks["cover_metrics"] = valid_metrics
    if not valid_metrics:
        issues.append("封面缺少来自项目详情的资料数量信息")
    meaningful_metrics = valid_metrics and all(
        isinstance(metric, dict)
        and str(metric.get("label") or "").strip() not in GENERIC_METRIC_LABELS
        and isinstance(metric.get("count"), int)
        and not isinstance(metric.get("count"), bool)
        and int(metric.get("count") or 0) > 0
        for metric in metrics
    )
    checks["meaningful_metric_labels"] = meaningful_metrics
    if not meaningful_metrics:
        issues.append("封面资料量包含“格式/类型”等无意义凑数指标")

    metric_presentation = str(design.get("metric_presentation") or "")
    valid_metric_presentation = metric_presentation in {"single-badge", "compact-strip", "support-inline"}
    if media_split and valid_metrics:
        if len(metrics) == 1:
            count_text = str(metrics[0].get("count") or "")
            valid_metric_presentation = metric_presentation == "support-inline" and count_text in support_text
        else:
            valid_metric_presentation = metric_presentation == "compact-strip"
    checks["metric_presentation"] = valid_metric_presentation
    if not valid_metric_presentation:
        issues.append("资料量没有按内容数量选择合适的呈现方式，单一指标不应强行生成空洞底栏")


def _check_support_evidence(
    metadata: dict[str, Any],
    details: dict[str, Any],
    issues: list[str],
    checks: dict[str, bool],
) -> None:
    design = metadata.get("design") if isinstance(metadata.get("design"), dict) else {}
    if design.get("layout_strategy") != "source-dominant-poster":
        checks["poster_support_evidence"] = True
        return

    values: list[str] = []
    media = details.get("media") if isinstance(details.get("media"), dict) else {}
    values.append(str(media.get("source_name") or ""))
    for key in ("items", "top_level", "representative_files"):
        for item in details.get(key, ()) or ():
            if not isinstance(item, dict):
                continue
            values.extend((str(item.get("name") or ""), str(item.get("path") or "")))

    evidence = re.sub(r"\s+", "", " ".join(values)).casefold()
    support_text = str(design.get("support_text") or "")
    fragments = [
        re.sub(r"\s+", "", fragment).casefold()
        for fragment in re.split(r"[·•|｜/、,，;；]+", support_text)
        if fragment.strip()
    ]
    authentic = bool(evidence and fragments) and all(fragment in evidence for fragment in fragments)
    checks["poster_support_evidence"] = authentic
    if not authentic:
        issues.append("封面支持信息无法在项目文件名或源预览标题中找到，可能是臆造文案")


def _check_text_summary_evidence(
    metadata: dict[str, Any],
    details: dict[str, Any],
    issues: list[str],
    checks: dict[str, bool],
) -> None:
    layout = str(metadata.get("layout") or "")
    media = details.get("media") if isinstance(details.get("media"), dict) else {}
    summary = details.get("summary") if isinstance(details.get("summary"), dict) else {}
    try:
        file_count = int(summary.get("file_count") or 0)
    except (TypeError, ValueError):
        file_count = 0
    if layout != "text-only-summary" or str(media.get("kind") or "") != "no-project-media" or file_count < 3:
        checks["text_summary_course_spine"] = True
        return

    design = metadata.get("design") if isinstance(metadata.get("design"), dict) else {}
    strategy = str(design.get("layout_strategy") or "")
    spine = design.get("content_spine")
    spine_source = str(design.get("content_spine_source") or "")
    support_text = str(design.get("support_text") or "").strip()
    support_source = str(design.get("support_source") or "")
    tiers = design.get("information_tiers")
    has_structure = (
        strategy in {"semantic-timeline", "semantic-grid", "semantic-guide"}
        and isinstance(spine, list)
        and len(spine) >= 3
        and all(isinstance(item, str) and item.strip() for item in spine)
        and spine_source in {"project.top_level", "project.files"}
        and bool(support_text)
        and support_source == "project.summary"
        and isinstance(tiers, list)
        and "support" in tiers
    )

    evidence_values: list[str] = []
    for key in ("items", "top_level", "representative_files"):
        for item in details.get(key, ()) or ():
            if isinstance(item, dict):
                evidence_values.extend((str(item.get("name") or ""), str(item.get("path") or "")))
    evidence = re.sub(r"[\W_]+", "", " ".join(evidence_values)).casefold()
    authentic_spine = bool(evidence and isinstance(spine, list)) and all(
        re.sub(r"[\W_]+", "", str(item)).casefold() in evidence for item in spine
    )
    valid = has_structure and authentic_spine
    checks["text_summary_course_spine"] = valid
    if not valid:
        issues.append("无可预览素材的课程封面缺少真实课程脉络，或仍在使用空洞的固定摘要布局")


def _previewable_inventory_count(details: dict[str, Any]) -> int:
    summary = details.get("summary") if isinstance(details.get("summary"), dict) else {}
    extension_counts = summary.get("extension_counts") if isinstance(summary.get("extension_counts"), dict) else {}
    total = 0
    for extension, raw_count in extension_counts.items():
        if str(extension).lower() not in PREVIEWABLE_EXTENSIONS:
            continue
        try:
            total += max(0, int(raw_count))
        except (TypeError, ValueError):
            continue
    if total:
        return total
    for item in details.get("items", ()) or ():
        if not isinstance(item, dict) or str(item.get("type") or "") != "file":
            continue
        extension = str(item.get("extension") or Path(str(item.get("name") or "")).suffix).lower()
        if extension in PREVIEWABLE_EXTENSIONS:
            total += 1
    return total


def _document_inventory_count(details: dict[str, Any]) -> int:
    summary = details.get("summary") if isinstance(details.get("summary"), dict) else {}
    extension_counts = summary.get("extension_counts") if isinstance(summary.get("extension_counts"), dict) else {}
    total = 0
    for extension, raw_count in extension_counts.items():
        if str(extension).lower() not in DOCUMENT_COVER_EXTENSIONS:
            continue
        try:
            total += max(0, int(raw_count))
        except (TypeError, ValueError):
            continue
    if total:
        return total
    for item in details.get("items", ()) or ():
        if not isinstance(item, dict) or str(item.get("type") or "") != "file":
            continue
        extension = str(item.get("extension") or Path(str(item.get("name") or "")).suffix).lower()
        if extension in DOCUMENT_COVER_EXTENSIONS:
            total += 1
    return total


def _check_details(details: dict[str, Any], issues: list[str], checks: dict[str, bool]) -> None:
    items = details.get("items")
    valid = isinstance(items, list) and bool(items)
    checks["details_items"] = valid
    if not valid:
        issues.append("项目详情为空，不能证明封面和文案来自真实资料")
    current_media_policy = details.get("media_policy_version") == EXPECTED_MEDIA_POLICY_VERSION
    checks["media_policy_version"] = current_media_policy
    if not current_media_policy:
        issues.append("项目媒体详情不是当前策略生成，必须重新检查真实图片、视频或文档预览")


def _check_media_alignment(
    *,
    metadata: dict[str, Any],
    details: dict[str, Any],
    asset_metadata_path: Path,
    image_path: Path,
    issues: list[str],
    checks: dict[str, bool],
) -> None:
    """Ensure the cover layout reflects the project's available media."""
    layout = str(metadata.get("layout") or "")
    media = details.get("media") if isinstance(details.get("media"), dict) else {}
    media_kind = str(media.get("kind") or "")
    source_value = metadata.get("source_image")
    previewable_count = _previewable_inventory_count(details)

    preview_ready = media_kind != "media-preview-required"
    checks["media_preview_ready"] = preview_ready
    if not preview_ready:
        issues.append("项目存在可预览文件，但媒体提取失败；这是发布阻断项，不能退化成纯文字目录封面")

    if layout == "document-cover-adaptive":
        source_path = resolve_project_path(str(source_value), base=asset_metadata_path.parent) if source_value else Path()
        source_exists = bool(source_value) and source_path.is_file() and source_path.resolve() != image_path.resolve()
        if source_exists:
            try:
                with Image.open(source_path) as source_image:
                    source_image.verify()
            except (OSError, ValueError):
                source_exists = False
        checks["source_media_file"] = source_exists
        if not source_exists:
            issues.append("自适应文档封面声明的真实预览页不存在或不可解码")

        valid_media_kind = media_kind in {"document-preview", "existing-local"}
        checks["source_media_kind"] = valid_media_kind
        if not valid_media_kind:
            issues.append(f"自适应文档封面的媒体类型无效：{media_kind or '缺失'}")

        document_count = _document_inventory_count(details)
        checks["document_inventory"] = document_count > 0
        if document_count <= 0:
            issues.append("自适应文档封面没有 PDF 或文档文件清单依据")

        checks["document_preview_safe_crop"] = metadata.get("source_render_mode") == "fit-document-page"
        if not checks["document_preview_safe_crop"]:
            issues.append("文档预览必须完整适配到所选横版或竖版画布，不能截断页面文字")
        return

    if layout == "image-gen":
        source_path = resolve_project_path(str(source_value), base=asset_metadata_path.parent) if source_value else Path()
        source_exists = bool(source_value) and source_path.is_file() and source_path.resolve() != image_path.resolve()
        checks["imagegen_source_file"] = source_exists
        if not source_exists:
            issues.append("ImageGen 封面没有保留可验证的原始生成图")
        valid_media = media_kind == "no-project-media" and previewable_count == 0
        checks["imagegen_without_project_media"] = valid_media
        if not valid_media:
            issues.append("存在真实可预览素材时不得用 ImageGen 替代")
        return

    if layout == "source-image":
        source_path = resolve_project_path(str(source_value), base=asset_metadata_path.parent) if source_value else Path()
        source_exists = bool(source_value) and source_path.is_file() and source_path.resolve() != image_path.resolve()
        if source_exists:
            try:
                with Image.open(source_path) as source_image:
                    source_image.verify()
            except (OSError, ValueError):
                source_exists = False
        checks["source_media_file"] = source_exists
        if not source_exists:
            issues.append("封面声明使用项目媒体，但源图片/视频关键帧不存在或不可解码")

        valid_media_kind = media_kind in {
            "existing-local",
            "project-image",
            "video-preview",
            "video-frame",
            "video-contact-sheet",
            "document-preview",
        }
        checks["source_media_kind"] = valid_media_kind
        if not valid_media_kind:
            issues.append(f"封面声明使用项目媒体，但详情记录的媒体类型无效：{media_kind or '缺失'}")
        if media_kind == "document-preview":
            safe_crop = metadata.get("source_render_mode") == "top-safe-crop"
            checks["document_preview_safe_crop"] = safe_crop
            if not safe_crop:
                issues.append("文档预览必须使用顶部安全裁切，不能把整页缩成不可读缩略图或随意截断文字")
        if media_kind in {"video-frame", "video-contact-sheet"}:
            try:
                evaluated_frames = int(media.get("evaluated_frames") or 0)
                frame_score = float(media.get("frame_quality_score") or 0)
            except (TypeError, ValueError):
                evaluated_frames = 0
                frame_score = 0.0
            multi_frame_qa = evaluated_frames >= 3 and frame_score >= 24.0
            checks["video_multi_frame_qa"] = multi_frame_qa
            if not multi_frame_qa:
                issues.append("视频封面没有比较至少 3 张真实候选帧，或选中帧质量分不足")
        return

    if layout == "text-only-summary":
        no_media = media_kind == "no-project-media" and not source_value and previewable_count == 0
        checks["text_only_without_media"] = no_media
        if not no_media:
            issues.append(
                f"项目清单中有 {previewable_count} 个可预览文件，但封面没有使用真实图片、视频关键帧或文档预览"
            )
        return

    checks["media_layout_alignment"] = False


def _check_caption(
    caption_path: Path,
    *,
    title: str,
    link: str,
    issues: list[str],
    checks: dict[str, bool],
) -> None:
    exists = caption_path.is_file() and caption_path.stat().st_size > 0
    checks["caption_file"] = exists
    if not exists:
        issues.append(f"Telegram 文案不存在或为空：{caption_path}")
        return
    try:
        caption = caption_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        issues.append(f"Telegram 文案不是有效 UTF-8：{exc}")
        return

    checks["caption_length"] = 0 < len(caption) <= 1024
    if not checks["caption_length"]:
        issues.append(f"Telegram 文案长度不合格：{len(caption)}，应为 1–1024 字符")
    checks["caption_encoding"] = "�" not in caption and "\x00" not in caption
    if not checks["caption_encoding"]:
        issues.append("Telegram 文案包含替换字符或空字节")

    unescaped = html.unescape(caption)
    checks["caption_title"] = bool(title.strip()) and title.strip() in unescaped
    if not checks["caption_title"]:
        issues.append("Telegram 文案没有完整资料标题")
    checks["caption_quark_link"] = _is_quark_link(link) and link in unescaped
    if not checks["caption_quark_link"]:
        issues.append("Telegram 文案缺少有效夸克分享链接")
    channel_link = TELEGRAM_CHANNEL_URL
    checks["caption_channel_link"] = channel_link in unescaped
    if not checks["caption_channel_link"]:
        issues.append("Telegram 文案缺少知识分享群链接")
    checks["caption_description"] = not any(marker in unescaped for marker in DESCRIPTION_PLACEHOLDERS)
    if not checks["caption_description"]:
        issues.append("Telegram 文案仍是占位介绍")

    tags = TAG_PATTERN.findall(unescaped)
    checks["caption_tags"] = 2 <= len(tags) <= 8
    if not checks["caption_tags"]:
        issues.append(f"Telegram 文案标签数量不合格：{len(tags)}，应为 2–8 个")

    audit = _HTMLAudit()
    try:
        audit.feed(caption)
        audit.close()
        if audit.stack:
            audit.errors.append(f"unclosed tag: {audit.stack[-1]}")
    except (TypeError, ValueError) as exc:
        audit.errors.append(str(exc))
    checks["caption_html"] = not audit.errors
    if audit.errors:
        issues.append(f"Telegram HTML 结构异常：{audit.errors[0]}")


def inspect_telegram_outputs(
    *,
    image_path: Path,
    caption_path: Path,
    asset_metadata_path: Path,
    details_path: Path,
    title: str,
    link: str,
) -> TelegramQualityReport:
    issues: list[str] = []
    checks: dict[str, bool] = {}

    metadata = _load_json(asset_metadata_path, issues, "封面元数据")
    expected_size = EXPECTED_IMAGE_SIZE
    if metadata.get("layout") == "document-cover-adaptive":
        design = metadata.get("design") if isinstance(metadata.get("design"), dict) else {}
        canvas_size = design.get("canvas_size")
        if isinstance(canvas_size, list) and len(canvas_size) == 2:
            candidate_size = tuple(canvas_size)
            if candidate_size in DOCUMENT_COVER_IMAGE_SIZES:
                expected_size = candidate_size
            else:
                expected_size = DOCUMENT_COVER_PORTRAIT_SIZE
    _check_image(image_path, issues, checks, expected_size=expected_size)
    _check_asset_metadata(metadata, issues, checks)
    _check_rendered_activity(image_path, metadata, issues, checks)
    details = _load_json(details_path, issues, "项目详情")
    _check_details(details, issues, checks)
    _check_support_evidence(metadata, details, issues, checks)
    _check_text_summary_evidence(metadata, details, issues, checks)
    _check_media_alignment(
        metadata=metadata,
        details=details,
        asset_metadata_path=asset_metadata_path,
        image_path=image_path,
        issues=issues,
        checks=checks,
    )
    _check_caption(caption_path, title=title, link=link, issues=issues, checks=checks)

    return TelegramQualityReport(passed=not issues, issues=tuple(issues), checks=checks)


def write_quality_report(path: Path, report: TelegramQualityReport, *, attempt: int) -> None:
    payload = report.as_dict()
    payload["attempt"] = attempt
    payload["checked_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
