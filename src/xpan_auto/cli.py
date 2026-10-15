from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from .excel_exporter import export_rows, update_existing_row, update_existing_rows
from .link_parser import extract_quark_links
from .quark_adapter import NewShare, QuarkAdapter, QuarkAPIError, QuarkItem
from .quark_tool import write_quark_url_file
from .state import StateStore


def _configure_output_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (OSError, ValueError):
            continue


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract Quark links and export an Excel result")
    parser.add_argument("--source-file", required=True, help="Text, Markdown, or Firecrawl output file")
    parser.add_argument("--xlsx", required=True, help="Output .xlsx path")
    parser.add_argument("--db", default="output/state.sqlite3", help="SQLite checkpoint path")
    parser.add_argument("--source-url", default="", help="Original Feishu source URL for the Excel column")
    parser.add_argument(
        "--quark-url-file",
        default="work/QuarkPanTool/url.txt",
        help="QuarkPanTool input file; one normalized Quark URL per line",
    )
    parser.add_argument(
        "--quark-run",
        action="store_true",
        help="Run the Quark inspect/save/share workflow after extraction",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually write to Quark; without this flag --quark-run only prints a plan",
    )
    parser.add_argument(
        "--cookie-file",
        default="work/QuarkPanTool/config/cookies.txt",
        help="Local Quark storage-state/cookie file",
    )
    parser.add_argument("--target-root", default="/推文分享", help="Destination folder path in Quark")
    parser.add_argument(
        "--numbered-folders",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Create a numbered folder under the target root for each source share",
    )
    parser.add_argument(
        "--share-output-file",
        default="output/share_url.txt",
        help="Plain-text output containing generated share URLs",
    )
    parser.add_argument(
        "--share-expiry",
        choices=("1d", "7d", "30d", "permanent"),
        default="permanent",
        help="New share expiry",
    )
    parser.add_argument(
        "--share-password-mode",
        choices=("none", "generated", "fixed"),
        default="none",
        help="New share password policy; source passwords remain optional",
    )
    parser.add_argument("--share-password", default=None, help="Password for --share-password-mode fixed")
    parser.add_argument("--limit", type=int, default=1, help="Maximum links to execute in canary mode")
    parser.add_argument(
        "--run-all",
        action="store_true",
        help="Allow execution for all extracted links; use with --execute explicitly",
    )
    parser.add_argument(
        "--update-existing-xlsx",
        action="store_true",
        help="Preserve extra workbook columns and update only Quark result columns",
    )
    parser.add_argument(
        "--checkpoint-each",
        action="store_true",
        help="Atomically save the existing workbook after every processed row",
    )
    parser.add_argument("--item-delay-seconds", type=float, default=0.0)
    parser.add_argument("--item-retries", type=int, default=1)
    parser.add_argument("--retry-delay-seconds", type=float, default=30.0)
    parser.add_argument(
        "--capacity-pause-seconds",
        type=float,
        default=0.0,
        help="When positive, wait and retry the same row after Quark reports insufficient capacity",
    )
    parser.add_argument(
        "--max-failure-attempts",
        type=int,
        default=8,
        help="Skip transient failures that have already reached this many state attempts",
    )
    parser.add_argument(
        "--calculate-sizes",
        action="store_true",
        help="Recursively calculate real saved-file bytes for existing and future successful rows",
    )
    parser.add_argument(
        "--size-delay-seconds",
        type=float,
        default=0.25,
        help="Delay between recursive Quark folder reads used for size calculation",
    )
    parser.add_argument(
        "--size-checkpoint-every",
        type=int,
        default=10,
        help="Atomically update Excel after this many successful size calculations",
    )
    parser.add_argument(
        "--size-request-retries",
        type=int,
        default=3,
        help="Retry a transient folder read without restarting the whole size calculation",
    )
    parser.add_argument(
        "--size-retry-delay-seconds",
        type=float,
        default=5.0,
        help="Delay between transient folder-read retries",
    )
    return parser


def _item_metadata(item: QuarkItem) -> dict[str, object]:
    return {
        "fid": item.fid,
        "name": item.name,
        "is_dir": item.is_dir,
        "pdir_fid": item.pdir_fid,
        "include_items": item.include_items,
        "size_bytes": item.size_bytes,
    }


def _numbered_folder_name(index: int, items: tuple[QuarkItem, ...]) -> str:
    source_name = next((item.name for item in items if item.name), "资料")
    safe_name = re.sub(r'[\\/:*?"<>|]+', "_", source_name).strip()[:80] or "资料"
    return f"{index:04d}_{safe_name}"


def _write_share_output(links, store: StateStore, output_path: str | Path) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for index, item in enumerate(links, start=1):
        job = store.get(item.key)
        if job is None:
            continue
        try:
            metadata = json.loads(job["metadata_json"] or "{}")
        except json.JSONDecodeError:
            metadata = {}
        for share in metadata.get("new_shares") or []:
            url = str(share.get("url") or "")
            if url:
                title = str(share.get("title") or "")
                lines.append(f"{index:04d} | {title} | {url}")
    output.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return output


def _load_metadata(job) -> dict[str, object]:
    if job is None:
        return {}
    try:
        return json.loads(job["metadata_json"] or "{}")
    except json.JSONDecodeError:
        return {}


def _saved_item_model(saved_item: dict[str, object]) -> QuarkItem:
    return QuarkItem(
        fid=str(saved_item.get("fid") or ""),
        name=str(saved_item.get("name") or ""),
        is_dir=bool(saved_item.get("is_dir")),
        pdir_fid=str(saved_item.get("pdir_fid") or "0"),
        include_items=saved_item.get("include_items"),
        size_bytes=(
            int(saved_item["size_bytes"])
            if saved_item.get("size_bytes") is not None
            else None
        ),
    )


def _format_bytes(size_bytes: int) -> str:
    value = float(max(0, size_bytes))
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    unit = units[0]
    for candidate in units:
        unit = candidate
        if value < 1024 or candidate == units[-1]:
            break
        value /= 1024
    if unit == "B":
        return f"{int(value)} B"
    return f"{value:.2f} {unit}"


def _sync_workbook_rows(links, store: StateStore, args: argparse.Namespace) -> bool:
    try:
        update_existing_rows(
            _rows_from_store(links, store, source_url=args.source_url),
            args.xlsx,
        )
    except PermissionError as exc:
        print(f"workbook_sync_deferred workbook={args.xlsx} error={exc}")
        return False
    return True


def _calculate_and_store_size(
    adapter: QuarkAdapter,
    item,
    index: int,
    store: StateStore,
    args: argparse.Namespace,
) -> bool:
    job = store.get(item.key)
    metadata = _load_metadata(job)
    if metadata.get("total_size_bytes") is not None:
        return False
    saved_items = [
        _saved_item_model(saved_item)
        for saved_item in metadata.get("saved_items") or []
        if isinstance(saved_item, dict) and saved_item.get("fid")
    ]
    if not saved_items:
        return False

    try:
        usage = adapter.calculate_usage(
            saved_items,
            folder_delay_seconds=args.size_delay_seconds,
            folder_retries=args.size_request_retries,
            retry_delay_seconds=args.size_retry_delay_seconds,
        )
    except (QuarkAPIError, OSError, ValueError) as exc:
        store.update_metadata(item.key, {"total_size_error": str(exc)[:500]})
        print(f"size_failed row={index + 1} error={exc}")
        return False

    display = _format_bytes(usage.total_bytes)
    store.update_metadata(
        item.key,
        {
            "total_size_bytes": usage.total_bytes,
            "total_size_display": display,
            "total_size_file_count": usage.file_count,
            "total_size_folder_count": usage.folder_count,
            "total_size_error": "",
        },
    )
    print(
        f"size_measured row={index + 1} total={display} bytes={usage.total_bytes} "
        f"files={usage.file_count} folders={usage.folder_count}"
    )
    return True


def _backfill_quark_sizes(
    adapter: QuarkAdapter,
    links,
    store: StateStore,
    args: argparse.Namespace,
) -> None:
    if not args.calculate_sizes:
        return

    changed = 0
    eligible = 0
    for index, item in enumerate(links, start=1):
        job = store.get(item.key)
        metadata = _load_metadata(job)
        has_new_link = any(
            str(share.get("url") or "")
            for share in metadata.get("new_shares") or []
            if isinstance(share, dict)
        )
        has_save_path = bool(str(metadata.get("target_root") or ""))
        if job is None or not (has_new_link and has_save_path):
            continue
        eligible += 1
        if _calculate_and_store_size(adapter, item, index, store, args):
            changed += 1
            if changed % args.size_checkpoint_every == 0:
                if _sync_workbook_rows(links, store, args):
                    print(f"size_checkpoint measured={changed} workbook={args.xlsx}")

    if changed and changed % args.size_checkpoint_every:
        if _sync_workbook_rows(links, store, args):
            print(f"size_checkpoint measured={changed} workbook={args.xlsx}")
    elif not changed and eligible:
        if _sync_workbook_rows(links, store, args):
            print(f"size_checkpoint_retry measured=0 workbook={args.xlsx}")
    print(f"size_backfill_complete newly_measured={changed}")


def _is_capacity_error(exc: BaseException) -> bool:
    return getattr(exc, "code", None) in (32003, "32003") or "capacity limit" in str(exc).lower()


def _retry_quark_call(label: str, action, *, retries: int, delay_seconds: float):
    for attempt in range(1, retries + 1):
        try:
            return action()
        except (QuarkAPIError, OSError) as exc:
            if attempt == retries:
                raise
            print(
                f"startup_retry label={label} attempt={attempt + 1}/{retries} "
                f"delay={delay_seconds:g} error={exc}"
            )
            if delay_seconds > 0:
                time.sleep(delay_seconds)
    raise RuntimeError(f"unreachable retry state: {label}")


def _is_terminal_failure(job) -> bool:
    if job is None:
        return False
    if str(job["status"] or "") == "BLOCKED":
        return True
    error = str(job["error"] or "")
    return "夸克分享内容为空" in error or "单次转存文件个数超出用户等级限制" in error


def _finish_saved_items(
    adapter: QuarkAdapter,
    item,
    metadata: dict[str, object],
    store: StateStore,
    args: argparse.Namespace,
) -> None:
    saved_items = list(metadata.get("saved_items") or [])
    prior_shares = list(metadata.get("new_shares") or [])
    recovered_shares: list[dict[str, object]] = []
    for saved_item in saved_items:
        prior_share = next(
            (
                share
                for share in prior_shares
                if str(share.get("fid") or "") == str(saved_item.get("fid") or "")
            ),
            None,
        )
        saved_model = _saved_item_model(saved_item)
        if prior_share and adapter.validate_share(
            NewShare(
                fid=str(prior_share.get("fid") or saved_model.fid),
                title=str(prior_share.get("title") or saved_model.name),
                share_url=str(prior_share.get("url") or ""),
                passcode=str(prior_share.get("passcode") or "") or None,
            )
        ):
            recovered_shares.append({**prior_share, "validated": True})
        else:
            recreated = adapter.create_share(
                saved_model,
                expiry=args.share_expiry,
                password_mode=args.share_password_mode,
                password=args.share_password,
            )
            recovered_shares.append(
                {
                    "fid": recreated.fid,
                    "title": recreated.title,
                    "url": recreated.share_url,
                    "passcode": recreated.passcode or "",
                    "validated": adapter.validate_share(recreated),
                }
            )
        store.update(
            item.key,
            "SHARED",
            metadata={**metadata, "new_shares": recovered_shares},
            error="新分享尚未全部通过公开页面校验。",
        )

    all_valid = bool(recovered_shares) and all(bool(share["validated"]) for share in recovered_shares)
    store.update(
        item.key,
        "SHARE_VALIDATED" if all_valid else "SHARED",
        metadata={**metadata, "new_shares": recovered_shares},
        error=None if all_valid else "新分享已创建，但公开页面可达性校验未通过。",
    )


def _process_quark_item(
    adapter: QuarkAdapter,
    item,
    index: int,
    total: int,
    base_target_folder_id: str,
    store: StateStore,
    args: argparse.Namespace,
) -> None:
    existing = store.get(item.key)
    existing_metadata = _load_metadata(existing)
    if existing_metadata.get("saved_items"):
        print(f"resuming={index}/{total} status={existing['status']} url={item.normalized_url}")
        _finish_saved_items(adapter, item, existing_metadata, store, args)
        if args.calculate_sizes:
            _calculate_and_store_size(adapter, item, index, store, args)
        return

    print(f"processing={index}/{total} url={item.normalized_url}")
    inspected = adapter.inspect_share(item.normalized_url)
    inspected_metadata = {
        "source_items": [_item_metadata(source_item) for source_item in inspected.items],
        "source_is_owner": inspected.is_owner,
    }
    store.update(item.key, "INSPECTED", metadata=inspected_metadata)

    target_path = args.target_root
    if args.numbered_folders:
        folder_name = _numbered_folder_name(index, inspected.items)
        target_path = f"{args.target_root.rstrip('/')}/{folder_name}"
    target_folder_id = (
        adapter.ensure_folder(target_path)
        if target_path != args.target_root
        else base_target_folder_id
    )
    print(f"target_path={target_path} target_folder_id={target_folder_id}")
    saved = adapter.save_share(item.normalized_url, target_folder_id)
    saved_metadata = {
        **inspected_metadata,
        "target_root": target_path,
        "target_base_root": args.target_root,
        "target_folder_id": target_folder_id,
        "save_task_id": saved.task_id,
        "saved_items": [_item_metadata(saved_item) for saved_item in saved.items],
    }
    if not saved.items:
        store.update(
            item.key,
            "BLOCKED",
            metadata=saved_metadata,
            error="转存任务完成，但未发现新的目标文件项；为避免分享错误目录，未自动新建分享。",
        )
        return
    store.update(item.key, "SAVED", metadata=saved_metadata)
    _finish_saved_items(adapter, item, saved_metadata, store, args)
    if args.calculate_sizes:
        _calculate_and_store_size(adapter, item, index, store, args)


def _checkpoint_quark_row(index: int, item, store: StateStore, args: argparse.Namespace) -> None:
    if not args.checkpoint_each:
        return
    row = _row_from_store(index, item, store, source_url=args.source_url)
    try:
        update_existing_row(index + 1, row, args.xlsx)
    except PermissionError as exc:
        print(f"workbook_sync_deferred row={index + 1} workbook={args.xlsx} error={exc}")
    else:
        print(f"checkpoint_saved row={index + 1} workbook={args.xlsx}")


def _run_quark(links, store: StateStore, args: argparse.Namespace) -> None:
    if not args.execute:
        count = len(links) if args.run_all else min(args.limit, len(links))
        print(f"dry_run=1 quark_links={len(links)} planned={count} target={args.target_root}")
        print("未执行转存；需要 --execute，并建议先用默认 limit=1 做单条验证。")
        return
    if args.share_password_mode == "fixed" and not args.share_password:
        raise ValueError("--share-password-mode fixed 需要同时提供 --share-password")
    if args.run_all:
        selected = links
    else:
        if args.limit < 1:
            raise ValueError("--limit 必须大于 0")
        selected = links[: args.limit]

    adapter = QuarkAdapter(cookie_file=args.cookie_file)
    nickname = _retry_quark_call(
        "whoami",
        adapter.whoami,
        retries=args.size_request_retries,
        delay_seconds=args.size_retry_delay_seconds,
    )
    print(f"quark_user={nickname}")
    _backfill_quark_sizes(adapter, selected, store, args)
    base_target_folder_id = _retry_quark_call(
        "ensure_target_root",
        lambda: adapter.ensure_folder(args.target_root),
        retries=args.size_request_retries,
        delay_seconds=args.size_retry_delay_seconds,
    )
    print(f"target_root={args.target_root} target_folder_id={base_target_folder_id}")

    for index, item in enumerate(selected, start=1):
        existing = store.get(item.key)
        if existing is not None and existing["status"] == "SHARE_VALIDATED":
            print(f"skipped={index}/{len(selected)} status=SHARE_VALIDATED url={item.normalized_url}")
            continue
        if _is_terminal_failure(existing):
            print(f"terminal_failure={index}/{len(selected)} error={existing['error']} url={item.normalized_url}")
            continue
        if (
            existing is not None
            and existing["status"] == "FAILED"
            and int(existing["attempts"] or 0) >= args.max_failure_attempts
            and "capacity limit" not in str(existing["error"] or "").lower()
        ):
            print(f"retry_exhausted={index}/{len(selected)} attempts={existing['attempts']} url={item.normalized_url}")
            continue

        attempt = 0
        while True:
            try:
                _process_quark_item(
                    adapter,
                    item,
                    index,
                    len(selected),
                    base_target_folder_id,
                    store,
                    args,
                )
                _checkpoint_quark_row(index, item, store, args)
                break
            except (QuarkAPIError, OSError, ValueError) as exc:
                if _is_capacity_error(exc) and args.capacity_pause_seconds > 0:
                    store.update(item.key, "WAITING_CAPACITY", error=str(exc))
                    _checkpoint_quark_row(index, item, store, args)
                    _backfill_quark_sizes(adapter, selected, store, args)
                    print(
                        f"waiting_capacity row={index + 1} seconds={args.capacity_pause_seconds:g} "
                        f"url={item.normalized_url}"
                    )
                    time.sleep(args.capacity_pause_seconds)
                    continue

                attempt += 1
                store.update(item.key, "FAILED", error=str(exc))
                _checkpoint_quark_row(index, item, store, args)
                if _is_terminal_failure(store.get(item.key)) or attempt >= args.item_retries:
                    print(f"failed={item.normalized_url} error={exc}")
                    break
                print(
                    f"retrying={index}/{len(selected)} attempt={attempt + 1}/{args.item_retries} "
                    f"delay={args.retry_delay_seconds:g} error={exc}"
                )
                time.sleep(args.retry_delay_seconds)

        if args.item_delay_seconds > 0:
            time.sleep(args.item_delay_seconds)


def _row_from_store(index: int, item, store: StateStore, source_url: str = "") -> dict[str, object]:
    job = store.get(item.key)
    metadata = _load_metadata(job)
    shares = metadata.get("new_shares") or []
    source_items = metadata.get("source_items") or []
    titles = [str(share.get("title") or "") for share in shares if share.get("title")]
    if not titles:
        titles = [str(source_item.get("name") or "") for source_item in source_items if source_item.get("name")]
    description = re.sub(r"https?://\S+", "", item.context)
    description = " ".join(description.split())
    if (
        not description
        or not re.search(r"[\u4e00-\u9fff]", description)
        or description.count('"') > 1
    ):
        description = "来源飞书页面已识别，待转存后补充目录说明。"
    return {
        "序号": index,
        "来源飞书链接": source_url,
        "资料标题": "\n".join(titles),
        "原夸克链接": item.normalized_url,
        "原提取码": item.passcode or "",
        "新夸克链接": "\n".join(str(share.get("url") or "") for share in shares),
        "新提取码": "\n".join(str(share.get("passcode") or "") for share in shares),
        "保存目录": metadata.get("target_root", ""),
        "文件数量": len(metadata.get("saved_items") or []),
        "文件类型": "",
        "总大小": metadata.get("total_size_display") or (
            _format_bytes(int(metadata["total_size_bytes"]))
            if metadata.get("total_size_bytes") is not None
            else ""
        ),
        "文字介绍": description[:160],
        "图片": "",
        "处理状态": job["status"] if job is not None else "EXTRACTED",
        "错误信息": job["error"] if job is not None and job["error"] else "",
        "更新时间": job["updated_at"] if job is not None else "",
    }


def _rows_from_store(links, store: StateStore, source_url: str = "") -> list[dict[str, object]]:
    return [
        _row_from_store(index, item, store, source_url=source_url)
        for index, item in enumerate(links, start=1)
    ]


def main(argv: list[str] | None = None) -> int:
    _configure_output_encoding()
    parser = _parser()
    args = parser.parse_args(argv)
    source = Path(args.source_file)
    text = source.read_text(encoding="utf-8")
    links = extract_quark_links(text)
    quark_url_file = write_quark_url_file(links, args.quark_url_file)
    print(f"quark_url_file={quark_url_file} quark_input={len(links)}")
    store = StateStore(args.db)

    if args.item_retries < 1:
        parser.error("--item-retries 必须大于 0")
    if min(
        args.item_delay_seconds,
        args.retry_delay_seconds,
        args.capacity_pause_seconds,
        args.size_delay_seconds,
        args.size_retry_delay_seconds,
    ) < 0:
        parser.error("等待时间不能为负数")
    if args.size_checkpoint_every < 1:
        parser.error("--size-checkpoint-every 必须大于 0")
    if args.size_request_retries < 1:
        parser.error("--size-request-retries 必须大于 0")
    if args.checkpoint_each and not args.update_existing_xlsx:
        parser.error("--checkpoint-each 必须和 --update-existing-xlsx 一起使用")

    for item in links:
        store.upsert_extracted(item)

    if args.update_existing_xlsx and Path(args.xlsx).is_file():
        if _sync_workbook_rows(links, store, args):
            print(f"checkpoint_sync rows={len(links)} workbook={args.xlsx}")

    if args.execute and not args.quark_run:
        parser.error("--execute 必须和 --quark-run 一起使用")
    if args.quark_run:
        _run_quark(links, store, args)

    share_output = _write_share_output(links, store, args.share_output_file)
    print(f"share_output_file={share_output}")

    rows = _rows_from_store(links, store, source_url=args.source_url)

    if args.update_existing_xlsx and Path(args.xlsx).is_file():
        try:
            output = update_existing_rows(rows, args.xlsx)
        except PermissionError as exc:
            output = Path(args.xlsx)
            print(f"workbook_sync_deferred workbook={args.xlsx} error={exc}")
    else:
        output = export_rows(rows, args.xlsx)
    print(f"extracted={len(links)} output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
