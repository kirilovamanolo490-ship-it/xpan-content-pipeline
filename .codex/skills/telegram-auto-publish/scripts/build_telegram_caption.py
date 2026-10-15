#!/usr/bin/env python3
"""Build unreviewed Telegram/X seed copy for the local preparation stage."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def project_root() -> Path:
    # .../<project>/.codex/skills/telegram-auto-publish/scripts/<file>
    return Path(__file__).resolve().parents[4]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True)
    parser.add_argument("--description", default="")
    parser.add_argument("--link", required=True)
    parser.add_argument("--file-name", action="append", default=[])
    parser.add_argument(
        "--details-file",
        type=Path,
        help="optional telegram-project-details.json; replaces placeholder descriptions and enriches tags",
    )
    parser.add_argument("--max-tags", type=int, default=8)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--x-output", type=Path, help="optional unreviewed plain-text X seed")
    return parser.parse_args()


def _load_details(path: Path | None) -> dict[str, object]:
    if path is None:
        return {}
    resolved = path if path.is_absolute() else project_root() / path
    if not resolved.is_file():
        raise RuntimeError(f"Project details file not found: {resolved}")
    try:
        details = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Project details JSON is invalid: {resolved}") from exc
    if not isinstance(details, dict):
        raise RuntimeError(f"Project details JSON must be an object: {resolved}")
    return details


def main() -> int:
    args = parse_args()
    src_dir = project_root() / "src"
    sys.path.insert(0, str(src_dir))

    from xpan_auto.telegram_formatter import (
        build_promotional_description,
        build_telegram_post,
        detail_file_names,
        is_placeholder_description,
        x_weighted_length,
    )
    from xpan_auto.copy_review import SEED_MARKER

    details = _load_details(args.details_file)
    factual_description = args.description.strip()
    description = factual_description
    description_source = "unreviewed-seed"
    file_names = list(args.file_name)
    if details:
        file_names.extend(detail_file_names(details))
        description = build_promotional_description(args.title, details, factual_description)
    if is_placeholder_description(description):
        raise RuntimeError("Description is empty or still a placeholder; collect project details before publishing")

    post = build_telegram_post(
        title=args.title,
        description=description,
        link=args.link,
        file_names=file_names,
        max_tags=args.max_tags,
    )
    output = args.output if args.output.is_absolute() else project_root() / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    caption_value = f"{SEED_MARKER}\n{post['caption']}"
    output.write_text(caption_value, encoding="utf-8", newline="\n")
    x_output_value = ""
    if args.x_output is not None:
        x_output = args.x_output if args.x_output.is_absolute() else project_root() / args.x_output
        x_output.parent.mkdir(parents=True, exist_ok=True)
        seed_description = factual_description if not is_placeholder_description(factual_description) else description
        x_output_value = f"{SEED_MARKER}\n\n{args.title.strip()}\n\n{seed_description.strip()[:240]}\n\n{args.link.strip()}"
        x_tags = re.findall(r"(?<!\S)#[^\s#]+", x_output_value)
        x_output.write_text(x_output_value, encoding="utf-8", newline="\n")
    else:
        x_tags = []

    print(
        json.dumps(
            {
                "output": str(output),
                "parse_mode": post["parse_mode"],
                "tags": post["tags"],
                "caption_chars": len(caption_value),
                "fixed_links": post["fixed_links"],
                "description_source": description_source,
                "description_chars": len(description),
                "x_output": str(args.x_output or ""),
                "x_chars": len(x_output_value),
                "x_weighted_chars": x_weighted_length(x_output_value),
                "x_tags": x_tags,
                "detail_count": len(details.get("items") or []),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
