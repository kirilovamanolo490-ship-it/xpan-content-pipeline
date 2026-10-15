#!/usr/bin/env python3
"""Local fixed-slot planning and MCP-GET schedule receipt tool."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[4]
    sys.path.insert(0, str(root / "src"))
    from xpan_auto.typefully_schedule import main as schedule_main

    return schedule_main()


if __name__ == "__main__":
    raise SystemExit(main())
