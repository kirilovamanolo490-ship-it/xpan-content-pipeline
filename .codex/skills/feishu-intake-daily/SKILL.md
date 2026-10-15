---
name: feishu-intake-daily
description: "Run or maintain the daily Feishu-to-collection workflow in this workspace. Use for incremental Feishu collection and its 20:00 schedule; do not use it for archive processing, Quark transfers, sharing, or Excel updates."
---

# Feishu Intake Daily

Run the first, independent knowledge workflow for this workspace.

## Scope boundary

- `knowledge/资料渠道一收录.md` is the raw intake pool. The Feishu stage only appends deduplicated entries using its top date as the dynamic watermark.
- Stop after `收录.md` and the `collected` SQLite state are updated.
- `knowledge/资料渠道一归档.md`, Quark transfers, new share links, and the Excel ledger belong to a separate second workflow. Do not invoke or modify them here.

## Execute

Use the deterministic launcher:

```bash
python scripts/run_workflow.py ingest
```

For a verification run, use `--dry-run`. It refreshes the Feishu snapshot and previews the collection delta, but does not write `收录.md`. The launcher selects the native project `.venv` on Windows/macOS/Linux; run `python scripts/setup_runtime.py` after moving to a new machine. Do not invoke the Windows-only scheduler on macOS.

The live run performs only these steps:

1. Python fetches the public Feishu SSR page with verified TLS and a temporary redirect-cookie session; no PowerShell or Firecrawl dependency.
2. The top date in `收录.md` is used as the dynamic watermark; all dates available after that watermark, including the watermark date, are checked for unseen Quark share IDs. This catches up entries when one or more daily runs were missed.
3. Only unseen entries are appended to `收录.md`, recorded in the `collected` SQLite state, and logged in `output/logs/`.

The launcher retries transient fetch failures and validates that the extracted page is non-empty and contains parseable Quark links. Do not require the source to contain today's `MM/DD` date: Feishu may publish late, and a later run must collect every unseen entry newer than the collection watermark. A valid older snapshot may yield no additions; only report outcomes shown by the actual run and its log.

Do not start a second live run while another is still running. For a failed scheduled run, inspect its latest log and retry only after the failure cause is understood.

The primary schedule is the Codex local automation at 20:00. `scripts/windows/Register-KnowledgeTasks.ps1` is a Windows Task Scheduler fallback and must not be enabled alongside that Codex automation.
