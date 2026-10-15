from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Iterable, Mapping

from openpyxl import Workbook, load_workbook
from openpyxl.drawing.image import Image as ExcelImage
from openpyxl.styles import Alignment, Font, PatternFill

EXCEL_COLUMNS = [
    "序号",
    "来源飞书链接",
    "资料标题",
    "原夸克链接",
    "原提取码",
    "新夸克链接",
    "新提取码",
    "保存目录",
    "文件数量",
    "文件类型",
    "总大小",
    "文字介绍",
    "图片",
    "处理状态",
    "错误信息",
    "更新时间",
]


def _atomic_save(workbook, output: Path) -> None:
    temporary = output.with_name(f".{output.stem}.{os.getpid()}.tmp{output.suffix}")
    try:
        workbook.save(temporary)
        for attempt in range(10):
            try:
                os.replace(temporary, output)
                break
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(0.5)
    finally:
        if temporary.exists():
            temporary.unlink()


def _existing_header_columns(sheet) -> dict[str, int]:
    headers = {
        str(cell.value): cell.column
        for cell in sheet[1]
        if cell.value not in (None, "")
    }
    missing = [name for name in EXCEL_COLUMNS if name not in headers]
    if missing:
        raise ValueError(f"Existing workbook is missing required columns: {', '.join(missing)}")
    return headers


def update_existing_row(
    row_number: int,
    row: Mapping[str, object],
    output_path: str | Path,
) -> Path:
    """Update one Quark result row while preserving publisher columns and assets."""

    output = Path(output_path)
    workbook = load_workbook(output)
    sheet = workbook.active
    headers = _existing_header_columns(sheet)
    for name in EXCEL_COLUMNS:
        if name == "图片":
            continue
        sheet.cell(row=row_number, column=headers[name], value=row.get(name, ""))
    _atomic_save(workbook, output)
    return output


def update_existing_rows(
    rows: Iterable[Mapping[str, object]],
    output_path: str | Path,
) -> Path:
    """Sync Quark columns into an existing workbook without replacing extra columns."""

    output = Path(output_path)
    workbook = load_workbook(output)
    sheet = workbook.active
    headers = _existing_header_columns(sheet)
    for row_number, row in enumerate(rows, start=2):
        for name in EXCEL_COLUMNS:
            if name == "图片":
                continue
            sheet.cell(row=row_number, column=headers[name], value=row.get(name, ""))
    _atomic_save(workbook, output)
    return output


def export_rows(rows: Iterable[Mapping[str, object]], output_path: str | Path) -> Path:
    """Write result rows to an xlsx file and embed available thumbnails."""

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "处理结果"

    header_fill = PatternFill("solid", fgColor="1F4E78")
    for column, name in enumerate(EXCEL_COLUMNS, start=1):
        cell = sheet.cell(row=1, column=column, value=name)
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")

    image_column = EXCEL_COLUMNS.index("图片") + 1
    for row_number, row in enumerate(rows, start=2):
        for column, name in enumerate(EXCEL_COLUMNS, start=1):
            if name == "图片":
                continue
            value = row.get(name, "")
            sheet.cell(row=row_number, column=column, value=value)
            sheet.cell(row=row_number, column=column).alignment = Alignment(
                vertical="top", wrap_text=True
            )

        image_path = row.get("图片文件")
        if image_path:
            path = Path(str(image_path))
            if path.is_file():
                image = ExcelImage(str(path))
                image.width = 160
                image.height = 90
                sheet.add_image(image, f"{chr(64 + image_column)}{row_number}")
                sheet.row_dimensions[row_number].height = 72

    widths = {
        "A": 8, "B": 26, "C": 28, "D": 36, "E": 12, "F": 36,
        "G": 12, "H": 28, "I": 12, "J": 18, "K": 14, "L": 48,
        "M": 24, "N": 16, "O": 32, "P": 24,
    }
    for column, width in widths.items():
        sheet.column_dimensions[column].width = width
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    workbook.save(output)
    return output
