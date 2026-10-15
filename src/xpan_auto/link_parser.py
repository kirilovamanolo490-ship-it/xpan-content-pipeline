from __future__ import annotations

import html
import re
from urllib.parse import parse_qs, urlsplit, urlunsplit

from .models import QuarkLink

_QUARK_URL = re.compile(
    r"https?://pan\.quark\.cn/s/[A-Za-z0-9_-]+(?:\?[A-Za-z0-9_=&%.-]+)?(?:#[^\s<>\"']*)?",
    re.IGNORECASE,
)
_LABELED_PASSCODE = re.compile(
    r"(?:提取码|提取碼|密码|密碼)\s*[:：=]?\s*([A-Za-z0-9]{4,8})",
    re.IGNORECASE,
)
_TRAILING_PUNCTUATION = "，。；、,.!?！？;:：)]}》」』\"'"


def _clean_url(value: str) -> str:
    value = html.unescape(value).replace("\\/", "/").strip()
    return value.rstrip(_TRAILING_PUNCTUATION)


def _url_passcode(url: str) -> str | None:
    query = parse_qs(urlsplit(url).query)
    values = query.get("pwd") or query.get("passcode")
    return values[0] if values else None


def _dedupe_key(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, "", parts.fragment))


def extract_quark_links(text: str) -> list[QuarkLink]:
    """Extract, annotate, and de-duplicate Quark share links from arbitrary text."""

    text = html.unescape(text).replace("\\/", "/")
    results: list[QuarkLink] = []
    seen: set[str] = set()

    for match in _QUARK_URL.finditer(text):
        original = match.group(0)
        normalized = _clean_url(original)
        key = _dedupe_key(normalized)
        if key in seen:
            continue

        start = max(0, match.start() - 100)
        end = min(len(text), match.end() + 100)
        context = text[start:end]
        after_url = text[match.end() : min(len(text), match.end() + 80)]
        before_url = text[max(0, match.start() - 80) : match.start()]
        # Only accept human-labelled codes from nearby text.  A generic
        # ``pwd=`` match here can belong to an adjacent Baidu link rather
        # than to this Quark link; URL query parameters are handled separately.
        passcode_match = _LABELED_PASSCODE.search(after_url) or _LABELED_PASSCODE.search(before_url)
        passcode = passcode_match.group(1) if passcode_match else _url_passcode(normalized)
        results.append(
            QuarkLink(
                original_url=original,
                normalized_url=normalized,
                passcode=passcode,
                context=context.strip(),
            )
        )
        seen.add(key)

    return results
