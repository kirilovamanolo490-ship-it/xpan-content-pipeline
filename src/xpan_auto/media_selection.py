"""Deterministic selection of the first publishable video in a project tree."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping


_CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CHINESE_UNITS = {"十": 10, "百": 100, "千": 1000}
_LESSON_UNITS = "天节讲课章条篇部集阶段"
_STRUCTURE_NUMBER = r"[0-9零〇一二两三四五六七八九十百千]+"


def _parse_chinese_number(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    if not value or any(char not in _CHINESE_DIGITS and char not in _CHINESE_UNITS for char in value):
        return None
    total = 0
    current = 0
    for char in value:
        if char in _CHINESE_UNITS:
            unit = _CHINESE_UNITS[char]
            total += (current or 1) * unit
            current = 0
        else:
            current = current * 10 + _CHINESE_DIGITS[char]
    result = total + current
    return result if result > 0 else None


def extract_sequence_marker(name: str) -> int | None:
    """Extract an explicit lesson/sequence number from a filename only.

    Directory numbers such as ``62-72`` are intentionally ignored. A marker
    must be at the beginning of the filename, so dates and unrelated numbers
    later in a title cannot decide the first video.
    """

    stem = Path(str(name or "")).stem
    compact = re.sub(r"\s+", "", stem)
    patterns = (
        rf"^第(?P<num>\d{{1,3}})(?=[{_LESSON_UNITS}])",
        rf"^第(?P<num>[零〇一二三四五六七八九十百千两]+)(?=[{_LESSON_UNITS}])",
        r"^(?P<num>0\d{1,2})(?=\D)",
        r"^(?P<num>\d{1,3})(?=第)",
        rf"^(?P<num>\d{{1,3}})(?=[{_LESSON_UNITS}])",
        r"^(?P<num>\d{1,3})(?=\s|[._、:：\-]|$)",
        r"^(?P<num>[零〇一二三四五六七八九十百千两]+)(?=[、.．:：\-])",
    )
    for pattern in patterns:
        match = re.search(pattern, stem if "\\s" in pattern else compact)
        if match:
            number = _parse_chinese_number(match.group("num"))
            if number is not None:
                return number
    for pattern in (
        rf"第(?P<num>\d{{1,3}})(?=[{_LESSON_UNITS}])",
        rf"第(?P<num>[零〇一二三四五六七八九十百千两]+)(?=[{_LESSON_UNITS}])",
    ):
        match = re.search(pattern, compact)
        if match:
            number = _parse_chinese_number(match.group("num"))
            if number is not None:
                return number
    return None


def _extract_sequence_key(name: str) -> tuple[int, ...] | None:
    """Return a sortable explicit sequence, including decimal or hyphenated parts."""

    stem = Path(str(name or "")).stem
    compact = re.sub(r"\s+", "", stem)
    # Dates followed by a presenter's name are recording dates, not lessons.
    if re.match(r"^(?:\d{2}[.．]\d{1,2}[.．]\d{1,2}|\d{1,2}[.．]\d{1,2})[^.．\d]{1,12}老师", compact):
        return None
    staged_lesson = re.match(
        rf"^第(?P<stage>{_STRUCTURE_NUMBER})阶段[-_、.．](?P<lesson>\d{{1,3}})(?=\D|$)",
        compact,
    )
    if staged_lesson:
        stage = _parse_chinese_number(staged_lesson.group("stage"))
        if stage is not None:
            return (stage, int(staged_lesson.group("lesson")))
    if re.match(rf"^第{_STRUCTURE_NUMBER}阶段", compact):
        return None
    labelled_lesson = re.match(
        rf"^第(?P<lesson>{_STRUCTURE_NUMBER})[{_LESSON_UNITS}][-_、.．](?P<part>\d{{1,3}})(?=\D|$)",
        compact,
    )
    if labelled_lesson:
        lesson = _parse_chinese_number(labelled_lesson.group("lesson"))
        if lesson is not None:
            return (lesson, int(labelled_lesson.group("part")))
    task_prefix = re.match(r"^任务(?P<num>\d{1,3})(?=[：:、.．-]|$)", compact)
    if task_prefix:
        return (int(task_prefix.group("num")),)
    bracketed = re.match(
        r"^[\[【(（](?P<parts>\d{1,3}(?:[.．]\d{1,3}){0,2})[\]】)）]",
        compact,
    )
    if bracketed:
        return tuple(int(part) for part in re.split(r"[.．]", bracketed.group("parts")))
    labelled_prefix = re.match(
        r"^[\[【(（][^\]】)）]{1,30}[\]】)）](?P<rest>.+)$",
        compact,
    )
    if labelled_prefix:
        prefixed_sequence = _extract_sequence_key(labelled_prefix.group("rest"))
        if prefixed_sequence is not None:
            return prefixed_sequence
    hierarchical = re.match(
        r"^(?P<parts>\d{1,3}(?:-\d{1,3}){1,2})(?=\s|[._、:：]|$)",
        stem,
    )
    if hierarchical:
        return tuple(int(part) for part in hierarchical.group("parts").split("-"))
    decimal = re.match(
        r"^(?P<parts>\d{1,3}(?:[.．]\d{1,3}){1,2})(?=\D|$)",
        stem,
    )
    if decimal:
        return tuple(int(part) for part in re.split(r"[.．]", decimal.group("parts")))
    ordinal = extract_sequence_marker(name)
    return (ordinal,) if ordinal is not None else None


def is_video_record(record: Mapping[str, Any]) -> bool:
    return str(record.get("type") or record.get("kind") or "") == "video" or Path(
        str(record.get("name") or "")
    ).suffix.lower() in {".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv", ".m4v"}


def _extract_structure_key(path: str) -> tuple[int, int, int]:
    """Return an explicit week/chapter key from directory components only."""

    week: int | None = None
    chapter: int | None = None
    components = str(path or "").replace("\\", "/").split("/")
    for component in components[:-1]:
        if week is None:
            match = re.search(rf"第(?P<num>{_STRUCTURE_NUMBER})周", component)
            if match:
                week = _parse_chinese_number(match.group("num"))
        if chapter is None:
            match = re.search(rf"第(?P<num>{_STRUCTURE_NUMBER})章", component)
            if match:
                chapter = _parse_chinese_number(match.group("num"))

    if week is None and chapter is None:
        return (1, 10**9, 10**9)
    return (0, week if week is not None else 10**9, chapter if chapter is not None else 10**9)


def _extract_stage_key(path: str) -> tuple[int, int]:
    """Keep explicitly numbered course stages in their teaching order."""

    for component in str(path or "").replace("\\", "/").split("/")[:-1]:
        match = re.match(rf"^第(?P<num>{_STRUCTURE_NUMBER})阶段", component)
        if match:
            number = _parse_chinese_number(match.group("num"))
            if number is not None:
                return (0, number)
        match = re.match(r"^0*(?P<num>\d{1,2})[-_.、].*阶段", component)
        if match:
            return (0, int(match.group("num")))
    return (1, 10**9)


def order_video_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order videos by explicit lesson number, then structure order.

    The complete tree must already have been collected. Explicit markers beat
    API return order, file size, timestamps, and lexical sorting. Unmarked
    videos retain their original depth-first order after marked lessons.
    """

    candidates = [(index, record) for index, record in enumerate(records) if is_video_record(record)]

    def key(item: tuple[int, dict[str, Any]]) -> tuple[Any, ...]:
        index, record = item
        sequence = _extract_sequence_key(str(record.get("name") or ""))
        depth = int(record.get("depth") or 0)
        stage_group, stage = _extract_stage_key(str(record.get("path") or ""))
        structure_group, week, chapter = _extract_structure_key(str(record.get("path") or ""))
        if sequence is None:
            return (stage_group, stage, 1, (10**9,), 1, 10**9, 10**9, depth, index)
        return (stage_group, stage, 0, sequence, structure_group, week, chapter, index, depth)

    return [record for _, record in sorted(candidates, key=key)]


def select_first_video(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    ordered = order_video_records(records)
    return ordered[0] if ordered else None


def selection_basis(record: Mapping[str, Any] | None) -> str:
    if not record:
        return "no-video"
    sequence = _extract_sequence_key(str(record.get("name") or ""))
    if sequence is None:
        return "depth-first-fallback-no-explicit-sequence"
    return f"explicit-lesson-sequence:{'.'.join(str(part) for part in sequence)}"
