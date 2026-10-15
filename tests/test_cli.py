import argparse
import json
import tempfile
import unittest
from pathlib import Path

from xpan_auto.cli import _backfill_quark_sizes, _format_bytes, _retry_quark_call, _row_from_store
from xpan_auto.excel_exporter import export_rows
from xpan_auto.models import QuarkLink
from xpan_auto.quark_adapter import QuarkAPIError, UsageSummary
from xpan_auto.state import StateStore


class CliSizeTests(unittest.TestCase):
    def test_startup_call_retries_a_transient_quark_error(self):
        attempts = 0

        def action():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise QuarkAPIError("temporary TLS failure")
            return "ok"

        result = _retry_quark_call("whoami", action, retries=2, delay_seconds=0)

        self.assertEqual(result, "ok")
        self.assertEqual(attempts, 2)

    def test_formats_binary_size_for_excel_display(self):
        self.assertEqual(_format_bytes(0), "0 B")
        self.assertEqual(_format_bytes(1536), "1.50 KB")

    def test_row_uses_checkpointed_real_total_size(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = StateStore(Path(temp_dir) / "state.sqlite3")
            item = QuarkLink(
                original_url="https://pan.quark.cn/s/abc123",
                normalized_url="https://pan.quark.cn/s/abc123",
            )
            store.upsert_extracted(item)
            store.update(
                item.key,
                "SHARE_VALIDATED",
                metadata={"total_size_bytes": 3072},
            )

            row = _row_from_store(1, item, store)

            self.assertEqual(row["总大小"], "3.00 KB")

    def test_size_backfill_selects_new_link_and_path_independent_of_status(self):
        class Adapter:
            def calculate_usage(self, items, **kwargs):
                return UsageSummary(total_bytes=4096, file_count=1, folder_count=0)

        with tempfile.TemporaryDirectory() as temp_dir:
            store = StateStore(Path(temp_dir) / "state.sqlite3")
            item = QuarkLink(
                original_url="https://pan.quark.cn/s/abc123",
                normalized_url="https://pan.quark.cn/s/abc123",
            )
            store.upsert_extracted(item)
            store.update(
                item.key,
                "FAILED",
                metadata={
                    "new_shares": [{"url": "https://pan.quark.cn/s/new123"}],
                    "target_root": "/推文分享/0001_资料",
                    "saved_items": [{"fid": "file-1", "name": "资料.zip", "is_dir": False}],
                },
                error="temporary validation error",
            )
            xlsx = Path(temp_dir) / "result.xlsx"
            export_rows([_row_from_store(1, item, store)], xlsx)
            args = argparse.Namespace(
                calculate_sizes=True,
                size_delay_seconds=0,
                size_request_retries=3,
                size_retry_delay_seconds=0,
                size_checkpoint_every=10,
                source_url="",
                xlsx=str(xlsx),
            )

            _backfill_quark_sizes(Adapter(), [item], store, args)

            metadata = json.loads(store.get(item.key)["metadata_json"])
            self.assertEqual(metadata["total_size_bytes"], 4096)
            self.assertEqual(metadata["total_size_display"], "4.00 KB")


if __name__ == "__main__":
    unittest.main()
