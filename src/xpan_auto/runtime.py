"""Local paths and tools shared by Windows, macOS and Linux workflows."""
from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path, PureWindowsPath

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def resolve_project_path(value: str | Path, *, base: Path | None = None,
                         root: Path = PROJECT_ROOT) -> Path:
    """Rebase a moved project path, never guess a file from its basename."""
    text = str(value)
    native = Path(text)
    if native.is_absolute() and native.exists():
        return native
    windows = PureWindowsPath(text)
    parts = windows.parts if "\\" in text or windows.drive else native.parts
    if windows.drive or native.is_absolute():
        # Only migrate paths explicitly belonging to this project. Do not map
        # arbitrary drive roots, cloud paths, or another project's assets.
        matches = [i for i, part in enumerate(parts) if part == root.name]
        if len(matches) == 1:
            tail = parts[matches[0] + 1:]
            if tail and ".." not in tail:
                return root.joinpath(*tail)
        return native
    if ".." in parts:
        return (base or root).joinpath(*parts).resolve()
    if parts and parts[0] in {"output", "work", "config", "knowledge", ".codex"}:
        return root.joinpath(*parts)
    return (base or root).joinpath(*parts)


def find_media_tool(name: str) -> str | None:
    override = os.environ.get(f"XPAN_{name.upper()}")
    if override:
        return str(resolve_project_path(override))
    found = shutil.which(name)
    if found:
        return found
    executable = name + (".exe" if os.name == "nt" else "")
    local = Path(sys.executable).parent / executable
    if local.is_file():
        return str(local)
    machine = platform.machine().lower()
    arch = {"aarch64": "arm64", "amd64": "x64", "x86_64": "x64"}.get(machine, machine)
    package = f"{sys.platform}-{arch}"
    candidate = PROJECT_ROOT / ".tools/media/node_modules" / f"@{name}-installer" / package / executable
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return None


def cjk_font_candidates(*, bold: bool = False, family: str = "sans") -> tuple[str, ...]:
    override = os.environ.get("XPAN_CJK_FONT_BOLD" if bold else "XPAN_CJK_FONT")
    serif = family in {"editorial", "learning-editorial"}
    classical = family == "classical"
    mac = Path("/System/Library/Fonts")
    candidates = [override] if override else []
    if serif:
        candidates.append(str(mac / "Supplemental/Songti.ttc"))
    if classical:
        candidates.append(str(mac / "Supplemental/Kaiti.ttc"))
    candidates.extend([
        str(mac / ("STHeiti Medium.ttc" if bold else "STHeiti Light.ttc")),
        str(mac / "Hiragino Sans GB.ttc"),
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc",
    ])
    return tuple(candidates)
