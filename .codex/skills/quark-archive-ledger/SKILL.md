---
name: quark-archive-ledger
description: "Run or maintain the independent 资料渠道一 archive workflow: save approved Quark links, create and validate new share links, and record file size and storage path in the archive ledger. Use only after items are in 归档.md; do not use for Feishu intake."
---

# Quark Archive Ledger

Run the second, independent workflow for `资料渠道一`.

## Scope boundary

- Read only the already-approved entries in `knowledge/资料渠道一归档.md`.
- Do not fetch Feishu or modify `knowledge/资料渠道一收录.md`; that is the separate `$feishu-intake-daily` workflow.
- Do not process entries that already have a terminal state or a validated replacement link.

## Execute

Preview without external changes:

```bash
python scripts/run_workflow.py archive --dry-run
```

After the user explicitly authorizes a live archive run:

```bash
python scripts/run_workflow.py archive --execute
```

The live run saves each original link under `/推文分享/<序号>_<标题>`, creates and validates a new share link, then appends to the existing `处理结果` sheet in `output/quark_links.typefully.xlsx`.

Preserve the workbook's existing column layout and publisher columns; locate columns by header instead of a historical fixed column count. Read ledger data directly with `scripts/query_ledger.py` or the existing Python code, without screenshots, rendering, GUI inspection, or workbook copies. New rows must copy the previous row's format and fill the established Quark fields, including source Feishu URL, original/new links, storage path, file count, total size, description, status, error, and update time. Folder numbering continues from the highest number found in the current Quark root, SQLite state, or workbook; it must not restart at `0001` on later runs.

Use `--retry-failed` only when the user asks to retry failed entries. Do not schedule this workflow automatically unless the user explicitly requests a separate trigger after their manual archive selection. The launcher chooses the native project `.venv` and fixes the working directory on all platforms; use `python scripts/setup_runtime.py` when dependencies need installation.
