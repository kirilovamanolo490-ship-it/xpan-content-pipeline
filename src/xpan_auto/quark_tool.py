from __future__ import annotations

from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from .models import QuarkLink


def _has_passcode(query: dict[str, list[str]]) -> bool:
    return any(value for key in ("pwd", "passcode") for value in query.get(key, []))


def tool_input_url(item: QuarkLink) -> str:
    """Return one URL in the format expected by QuarkPanTool/url.txt."""

    parts = urlsplit(item.normalized_url)
    query = parse_qs(parts.query, keep_blank_values=True)
    if item.passcode and not _has_passcode(query):
        query["pwd"] = [item.passcode]
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), parts.fragment)
        )
    return item.normalized_url


def write_quark_url_file(items: Iterable[QuarkLink], output_path: str | Path) -> Path:
    """Write one normalized Quark URL per line for QuarkPanTool."""

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [tool_input_url(item) for item in items]
    output.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return output
