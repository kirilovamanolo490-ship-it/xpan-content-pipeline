from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit


@dataclass(frozen=True)
class QuarkLink:
    """A normalized Quark share link extracted from a source document."""

    original_url: str
    normalized_url: str
    passcode: str | None = None
    context: str = ""

    @property
    def key(self) -> str:
        parts = urlsplit(self.normalized_url)
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, "", parts.fragment))
