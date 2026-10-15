"""Require source-backed editorial review before a Telegram/X publishing run."""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from .telegram_quality import _HTMLAudit
from .telegram_formatter import TELEGRAM_X_URL, TELEGRAM_CHANNEL_URL


REVIEW_VERSION = 1
REVIEW_FILE = "copy-review.json"
STYLE_LABELS = frozenset({
    "极短资源型", "视频标题直给型", "指定人群型", "疑问／观点型",
    "个人发现型", "亲手试用型", "怀疑—验证型", "痛点＋判断型",
    "反差／类比型", "大白话拆步骤型", "工具流水线型",
    "小故事／书评型", "来源数字案例型", "清单／知识型",
    "稀缺背景型", "媒体优先型",
})
CATEGORIES = frozenset({"commercial", "tool", "course", "reference", "media", "other"})
GENERIC_KEY_PHRASES = frozenset({"资料", "课程", "学习", "内容", "工具", "方法", "资源", "视频", "赚钱"})
COMMERCIAL_TITLE_SIGNALS = (
    "赚钱", "变现", "收益", "稿费", "接单", "带货", "付费", "收入",
    "掘金", "副业", "搞钱", "佣金", "生财",
)
SEED_MARKER = "【待审初稿】"
BOILERPLATE_MARKERS = (
    SEED_MARKER,
    "这套资料最让人心动的地方", "本资料围绕", "适合相关学习者按主题学习和查阅",
    "它不是看一遍就放着的资料", "这份真的值得认真看",
    "#学习资料 #资源分享 #实战教程 #技能提升",
)
_TAG_RE = re.compile(r"(?<!\S)#[^\s#]+")
_QUARK_RE = re.compile(r"https://pan\.quark\.cn/s/[A-Za-z0-9]+")


class CopyReviewError(RuntimeError):
    """The reviewed copy is absent, stale, or fails its publishing gate."""


def _read_text(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise CopyReviewError(f"文案审阅缺少可读文件：{path}") from exc
    if not text.strip() or "\ufffd" in text or "\x00" in text:
        raise CopyReviewError(f"文案审阅文件为空或编码异常：{path}")
    return text


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise CopyReviewError(f"文案审阅缺少文件：{path}") from exc


def _load_details(path: Path) -> dict[str, object]:
    try:
        details = json.loads(_read_text(path))
    except json.JSONDecodeError as exc:
        raise CopyReviewError(f"项目目录 JSON 无效：{path}") from exc
    if not isinstance(details, dict) or not isinstance(details.get("items"), list) or not details["items"]:
        raise CopyReviewError("文案审阅需要完整的项目文件树")
    summary = details.get("summary")
    if isinstance(summary, Mapping) and summary.get("truncated") is True:
        raise CopyReviewError("项目文件树已截断，不能据此审阅文案")
    return details


def _opening(text: str, link: str) -> str:
    body = text.replace(link, "")
    body = re.sub(r"\s+", "", body)
    return body[:10]


def _layout(text: str, link: str) -> str:
    body = text.replace(link, "").strip()
    if re.search(r"(?m)^\s*(?:[①-⑩]|[1-9][.、])", body):
        return "numbered"
    if "→" in body or "➡" in body:
        return "flow"
    blocks = [block for block in re.split(r"\n\s*\n", body) if block.strip()]
    return f"blocks-{len(blocks)}"


def _check_review(
    asset_dir: Path,
    review: Mapping[str, object],
    *,
    serial: int,
    title: str,
    description: str,
    link: str,
) -> dict[str, str]:
    details_path = asset_dir / "telegram-project-details.json"
    caption_path = asset_dir / "telegram-caption.html"
    x_path = asset_dir / "x.txt"
    details = _load_details(details_path)
    caption = _read_text(caption_path)
    x_text = _read_text(x_path)
    if int(details.get("row_index") or 0) != serial or str(details.get("title") or "").strip() != title:
        raise CopyReviewError("文案审阅的项目序号或标题与完整目录不一致")
    if str(details.get("source_share_link") or "").strip() != link:
        raise CopyReviewError("文案审阅的夸克链接与完整目录不一致")
    if review.get("version") != REVIEW_VERSION or review.get("serial") != serial:
        raise CopyReviewError("文案审阅记录版本或序号不正确")
    if review.get("title") != title or review.get("source_share_link") != link:
        raise CopyReviewError("文案审阅记录与当前项目身份不一致")
    if review.get("source_description_sha256") != hashlib.sha256(description.encode("utf-8")).hexdigest():
        raise CopyReviewError("项目介绍在审阅后发生变化；请重新核对文案")

    hashes = review.get("sha256")
    expected = {
        "details": _sha256(details_path),
        "telegram": _sha256(caption_path),
        "x": _sha256(x_path),
    }
    if not isinstance(hashes, Mapping) or any(hashes.get(key) != value for key, value in expected.items()):
        raise CopyReviewError("文案或目录在审阅后发生变化；请重新审阅并记录")

    style = str(review.get("style_label") or "")
    category = str(review.get("category") or "")
    angle = str(review.get("primary_angle") or "").strip()
    key_phrase = str(review.get("key_phrase") or "").strip()
    source_note = str(review.get("source_note") or "").strip()
    if style not in STYLE_LABELS or category not in CATEGORIES or len(angle) < 6 or len(source_note) < 8:
        raise CopyReviewError("文案审阅缺少有效的题材、主角度、来源判断或 X 风格")

    evidence = review.get("source_evidence")
    item_values = {
        str(item.get(key)).strip()
        for item in details["items"] if isinstance(item, Mapping)
        for key in ("name", "path") if item.get(key)
    }
    if not isinstance(evidence, list) or not evidence or any(
        not isinstance(value, str) or value.strip() not in item_values for value in evidence
    ):
        raise CopyReviewError("文案审阅必须引用完整目录中真实存在的文件名或路径")
    source_text = " ".join((title, description, *item_values))
    if any(signal in source_text for signal in COMMERCIAL_TITLE_SIGNALS) and category != "commercial":
        raise CopyReviewError("标题、介绍或目录涉及变现，必须核对商业路径并按 commercial 审阅")

    if category == "commercial":
        route = review.get("commercial_route")
        if not isinstance(route, Mapping) or route.get("support") not in {"supported", "partial", "unclear"}:
            raise CopyReviewError("商业资料必须标明变现路径的证据程度")
        if any(len(str(route.get(key) or "").strip()) < 2 for key in ("offer", "audience", "revenue")):
            raise CopyReviewError("商业资料必须说明做什么、给谁、收入来自哪里；不明确时写明未证实")

    visible_caption = html.unescape(re.sub(r"<[^>]+>", "", caption))
    html_audit = _HTMLAudit()
    html_audit.feed(caption)
    html_audit.close()
    if html_audit.errors or html_audit.stack:
        raise CopyReviewError("Telegram 文案 HTML 结构不完整")
    if len(key_phrase) < 3 or key_phrase in GENERIC_KEY_PHRASES or key_phrase not in visible_caption or key_phrase not in x_text:
        raise CopyReviewError("Telegram 与 X 必须共同写明审阅记录中的项目关键点")
    if title not in visible_caption or link not in visible_caption:
        raise CopyReviewError("Telegram 文案缺少当前标题或真实夸克链接")
    if TELEGRAM_X_URL not in caption or TELEGRAM_CHANNEL_URL not in caption:
        raise CopyReviewError("Telegram 文案缺少固定双入口")
    if len(caption) > 1024 or not 2 <= len(_TAG_RE.findall(visible_caption)) <= 8:
        raise CopyReviewError("Telegram 文案长度或标签数量不符合发布要求")
    x_lines = x_text.splitlines()
    if (
        x_text.count(link) != 1
        or _QUARK_RE.findall(x_text) != [link]
        or len(x_lines) < 3
        or x_lines[-1] != link
        or x_lines[-2].strip()
    ):
        raise CopyReviewError("X 文案必须在空行后以独立的真实夸克链接作为末行，且只出现一次")
    if len(_TAG_RE.findall(x_text)) > 2 or TELEGRAM_CHANNEL_URL in x_text:
        raise CopyReviewError("X 文案仍有标签堆砌或 Telegram 固定尾句")
    if any(marker in caption or marker in x_text for marker in BOILERPLATE_MARKERS):
        raise CopyReviewError("文案仍含旧模板套话，须根据项目事实重新写")

    return {"serial": str(serial), "style_label": style, "opening": _opening(x_text, link), "layout": _layout(x_text, link)}


def validate_review(asset_dir: Path, *, serial: int, title: str, description: str, link: str) -> dict[str, str]:
    path = asset_dir / REVIEW_FILE
    try:
        review = json.loads(_read_text(path))
    except json.JSONDecodeError as exc:
        raise CopyReviewError(f"文案审阅 JSON 无效：{path}") from exc
    if not isinstance(review, Mapping):
        raise CopyReviewError("文案审阅记录必须是 JSON 对象")
    return _check_review(asset_dir, review, serial=serial, title=title, description=description, link=link)


def record_review(
    asset_dir: Path,
    *,
    category: str,
    style_label: str,
    primary_angle: str,
    key_phrase: str,
    description: str,
    source_note: str,
    source_evidence: Sequence[str],
    offer: str = "",
    audience: str = "",
    revenue: str = "",
    support: str = "",
) -> dict[str, str]:
    details_path = asset_dir / "telegram-project-details.json"
    details = _load_details(details_path)
    serial = int(details.get("row_index") or 0)
    title = str(details.get("title") or "").strip()
    link = str(details.get("source_share_link") or "").strip()
    review: dict[str, object] = {
        "version": REVIEW_VERSION,
        "serial": serial,
        "title": title,
        "source_share_link": link,
        "source_description_sha256": hashlib.sha256(description.encode("utf-8")).hexdigest(),
        "category": category,
        "style_label": style_label,
        "primary_angle": primary_angle,
        "key_phrase": key_phrase,
        "source_note": source_note,
        "source_evidence": list(source_evidence),
        "sha256": {
            "details": _sha256(details_path),
            "telegram": _sha256(asset_dir / "telegram-caption.html"),
            "x": _sha256(asset_dir / "x.txt"),
        },
    }
    if category == "commercial":
        review["commercial_route"] = {
            "offer": offer, "audience": audience, "revenue": revenue, "support": support,
        }
    result = _check_review(asset_dir, review, serial=serial, title=title, description=description, link=link)
    path = asset_dir / REVIEW_FILE
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return result


def validate_review_batch(reviews: Sequence[Mapping[str, str]]) -> None:
    if not reviews:
        return
    for left, right in zip(reviews, reviews[1:]):
        if left["style_label"] == right["style_label"]:
            raise CopyReviewError("相邻两条 X 文案采用了相同主风格")
        if left["opening"] == right["opening"]:
            raise CopyReviewError("相邻两条 X 文案使用了相同开头")
    for start in range(max(0, len(reviews) - 7)):
        window = reviews[start:start + 8]
        if len({item["style_label"] for item in window}) < 6:
            raise CopyReviewError("连续八条 X 文案至少需要六种主风格")
        if len({item["opening"] for item in window}) < 8:
            raise CopyReviewError("连续八条 X 文案的前十个可见字符重复")
        if len({item["layout"] for item in window}) < 3:
            raise CopyReviewError("连续八条 X 文案至少需要三种版式")
        if sum(item["style_label"] == "个人发现型" for item in window) > 2:
            raise CopyReviewError("连续八条 X 文案个人发现型开头不得超过两条")
