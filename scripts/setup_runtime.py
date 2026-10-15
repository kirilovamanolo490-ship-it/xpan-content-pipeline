#!/usr/bin/env python3
"""Install the native Python environment and project-local macOS media tools."""
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    uv = shutil.which("uv")
    if not uv:
        raise SystemExit("Install uv first, then rerun this setup.")
    venv = ROOT / ".venv"
    interpreter = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if venv.exists() and not interpreter.is_file():
        raise SystemExit(".venv belongs to another platform. Rename it as a backup before setup.")
    subprocess.run([uv, "sync", "--python", "3.12", "--extra", "browser", "--extra", "documents"], cwd=ROOT, check=True)
    if sys.platform == "darwin":
        npm = shutil.which("npm")
        if not npm:
            raise SystemExit("Node/npm is required to install local ffmpeg/ffprobe.")
        arch = "arm64" if platform.machine() == "arm64" else "x64"
        # Versions correspond to platform-specific binary packages, not FFmpeg's version.
        packages = ["@ffmpeg-installer/darwin-" + arch, "@ffprobe-installer/darwin-" + arch]
        if arch == "arm64":
            packages = [packages[0] + "@4.1.5", packages[1] + "@5.0.1"]
        subprocess.run([npm, "install", "--prefix", str(ROOT / ".tools/media"),
                        "--ignore-scripts", "--no-audit", "--no-fund", "--save-exact"] + packages, cwd=ROOT, check=True)
        for name in ("ffmpeg", "ffprobe"):
            binary = ROOT / ".tools/media/node_modules" / ("@" + name + "-installer") / ("darwin-" + arch) / name
            binary.chmod(binary.stat().st_mode | 0o100)
            link = interpreter.parent / name
            if not link.exists() and not link.is_symlink():
                link.symlink_to(os.path.relpath(binary, link.parent))
    return subprocess.call([str(interpreter), str(ROOT / "scripts/run_workflow.py"), "doctor"], cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
