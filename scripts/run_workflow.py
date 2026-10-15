#!/usr/bin/env python3
"""Cross-platform workflow launcher; run from any working directory."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workflow", choices=("ingest", "archive", "publish", "doctor"))
    args, extra = parser.parse_known_args()
    python = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        parser.error("Missing native project environment. Run: uv sync --extra browser --extra documents")
    if args.workflow == "archive" and not any(flag in extra for flag in ("--dry-run", "--execute", "--help")):
        parser.error("archive requires --dry-run or --execute")
    commands = {
        "ingest": ["-m", "xpan_auto.knowledge_flow", "ingest", "--scrape"],
        "archive": ["-m", "xpan_auto.knowledge_flow", "archive", "--run-all", "--quark-run"],
        "publish": ["-m", "xpan_auto.publish_pipeline"],
        "doctor": ["-m", "xpan_auto.doctor"],
    }
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["PATH"] = str(python.parent) + os.pathsep + env.get("PATH", "")
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    command = [str(python)] + commands[args.workflow] + extra
    temporary_scrape_dir = None
    if args.workflow == "doctor" or "--help" in extra:
        return subprocess.call(command, cwd=ROOT, env=env)
    logs = ROOT / "output/logs"
    logs.mkdir(parents=True, exist_ok=True)
    lock = logs / (args.workflow + ".lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        parser.error("Workflow lock exists: %s. Check the running process before removing a stale lock." % lock)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log = logs / (args.workflow + "-" + stamp + ".log")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(str(os.getpid()))
            if args.workflow == "ingest" and not any(
                flag == "--scrape-file" or flag.startswith("--scrape-file=")
                for flag in extra
            ):
                # The live intake workflow is allowed to write its log, the
                # collection Markdown, and collected SQLite state only. Keep
                # the scrape snapshot outside the workspace and remove it
                # after the child process exits.
                temporary_scrape_dir = tempfile.TemporaryDirectory(
                    prefix="xpan-feishu-ingest-"
                )
                command.extend([
                    "--scrape-file",
                    str(Path(temporary_scrape_dir.name) / "feishu-source.json"),
                ])
        with log.open("w", encoding="utf-8") as handle:
            handle.write("workflow=%s started=%s\n" % (args.workflow, stamp))
            handle.flush()
            with subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace") as process:
                for line in process.stdout:
                    print(line, end="")
                    handle.write(line)
                    handle.flush()
                code = process.wait()
            handle.write("exit_code=%s\n" % code)
        print("log=%s" % log)
        return code
    finally:
        if temporary_scrape_dir is not None:
            temporary_scrape_dir.cleanup()
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
