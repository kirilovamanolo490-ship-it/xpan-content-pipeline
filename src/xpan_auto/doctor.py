"""Read-only local deployment checks; never contacts publishing services."""
import importlib.util
import json
import platform
import subprocess
import sys
from pathlib import Path

from .runtime import PROJECT_ROOT, cjk_font_candidates, find_media_tool


def main():
    checks = {name: importlib.util.find_spec(name) is not None
              for name in ("openpyxl", "PIL", "requests", "natsort", "treelib")}
    checks["python_version"] = sys.version_info >= (3, 11)
    tools = {}
    for name in ("ffmpeg", "ffprobe"):
        path = find_media_tool(name)
        try:
            valid = bool(path) and subprocess.run([path, "-version"], capture_output=True, timeout=15).returncode == 0
        except (OSError, subprocess.SubprocessError):
            valid = False
        checks[name] = valid
        tools[name] = path
    checks["cjk_font"] = any(Path(p).is_file() for p in cjk_font_candidates())
    checks["download_helper"] = (PROJECT_ROOT / "work/quark-auto-save/download_first_video.py").is_file()
    print(json.dumps({"passed": all(checks.values()), "platform": platform.platform(),
                      "python": sys.executable, "checks": checks, "tools": tools}, ensure_ascii=False, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
