import json
import tempfile
import unittest
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from xpan_auto.knowledge_flow import (
    Entry,
    _entries_after_collection_watermark,
    load_scrape_markdown,
)


def _entry(date: str, share_id: str) -> Entry:
    return Entry(date=date, title=share_id, url=f"https://pan.quark.cn/s/{share_id}")


def _feishu_page(*blocks: tuple[str, str]) -> str:
    block_map = {
        "page": {"data": {"type": "page", "children": [f"block-{index}" for index in range(len(blocks))]}},
    }
    for index, (block_type, text) in enumerate(blocks):
        block_map[f"block-{index}"] = {
            "data": {
                "type": block_type,
                "text": {"initialAttributedTexts": {"text": {"0": text}}},
            }
        }
    return "<script>clientVars: Object(" + json.dumps({"data": {"block_map": block_map}}) + ")</script>"


class CollectionWatermarkTests(unittest.TestCase):
    def test_native_fetch_keeps_cookie_across_redirects(self):
        from xpan_auto.knowledge_flow import _fetch_feishu_html, _extract_feishu_markdown
        body = _feishu_page(("heading1", "📆 09/07"), ("text", "中文资料"))

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.headers.get("Cookie") != "visited=yes":
                    self.send_response(302)
                    self.send_header("Location", "/page")
                    self.send_header("Set-Cookie", "visited=yes; Path=/")
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(body.encode("utf-8"))

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = _fetch_feishu_html(f"http://127.0.0.1:{server.server_port}/page")
            self.assertIn("中文资料", _extract_feishu_markdown(result))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_load_scrape_markdown_accepts_current_raw_markdown_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scrape_file = Path(directory) / "feishu.md"
            scrape_file.write_text("# 📆 08/21\n", encoding="utf-8")

            self.assertEqual(load_scrape_markdown(scrape_file), "# 📆 08/21\n")

    @patch("xpan_auto.knowledge_flow._fetch_feishu_html")
    def test_scrape_accepts_latest_available_date_without_today(self, fetch) -> None:
        from xpan_auto.knowledge_flow import scrape_feishu

        with tempfile.TemporaryDirectory() as directory:
            scrape_file = Path(directory) / "source.json"
            fetch.return_value = _feishu_page(
                ("heading1", "📆 08/21"),
                ("text", "资料"),
                ("text", "https://pan.quark.cn/s/test-link"),
            )
            scrape_feishu(
                "https://example.test/feishu",
                scrape_file,
            )
            self.assertEqual(
                load_scrape_markdown(scrape_file),
                "# 📆 08/21\n资料\nhttps://pan.quark.cn/s/test-link",
            )

        self.assertEqual(fetch.call_count, 1)

    @patch("xpan_auto.knowledge_flow.time.sleep")
    @patch("xpan_auto.knowledge_flow._fetch_feishu_html")
    def test_scrape_retries_invalid_ssr_before_accepting_content(self, fetch, sleep) -> None:
        from xpan_auto.knowledge_flow import scrape_feishu

        with tempfile.TemporaryDirectory() as directory:
            scrape_file = Path(directory) / "source.json"
            fetch.side_effect = [
                "<html>not a feishu SSR page</html>",
                _feishu_page(
                    ("heading1", "📆 08/22"),
                    ("text", "资料"),
                    ("text", "https://pan.quark.cn/s/retry-link"),
                ),
            ]
            scrape_feishu(
                "https://example.test/feishu",
                scrape_file,
            )

        self.assertEqual(fetch.call_count, 2)
        sleep.assert_called_once_with(2)

    def test_selects_newer_dates_and_current_date(self) -> None:
        source = [
            _entry("08/20", "new-20"),
            _entry("08/19", "new-19"),
            _entry("08/18", "old-18"),
            _entry("08/18", "new-18"),
            _entry("08/17", "old-17"),
        ]
        selected, watermark, dates = _entries_after_collection_watermark(
            source, [_entry("08/18", "already-18")]
        )

        self.assertEqual(watermark, "08/18")
        self.assertEqual(dates, ["08/20", "08/19", "08/18"])
        self.assertEqual(
            [item.share_id for item in selected],
            ["new-20", "new-19", "old-18", "new-18"],
        )

    def test_bootstrap_only_selects_latest_date(self) -> None:
        source = [_entry("08/20", "new-20"), _entry("08/19", "old-19")]

        selected, watermark, dates = _entries_after_collection_watermark(source, [])

        self.assertEqual(watermark, "")
        self.assertEqual(dates, ["08/20"])
        self.assertEqual([item.share_id for item in selected], ["new-20"])

    def test_missing_watermark_selects_only_dates_after_it(self) -> None:
        source = [
            _entry("08/20", "new-20"),
            _entry("08/19", "new-19"),
            _entry("08/17", "old-17"),
        ]

        selected, watermark, dates = _entries_after_collection_watermark(
            source, [_entry("08/18", "already-18")]
        )

        self.assertEqual(watermark, "08/18")
        self.assertEqual(dates, ["08/20", "08/19"])
        self.assertEqual([item.share_id for item in selected], ["new-20", "new-19"])


if __name__ == "__main__":
    unittest.main()
