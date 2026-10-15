import tempfile
import unittest
from pathlib import Path

from xpan_auto.knowledge_flow import (
    ArchiveCursor,
    Entry,
    KnowledgeState,
    _advance_archive_cursor,
    _archive_window_entries,
    read_archive_cursor,
    write_archive_cursor,
)


def _entry(date: str, share_id: str) -> Entry:
    return Entry(date=date, title=share_id, url=f"https://pan.quark.cn/s/{share_id}")


class ArchiveCursorTests(unittest.TestCase):
    def test_window_includes_scan_start_and_excludes_older_dates(self) -> None:
        cursor = ArchiveCursor(last_completed_date="08/22", scan_from_date="08/23")
        entries = [
            _entry("08/27", "27"),
            _entry("08/23", "23"),
            _entry("08/22", "22"),
            _entry("08/19", "19"),
        ]

        selected = _archive_window_entries(entries, cursor)

        self.assertEqual([entry.share_id for entry in selected], ["27", "23"])

    def test_cursor_round_trips_as_human_readable_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cursor.md"
            cursor = ArchiveCursor(last_completed_date="08/22", scan_from_date="08/23")
            write_archive_cursor(
                path,
                cursor,
                run_at="2026-08-29T21:00:00+08:00",
                run_status="INITIALIZED",
                scope_dates=["08/27", "08/26"],
                candidate_count=10,
                processed_count=0,
                pending_dates=["08/27"],
            )

            self.assertEqual(read_archive_cursor(path), cursor)
            self.assertIn("最后完成日期：08/22", path.read_text(encoding="utf-8"))
            self.assertIn("扫描起点日期（含）：08/23", path.read_text(encoding="utf-8"))

    def test_cursor_advancement_stops_at_first_incomplete_date(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = KnowledgeState(root / "state.sqlite3")
            entries = [
                _entry("08/23", "23-a"),
                _entry("08/23", "23-b"),
                _entry("08/24", "24-a"),
                _entry("08/25", "25-a"),
            ]
            for entry, status in (
                (entries[0], "SHARE_VALIDATED"),
                (entries[1], "SHARE_VALIDATED"),
                (entries[2], "FAILED"),
                (entries[3], "SHARE_VALIDATED"),
            ):
                state.upsert_archived(
                    entry,
                    category="未分类",
                    status=status,
                    updated_at="2026-08-29T21:00:00+08:00",
                )

            next_cursor, pending = _advance_archive_cursor(
                entries,
                state,
                root / "missing-ledger.xlsx",
                ArchiveCursor(last_completed_date="08/22", scan_from_date="08/23"),
            )

        self.assertEqual(next_cursor, ArchiveCursor(last_completed_date="08/23", scan_from_date="08/23"))
        self.assertEqual(pending, ["08/24"])

    def test_cursor_advances_through_all_terminal_dates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = KnowledgeState(root / "state.sqlite3")
            entries = [_entry("08/23", "23-a"), _entry("08/24", "24-a")]
            for entry in entries:
                state.upsert_archived(
                    entry,
                    category="未分类",
                    status="SAVED",
                    updated_at="2026-08-29T21:00:00+08:00",
                )

            next_cursor, pending = _advance_archive_cursor(
                entries,
                state,
                root / "missing-ledger.xlsx",
                ArchiveCursor(last_completed_date="08/22", scan_from_date="08/23"),
            )

        self.assertEqual(next_cursor, ArchiveCursor(last_completed_date="08/24", scan_from_date="08/24"))
        self.assertEqual(pending, [])


if __name__ == "__main__":
    unittest.main()
