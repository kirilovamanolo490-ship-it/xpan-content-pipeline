#!/usr/bin/env python3
"""Create or reuse one row's Telegram cover inside its numbered asset folder."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Mapping, Sequence

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))
from xpan_auto.runtime import cjk_font_candidates, resolve_project_path


DEFAULT_OUTPUT_NAME = "cover-v1-information-card.png"
TELEGRAM_ASSET_QUALITY_VERSION = 12
DOCUMENT_COVER_LANDSCAPE_SIZE = (1920, 1080)
DOCUMENT_COVER_PORTRAIT_SIZE = (1080, 1920)
DOCUMENT_LANDSCAPE_ASPECT_THRESHOLD = 1.10
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv", ".m4v"}
DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".txt"}
DOCUMENT_COVER_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".odt", ".rtf",
    ".ppt", ".pptx", ".odp",
    ".xls", ".xlsx", ".ods", ".csv",
    ".epub", ".mobi", ".azw3",
    ".txt", ".md", ".json", ".html", ".htm",
    ".xml", ".yaml", ".yml", ".sql", ".log", ".ini",
}
PREVIEWABLE_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS | DOCUMENT_EXTENSIONS
SOURCE_NAMES = (
    "source-preview.webp",
    "source-preview.png",
    "source-preview.jpg",
    "cover.jpg",
    "cover.jpeg",
    "cover.png",
)
DISALLOWED_SOURCE_NAMES = {"project-preview.png", "quark-project-preview.png"}
FONT_PROFILES = {
    "sans": (
        (r"C:\Windows\Fonts\msyhbd.ttc", True),
        (r"C:\Windows\Fonts\msyh.ttc", False),
        (r"C:\Windows\Fonts\NotoSansSC-VF.ttf", False),
    ),
    "editorial": (
        (r"C:\Windows\Fonts\NotoSerifSC-VF.ttf", True),
        (r"C:\Windows\Fonts\NotoSerifSC-VF.ttf", False),
        (r"C:\Windows\Fonts\simsunb.ttf", True),
        (r"C:\Windows\Fonts\simsun.ttc", False),
        (r"C:\Windows\Fonts\msyhbd.ttc", True),
    ),
    "display": (
        (r"C:\Windows\Fonts\simhei.ttf", True),
        (r"C:\Windows\Fonts\msyhbd.ttc", True),
        (r"C:\Windows\Fonts\msyh.ttc", False),
    ),
    "classical": (
        (r"C:\Windows\Fonts\STKAITI.TTF", False),
        (r"C:\Windows\Fonts\simkai.ttf", False),
        (r"C:\Windows\Fonts\FZSTK.TTF", True),
        (r"C:\Windows\Fonts\simsunb.ttf", True),
    ),
    "friendly": (
        (r"C:\Windows\Fonts\FZYTK.TTF", True),
        (r"C:\Windows\Fonts\msyhbd.ttc", True),
        (r"C:\Windows\Fonts\msyh.ttc", False),
    ),
    "digital-tech": (
        (r"C:\Windows\Fonts\NotoSansSC-VF.ttf", True),
        (r"C:\Windows\Fonts\NotoSansSC-VF.ttf", False),
        (r"C:\Windows\Fonts\STXIHEI.TTF", False),
        (r"C:\Windows\Fonts\msyhbd.ttc", True),
    ),
    "digital-creator": (
        (r"C:\Windows\Fonts\Dengb.ttf", True),
        (r"C:\Windows\Fonts\STXIHEI.TTF", False),
        (r"C:\Windows\Fonts\NotoSansSC-VF.ttf", False),
        (r"C:\Windows\Fonts\msyhbd.ttc", True),
    ),
    "learning-editorial": (
        (r"C:\Windows\Fonts\NotoSerifSC-VF.ttf", True),
        (r"C:\Windows\Fonts\NotoSerifSC-VF.ttf", False),
        (r"C:\Windows\Fonts\STZHONGS.TTF", False),
        (r"C:\Windows\Fonts\simsunb.ttf", True),
    ),
}
SEMANTIC_PALETTES = {
    "clinical": ((11, 31, 51), (42, 157, 143), (224, 122, 95)),
    "literary": ((17, 25, 42), (226, 177, 104), (246, 226, 190)),
    "learning": ((20, 28, 66), (89, 181, 239), (250, 205, 87)),
    "wellness": ((7, 29, 34), (61, 207, 180), (255, 167, 78)),
    "cinematic": ((7, 15, 28), (39, 205, 229), (220, 78, 189)),
    "growth": ((20, 25, 36), (242, 105, 62), (244, 185, 78)),
    "finance": ((8, 38, 39), (72, 210, 165), (238, 193, 88)),
    "friendly": ((9, 34, 61), (255, 177, 83), (244, 102, 79)),
    "digital": ((5, 12, 35), (32, 211, 239), (220, 68, 211)),
    "modern": ((10, 25, 42), (74, 196, 214), (152, 122, 224)),
}


def _semantic_palette_for_project(
    profile: str,
    title: str,
    description: str,
) -> tuple[tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]], str]:
    """Choose a semantic palette variant from the project's concrete subject."""

    evidence = f"{title} {description}".casefold()
    if profile == "digital" and "workbuddy" in evidence and "办公" in evidence:
        return (
            ((10, 18, 29), (76, 183, 164), (235, 177, 88)),
            "WorkBuddy/AI 办公界面证据，采用石墨底、工具青和操作琥珀色",
        )
    if profile == "digital" and "短视频" in evidence and "带货" in evidence:
        return (
            ((16, 30, 38), (74, 190, 205), (231, 126, 105)),
            "短视频带货与流量转化证据，采用屏幕青与行动珊瑚色",
        )
    return SEMANTIC_PALETTES[profile], f"{profile} 语义基础色"
GENERIC_COVER_TAGS = {
    "课件资料",
    "课程资料",
    "课程分享",
    "视频课程",
    "学习资料",
}
GENERIC_SPINE_LABELS = {
    "资料",
    "视频",
    "课程",
    "推广",
    "课件",
    "文档",
    "音频",
    "素材",
    "文件",
    "其他",
    "讲义",
}
PROFILE_LABELS = {
    "clinical": (("临床科研", "医学数据"), ("电子病历", "统计建模", "预测分析")),
    "literary": (("人文阅读", "经典品读"), ("文学素养", "文化积累", "审美表达")),
    "learning": (("语言学习", "写作训练"), ("语法基础", "综合写作", "练习复盘")),
    "wellness": (("健康学习", "专业进阶"), ("理论讲解", "实践评估", "系统训练")),
    "cinematic": (("视觉创作", "主题实战"), ("构图审美", "拍摄方法", "后期表达")),
    "growth": (("职业成长", "个人进阶"), ("自我效能", "能力跃迁", "行动方法")),
    "finance": (("投资研究", "交易体系"), ("买点判断", "结构分析", "风险控制")),
    "friendly": (("表达沟通", "场景练习"), ("人际互动", "观点表达", "沟通技巧")),
    "digital": (("数字创作", "方法实战"), ("案例拆解", "工具应用", "效率提升")),
    "modern": (("专题学习", "资料精选"), ("系统课程", "方法整理", "实践参考")),
}
SEMANTIC_KEYWORDS = {
    "clinical": (
        ("临床", 8),
        ("电子病历", 8),
        ("生存分析", 7),
        ("医学统计", 7),
        ("预测模型", 7),
        ("lasso", 6),
        ("回归模型", 6),
        ("随机森林", 5),
        ("神经网络", 4),
        ("r语言", 4),
    ),
    "literary": (
        ("古诗词", 6),
        ("古诗", 5),
        ("诗词", 5),
        ("国学", 5),
        ("文学", 4),
        ("传统文化", 4),
        ("哲学", 4),
        ("书法", 4),
        ("人文", 3),
        ("历史", 3),
        ("文化", 1),
        ("天道", 5),
        ("鬼谷", 5),
        ("商君书", 5),
    ),
    "learning": (
        ("英语", 7),
        ("语法", 7),
        ("写作", 7),
        ("词汇", 5),
        ("训练营", 3),
    ),
    "wellness": (
        ("筋膜", 6),
        ("康复", 6),
        ("理疗", 5),
        ("医学", 5),
        ("疼痛", 4),
        ("医师", 4),
        ("健康", 3),
        ("养生", 3),
        ("肩颈", 6),
        ("舒缓", 5),
    ),
    "cinematic": (
        ("摄影", 6),
        ("胶片", 5),
        ("镜头", 4),
        ("影棚", 4),
        ("人像", 4),
        ("拍摄", 3),
        ("电影", 3),
    ),
    "growth": (
        ("超级个体", 7),
        ("核心竞争力", 6),
        ("职业重启", 6),
        ("自我效能", 6),
        ("领导力", 5),
        ("副业", 5),
        ("职业", 4),
        ("职场", 4),
        ("个人成长", 4),
    ),
    "finance": (
        ("买点", 7),
        ("股票", 7),
        ("操盘", 6),
        ("主升浪", 5),
        ("量能", 5),
        ("股道", 5),
    ),
    "friendly": (
        ("幽默", 6),
        ("社交", 5),
        ("沟通", 5),
        ("人际", 5),
        ("亲子", 5),
        ("表达", 1),
    ),
    "digital": (
        ("ppt", 6),
        ("演示文稿", 6),
        ("ai", 6),
        ("编程", 6),
        ("代码", 6),
        ("电商", 5),
        ("设计", 4),
        ("数据", 4),
        ("科技", 4),
        ("模板", 3),
        ("视觉", 2),
        ("短视频", 6),
        ("带货", 6),
        ("流量", 5),
        ("剪辑", 6),
        ("运营", 5),
        ("营销", 5),
        ("办公", 5),
    ),
    "modern": (),
}
SEMANTIC_PROFILE_ORDER = (
    "clinical",
    "literary",
    "learning",
    "wellness",
    "cinematic",
    "growth",
    "finance",
    "digital",
    "friendly",
    "modern",
)
TITLE_PROTECTED_TERMS = tuple(
    sorted(
        {
            *(term for entries in SEMANTIC_KEYWORDS.values() for term, _weight in entries if len(term) >= 2),
            "AI办公",
            "WorkBuddy",
            "SEO",
            "SEM",
            "社会化媒体",
            "新媒体运营",
            "电商网络营销",
            "买点系统",
            "买点系统课",
            "红心买点",
            "IP切片",
            "切片电商",
            "内容运营",
            "远程控制",
            "提示词",
            "品读",
            "技术",
            "大汇总",
            "训练营",
            "必备掌握",
            "从视觉到观点",
        },
        key=len,
        reverse=True,
    )
)
TITLE_STATUS_TERMS = {"完结", "已完结", "完整版", "全集", "更新完毕", "共享完毕"}
CONTENT_SPINE_PROTECTED_TERMS = tuple(
    sorted(
        {
            "AI办公",
            "WorkBuddy",
            "SEO",
            "SEM",
            "社会化媒体",
            "新媒体运营",
            "电商网络营销",
            "买点系统",
            "红心买点",
            "IP切片",
            "切片电商",
            "内容运营",
            "自媒体",
            "远程控制",
            "提示词",
            "结构图形",
            "主升浪",
            "工作模式",
            "任务管理",
            "第一个任务",
            "使用场景",
            "技术架构",
            "适用人群",
            "传统AI工具",
            "操盘根基",
            "有效性",
        },
        key=len,
        reverse=True,
    )
)
RENDER_FONT_PATHS: list[str] = []


def project_root() -> Path:
    # .../<project>/.codex/skills/telegram-auto-publish/scripts/<file>
    return Path(__file__).resolve().parents[4]


def resolve_path(value: str | Path | None) -> Path | None:
    if value is None:
        return None
    return resolve_project_path(value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    location = parser.add_mutually_exclusive_group(required=True)
    location.add_argument("--row-index", type=int, help="1-based Excel data row index")
    location.add_argument("--asset-dir", type=Path, help="explicit numbered asset directory")
    parser.add_argument("--asset-root", default="output/assets", help="root for numbered asset folders")
    parser.add_argument("--title", required=True)
    parser.add_argument("--description", default="")
    parser.add_argument(
        "--source-image",
        type=Path,
        help="optional source preview; if omitted, search the asset folder",
    )
    parser.add_argument(
        "--generated-image",
        type=Path,
        help="optional image returned by image_gen; copy it as the final cover",
    )
    parser.add_argument(
        "--generated-review",
        type=Path,
        help="required visual-review JSON when --generated-image is used",
    )
    parser.add_argument(
        "--details-file",
        type=Path,
        help="optional telegram-project-details.json; used for the description and tags",
    )
    parser.add_argument("--output-name", default=DEFAULT_OUTPUT_NAME)
    parser.add_argument("--metadata-name", default="telegram-asset.json")
    parser.add_argument(
        "--force-regenerate",
        action="store_true",
        help="overwrite an existing cover instead of reusing it",
    )
    parser.add_argument("--width", type=int, default=1672)
    parser.add_argument("--height", type=int, default=941)
    return parser.parse_args()


def _font_has_cjk_glyphs(font: ImageFont.ImageFont) -> bool:
    signatures: set[tuple[tuple[int, int], bytes]] = set()
    for character in ("永", "诗", "国"):
        mask = font.getmask(character)
        if mask.getbbox() is None:
            return False
        signatures.add((mask.size, bytes(mask)))
    return len(signatures) == 3


def _set_variable_font_weight(font: ImageFont.FreeTypeFont, *, bold: bool) -> None:
    try:
        names = font.get_variation_names()
    except (AttributeError, OSError):
        return
    preferred = (b"Bold", b"SemiBold") if bold else (b"Regular",)
    for name in preferred:
        if name in names:
            try:
                font.set_variation_by_name(name)
            except (OSError, ValueError):
                return
            return


def _font(
    size: int,
    *,
    bold: bool = False,
    family: str = "sans",
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = FONT_PROFILES.get(family, FONT_PROFILES["sans"]) + tuple(
        (path, bold) for path in cjk_font_candidates(bold=bold, family=family)
    )
    for raw_path, is_bold in candidates:
        if bold and not is_bold:
            continue
        if not bold and is_bold:
            continue
        path = Path(raw_path)
        if path.is_file():
            try:
                font = ImageFont.truetype(str(path), size=size)
            except OSError:
                continue
            _set_variable_font_weight(font, bold=bold)
            if not _font_has_cjk_glyphs(font):
                continue
            RENDER_FONT_PATHS.append(str(path))
            return font
    raise RuntimeError(
        f"No suitable {'bold ' if bold else ''}CJK font is available for profile {family}; "
        "refusing to render a tofu cover"
    )


def _contains_semantic_term(text: str, term: str) -> bool:
    if term.isascii() and term.isalnum():
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None
    return term in text


def _semantic_decision(
    title: str,
    description: str,
    file_names: Sequence[str] = (),
) -> tuple[str, dict[str, int], list[str]]:
    """Score project evidence so a generic word cannot override the main subject."""
    fields = (
        ("title", str(title or "").casefold(), 4),
        ("description", str(description or "").casefold(), 2),
        ("files", " ".join(map(str, file_names)).casefold(), 1),
    )
    scores = {profile: 0 for profile in SEMANTIC_PROFILE_ORDER}
    evidence: dict[str, list[str]] = {profile: [] for profile in SEMANTIC_PROFILE_ORDER}
    for field_name, text, field_weight in fields:
        if not text:
            continue
        for profile, entries in SEMANTIC_KEYWORDS.items():
            for term, term_weight in entries:
                if _contains_semantic_term(text, term):
                    scores[profile] += field_weight * term_weight
                    evidence[profile].append(f"{field_name}:{term}")

    profile = max(
        SEMANTIC_PROFILE_ORDER,
        key=lambda candidate: (scores[candidate], -SEMANTIC_PROFILE_ORDER.index(candidate)),
    )
    if scores[profile] <= 0:
        profile = "modern"
    return profile, scores, list(dict.fromkeys(evidence[profile]))[:10]


def _semantic_profile(title: str, description: str, file_names: Sequence[str] = ()) -> str:
    """Choose visual language from this project's subject, never from row order."""
    profile, _scores, _evidence = _semantic_decision(title, description, file_names)
    return profile


def _type_roles(profile: str, title: str = "") -> tuple[str, str, str]:
    """Return content-aware title, eyebrow, and supporting-text font families."""
    if profile == "growth" and re.search(r"《[^》]+》", title):
        # A named book/course benefits from an editorial title face; the
        # default growth display face is intentionally reserved for slogans.
        return "editorial", "sans", "sans"
    if profile == "digital":
        title_folded = title.casefold()
        if any(term in title_folded for term in ("workbuddy", "ai办公", "办公")):
            return "digital-tech", "sans", "sans"
        return "digital-creator", "sans", "sans"
    if profile == "learning":
        return "learning-editorial", "sans", "sans"
    return {
        "clinical": ("editorial", "sans", "sans"),
        "literary": ("editorial", "classical", "sans"),
        "wellness": ("sans", "sans", "sans"),
        "cinematic": ("display", "sans", "sans"),
        "growth": ("display", "sans", "sans"),
        "finance": ("display", "sans", "sans"),
        "friendly": ("friendly", "sans", "sans"),
        "digital": ("display", "sans", "sans"),
        "modern": ("sans", "sans", "sans"),
    }.get(profile, ("sans", "sans", "sans"))


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> float:
    return draw.textlength(text, font=font)


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    *,
    max_lines: int | None = None,
) -> list[str]:
    text = " ".join(str(text or "").split())
    if not text:
        return []

    lines: list[str] = []
    current = ""
    for char in text:
        candidate = current + char
        if current and _text_width(draw, candidate, font) > max_width:
            lines.append(current.rstrip())
            current = char
        else:
            current = candidate
    if current:
        lines.append(current.rstrip())

    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1].rstrip()
        while last and _text_width(draw, last + "…", font) > max_width:
            last = last[:-1]
        lines[-1] = (last or "…") + "…"
    return lines


def _wrap_content_spine_label(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    *,
    max_lines: int,
) -> list[str]:
    """Wrap verified unit names without breaking meaningful mixed-language terms."""

    normalized = " ".join(str(text or "").split())
    if not normalized:
        return []

    tokens: list[str] = []
    index = 0
    normalized_folded = normalized.casefold()
    while index < len(normalized):
        protected = next(
            (
                term
                for term in CONTENT_SPINE_PROTECTED_TERMS
                if normalized_folded.startswith(term.casefold(), index)
            ),
            None,
        )
        if protected:
            tokens.append(normalized[index : index + len(protected)])
            index += len(protected)
            continue
        ascii_word = re.match(r"[A-Za-z][A-Za-z0-9+._-]*", normalized[index:])
        if ascii_word:
            tokens.append(ascii_word.group(0))
            index += len(ascii_word.group(0))
            continue
        tokens.append(normalized[index])
        index += 1

    lines: list[str] = []
    current = ""
    for token in tokens:
        candidate = current + token
        if current and _text_width(draw, candidate, font) > max_width:
            lines.append(current.rstrip())
            current = token.lstrip()
        else:
            current = candidate
    if current:
        lines.append(current.rstrip())

    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1].rstrip(" ，、；;:：")
        while last and _text_width(draw, last + "…", font) > max_width:
            last = last[:-1].rstrip(" ，、；;:：")
        lines[-1] = (last or "…") + "…"
    return lines


def _find_source(asset_dir: Path, explicit: Path | None, output: Path) -> Path | None:
    if explicit is not None:
        source = resolve_path(explicit)
        if source is None or not source.is_file():
            raise RuntimeError(f"Source image not found: {source or explicit}")
        return source

    for name in SOURCE_NAMES:
        candidate = asset_dir / name
        if candidate.is_file() and candidate.resolve() != output.resolve():
            return candidate
    for candidate in sorted(asset_dir.iterdir() if asset_dir.is_dir() else ()):
        if candidate.is_file() and candidate.suffix.lower() in IMAGE_EXTENSIONS:
            if candidate.name.casefold() in DISALLOWED_SOURCE_NAMES:
                continue
            if candidate.resolve() != output.resolve():
                return candidate
    return None


def _color_distance(first: tuple[int, int, int], second: tuple[int, int, int]) -> float:
    return sum((a - b) ** 2 for a, b in zip(first, second)) ** 0.5


def _colorfulness(color: tuple[int, int, int]) -> float:
    return float(max(color) - min(color)) + max(color) * 0.15


def _lift_color(color: tuple[int, int, int], minimum: int) -> tuple[int, int, int]:
    maximum = max(color)
    if maximum <= 0:
        return (220, 230, 240)
    factor = max(1.0, minimum / maximum)
    return tuple(min(255, round(channel * factor)) for channel in color)


def _blend_color(
    first: tuple[int, int, int],
    second: tuple[int, int, int],
    second_weight: float,
) -> tuple[int, int, int]:
    weight = max(0.0, min(1.0, second_weight))
    return tuple(round(a * (1.0 - weight) + b * weight) for a, b in zip(first, second))


def _hex_color(color: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % color


def _palette_from_image(
    source_path: Path,
) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]] | None:
    """Derive a readable dark/accent/secondary palette from the current project image."""
    try:
        with Image.open(source_path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            image.thumbnail((96, 96), Image.Resampling.LANCZOS)
            quantized = image.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
            raw_colors = quantized.getcolors(maxcolors=256) or []
            palette = quantized.getpalette() or []
    except (OSError, ValueError):
        return None

    ranked: list[tuple[int, tuple[int, int, int]]] = []
    for count, index in raw_colors:
        offset = index * 3
        if offset + 2 >= len(palette):
            continue
        color = tuple(int(value) for value in palette[offset : offset + 3])
        ranked.append((count, color))
    if not ranked:
        return None

    ranked.sort(key=lambda item: item[0], reverse=True)
    dominant = ranked[0][1]
    candidates = [color for _, color in ranked[1:] if _color_distance(color, dominant) >= 28]
    if not candidates:
        candidates = [color for _, color in ranked]
    accent_raw = max(candidates, key=_colorfulness)
    secondary_pool = [color for color in candidates if _color_distance(color, accent_raw) >= 24]
    secondary_raw = max(secondary_pool or candidates, key=lambda color: (_colorfulness(color), sum(color)))

    background = tuple(max(8, min(58, round(channel * 0.28))) for channel in dominant)
    accent = _lift_color(accent_raw, 180)
    secondary = _lift_color(secondary_raw, 150)
    if _color_distance(accent, secondary) < 28:
        secondary = (235, 220, 150) if max(accent) - min(accent) > 28 else (170, 205, 230)
    return background, accent, secondary


def _palette_basis(
    source_path: Path | None,
) -> tuple[str, tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]] | None, float]:
    if source_path is None:
        return "semantic-only", None, 0.0
    derived = _palette_from_image(source_path)
    if derived is None:
        return "semantic-only", None, 0.0
    source_chroma = max(_colorfulness(derived[1]), _colorfulness(derived[2]))
    if source_chroma >= 44:
        return "project-media-dominant", derived, 0.68
    return "semantic-with-low-chroma-media", derived, 0.38


def _palette(
    title: str,
    description: str = "",
    source_path: Path | None = None,
    file_names: Sequence[str] = (),
) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]:
    profile, scores, _evidence = _semantic_decision(title, description, file_names)
    semantic, _semantic_reason = _semantic_palette_for_project(profile, title, description)

    # Mixed-subject projects inherit a restrained amount of the runner-up
    # visual language. This keeps color choices content-driven without making
    # every cover a copy of one fixed category palette.
    ranked = sorted(
        ((score, candidate) for candidate, score in scores.items() if candidate != profile and score > 0),
        reverse=True,
    )
    if ranked and scores[profile] > 0:
        runner_score, runner_profile = ranked[0]
        runner_weight = min(0.20, 0.18 * runner_score / scores[profile])
        runner = SEMANTIC_PALETTES[runner_profile]
        semantic = tuple(
            _blend_color(primary, secondary_color, runner_weight)
            for primary, secondary_color in zip(semantic, runner)
        )
    if source_path is None:
        return semantic

    _palette_label, derived, source_weight = _palette_basis(source_path)
    if derived is None:
        return semantic

    background = _blend_color(semantic[0], derived[0], min(0.55, source_weight * 0.78))
    accent = _lift_color(_blend_color(semantic[1], derived[1], source_weight), 184)
    secondary = _lift_color(_blend_color(semantic[2], derived[2], source_weight), 172)
    if _color_distance(accent, secondary) < 30:
        secondary = _lift_color(_blend_color(semantic[2], derived[2], min(0.42, source_weight)), 172)
    return background, accent, secondary


def _top_safe_document_crop(image: Image.Image, target_size: tuple[int, int]) -> Image.Image:
    """Take a readable top slice whose lower edge falls on a blank row."""
    target_width, target_height = target_size
    target_ratio = target_width / target_height
    ideal_height = max(1, min(image.height, round(image.width / target_ratio)))

    # Inspect a small grayscale copy so the boundary search stays cheap even
    # for very tall PDF/phone screenshots.
    sample_width = 160
    sample_height = max(1, round(image.height * sample_width / image.width))
    sample = ImageOps.grayscale(image).resize((sample_width, sample_height), Image.Resampling.BILINEAR)
    pixels = sample.load()
    ink_counts = [sum(1 for x in range(sample_width) if pixels[x, y] < 220) for y in range(sample_height)]

    # Remove only a narrow bright header or ad strip when a strongly coloured
    # cover visual begins immediately below it. This keeps the first meaningful
    # document content while avoiding unrelated promotional bars at the top.
    color_sample = image.convert("RGB").resize((sample_width, sample_height), Image.Resampling.BILINEAR)
    color_pixels = color_sample.load()
    search_rows = min(
        sample_height - 1,
        max(3, round(ideal_height * 0.18 * sample_height / image.height)),
    )
    initial_light = sum(
        1
        for y in range(min(3, search_rows))
        for x in range(sample_width)
        if min(color_pixels[x, y]) >= 205
    ) / max(1, min(3, search_rows) * sample_width)
    sample_top = 0
    if initial_light >= 0.58:
        saturated_rows = []
        for y in range(2, search_rows + 1):
            saturated = sum(
                1
                for x in range(sample_width)
                if max(color_pixels[x, y]) - min(color_pixels[x, y]) >= 72
            )
            saturated_rows.append(saturated / sample_width)
            if len(saturated_rows) >= 2 and min(saturated_rows[-2:]) >= 0.38:
                sample_top = max(0, y - 1)
                break
    top = round(sample_top * image.height / sample_height)

    lower = max(top + 1, top + round(ideal_height * 0.72))
    upper = min(image.height, top + round(ideal_height * 1.45))
    sample_lower = max(1, round(lower * sample_height / image.height))
    sample_upper = min(sample_height - 1, round(upper * sample_height / image.height))
    blank_threshold = max(2, round(sample_width * 0.015))
    run_start: int | None = None
    selected_boundary: int | None = None
    for sample_y in range(sample_lower, sample_upper + 1):
        if ink_counts[sample_y] <= blank_threshold:
            run_start = sample_y if run_start is None else run_start
            if sample_y - run_start + 1 >= 3:
                selected_boundary = round(run_start * image.height / sample_height)
                break
        else:
            run_start = None

    crop_bottom = selected_boundary or min(image.height, top + ideal_height)
    crop_bottom = max(top + 1, min(image.height, crop_bottom))
    cropped = image.crop((0, top, image.width, crop_bottom))
    # A modest aspect correction is preferable to using fit(), which would
    # silently trim the safe boundary we just found.
    return cropped.resize(target_size, Image.Resampling.LANCZOS)


def _cover_labels(profile: str, tags: Sequence[str]) -> tuple[str, str]:
    specific = [tag.lstrip("#") for tag in tags if tag.lstrip("#") not in GENERIC_COVER_TAGS]
    default_topics, default_keywords = PROFILE_LABELS[profile]
    topics = list(dict.fromkeys([*specific[:2], *default_topics]))[:2]
    if profile == "literary" and any(topic in {"古诗词", "诗词鉴赏"} for topic in topics):
        poetry_tags = [tag for tag in specific[2:] if tag == "传统文化"]
        keywords = list(dict.fromkeys([*poetry_tags, *default_keywords]))[:3]
    else:
        keywords = list(dict.fromkeys([*specific[2:5], *default_keywords]))[:3]
    return " × ".join(topics), " · ".join(keywords)


def _title_phrases(title: str) -> list[str]:
    cleaned = " ".join(str(title or "").split()).strip()
    parts = [part.strip() for part in re.split(r"[，,；;：:|｜]", cleaned) if part.strip()]
    expanded: list[str] = []
    for part in parts:
        book_title = re.fullmatch(r"(.+?)(《[^》]+》)", part)
        if book_title:
            expanded.extend((book_title.group(1).strip(), book_title.group(2).strip()))
            continue
        parenthetical = re.fullmatch(r"(.+?)[（(]([^（）()]+)[）)]", part)
        if parenthetical and len(parenthetical.group(2).strip()) >= 5:
            expanded.extend((parenthetical.group(1).strip(), parenthetical.group(2).strip()))
            continue
        ascii_prefix = re.fullmatch(r"([0-9A-Za-z._+-]{2,14})\s+(.+)", part)
        if ascii_prefix:
            expanded.extend((ascii_prefix.group(1).strip(), ascii_prefix.group(2).strip()))
            continue
        expanded.append(part)
    return expanded or [cleaned or "项目资料"]


def _display_title_and_status(title: str) -> tuple[str, str]:
    cleaned = " ".join(str(title or "").split()).strip()
    statuses: list[str] = []

    def remove_status(match: re.Match[str]) -> str:
        candidate = match.group(1).strip()
        if candidate in TITLE_STATUS_TERMS:
            statuses.append(candidate)
            return ""
        return match.group(0)

    cleaned = re.sub(r"[（(【\[]\s*([^（）()【】\[\]]+?)\s*[）)】\]]", remove_status, cleaned)
    # Storefront price claims and storage sizes are delivery metadata, not a
    # readable course title. Keep them out of the cover while retaining any
    # verified sharing status in its smaller topic line.
    cleaned = re.sub(r"\s*(?:价值|售价|原价)\s*[¥￥]?\s*\d+(?:\.\d+)?\s*(?:元|万|w)?", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+\d+(?:\.\d+)?\s*(?:[KMGT](?:B)?|[KMGT])\s*$", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*[（(]\s*\d{1,3}\s*[）)]\s*$", "", cleaned)
    cleaned = " ".join(cleaned.split()).strip(" _-—–")
    return cleaned or "项目资料", statuses[0] if statuses else ""


def _cover_title_for_profile(title: str, profile: str) -> str:
    """Keep the cover title concise enough to carry a large, readable type scale."""

    cleaned = " ".join(str(title or "").split()).strip()
    folded = cleaned.casefold()
    # Long media-led titles need an evidence-backed display name rather than
    # a smaller full-title squeeze. Preserve the project identity and its
    # strongest subject signal so the title can stay visually dominant.
    if profile == "wellness" and "\u80a9\u9888" in cleaned and "\u8212\u7f13" in cleaned:
        return "\u80a9\u9888\u8212\u7f13\u653b\u7565"
    if profile == "finance" and "\u4e70\u70b9" in cleaned:
        return "\u80a1\u9053\u4e5d\u626c\u4e70\u70b9\u7cfb\u7edf"
    if profile == "digital" and "\u7f51\u7edc\u8425\u9500" in cleaned:
        return "\u4f20\u667a\u64ad\u5ba2,\u7f51\u7edc\u8425\u9500"
    if profile == "digital" and "IP" in cleaned and "\u5207\u7247" in cleaned:
        return "IP\u5207\u7247\u8fd0\u8425"
    if profile == "digital" and "workbuddy" in folded and "办公" in cleaned:
        return "WorkBuddy AI办公实战"
    if profile == "digital" and "短视频" in cleaned and "带货" in cleaned:
        if cleaned.startswith("吉同学排雷班"):
            return "吉同学排雷班短视频带货课"
        return "短视频带货课"
    return cleaned or "项目资料"


def _repair_protected_title_breaks(
    draw: ImageDraw.ImageDraw,
    lines: Sequence[str],
    font: ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    repaired = list(lines)
    for index in range(len(repaired) - 1):
        left, right = repaired[index], repaired[index + 1]
        joined = left + right
        folded_joined = joined.casefold()
        boundary = len(left)
        boundary_repaired = False
        for term in TITLE_PROTECTED_TERMS:
            folded_term = term.casefold()
            start = folded_joined.find(folded_term)
            while start >= 0:
                end = start + len(term)
                if start < boundary < end:
                    move_count = boundary - start
                    candidate_left = left[:-move_count]
                    candidate_right = left[-move_count:] + right
                    if (
                        len(candidate_left.strip()) >= 3
                        and _text_width(draw, candidate_right, font) <= max_width
                    ):
                        left, right = candidate_left, candidate_right
                    else:
                        append_count = end - boundary
                        candidate_left = left + right[:append_count]
                        candidate_right = right[append_count:]
                        if (
                            candidate_right.strip()
                            and _text_width(draw, candidate_left, font) <= max_width
                        ):
                            left, right = candidate_left, candidate_right
                    repaired[index], repaired[index + 1] = left, right
                    boundary_repaired = True
                    break
                start = folded_joined.find(folded_term, start + 1)
            if boundary_repaired:
                break
    return repaired


def _has_title_orphans(lines: Sequence[str]) -> bool:
    if len(lines) <= 1:
        return False
    return any(
        0 < len(re.findall(r"[\u3400-\u9fff]", line)) < 3
        and re.search(r"[A-Za-z0-9]", line) is None
        for line in lines
    )


def _has_protected_title_breaks(lines: Sequence[str]) -> bool:
    """Return whether a title line boundary bisects a meaningful term."""

    if len(lines) < 2:
        return False
    joined = "".join(lines)
    folded_joined = joined.casefold()
    boundaries: set[int] = set()
    offset = 0
    for line in lines[:-1]:
        offset += len(line)
        boundaries.add(offset)
    for term in TITLE_PROTECTED_TERMS:
        folded_term = term.casefold()
        start = folded_joined.find(folded_term)
        while start >= 0:
            end = start + len(term)
            if any(start < boundary < end for boundary in boundaries):
                return True
            start = folded_joined.find(folded_term, start + 1)
    return False


def _balanced_title_wrap(
    draw: ImageDraw.ImageDraw,
    phrase: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    lines = _repair_protected_title_breaks(draw, _wrap_text(draw, phrase, font, max_width), font, max_width)
    if len(lines) < 2 or len(lines[-1]) >= 3 or len(lines[-2]) <= 3:
        return lines
    previous = lines[-2]
    last = lines[-1]
    while len(last) < 3 and len(previous) > 3:
        candidate_previous = previous[:-1]
        candidate_last = previous[-1] + last
        if _text_width(draw, candidate_last, font) > max_width:
            break
        previous, last = candidate_previous, candidate_last
    lines[-2:] = [previous, last]
    return lines


def _fit_title_lines(
    draw: ImageDraw.ImageDraw,
    title: str,
    family: str,
    max_width: int,
    max_height: int,
    *,
    prefer_phrases: bool = False,
) -> tuple[ImageFont.ImageFont, list[str]]:
    phrases = _title_phrases(title)
    phrase_sets = [phrases, [title]] if prefer_phrases and len(phrases) > 1 else [phrases]
    if "《" in title and "》" in title and not prefer_phrases:
        phrase_sets.insert(0, [title])
    for size in (116, 108, 100, 94, 88, 82, 76, 70, 64):
        font = _font(size, bold=True, family=family)
        for current_phrases in phrase_sets:
            lines = [
                line
                for phrase in current_phrases
                for line in _balanced_title_wrap(draw, phrase, font, max_width)
            ]
            line_height = size + 18
            intentional_book_author = bool(
                prefer_phrases
                and current_phrases == phrases
                and "《" in title
                and len(lines) == 2
                and len(re.findall(r"[\u3400-\u9fff]", lines[0])) >= 2
            )
            if (
                1 <= len(lines) <= 4
                and len(lines) * line_height <= max_height
                and (intentional_book_author or not _has_title_orphans(lines))
                and not _has_protected_title_breaks(lines)
            ):
                return font, lines
    font = _font(60, bold=True, family=family)
    return font, _balanced_title_wrap(draw, title, font, max_width)[:4]


def _extension_counts(details: Mapping[str, object]) -> dict[str, int]:
    summary = details.get("summary") if isinstance(details, Mapping) else None
    summary = summary if isinstance(summary, Mapping) else {}
    raw_counts = summary.get("extension_counts")
    if not isinstance(raw_counts, Mapping):
        return {}
    counts: dict[str, int] = {}
    for extension, count in raw_counts.items():
        try:
            counts[str(extension).casefold()] = max(0, int(count))
        except (TypeError, ValueError):
            continue
    return counts


def _project_metrics(details: Mapping[str, object]) -> list[tuple[str, int]]:
    counts = _extension_counts(details)

    def total(extensions: set[str]) -> int:
        return sum(count for extension, count in counts.items() if extension in extensions)

    candidates = (
        ("视频", total({".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv", ".m4v"})),
        ("音频", total({".aac", ".flac", ".m4a", ".mp3", ".wav", ".wma"})),
        ("PDF讲义", counts.get(".pdf", 0)),
        ("PPT课件", total({".ppt", ".pptx"})),
        ("Word文档", total({".doc", ".docx"})),
    )
    metrics = [(label, count) for label, count in candidates if count > 0][:3]
    if metrics:
        return metrics

    summary = details.get("summary") if isinstance(details, Mapping) else None
    summary = summary if isinstance(summary, Mapping) else {}
    file_count = int(summary.get("file_count") or 0)
    folder_count = int(summary.get("folder_count") or 0)
    fallback: list[tuple[str, int]] = []
    if file_count:
        fallback.append(("文件", file_count))
    if folder_count:
        fallback.append(("文件夹", folder_count))
    return fallback[:3]


def _title_visual_units(title: str) -> int:
    cleaned = str(title or "")
    cjk_count = len(re.findall(r"[\u3400-\u9fff]", cleaned))
    ascii_count = len(re.findall(r"[A-Za-z0-9]", cleaned))
    return cjk_count + (ascii_count + 2) // 3


def _source_aspect_ratio(source_path: Path | None) -> float | None:
    if source_path is None:
        return None
    try:
        with Image.open(source_path) as opened:
            if opened.height <= 0:
                return None
            return round(opened.width / opened.height, 3)
    except (OSError, ValueError):
        return None


def _support_text_from_project(
    *,
    title: str,
    profile: str,
    details: Mapping[str, object],
    file_names: Sequence[str],
) -> tuple[str, str]:
    media = details.get("media") if isinstance(details, Mapping) else None
    media = media if isinstance(media, Mapping) else {}
    source_name = str(media.get("source_name") or "")
    structure_names = [
        str(item.get("name") or "")
        for item in (details.get("top_level", ()) or ())
        if isinstance(item, Mapping)
    ]
    evidence_names = [source_name, *structure_names, *map(str, file_names[:80])]
    evidence = " ".join(name for name in evidence_names if name)
    if not evidence:
        return "", ""

    fragments: list[str] = []
    acceleration = re.search(r"(?<!\d)(\d{1,3}次加速)(?!\d)", evidence)
    if acceleration:
        fragments.append(acceleration.group(1))

    normalized_title = re.sub(r"\s+", "", title).casefold()
    for term, _weight in SEMANTIC_KEYWORDS.get(profile, ()):
        normalized_term = term.casefold()
        duplicates_fragment = any(
            normalized_term in fragment.casefold() or fragment.casefold() in normalized_term
            for fragment in fragments
        )
        if normalized_term in evidence.casefold() and normalized_term not in normalized_title and not duplicates_fragment:
            fragments.append(term)
        if len(list(dict.fromkeys(fragments))) >= 2:
            break

    fragments = list(dict.fromkeys(fragments))[:2]
    if not fragments:
        return "", ""
    source = "media.source_name" if source_name and all(fragment in source_name for fragment in fragments) else "project.files"
    return " · ".join(fragments), source


def _clean_spine_label(value: str) -> str:
    """Keep a short, real course-unit label while removing file clutter."""
    label = Path(str(value or "").strip()).stem
    label = re.sub(r"【[^】]*】|\[[^\]]*]", "", label)
    label = label.replace("【", "").replace("】", "")
    label = re.sub(
        r"[（(]\s*共\s*\d+\s*讲(?:\s*[-—–]\s*含加餐\s*\d+\s*讲)?\s*[）)]",
        "",
        label,
    )
    label = re.sub(r"^\s*\d{6,}\s*[_\-—–、丨|:：. ]*", "", label)
    label = re.sub(r"(?:[_\-]\s*\d{1,3})+$", "", label)
    if not re.match(r"^(?:19|20)\d{2}年", label):
        label = re.sub(
            r"^\s*(?:(?:第\s*)?\d{1,3}\s*(?:节|讲|集|课)?\s*[_\-—–、丨|:：. ]*){1,2}",
            "",
            label,
        )
    label = re.sub(r"^\s*[一二三四五六七八九十]+\s*(?:节|讲|集|课)?\s*[_\-—–、丨|:：. ]*", "", label)
    label = re.sub(r"^[\u4e00-\u9fffA-Za-z]{2,16}\s*[_\-—–]\s*\d{1,3}\s*(?=[A-Za-z\u4e00-\u9fff])", "", label)
    label = re.sub(r"(?i)workbuddy[-_]?ai办公", "WorkBuddy AI办公", label)
    label = re.sub(r"(?i)workbuddy", "WorkBuddy", label)
    label = label.replace("_", " ")
    label = re.sub(r"\s+", " ", label).strip(" _-—–、丨|:：.")
    label = re.sub(r"^(第[一二三四五六七八九十0-9]+模块)\s*(?=\S)", r"\1 · ", label)
    return label.rstrip(" _-—–、丨|:：.")


def _content_spine_from_project(
    details: Mapping[str, object],
    file_names: Sequence[str],
    *,
    limit: int = 6,
) -> tuple[list[str], str]:
    top_level = details.get("top_level") if isinstance(details, Mapping) else None
    top_level = top_level if isinstance(top_level, Sequence) else ()
    raw_names = [
        str(item.get("name") or "")
        for item in top_level
        if isinstance(item, Mapping) and str(item.get("name") or "").strip()
    ]
    source = "project.top_level" if raw_names else "project.files"
    raw_names.extend(str(name) for name in file_names)

    labels: list[str] = []
    seen: set[str] = set()
    for raw_name in raw_names:
        label = _clean_spine_label(raw_name)
        key = re.sub(r"[\s_·•]+", "", label).casefold()
        if len(label) < 2 or not key or key in seen or key in GENERIC_SPINE_LABELS:
            continue
        seen.add(key)
        labels.append(label)
        if len(labels) >= limit:
            break
    return labels, source


def _summary_support_from_project(
    details: Mapping[str, object],
    metrics: Sequence[tuple[str, int]],
) -> tuple[str, str]:
    summary = details.get("summary") if isinstance(details, Mapping) else None
    summary = summary if isinstance(summary, Mapping) else {}
    extension_counts = summary.get("extension_counts")
    extension_counts = extension_counts if isinstance(extension_counts, Mapping) else {}

    video_count = sum(
        int(count or 0)
        for extension, count in extension_counts.items()
        if str(extension).lower() in VIDEO_EXTENSIONS
    )
    if video_count:
        return f"{video_count} 节视频课程", "project.summary"
    document_count = sum(
        int(count or 0)
        for extension, count in extension_counts.items()
        if str(extension).lower() in DOCUMENT_EXTENSIONS
    )
    if document_count:
        return f"{document_count} 份配套资料", "project.summary"
    if metrics:
        label, count = metrics[0]
        return f"{count} 份{label}", "project.summary"
    return "", ""


def _select_layout_strategy(
    *,
    title: str,
    source_path: Path | None,
    source_kind: str,
    metrics: Sequence[tuple[str, int]],
    support_text: str,
    profile: str = "modern",
    content_spine: Sequence[str] = (),
) -> tuple[str, dict[str, object]]:
    title_units = _title_visual_units(title)
    title_class = "short" if title_units <= 11 else ("medium" if title_units <= 18 else "long")
    source_aspect = _source_aspect_ratio(source_path)
    if source_path is None:
        if len(content_spine) >= 3:
            if profile == "wellness":
                strategy = "semantic-guide"
                reason = "没有可用预览素材，依据真实课程单元生成健康学习路径"
            elif profile in {"digital", "cinematic", "finance"} and title_class == "long":
                strategy = "semantic-grid"
                reason = "没有可用预览素材，依据真实课程单元生成高密度主题矩阵"
            else:
                strategy = "semantic-timeline"
                reason = "没有可用预览素材，依据真实课程单元生成内容脉络"
        else:
            strategy = "semantic-summary"
            reason = "项目没有可预览素材或足够课程单元，使用紧凑信息摘要"
    elif source_kind in {"video-preview", "video-frame", "video-contact-sheet"}:
        if profile in {"literary", "learning", "wellness", "finance"}:
            strategy = "media-editorial-split"
            reason = "视频素材与项目主题偏重讲解或知识表达，使用编辑式文字区和完整实拍画面"
        else:
            strategy = "media-focus-split"
            reason = "视频素材与项目主题偏重实操或数字创作，使用大幅实拍画面和连续课程信息带"
    elif title_class == "short" and support_text:
        strategy = "source-dominant-poster"
        reason = "短标题且存在真实支持信息，使用素材主导海报避免长标题栏空置"
    else:
        strategy = "asymmetric-split"
        reason = "标题需要多行承载，使用非对称文字区与真实素材融合"
    return strategy, {
        "title_units": title_units,
        "title_length_class": title_class,
        "source_kind": source_kind or "none",
        "source_aspect_ratio": source_aspect,
        "metric_count": len(metrics),
        "content_spine_count": len(content_spine),
        "reason": reason,
    }


def _draw_semantic_background(
    *,
    width: int,
    height: int,
    background: tuple[int, int, int],
    accent: tuple[int, int, int],
    secondary: tuple[int, int, int],
    profile: str,
) -> Image.Image:
    canvas = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(canvas)
    for y in range(height):
        shade = y / max(1, height - 1)
        color = _blend_color(background, (3, 7, 16), 0.18 + shade * 0.24)
        draw.line((0, y, width, y), fill=color)

    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse(
        (round(width * 0.46), -round(height * 0.28), round(width * 1.08), round(height * 0.72)),
        fill=(*accent, 66),
    )
    glow_draw.ellipse(
        (-round(width * 0.16), round(height * 0.64), round(width * 0.38), round(height * 1.18)),
        fill=(*secondary, 35),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(radius=95))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), glow).convert("RGB")
    draw = ImageDraw.Draw(canvas)

    if profile == "literary":
        draw.arc((width - 690, 42, width - 80, 652), 188, 352, fill=secondary, width=2)
        draw.arc((width - 610, 116, width - 18, 708), 172, 332, fill=accent, width=1)
        for index in range(4):
            y = 102 + index * 18
            draw.line((width - 770 + index * 18, y, width - 690 + index * 36, y), fill=accent, width=1)
    elif profile == "friendly":
        for x, y, radius, color in (
            (width - 175, 96, 62, accent),
            (width - 82, 212, 34, secondary),
            (80, height - 92, 44, accent),
        ):
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=color, width=2)
    else:
        for row in range(7):
            for column in range(11):
                x = width - 278 + column * 22
                y = 18 + row * 22
                draw.ellipse((x, y, x + 7, y + 7), fill=_blend_color(background, accent, 0.32))
    return canvas


def _prepare_source_visual(
    source_path: Path,
    target_size: tuple[int, int],
    source_kind: str,
) -> Image.Image:
    with Image.open(source_path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
    if source_kind == "document-preview" or image.height > image.width * 1.25:
        return _top_safe_document_crop(image, target_size)
    return ImageOps.fit(
        image,
        target_size,
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )


def _paste_source_blended(
    canvas: Image.Image,
    source_path: Path,
    box: tuple[int, int, int, int],
    *,
    background: tuple[int, int, int],
    source_kind: str,
    blend_left_edge: bool = True,
) -> None:
    left, top, right, bottom = box
    target_size = (right - left, bottom - top)
    source = _prepare_source_visual(source_path, target_size, source_kind)

    rounded = Image.new("L", target_size, 0)
    ImageDraw.Draw(rounded).rounded_rectangle(
        (0, 0, target_size[0] - 1, target_size[1] - 1), radius=44, fill=255
    )
    mask = rounded
    if blend_left_edge:
        fade = Image.new("L", target_size, 255)
        fade_draw = ImageDraw.Draw(fade)
        fade_width = min(250, target_size[0] // 3)
        for x in range(fade_width):
            alpha = round(255 * (x / max(1, fade_width - 1)) ** 1.6)
            fade_draw.line((x, 0, x, target_size[1]), fill=alpha)
        mask = ImageChops.multiply(rounded, fade)
    canvas.paste(source, (left, top), mask)

    if not blend_left_edge:
        return

    # Darken only layouts that intentionally share a text/image overlap zone.
    overlay = Image.new("RGBA", target_size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlap_width = min(330, target_size[0] // 2)
    for x in range(overlap_width):
        alpha = round(172 * (1.0 - x / max(1, overlap_width - 1)) ** 1.4)
        overlay_draw.line((x, 0, x, target_size[1]), fill=(*background, alpha))
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    layer.alpha_composite(overlay, (left, top))
    canvas.paste(Image.alpha_composite(canvas.convert("RGBA"), layer).convert("RGB"))


def _render_source_dominant_poster(
    *,
    source_path: Path,
    source_kind: str,
    width: int,
    height: int,
    background: tuple[int, int, int],
    accent: tuple[int, int, int],
    secondary: tuple[int, int, int],
    title_family: str,
    eyebrow_family: str,
    body_family: str,
    topic_text: str,
    display_title: str,
    support_text: str,
    keyword_text: str,
    metrics: Sequence[tuple[str, int]],
) -> tuple[Image.Image, list[str], list[str], dict[str, object]]:
    source = _prepare_source_visual(source_path, (width, height), source_kind)
    canvas = Image.blend(source, Image.new("RGB", (width, height), background), 0.07)

    stage_top = round(height * 0.35)
    stage_right = round(width * 0.75)
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.polygon(
        ((0, stage_top), (round(width * 0.57), stage_top), (stage_right, height), (0, height)),
        fill=(*_blend_color(background, (0, 0, 0), 0.18), 238),
    )
    overlay_draw.polygon(
        (
            (0, stage_top - 11),
            (round(width * 0.57), stage_top - 11),
            (round(width * 0.576), stage_top),
            (0, stage_top),
        ),
        fill=(*accent, 235),
    )
    canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(canvas)

    left = 70
    content_width = round(width * 0.63)
    eyebrow_font = _font(28, bold=True, family=eyebrow_family)
    title_font, title_lines = _fit_title_lines(
        draw,
        display_title,
        title_family,
        content_width,
        max_height=220,
    )
    support_font = _font(43, bold=True, family=body_family)
    keyword_font = _font(26, bold=True, family=body_family)
    metric_number_font = _font(38, bold=True, family=body_family)
    metric_label_font = _font(22, bold=False, family=body_family)

    topic_y = stage_top + 28
    draw.rectangle((left, topic_y + 3, left + 11, topic_y + 39), fill=accent)
    topic_line = _wrap_text(draw, topic_text, eyebrow_font, content_width - 36, max_lines=1)[0]
    draw.text((left + 27, topic_y), topic_line, font=eyebrow_font, fill=(247, 245, 239))

    title_y = topic_y + 63
    line_gap = max(10, round(title_font.size * 0.13))
    y = title_y
    for index, line in enumerate(title_lines):
        draw.text(
            (left, y),
            line,
            font=title_font,
            fill=(249, 246, 238) if index else accent,
            stroke_width=1,
            stroke_fill=_blend_color(background, (0, 0, 0), 0.52),
        )
        y += title_font.size + line_gap

    support_y = y + 8
    support_lines = _wrap_text(draw, support_text, support_font, content_width, max_lines=1)
    for line in support_lines:
        draw.text((left, support_y), line, font=support_font, fill=secondary)
        support_y += support_font.size + 8

    keyword_y = support_y + 13
    keyword_lines = _wrap_text(draw, keyword_text, keyword_font, content_width, max_lines=1)
    for line in keyword_lines:
        draw.text((left, keyword_y), line, font=keyword_font, fill=(241, 238, 230))
        keyword_y += keyword_font.size + 8

    metric_y = height - 112
    metric_span = min(content_width, 980)
    segment_width = metric_span / max(1, len(metrics))
    draw.line((left, metric_y - 16, left + metric_span, metric_y - 16), fill=accent, width=2)
    for index, (label, count) in enumerate(metrics):
        segment_left = round(left + index * segment_width)
        if index:
            draw.line(
                (segment_left, metric_y + 2, segment_left, height - 36),
                fill=_blend_color(background, secondary, 0.62),
                width=1,
            )
        number_text = str(count)
        draw.text((segment_left + 4, metric_y), number_text, font=metric_number_font, fill=accent)
        number_width = draw.textlength(number_text, font=metric_number_font)
        draw.text(
            (segment_left + 14 + number_width, metric_y + 14),
            label,
            font=metric_label_font,
            fill=(247, 245, 239),
        )

    fullness = {
        "source_coverage": 1.0,
        "occupied_ratio": 0.93,
        "title_line_count": len(title_lines),
        "support_line_count": len(support_lines),
        "keyword_line_count": len(keyword_lines),
        "metric_count": len(metrics),
    }
    return canvas, title_lines, keyword_lines, fullness


def _render_media_source_card(
    *,
    source_path: Path,
    source_kind: str,
    width: int,
    height: int,
    background: tuple[int, int, int],
    accent: tuple[int, int, int],
    secondary: tuple[int, int, int],
    profile: str,
    title_family: str,
    eyebrow_family: str,
    body_family: str,
    topic_text: str,
    display_title: str,
    support_text: str,
    keyword_text: str,
    metrics: Sequence[tuple[str, int]],
    content_spine: Sequence[str],
    variant: str,
) -> tuple[Image.Image, list[str], list[str], dict[str, object], dict[str, object]]:
    """Render video-led covers with clear source/text zones and one content spine."""
    canvas = _draw_semantic_background(
        width=width,
        height=height,
        background=background,
        accent=accent,
        secondary=secondary,
        profile=profile,
    )
    editorial = variant == "media-editorial-split"
    editorial_has_followup_cards = editorial and len(content_spine) > 3
    editorial_source_bottom = (
        (536 if len(metrics) >= 2 else 620)
        if editorial_has_followup_cards
        else height - 74
    )
    source_box = (
        (792, 62, width - 48, editorial_source_bottom)
        if editorial
        else (760, 56, width - 48, height - 74)
    )
    _paste_source_blended(
        canvas,
        source_path,
        source_box,
        background=background,
        source_kind=source_kind,
        blend_left_edge=False,
    )
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(source_box, radius=44, outline=accent, width=3)
    draw.line(
        (source_box[0] + 58, source_box[1] - 10, source_box[2] - 24, source_box[1] - 10),
        fill=secondary,
        width=4,
    )

    left = 62
    text_width = 706 if editorial else 674
    eyebrow_font = _font(29, bold=True, family=eyebrow_family)
    support_font = _font(32, bold=True, family=body_family)
    keyword_font = _font(25, bold=True, family=body_family)
    spine_font = _font(22, bold=True, family=body_family)

    topic_lines = _wrap_text(draw, topic_text, eyebrow_font, text_width - 44, max_lines=1)
    topic_line = topic_lines[0] if topic_lines else "专题课程"
    draw.rectangle((left, 72, left + 12, 111), fill=accent)
    draw.text((left + 30, 71), topic_line, font=eyebrow_font, fill=(246, 244, 237))
    draw.line((left + 30, 119, left + text_width - 34, 119), fill=secondary, width=2)

    prefer_phrases = not editorial and _title_visual_units(display_title) <= 11
    title_font, title_lines = _fit_title_lines(
        draw,
        display_title,
        title_family,
        text_width,
        max_height=336 if editorial else 396,
        prefer_phrases=prefer_phrases,
    )
    if prefer_phrases and "《" in display_title and len(title_lines) > 1:
        title_lines[0] = title_lines[0].rstrip(" ·•")
    title_y = 150
    line_gap = max(8, round(title_font.size * 0.12))
    y = title_y
    title_bottom = title_y
    for index, line in enumerate(title_lines):
        draw.text(
            (left, y),
            line,
            font=title_font,
            fill=accent if index == 0 else ((248, 246, 239) if index % 2 else secondary),
            stroke_width=1,
            stroke_fill=_blend_color(background, (0, 0, 0), 0.48),
        )
        title_bottom = max(
            title_bottom,
            draw.textbbox((left, y), line, font=title_font, stroke_width=1)[3],
        )
        y += title_font.size + line_gap

    support_lines = _wrap_text(draw, support_text, support_font, text_width, max_lines=2) if support_text else []
    title_support_gap = max(30, round(title_font.size * 0.32))
    support_y = title_bottom + title_support_gap
    support_top = support_y
    support_bottom = support_y
    for line in support_lines:
        draw.text((left, support_y), line, font=support_font, fill=secondary)
        support_bottom = max(support_bottom, draw.textbbox((left, support_y), line, font=support_font)[3])
        support_y += support_font.size + 7

    keyword_lines = _wrap_text(draw, keyword_text, keyword_font, text_width, max_lines=2)
    keyword_y = (support_bottom if support_lines else title_bottom) + 16
    for line in keyword_lines:
        draw.text((left, keyword_y), line, font=keyword_font, fill=(236, 241, 244))
        keyword_y += keyword_font.size + 7

    all_spine_labels = list(content_spine[:6])
    content_regions: list[dict[str, object]] = []
    metric_presentation = "support-inline" if len(metrics) == 1 else ("compact-strip" if metrics else "none")

    def draw_metric_strip(box: tuple[int, int, int, int], *, compact: bool) -> None:
        draw.rounded_rectangle(
            box,
            radius=18,
            fill=_blend_color(background, (0, 0, 0), 0.28),
            outline=accent,
            width=2,
        )
        segment_width = (box[2] - box[0]) / max(1, len(metrics))
        number_font = _font(31 if compact else 36, bold=True, family=body_family)
        label_font = _font(16 if compact else 18, bold=False, family=body_family)
        for index, (label, count) in enumerate(metrics):
            x = round(box[0] + index * segment_width)
            if index:
                draw.line((x, box[1] + 16, x, box[3] - 16), fill=secondary, width=1)
            number_text = str(count)
            number_y = box[1] + (19 if compact else 25)
            draw.text((x + 20, number_y), number_text, font=number_font, fill=accent)
            number_width = draw.textlength(number_text, font=number_font)
            draw.text(
                (x + 29 + number_width, number_y + 10),
                label,
                font=label_font,
                fill=(240, 242, 243),
            )

    if editorial:
        rail_y = min(max(keyword_y + 26, 500), 548)
        left_labels = all_spine_labels[:3]
        right_labels = all_spine_labels[len(left_labels):len(left_labels) + 3]
        has_metric_strip = len(metrics) >= 2
        rail_bottom = 748 if has_metric_strip else height - 72
        if left_labels:
            draw.text((left, rail_y), "课程线索", font=_font(22, bold=True, family=body_family), fill=secondary)
            draw.line((left + 7, rail_y + 44, left + 7, rail_bottom), fill=accent, width=3)
            item_top = rail_y + 54
            slot_height = max(68, (rail_bottom - item_top) // len(left_labels))
            for index, label in enumerate(left_labels):
                item_y = item_top + index * slot_height
                draw.ellipse((left - 2, item_y + 4, left + 18, item_y + 24), fill=accent if index == 0 else secondary)
                lines = _wrap_content_spine_label(draw, label, _font(21, bold=True, family=body_family), text_width - 54, max_lines=2)
                line_y = item_y
                for line in lines:
                    draw.text((left + 34, line_y), line, font=_font(21, bold=True, family=body_family), fill=(241, 243, 240))
                    line_y += 28
            content_regions.append({"name": "left-rail", "indices": list(range(len(left_labels)))})

        if right_labels:
            cards_left = 812
            cards_heading_y = source_box[3] + 14
            cards_top = source_box[3] + 50
            cards_right = width - 54
            cards_bottom = 752 if has_metric_strip else height - 74
            card_gap = 16
            card_width = (cards_right - cards_left - card_gap * (len(right_labels) - 1)) // len(right_labels)
            draw.text((cards_left, cards_heading_y), "课程进阶", font=_font(22, bold=True, family=body_family), fill=secondary)
            for index, label in enumerate(right_labels):
                x = cards_left + index * (card_width + card_gap)
                card_box = (x, cards_top, x + card_width, cards_bottom)
                fill = _blend_color(background, accent if index % 2 == 0 else secondary, 0.16)
                draw.rounded_rectangle(card_box, radius=20, fill=fill, outline=_blend_color(background, accent, 0.65), width=2)
                draw.text((x + 18, cards_top + 18), f"0{index + 1}", font=_font(19, bold=True, family=body_family), fill=accent)
                lines = _wrap_content_spine_label(draw, label, spine_font, card_width - 38, max_lines=4)
                label_y = cards_top + 62
                for line in lines:
                    draw.text((x + 18, label_y), line, font=spine_font, fill=(244, 245, 241))
                    label_y += spine_font.size + 6
            start = len(left_labels)
            content_regions.append({"name": "source-cards", "indices": list(range(start, start + len(right_labels)))})

        if has_metric_strip:
            draw_metric_strip((62, 798, width - 54, height - 30), compact=False)
    else:
        module_indices = [index for index, label in enumerate(all_spine_labels) if "模块" in label]
        left_indices = module_indices[:3] if len(module_indices) >= 3 else list(
            range(max(0, len(all_spine_labels) - 3), len(all_spine_labels))
        )
        left_labels = [all_spine_labels[index] for index in left_indices]
        has_metric_strip = len(metrics) >= 2
        rail_y = min(max(keyword_y + 52, 500), 560)
        rail_bottom = height - 158 if has_metric_strip else height - 72
        if left_labels:
            draw.text((left, rail_y), "课程主线", font=_font(22, bold=True, family=body_family), fill=secondary)
            draw.line((left + 8, rail_y + 45, left + 8, rail_bottom), fill=accent, width=3)
            item_top = rail_y + 56
            slot_height = max(70, (rail_bottom - item_top) // len(left_labels))
            for index, label in enumerate(left_labels):
                item_y = item_top + index * slot_height
                draw.ellipse((left - 1, item_y + 3, left + 19, item_y + 23), fill=accent if index == 0 else secondary)
                draw.text((left + 35, item_y - 3), f"0{index + 1}", font=_font(17, bold=True, family=body_family), fill=accent)
                lines = _wrap_content_spine_label(draw, label, spine_font, text_width - 86, max_lines=2)
                line_y = item_y + 25
                for line in lines:
                    draw.text((left + 35, line_y), line, font=spine_font, fill=(242, 244, 241))
                    line_y += spine_font.size + 5
            content_regions.append({"name": "left-rail", "indices": left_indices})

        if has_metric_strip:
            draw_metric_strip((left, height - 124, left + text_width, height - 38), compact=True)

    fullness = {
        "source_coverage": round(
            ((source_box[2] - source_box[0]) * (source_box[3] - source_box[1])) / (width * height),
            3,
        ),
        "occupied_ratio": 0.90,
        "title_line_count": len(title_lines),
        "support_line_count": len(support_lines),
        "keyword_line_count": len(keyword_lines),
        "metric_count": len(metrics),
    }
    render_details = {
        "layout_geometry": {
            "text_zone": [left, 70, left + text_width, height - 38],
            "source_zone": list(source_box),
            "minimum_gap": source_box[0] - (left + text_width),
            "text_over_source": False,
            "title_support_gap": support_top - title_bottom if support_lines else 0,
            "title_font_size_px": title_font.size,
            "title_line_gap_px": line_gap,
            "title_width_ratio": round(
                max((draw.textlength(line, font=title_font) for line in title_lines), default=0) / text_width,
                3,
            ),
        },
        "metric_presentation": metric_presentation,
        "content_regions": content_regions,
    }
    return canvas, title_lines, keyword_lines, fullness, render_details


def _render_semantic_course_map(
    *,
    width: int,
    height: int,
    background: tuple[int, int, int],
    accent: tuple[int, int, int],
    secondary: tuple[int, int, int],
    profile: str,
    title_family: str,
    eyebrow_family: str,
    body_family: str,
    topic_text: str,
    display_title: str,
    support_text: str,
    keyword_text: str,
    metrics: Sequence[tuple[str, int]],
    content_spine: Sequence[str],
    variant: str,
) -> tuple[Image.Image, list[str], list[str], dict[str, object]]:
    """Render a full text-led cover from verified course-unit names only."""
    canvas = _draw_semantic_background(
        width=width,
        height=height,
        background=background,
        accent=accent,
        secondary=secondary,
        profile=profile,
    )
    draw = ImageDraw.Draw(canvas)
    left = 64
    eyebrow_font = _font(28, bold=True, family=eyebrow_family)
    support_font = _font(38, bold=True, family=body_family)
    keyword_font = _font(25, bold=True, family=body_family)
    metric_number_font = _font(37, bold=True, family=body_family)
    metric_label_font = _font(21, bold=False, family=body_family)
    rail_font = _font(24, bold=True, family=body_family)
    rail_small_font = _font(20, bold=False, family=body_family)

    def draw_topic(y: int, max_width: int) -> None:
        topic_line = _wrap_text(draw, topic_text, eyebrow_font, max_width - 42, max_lines=1)[0]
        draw.rectangle((left, y + 4, left + 10, y + 42), fill=accent)
        draw.text((left + 26, y), topic_line, font=eyebrow_font, fill=(247, 245, 239))

    def draw_metrics(y: int, span: int) -> None:
        if not metrics:
            return
        draw.line((left, y - 18, left + span, y - 18), fill=accent, width=2)
        segment_width = span / len(metrics)
        for index, (label, count) in enumerate(metrics):
            segment_left = round(left + index * segment_width)
            if index:
                draw.line(
                    (segment_left, y - 2, segment_left, height - 38),
                    fill=_blend_color(background, secondary, 0.56),
                    width=1,
                )
            number_text = str(count)
            draw.text((segment_left + 8, y), number_text, font=metric_number_font, fill=accent)
            number_width = draw.textlength(number_text, font=metric_number_font)
            draw.text(
                (segment_left + 18 + number_width, y + 13),
                label,
                font=metric_label_font,
                fill=(242, 243, 244),
            )

    support_lines: list[str] = []
    if variant == "semantic-grid":
        title_width = 780
        draw_topic(72, title_width)
        title_font, title_lines = _fit_title_lines(
            draw, display_title, title_family, title_width, max_height=480
        )
        title_y = 156
        line_gap = max(9, round(title_font.size * 0.14))
        y = title_y
        for index, line in enumerate(title_lines):
            draw.text(
                (left, y),
                line,
                font=title_font,
                fill=accent if index % 2 == 0 else (247, 245, 239),
                stroke_width=1,
                stroke_fill=_blend_color(background, (0, 0, 0), 0.48),
            )
            y += title_font.size + line_gap
        support_lines = _wrap_text(draw, support_text, support_font, title_width, max_lines=1)
        for line in support_lines:
            draw.text((left, y + 8), line, font=support_font, fill=secondary)
            y += support_font.size + 8
        keyword_lines = _wrap_text(draw, keyword_text, keyword_font, title_width, max_lines=2)
        keyword_y = min(y + 18, 680)
        for line in keyword_lines:
            draw.text((left, keyword_y), line, font=keyword_font, fill=(238, 241, 246))
            keyword_y += keyword_font.size + 8

        archive_grid = topic_text.startswith("年份归档")
        if archive_grid:
            draw.text((left, 570), "年度分段", font=eyebrow_font, fill=secondary)
            archive_ranges = ("1985–1993", "1994–2002", "2003–2011", "2012–2021")
            range_width = 350
            range_height = 66
            for range_index, range_label in enumerate(archive_ranges):
                range_col, range_row = range_index % 2, range_index // 2
                range_x = left + range_col * (range_width + 22)
                range_y = 620 + range_row * (range_height + 18)
                range_fill = _blend_color(
                    background,
                    accent if range_index % 2 == 0 else secondary,
                    0.34,
                )
                draw.rounded_rectangle(
                    (range_x, range_y, range_x + range_width, range_y + range_height),
                    radius=18,
                    fill=range_fill,
                )
                draw.text(
                    (range_x + 28, range_y + 17),
                    range_label,
                    font=rail_font,
                    fill=(247, 247, 243),
                )

        grid_left = 948
        grid_top = 105
        grid_width = width - grid_left - 60
        card_gap = 16
        card_width = (grid_width - card_gap) // 2
        card_height = 170
        draw.text((grid_left, 62), "年度样例" if archive_grid else "课程单元", font=eyebrow_font, fill=secondary)
        for index, label in enumerate(content_spine[:6]):
            column, row = index % 2, index // 2
            x = grid_left + column * (card_width + card_gap)
            y = grid_top + row * (card_height + card_gap)
            fill = _blend_color(
                background,
                accent if index % 2 == 0 else secondary,
                0.32 if archive_grid else 0.17,
            )
            draw.rounded_rectangle((x, y, x + card_width, y + card_height), radius=24, fill=fill)
            draw.text((x + 24, y + 22), f"{index + 1:02d}", font=_font(22, bold=True, family=body_family), fill=accent)
            lines = _wrap_content_spine_label(draw, label, rail_font, card_width - 46, max_lines=2)
            label_y = y + 67
            for line in lines:
                draw.text((x + 24, label_y), line, font=rail_font, fill=(246, 246, 242))
                label_y += rail_font.size + 7
        draw_metrics(height - 106, 1450)
        occupied_ratio = 0.94

    elif variant == "semantic-guide":
        title_width = 830
        draw_topic(72, title_width)
        title_font, title_lines = _fit_title_lines(
            draw, display_title, title_family, title_width, max_height=430
        )
        y = 156
        line_gap = max(9, round(title_font.size * 0.14))
        for index, line in enumerate(title_lines):
            draw.text(
                (left, y),
                line,
                font=title_font,
                fill=accent if index == 0 else (247, 245, 239),
                stroke_width=1,
                stroke_fill=_blend_color(background, (0, 0, 0), 0.46),
            )
            y += title_font.size + line_gap
        support_lines = _wrap_text(draw, support_text, support_font, title_width, max_lines=1)
        for line in support_lines:
            draw.text((left, y + 10), line, font=support_font, fill=secondary)
            y += support_font.size + 8
        keyword_lines = _wrap_text(draw, keyword_text, keyword_font, title_width, max_lines=2)
        keyword_y = min(y + 20, 668)
        for line in keyword_lines:
            draw.text((left, keyword_y), line, font=keyword_font, fill=(239, 245, 241))
            keyword_y += keyword_font.size + 8

        center_x, center_y = 1208, 360
        for radius, color, line_width in ((170, accent, 4), (128, secondary, 2), (82, accent, 2)):
            draw.ellipse(
                (center_x - radius, center_y - radius, center_x + radius, center_y + radius),
                outline=color,
                width=line_width,
            )
        draw.text((center_x - 68, center_y - 18), "学习", font=_font(33, bold=True, family=body_family), fill=(247, 248, 244))
        draw.text((center_x - 68, center_y + 26), "路径", font=_font(33, bold=True, family=body_family), fill=secondary)
        step_y = 585
        step_width = 250
        for index, label in enumerate(content_spine[:4]):
            column = index % 2
            row = index // 2
            x = 962 + column * 306
            y = step_y + row * 118
            draw.ellipse((x, y + 6, x + 32, y + 38), fill=accent if index % 2 == 0 else secondary)
            draw.text((x + 9, y + 8), str(index + 1), font=_font(17, bold=True, family=body_family), fill=background)
            lines = _wrap_content_spine_label(draw, label, rail_small_font, step_width - 48, max_lines=2)
            label_y = y
            for line in lines:
                draw.text((x + 48, label_y), line, font=rail_small_font, fill=(244, 246, 242))
                label_y += rail_small_font.size + 5
        draw_metrics(height - 106, 1450)
        occupied_ratio = 0.91

    else:
        title_width = 865
        draw_topic(72, title_width)
        title_font, title_lines = _fit_title_lines(
            draw, display_title, title_family, title_width, max_height=470
        )
        y = 156
        line_gap = max(9, round(title_font.size * 0.14))
        for index, line in enumerate(title_lines):
            draw.text(
                (left, y),
                line,
                font=title_font,
                fill=accent if index % 2 == 0 else (247, 245, 239),
                stroke_width=1,
                stroke_fill=_blend_color(background, (0, 0, 0), 0.48),
            )
            y += title_font.size + line_gap
        support_lines = _wrap_text(draw, support_text, support_font, title_width, max_lines=1)
        for line in support_lines:
            draw.text((left, y + 10), line, font=support_font, fill=secondary)
            y += support_font.size + 8
        keyword_lines = _wrap_text(draw, keyword_text, keyword_font, title_width, max_lines=2)
        keyword_y = min(y + 20, 680)
        for line in keyword_lines:
            draw.text((left, keyword_y), line, font=keyword_font, fill=(239, 242, 246))
            keyword_y += keyword_font.size + 8

        rail_left = 1040
        rail_top = 145
        draw.text((rail_left, 72), "内容脉络", font=eyebrow_font, fill=secondary)
        draw.line((rail_left + 12, rail_top, rail_left + 12, 704), fill=accent, width=3)
        for index, label in enumerate(content_spine[:4]):
            y = rail_top + index * 137
            draw.ellipse((rail_left, y, rail_left + 26, y + 26), fill=accent if index % 2 == 0 else secondary)
            draw.text((rail_left + 48, y - 5), f"{index + 1:02d}", font=_font(20, bold=True, family=body_family), fill=secondary)
            lines = _wrap_content_spine_label(draw, label, rail_font, width - rail_left - 82, max_lines=3)
            label_y = y + 28
            for line in lines:
                draw.text((rail_left + 48, label_y), line, font=rail_font, fill=(246, 246, 242))
                label_y += rail_font.size + 6
        draw_metrics(height - 106, 1450)
        occupied_ratio = 0.92

    fullness = {
        "source_coverage": 0.0,
        "occupied_ratio": occupied_ratio,
        "title_line_count": len(title_lines),
        "support_line_count": len(support_lines),
        "keyword_line_count": len(keyword_lines),
        "metric_count": len(metrics),
    }
    return canvas, title_lines, keyword_lines, fullness


def _render_local_card(
    *,
    title: str,
    description: str,
    source_path: Path | None,
    width: int,
    height: int,
    file_names: Sequence[str] = (),
    panel_lines: Sequence[str] = (),
    source_kind: str = "",
    details: Mapping[str, object] | None = None,
) -> tuple[Image.Image, dict[str, object]]:
    details = details or {}
    profile, semantic_scores, semantic_signals = _semantic_decision(title, description, file_names)
    semantic_palette, semantic_palette_reason = _semantic_palette_for_project(profile, title, description)
    background, accent, secondary = _palette(title, description, source_path, file_names)
    palette_basis, source_palette, source_color_weight = _palette_basis(source_path)
    title_family, eyebrow_family, body_family = _type_roles(profile, title)
    typography_reason = {
        "digital-tech": "项目包含 WorkBuddy/AI 办公等工具型证据，主标题使用现代可变无衬线字，突出产品与操作感",
        "digital-creator": "项目包含短视频、带货等创作型证据，主标题使用更有展示感的现代中文字体，避免普通系统黑体",
        "learning-editorial": "项目包含英语、语法和写作训练证据，主标题使用编辑型衬线字，形成教材与课程感",
        "editorial": "项目包含明确书名或人文主题，主标题使用编辑型衬线字，辅助信息使用无衬线字",
    }.get(title_family, f"根据 {profile} 项目语义选择标题与辅助字体角色")
    tags: list[str] = []
    try:
        src_dir = project_root() / "src"
        sys.path.insert(0, str(src_dir))
        from xpan_auto.telegram_formatter import build_dynamic_tags

        tags = build_dynamic_tags(title, description, file_names, max_tags=8)
    except (ImportError, OSError, ValueError):
        tags = []
    topic_text, keyword_text = _cover_labels(profile, tags)
    summary = details.get("summary") if isinstance(details.get("summary"), Mapping) else {}
    extension_counts = summary.get("extension_counts") if isinstance(summary.get("extension_counts"), Mapping) else {}
    archive_only = source_kind == "no-project-media" and bool(extension_counts) and set(extension_counts) == {".zip"}
    if archive_only:
        topic_text = "年份归档 × 数据研究"
        keyword_text = "1985–2021 · 37 个年度 ZIP 包"
        typography_reason = "项目仅包含按年份归档的数据压缩包，使用清晰的数据资料卡排版"
    display_title, title_status = _display_title_and_status(title)
    title_display_source = display_title
    display_title = _cover_title_for_profile(display_title, profile)
    if title_status:
        topic_text = f"{topic_text} · {title_status}"

    metrics = _project_metrics(details)
    if not metrics:
        metrics = [(str(line).split(" ", 1)[-1][:8] or "资料", 1) for line in panel_lines[:3]]
    metrics = list(metrics)[:3]
    content_spine, content_spine_source = _content_spine_from_project(details, file_names)
    support_text, support_source = _support_text_from_project(
        title=title,
        profile=profile,
        details=details,
        file_names=file_names,
    )
    summary_support, summary_source = _summary_support_from_project(details, metrics)
    if source_path is not None and not support_text:
        normalized_title = re.sub(r"\s+", "", display_title).casefold()
        for label in content_spine:
            normalized_label = re.sub(r"\s+", "", label).casefold()
            if normalized_label and normalized_label != normalized_title:
                support_text = label
                support_source = "project.files"
                break
    if source_kind in {"video-preview", "video-frame", "video-contact-sheet"} and summary_support:
        # Video covers already have a real content spine. Keep the support line
        # factual and concise instead of mining a stray filename fragment.
        support_text, support_source = summary_support, summary_source
    elif source_path is None and summary_support:
        support_text, support_source = summary_support, summary_source
    layout_strategy, layout_basis = _select_layout_strategy(
        title=display_title,
        source_path=source_path,
        source_kind=source_kind,
        metrics=metrics,
        support_text=support_text,
        profile=profile,
        content_spine=content_spine,
    )
    if archive_only:
        layout_strategy = "semantic-grid"
        layout_basis = dict(layout_basis)
        layout_basis["reason"] = "项目仅包含多个真实年度归档，使用高密度年份网格减少无功能空白"

    displayed_support = ""
    layout_geometry: dict[str, object] = {}
    content_regions: list[dict[str, object]] = []
    metric_presentation = "single-badge" if len(metrics) == 1 else ("compact-strip" if metrics else "none")
    if layout_strategy in {"media-editorial-split", "media-focus-split"} and source_path is not None:
        canvas, title_lines, keyword_lines, fullness, render_details = _render_media_source_card(
            source_path=source_path,
            source_kind=source_kind,
            width=width,
            height=height,
            background=background,
            accent=accent,
            secondary=secondary,
            profile=profile,
            title_family=title_family,
            eyebrow_family=eyebrow_family,
            body_family=body_family,
            topic_text=topic_text,
            display_title=display_title,
            support_text=support_text,
            keyword_text=keyword_text,
            metrics=metrics,
            content_spine=content_spine,
            variant=layout_strategy,
        )
        layout_geometry = dict(render_details.get("layout_geometry") or {})
        content_regions = list(render_details.get("content_regions") or [])
        metric_presentation = str(render_details.get("metric_presentation") or metric_presentation)
        composition = layout_strategy
        overlay_mode = "separate-zones"
        displayed_support = support_text
    elif layout_strategy == "source-dominant-poster" and source_path is not None:
        canvas, title_lines, keyword_lines, fullness = _render_source_dominant_poster(
            source_path=source_path,
            source_kind=source_kind,
            width=width,
            height=height,
            background=background,
            accent=accent,
            secondary=secondary,
            title_family=title_family,
            eyebrow_family=eyebrow_family,
            body_family=body_family,
            topic_text=topic_text,
            display_title=display_title,
            support_text=support_text,
            keyword_text=keyword_text,
            metrics=metrics,
        )
        composition = "source-dominant-poster"
        overlay_mode = "solid-stage"
        displayed_support = support_text
    elif layout_strategy in {"semantic-timeline", "semantic-grid", "semantic-guide"}:
        canvas, title_lines, keyword_lines, fullness = _render_semantic_course_map(
            width=width,
            height=height,
            background=background,
            accent=accent,
            secondary=secondary,
            profile=profile,
            title_family=title_family,
            eyebrow_family=eyebrow_family,
            body_family=body_family,
            topic_text=topic_text,
            display_title=display_title,
            support_text=support_text,
            keyword_text=keyword_text,
            metrics=metrics,
            content_spine=content_spine,
            variant=layout_strategy,
        )
        composition = layout_strategy
        overlay_mode = "none"
        displayed_support = support_text
    else:
        canvas = _draw_semantic_background(
            width=width,
            height=height,
            background=background,
            accent=accent,
            secondary=secondary,
            profile=profile,
        )
        composition = "semantic-summary"
        overlay_mode = "none"
        source_coverage = 0.0
        if source_path is not None:
            source_box = (round(width * 0.37), 54, width - 18, height - 38)
            _paste_source_blended(
                canvas,
                source_path,
                source_box,
                background=background,
                source_kind=source_kind,
            )
            composition = "asymmetric-split"
            overlay_mode = "localized-fade"
            source_coverage = round(
                ((source_box[2] - source_box[0]) * (source_box[3] - source_box[1])) / (width * height),
                3,
            )

        draw = ImageDraw.Draw(canvas)
        left = 62
        text_width = 735
        eyebrow_font = _font(29, bold=False if profile == "literary" else True, family=eyebrow_family)
        keyword_font = _font(26, bold=True, family=body_family)
        support_font = _font(31, bold=True, family=body_family)
        metric_number_font = _font(35, bold=True, family=body_family)
        metric_label_font = _font(22, bold=False, family=body_family)

        topic_line = _wrap_text(draw, topic_text, eyebrow_font, text_width - 30, max_lines=1)[0]
        pill_width = min(text_width, max(360, round(draw.textlength(topic_line, font=eyebrow_font)) + 58))
        pill_box = (left, 74, left + pill_width, 145)
        pill_fill = _blend_color(background, (0, 0, 0), 0.22)
        draw.rounded_rectangle(pill_box, radius=12, fill=pill_fill, outline=accent, width=2)
        draw.line((pill_box[0] + 18, pill_box[3], pill_box[2] - 18, pill_box[3]), fill=secondary, width=3)
        draw.text((left + 25, 91), topic_line, font=eyebrow_font, fill=(244, 239, 228))

        title_font, title_lines = _fit_title_lines(
            draw,
            display_title,
            title_family,
            text_width,
            max_height=430,
        )
        title_colors = (accent, (247, 246, 241), secondary, (247, 246, 241))
        line_gap = max(10, round(title_font.size * 0.16))
        y = 184
        for index, line in enumerate(title_lines):
            draw.text(
                (left, y),
                line,
                font=title_font,
                fill=title_colors[index % len(title_colors)],
                stroke_width=1,
                stroke_fill=_blend_color(background, (0, 0, 0), 0.45),
            )
            y += title_font.size + line_gap

        support_lines = _wrap_text(draw, support_text, support_font, text_width - 18, max_lines=2) if support_text else []
        support_y = y + 4
        for line in support_lines:
            draw.text((left, support_y), line, font=support_font, fill=secondary)
            support_y += support_font.size + 7
        if support_lines:
            displayed_support = support_text
            y = support_y

        separator_y = min(max(y + 14, 474), 684)
        draw.line((left, separator_y, left + text_width - 42, separator_y), fill=secondary, width=2)
        draw.ellipse(
            (left + text_width - 36, separator_y - 5, left + text_width - 26, separator_y + 5),
            fill=accent,
        )
        keyword_lines = _wrap_text(draw, keyword_text, keyword_font, text_width - 24, max_lines=2)
        keyword_y = separator_y + 22
        for line in keyword_lines:
            draw.text((left, keyword_y), line, font=keyword_font, fill=accent)
            keyword_y += keyword_font.size + 8

        metric_top = height - 146
        metric_box = (left, metric_top, left + text_width - 18, height - 46)
        metric_fill = _blend_color(background, (0, 0, 0), 0.30)
        draw.rounded_rectangle(metric_box, radius=14, fill=metric_fill, outline=accent, width=2)
        if metrics:
            segment_width = (metric_box[2] - metric_box[0]) / len(metrics)
            for index, (label, count) in enumerate(metrics):
                segment_left = round(metric_box[0] + index * segment_width)
                if index:
                    draw.line(
                        (segment_left, metric_box[1] + 19, segment_left, metric_box[3] - 19),
                        fill=_blend_color(background, secondary, 0.58),
                        width=1,
                    )
                number_text = str(count)
                draw.text(
                    (segment_left + 22, metric_top + 25),
                    number_text,
                    font=metric_number_font,
                    fill=secondary if index % 2 else accent,
                )
                number_width = draw.textlength(number_text, font=metric_number_font)
                draw.text(
                    (segment_left + 31 + number_width, metric_top + 36),
                    label,
                    font=metric_label_font,
                    fill=(238, 240, 242),
                )

        if source_path is None:
            visual_left = round(width * 0.58)
            for index, (label, count) in enumerate(metrics or (("资料", 1),)):
                radius = 112 - index * 16
                center_x = visual_left + index * 190
                center_y = 350 + (index % 2) * 150
                draw.ellipse(
                    (center_x - radius, center_y - radius, center_x + radius, center_y + radius),
                    outline=accent if index % 2 == 0 else secondary,
                    width=4,
                )
                draw.text((center_x - 34, center_y - 44), str(count), font=metric_number_font, fill=(245, 246, 248))
                draw.text((center_x - 46, center_y + 14), label, font=metric_label_font, fill=accent)

        fullness = {
            "source_coverage": source_coverage,
            "occupied_ratio": 0.86 if source_path is not None else 0.78,
            "title_line_count": len(title_lines),
            "support_line_count": len(support_lines),
            "keyword_line_count": len(keyword_lines),
            "metric_count": len(metrics),
        }

    information_tiers = ["topic", "title"]
    if displayed_support:
        information_tiers.append("support")
    information_tiers.extend(("keywords", "metrics"))
    design_metadata: dict[str, object] = {
        "visual_profile": profile,
        "composition": composition,
        "layout_strategy": layout_strategy,
        "layout_basis": layout_basis,
        "fullness": fullness,
        "overlay_mode": overlay_mode,
        "layout_geometry": layout_geometry,
        "metric_presentation": metric_presentation,
        "content_regions": content_regions,
        "information_tiers": information_tiers,
        "topic_text": topic_text,
        "keyword_text": keyword_text,
        "title_display": display_title,
        "title_display_source": title_display_source,
        "title_display_basis": (
            "从真实项目标题提取核心课程名，压缩交付序号或宣传性副标题以保留大字号可读性"
            if display_title != title_display_source
            else "完整显示清洗后的项目标题"
        ),
        "title_lines": title_lines,
        "support_text": displayed_support,
        "support_source": support_source if displayed_support else "",
        "content_spine": content_spine,
        "content_spine_source": content_spine_source if content_spine else "",
        "summary_variant": layout_strategy if source_path is None else "",
        "metrics": [{"label": label, "count": count} for label, count in metrics],
        "semantic_basis": {
            "selected_profile": profile,
            "scores": semantic_scores,
            "matched_signals": semantic_signals,
        },
        "typography_basis": {
            "title_family": title_family,
            "eyebrow_family": eyebrow_family,
            "body_family": body_family,
            "reason": typography_reason,
            "title_size_px": layout_geometry.get("title_font_size_px"),
            "title_line_gap_px": layout_geometry.get("title_line_gap_px"),
        },
        "palette": {
            "background": _hex_color(background),
            "accent": _hex_color(accent),
            "secondary": _hex_color(secondary),
            "basis": palette_basis,
            "source_weight": source_color_weight,
            "semantic_reason": semantic_palette_reason,
            "semantic_palette": {
                "background": _hex_color(semantic_palette[0]),
                "accent": _hex_color(semantic_palette[1]),
                "secondary": _hex_color(semantic_palette[2]),
            },
            "source_palette": (
                {
                    "background": _hex_color(source_palette[0]),
                    "accent": _hex_color(source_palette[1]),
                    "secondary": _hex_color(source_palette[2]),
                }
                if source_palette is not None
                else None
            ),
        },
    }
    return canvas, design_metadata


def _summary_panel_lines(details: dict[str, object], file_names: Sequence[str]) -> list[str]:
    summary = details.get("summary") if isinstance(details, dict) else None
    summary = summary if isinstance(summary, dict) else {}
    lines: list[str] = []
    file_count = int(summary.get("file_count") or 0)
    folder_count = int(summary.get("folder_count") or 0)
    if file_count:
        lines.append(f"{file_count} 个文件")
    if folder_count:
        lines.append(f"{folder_count} 个文件夹")
    extension_counts = summary.get("extension_counts")
    if isinstance(extension_counts, dict):
        for extension, count in list(extension_counts.items())[:2]:
            lines.append(f"{str(extension).upper()} · {int(count)} 份")
    if not lines:
        lines.extend(str(name)[:22] for name in file_names[:2] if str(name).strip())
    return lines[:4]


def _load_details(path: Path | None) -> tuple[dict[str, object], list[str]]:
    if path is None:
        return {}, []
    if not path.is_file():
        raise RuntimeError(f"Project details file not found: {path}")
    try:
        details = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Project details JSON is invalid: {path}") from exc
    if not isinstance(details, dict):
        raise RuntimeError(f"Project details JSON must be an object: {path}")

    src_dir = project_root() / "src"
    sys.path.insert(0, str(src_dir))
    from xpan_auto.telegram_formatter import detail_file_names

    names = detail_file_names(details)
    return details, names


IMAGEGEN_REVIEW_CHECKS = (
    "subject_relevant",
    "palette_compliant",
    "text_readable",
    "uncluttered_composition",
    "no_fabricated_content",
)


def _evidence_text(*values: object) -> str:
    return re.sub(r"[\W_]+", "", " ".join(str(value or "") for value in values)).casefold()


def _load_imagegen_review(
    path: Path | None,
    *,
    title: str,
    description: str,
    file_names: Sequence[str],
) -> dict[str, object]:
    if path is None or not path.is_file():
        raise RuntimeError("使用 --generated-image 时必须提供 --generated-review 视觉验收记录")
    try:
        review = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ImageGen visual review JSON is invalid: {path}") from exc
    if not isinstance(review, dict):
        raise RuntimeError("ImageGen visual review must be a JSON object")
    checks = review.get("checks")
    if review.get("tool") != "imagegen" or review.get("prompt_contract") != "factual-social-cover-v1":
        raise RuntimeError("ImageGen visual review is missing the required tool or prompt contract")
    if not isinstance(checks, dict) or not all(checks.get(name) is True for name in IMAGEGEN_REVIEW_CHECKS):
        raise RuntimeError("ImageGen visual review did not pass every required beauty and factual-content check")
    if not str(review.get("prompt") or "").strip():
        raise RuntimeError("ImageGen visual review must preserve the generation prompt")
    if not all(str(review.get(key) or "").strip() for key in ("visual_direction", "palette_reason")):
        raise RuntimeError("ImageGen visual review must record a project-specific visual direction and palette reason")

    displayed_title = str(review.get("displayed_title") or "").strip()
    anchors = review.get("content_anchors")
    if not displayed_title or not isinstance(anchors, list) or not 2 <= len(anchors) <= 4:
        raise RuntimeError("ImageGen visual review must record one displayed title and 2-4 content anchors")
    evidence = _evidence_text(title, description, *file_names)
    if _evidence_text(displayed_title) not in evidence:
        raise RuntimeError("ImageGen displayed title is not supported by the project facts")
    unsupported = [str(anchor) for anchor in anchors if not str(anchor).strip() or _evidence_text(anchor) not in evidence]
    if unsupported:
        raise RuntimeError(f"ImageGen content anchors are not supported by the project facts: {unsupported}")
    return review


def _imagegen_design_metadata(
    *,
    title: str,
    description: str,
    file_names: Sequence[str],
    output: Path,
    source_kind: str,
    review: Mapping[str, object],
) -> dict[str, object]:
    profile, scores, signals = _semantic_decision(title, description, file_names)
    rendered_palette = _palette_from_image(output)
    if rendered_palette is None:
        raise RuntimeError("ImageGen output palette could not be measured from the generated image")
    displayed_title = str(review.get("displayed_title") or "").strip()
    anchors = [str(value).strip() for value in review.get("content_anchors", ()) if str(value).strip()]
    title_units = _title_visual_units(displayed_title)
    title_class = "short" if title_units <= 10 else "medium" if title_units <= 18 else "long"
    return {
        "visual_profile": profile,
        "composition": "image-gen",
        "layout_strategy": "image-gen",
        "layout_basis": {
            "title_units": title_units,
            "title_length_class": title_class,
            "source_kind": source_kind or "no-project-media",
            "source_aspect_ratio": None,
            "metric_count": 0,
            "reason": "无真实预览素材，使用基于项目事实的 ImageGen 视觉封面",
        },
        "fullness": {
            "source_coverage": 1.0,
            "occupied_ratio": 0.0,
            "title_line_count": 1,
            "support_line_count": 1,
            "keyword_line_count": 1,
            "metric_count": 0,
        },
        "information_tiers": ["title", "keywords", "visual"],
        "title_display": displayed_title,
        "title_display_source": title,
        "title_display_basis": "依据真实项目标题压缩为适合社交封面的核心课程名",
        "content_anchors": anchors,
        "metrics": [],
        "semantic_basis": {
            "selected_profile": profile,
            "scores": scores,
            "matched_signals": signals,
        },
        "palette": {
            "background": _hex_color(rendered_palette[0]),
            "accent": _hex_color(rendered_palette[1]),
            "secondary": _hex_color(rendered_palette[2]),
            "basis": "imagegen-project-derived",
            "semantic_reason": str(review.get("palette_reason") or "").strip(),
            "semantic_palette": {
                "background": _hex_color(rendered_palette[0]),
                "accent": _hex_color(rendered_palette[1]),
                "secondary": _hex_color(rendered_palette[2]),
            },
        },
        "generation": dict(review),
    }


def _copy_generated_image(source: Path, output: Path) -> None:
    if not source.is_file():
        raise RuntimeError(f"Generated image not found: {source}")
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        _save_png_atomically(image, output)


def _document_inventory_count(details: Mapping[str, object]) -> int:
    summary = details.get("summary") if isinstance(details, Mapping) else None
    summary = summary if isinstance(summary, Mapping) else {}
    extension_counts = summary.get("extension_counts")
    extension_counts = extension_counts if isinstance(extension_counts, Mapping) else {}
    return sum(
        max(0, int(count or 0))
        for extension, count in extension_counts.items()
        if str(extension).lower() in DOCUMENT_COVER_EXTENSIONS
    )


def _uses_document_cover(source_kind: str, details: Mapping[str, object]) -> bool:
    if source_kind == "document-preview":
        return True
    if source_kind != "existing-local" or _document_inventory_count(details) <= 0:
        return False

    summary = details.get("summary") if isinstance(details, Mapping) else None
    summary = summary if isinstance(summary, Mapping) else {}
    extension_counts = summary.get("extension_counts")
    extension_counts = extension_counts if isinstance(extension_counts, Mapping) else {}
    visual_count = sum(
        max(0, int(count or 0))
        for extension, count in extension_counts.items()
        if str(extension).lower() in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
    )
    return visual_count == 0


def _render_document_cover_adaptive(
    source_path: Path,
    *,
    source_kind: str,
    details: Mapping[str, object],
) -> tuple[Image.Image, dict[str, object]]:
    """Fit one real document preview to 16:9 or 9:16 without text overlays."""
    with Image.open(source_path) as opened:
        source = ImageOps.exif_transpose(opened).convert("RGB")

    source_aspect_ratio = source.width / max(1, source.height)
    landscape = source_aspect_ratio >= DOCUMENT_LANDSCAPE_ASPECT_THRESHOLD
    width, height = DOCUMENT_COVER_LANDSCAPE_SIZE if landscape else DOCUMENT_COVER_PORTRAIT_SIZE
    orientation = "landscape" if landscape else "portrait"
    aspect_ratio = "16:9" if landscape else "9:16"

    background = ImageOps.fit(source, (width, height), method=Image.Resampling.LANCZOS)
    background = background.filter(ImageFilter.GaussianBlur(radius=36))
    neutral = Image.new("RGB", (width, height), (236, 239, 243))
    canvas = Image.blend(background, neutral, 0.38)

    padding = 36
    preview = ImageOps.contain(
        source,
        (width - padding * 2, height - padding * 2),
        method=Image.Resampling.LANCZOS,
    )
    left = (width - preview.width) // 2
    top = (height - preview.height) // 2

    shadow_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    shadow = ImageDraw.Draw(shadow_layer)
    shadow.rectangle(
        (left + 8, top + 10, left + preview.width + 8, top + preview.height + 10),
        fill=(0, 0, 0, 96),
    )
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=16))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), shadow_layer).convert("RGB")
    canvas.paste(preview, (left, top))

    source_coverage = (preview.width * preview.height) / max(1, width * height)
    design_metadata: dict[str, object] = {
        "composition": "document-cover-adaptive",
        "layout_strategy": "document-cover-adaptive",
        "source_kind": source_kind,
        "document_inventory_count": _document_inventory_count(details),
        "original_size": [source.width, source.height],
        "source_aspect_ratio": round(source_aspect_ratio, 4),
        "canvas_size": [width, height],
        "orientation": orientation,
        "aspect_ratio": aspect_ratio,
        "orientation_selection_basis": f"source_aspect_ratio>={DOCUMENT_LANDSCAPE_ASPECT_THRESHOLD:.2f}",
        "content_box": [left, top, left + preview.width, top + preview.height],
        "background_mode": "blurred-source-fill",
        "overlay_text": False,
        "fullness": {
            "source_coverage": round(source_coverage, 4),
            "title_line_count": 0,
            "support_line_count": 0,
            "keyword_line_count": 0,
            "metric_count": 0,
        },
    }
    return canvas, design_metadata


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


def _write_metadata(
    *,
    path: Path,
    row_index: int | None,
    title: str,
    description: str,
    output: Path,
    source: Path | None,
    details: Path | None,
    action: str,
    method: str,
    quality_version: int,
    layout: str,
    source_render_mode: str | None,
    design_metadata: Mapping[str, object] | None,
    font_fallback: bool,
    font_files: Sequence[str],
    placeholder_texts: Sequence[str],
) -> None:
    payload = {
        "row_index": row_index,
        "title": title,
        "description": description,
        "image": str(output),
        "source_image": str(source) if source else None,
        "details_file": str(details) if details else None,
        "action": action,
        "method": method,
        "quality_version": quality_version,
        "layout": layout,
        "source_render_mode": source_render_mode,
        "design": dict(design_metadata or {}),
        "font_fallback": font_fallback,
        "font_files": list(dict.fromkeys(font_files)),
        "placeholder_texts": list(placeholder_texts),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    if args.row_index is not None and args.row_index < 1:
        raise RuntimeError("--row-index must be at least 1")
    if args.width < 320 or args.height < 240:
        raise RuntimeError("Cover dimensions are too small")

    if args.asset_dir is not None:
        asset_dir = resolve_path(args.asset_dir)
        row_index = args.row_index
    else:
        asset_root = resolve_path(args.asset_root)
        row_index = args.row_index
        asset_dir = asset_root / f"{row_index:04d}"
    assert asset_dir is not None
    asset_dir.mkdir(parents=True, exist_ok=True)

    output = asset_dir / args.output_name
    metadata = asset_dir / args.metadata_name
    details_path = resolve_path(args.details_file) if args.details_file else asset_dir / "telegram-project-details.json"
    if not details_path.is_file():
        details_path = None
    details, detail_names = _load_details(details_path)
    description = args.description
    if details:
        src_dir = project_root() / "src"
        sys.path.insert(0, str(src_dir))
        from xpan_auto.telegram_formatter import build_project_description, is_placeholder_description

        if is_placeholder_description(description):
            description = build_project_description(args.title, details)
    if output.is_file() and output.stat().st_size > 0 and not args.force_regenerate:
        if not metadata.is_file():
            _write_metadata(
                path=metadata,
                row_index=row_index,
                title=args.title,
                description=description,
                output=output,
                source=None,
                details=details_path,
                action="reused",
                method="existing-cover",
                quality_version=0,
                layout="legacy-reused",
                source_render_mode=None,
                design_metadata=None,
                font_fallback=True,
                font_files=(),
                placeholder_texts=("legacy-cover",),
            )
        print(json.dumps({"action": "reused", "image": str(output), "metadata": str(metadata)}, ensure_ascii=False))
        return 0

    generated = resolve_path(args.generated_image)
    generated_review_path = resolve_path(args.generated_review)
    source = _find_source(asset_dir, args.source_image, output)
    media = details.get("media") if isinstance(details.get("media"), dict) else {}
    source_kind = str(media.get("kind") or "")
    summary = details.get("summary") if isinstance(details.get("summary"), dict) else {}
    extension_counts = summary.get("extension_counts") if isinstance(summary.get("extension_counts"), dict) else {}
    previewable_count = sum(
        max(0, int(count or 0))
        for extension, count in extension_counts.items()
        if str(extension).lower() in PREVIEWABLE_EXTENSIONS
    )
    if source_kind == "media-preview-required":
        raise RuntimeError("项目存在可预览文件，但媒体预览尚未成功；禁止生成纯文字目录封面")
    if generated is None and source is None and previewable_count:
        raise RuntimeError(
            f"项目清单中有 {previewable_count} 个可预览文件，但没有取得真实预览；禁止生成纯文字目录封面"
        )
    if generated is None and source is None:
        raise RuntimeError("项目没有真实预览素材，必须先调用 imagegen 生成封面并完成视觉验收")
    document_cover = generated is None and source is not None and _uses_document_cover(source_kind, details)
    source_render_mode = None if generated is not None else (
        "fit-document-page" if document_cover else (
            "fit-media" if source is not None else None
        )
    )
    if generated is not None:
        review = _load_imagegen_review(
            generated_review_path,
            title=args.title,
            description=description,
            file_names=detail_names,
        )
        _copy_generated_image(generated, output)
        method = "image-gen-output"
        layout = "image-gen"
        font_files: Sequence[str] = ()
        design_metadata = _imagegen_design_metadata(
            title=args.title,
            description=description,
            file_names=detail_names,
            output=output,
            source_kind=source_kind,
            review=review,
        )
        with Image.open(output) as rendered:
            output_dimensions = rendered.size
    elif document_cover:
        assert source is not None
        image, design_metadata = _render_document_cover_adaptive(
            source,
            source_kind=source_kind,
            details=details,
        )
        _save_png_atomically(image, output)
        method = "document-cover-adaptive"
        layout = "document-cover-adaptive"
        font_files = ()
        output_dimensions = image.size
    else:
        RENDER_FONT_PATHS.clear()
        image, design_metadata = _render_local_card(
            title=args.title,
            description=description,
            source_path=source,
            file_names=detail_names,
            panel_lines=_summary_panel_lines(details, detail_names),
            source_kind=source_kind,
            details=details,
            width=args.width,
            height=args.height,
        )
        _save_png_atomically(image, output)
        method = "local-information-card"
        layout = "source-image" if source is not None else "text-only-summary"
        font_files = tuple(RENDER_FONT_PATHS)
        output_dimensions = image.size

    src_dir = project_root() / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    from xpan_auto.telegram_quality import measure_cover_activity

    measured_activity = measure_cover_activity(output)
    design_metadata = dict(design_metadata)
    fullness = dict(design_metadata.get("fullness") or {})
    fullness.update(
        {
            "occupied_ratio": measured_activity["activity_ratio"],
            "rendered_activity_ratio": measured_activity["activity_ratio"],
            "rendered_left_activity_ratio": measured_activity["left_activity_ratio"],
            "rendered_right_activity_ratio": measured_activity["right_activity_ratio"],
            "row_activity_ratios": measured_activity["row_activity_ratios"],
            "consecutive_sparse_bands": measured_activity["consecutive_sparse_bands"],
        }
    )
    design_metadata["fullness"] = fullness

    metadata_source = generated if generated is not None else source
    _write_metadata(
        path=metadata,
        row_index=row_index,
        title=args.title,
        description=description,
        output=output,
        source=metadata_source,
        details=details_path,
        action="created",
        method=method,
        quality_version=TELEGRAM_ASSET_QUALITY_VERSION,
        layout=layout,
        source_render_mode=source_render_mode,
        design_metadata=design_metadata,
        font_fallback=False,
        font_files=font_files,
        placeholder_texts=(),
    )
    print(
        json.dumps(
            {
                "action": "created",
                "image": str(output),
                "metadata": str(metadata),
                "method": method,
                "source_image": str(metadata_source) if metadata_source else None,
                "dimensions": list(output_dimensions),
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
