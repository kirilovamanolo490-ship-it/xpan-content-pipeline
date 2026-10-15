import json
import tempfile
import unittest
from pathlib import Path

from xpan_auto.models import QuarkLink
from xpan_auto.state import StateStore


class StateStoreTests(unittest.TestCase):
    def test_state_store_upserts_and_lists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = StateStore(Path(temp_dir) / "state.sqlite3")
            item = QuarkLink(
                original_url="https://pan.quark.cn/s/abc123",
                normalized_url="https://pan.quark.cn/s/abc123",
                passcode="A1B2",
            )

            store.upsert_extracted(item)
            store.upsert_extracted(item)
            jobs = store.list_jobs()

            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0]["status"], "EXTRACTED")
            self.assertEqual(jobs[0]["passcode"], "A1B2")

    def test_pwd_query_does_not_change_job_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = StateStore(Path(temp_dir) / "state.sqlite3")
            first = QuarkLink(
                original_url="https://pan.quark.cn/s/abc123",
                normalized_url="https://pan.quark.cn/s/abc123",
            )
            second = QuarkLink(
                original_url="https://pan.quark.cn/s/abc123?pwd=A1B2",
                normalized_url="https://pan.quark.cn/s/abc123?pwd=A1B2",
                passcode="A1B2",
            )

            store.upsert_extracted(first)
            store.upsert_extracted(second)

            self.assertEqual(len(store.list_jobs()), 1)

    def test_update_metadata_merges_with_existing_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = StateStore(Path(temp_dir) / "state.sqlite3")
            item = QuarkLink(
                original_url="https://pan.quark.cn/s/abc123",
                normalized_url="https://pan.quark.cn/s/abc123",
            )

            store.upsert_extracted(item)
            store.update(item.key, "SHARE_VALIDATED", metadata={"share_url": "https://pan.quark.cn/s/abc123"})
            store.update_metadata(item.key, {"typefully": {"draft_id": "draft-1"}}, status="TYPEFULLY_DRAFT_CREATED")

            row = store.get(item.key)
            self.assertIsNotNone(row)
            self.assertEqual(row["status"], "TYPEFULLY_DRAFT_CREATED")
            metadata = json.loads(row["metadata_json"])
            self.assertEqual(metadata["share_url"], "https://pan.quark.cn/s/abc123")
            self.assertEqual(metadata["typefully"]["draft_id"], "draft-1")

    def test_update_without_metadata_preserves_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = StateStore(Path(temp_dir) / "state.sqlite3")
            item = QuarkLink(
                original_url="https://pan.quark.cn/s/abc123",
                normalized_url="https://pan.quark.cn/s/abc123",
            )

            store.upsert_extracted(item)
            store.update(item.key, "SAVED", metadata={"saved_items": [{"fid": "saved-1"}]})
            store.update(item.key, "FAILED", error="temporary network error")

            row = store.get(item.key)
            self.assertIsNotNone(row)
            self.assertEqual(json.loads(row["metadata_json"])["saved_items"][0]["fid"], "saved-1")
