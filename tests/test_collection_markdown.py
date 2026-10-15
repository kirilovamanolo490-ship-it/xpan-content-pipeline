import stat
import tempfile
import unittest
from pathlib import Path

from xpan_auto.knowledge_flow import Entry, append_entries_to_md, parse_markdown


class CollectionMarkdownTests(unittest.TestCase):
    def test_parse_markdown_deduplicates_link_only_rows(self) -> None:
        url = "https://pan.quark.cn/s/repeated-id"
        entries = parse_markdown(
            "# 📆 10/12\n\n" + "\n\n".join([url] * 200) + "\n"
        )

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].share_id, "repeated-id")
        self.assertEqual(entries[0].date, "10/12")

    def test_append_compacts_duplicates_once_and_preserves_first_entry(self) -> None:
        duplicate_url = "https://pan.quark.cn/s/repeated-id"
        old_url = "https://pan.quark.cn/s/old-id"
        new_url = "https://pan.quark.cn/s/new-id"
        with tempfile.TemporaryDirectory() as directory:
            md_path = Path(directory) / "collection.md"
            md_path.write_text(
                "# 📆 10/12\n\n"
                + "\n\n".join([duplicate_url] * 5000)
                + f"\n\n# 📆 10/11\n\n{duplicate_url}\n\nOlder title\n\n{old_url}\n",
                encoding="utf-8",
            )
            md_path.chmod(0o640)
            original_mode = stat.S_IMODE(md_path.stat().st_mode)

            result = append_entries_to_md(
                md_path,
                [Entry("10/12", "New title", new_url)],
            )
            compacted = md_path.read_text(encoding="utf-8")
            entries = parse_markdown(compacted)
            by_id = {entry.share_id: entry for entry in entries}

            self.assertEqual(result, (1, 5000))
            self.assertEqual(set(by_id), {"repeated-id", "old-id", "new-id"})
            self.assertEqual(by_id["repeated-id"].date, "10/12")
            self.assertEqual(by_id["old-id"].title, "Older title")
            self.assertEqual(compacted.count(duplicate_url), 1)
            self.assertLess(compacted.index("# 📆 10/12"), compacted.index("# 📆 10/11"))
            self.assertEqual(stat.S_IMODE(md_path.stat().st_mode), original_mode)

            before = md_path.read_bytes()
            self.assertEqual(append_entries_to_md(md_path, []), (0, 0))
            self.assertEqual(md_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
