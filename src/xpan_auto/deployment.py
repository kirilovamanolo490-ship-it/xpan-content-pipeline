"""Public deployment settings: environment overrides the local, ignored .env."""
from __future__ import annotations
import os
from pathlib import Path
from .runtime import PROJECT_ROOT


def setting(name: str, default: str = "", *, root: Path = PROJECT_ROOT) -> str:
    if name in os.environ:
        return os.environ[name].strip()
    path = root / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == name:
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                    value = value[1:-1]
                return value
    return default


def verified_social_set_id() -> int:
    value = setting("XPAN_TYPEFULLY_SOCIAL_SET_ID")
    if not value.isdecimal() or int(value) < 1:
        raise ValueError("请先配置已通过 Typefully MCP 核对的 XPAN_TYPEFULLY_SOCIAL_SET_ID")
    return int(value)
