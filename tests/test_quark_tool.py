import tempfile
import unittest
from pathlib import Path

from xpan_auto.models import QuarkLink
from xpan_auto.quark_tool import tool_input_url, write_quark_url_file


class QuarkToolInputTests(unittest.TestCase):
    def test_adds_labeled_passcode_as_pwd_query(self):
        item = QuarkLink(
            original_url="https://pan.quark.cn/s/abc123",
            normalized_url="https://pan.quark.cn/s/abc123",
            passcode="a1b2",
        )
        self.assertEqual(tool_input_url(item), "https://pan.quark.cn/s/abc123?pwd=a1b2")

    def test_preserves_url_passcode(self):
        item = QuarkLink(
            original_url="https://pan.quark.cn/s/abc123?pwd=z9x8",
            normalized_url="https://pan.quark.cn/s/abc123?pwd=z9x8",
            passcode="other",
        )
        self.assertEqual(tool_input_url(item), item.normalized_url)

    def test_writes_one_url_per_line(self):
        items = [
            QuarkLink("https://pan.quark.cn/s/a", "https://pan.quark.cn/s/a"),
            QuarkLink("https://pan.quark.cn/s/b", "https://pan.quark.cn/s/b", "1234"),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            output = write_quark_url_file(items, Path(temp_dir) / "nested" / "url.txt")
            self.assertEqual(
                output.read_text(encoding="utf-8"),
                "https://pan.quark.cn/s/a\nhttps://pan.quark.cn/s/b?pwd=1234\n",
            )
