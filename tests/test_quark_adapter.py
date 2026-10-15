import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError
from urllib.parse import urlsplit

from xpan_auto.quark_adapter import QuarkAdapter, QuarkItem, load_cookie_header


class QuarkAdapterTests(unittest.TestCase):
    def test_read_request_retries_transient_network_error(self):
        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"status": 200, "data": {"ok": true}}'

        sleeps = []
        adapter = QuarkAdapter(
            cookie_header="cookie",
            read_retries=2,
            retry_delay_seconds=1,
            sleep_fn=sleeps.append,
        )
        with patch("xpan_auto.quark_adapter.urlopen", side_effect=[URLError("temporary TLS"), Response()]) as mocked:
            result = adapter._request("GET", "/test")

        self.assertTrue(result["data"]["ok"])
        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(sleeps, [1])

    def test_mutation_request_does_not_retry_network_error(self):
        adapter = QuarkAdapter(cookie_header="cookie", read_retries=3, retry_delay_seconds=0)
        with patch("xpan_auto.quark_adapter.urlopen", side_effect=URLError("temporary TLS")) as mocked:
            with self.assertRaises(Exception):
                adapter._request("POST", "/test", payload={"x": 1}, mutation=True)

        self.assertEqual(mocked.call_count, 1)

    def test_whoami_uses_web_account_endpoint(self):
        calls = []

        def request(method, url, headers, params, payload, timeout):
            calls.append((method, urlsplit(url).netloc, urlsplit(url).path))
            return {"status": 200, "data": {"nickname": "测试账号"}}

        adapter = QuarkAdapter(request_fn=request, min_interval=0, poll_interval=0)
        self.assertEqual(adapter.whoami(), "测试账号")
        self.assertEqual(calls, [("GET", "pan.quark.cn", "/account/info")])

    def test_loads_playwright_storage_state_without_exposing_other_domains(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "storage.json"
            path.write_text(
                json.dumps(
                    {
                        "cookies": [
                            {"name": "quark_sid", "value": "secret", "domain": ".quark.cn"},
                            {"name": "other", "value": "ignore", "domain": ".example.com"},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            header = load_cookie_header(path)

        self.assertEqual(header, "quark_sid=secret")

    def test_inspect_share_keeps_optional_source_passcode_empty(self):
        calls = []

        def request(method, url, headers, params, payload, timeout):
            calls.append((method, urlsplit(url).path, params, payload))
            path = urlsplit(url).path
            if path.endswith("/sharepage/token"):
                return {"status": 200, "data": {"stoken": "token"}}
            if path.endswith("/sharepage/detail"):
                return {
                    "status": 200,
                    "data": {
                        "is_owner": 0,
                        "list": [{
                            "fid": "source-fid",
                            "file_name": "资料文件夹",
                            "dir": True,
                            "pdir_fid": "0",
                            "share_fid_token": "share-token",
                        }],
                    },
                    "metadata": {"_total": 1, "_size": 50, "_count": 1},
                }
            raise AssertionError(path)

        adapter = QuarkAdapter(request_fn=request, min_interval=0, poll_interval=0)
        info = adapter.inspect_share("https://pan.quark.cn/s/source-id")

        self.assertEqual(info.pwd_id, "source-id")
        self.assertEqual(len(info.items), 1)
        token_call = next(call for call in calls if call[1].endswith("/sharepage/token"))
        self.assertEqual(token_call[3], {"pwd_id": "source-id", "passcode": ""})

    def test_create_share_without_password_uses_public_policy(self):
        calls = []

        def request(method, url, headers, params, payload, timeout):
            path = urlsplit(url).path
            calls.append((method, path, payload))
            if path == "/1/clouddrive/share":
                return {"status": 200, "data": {"task_id": "share-task"}}
            if path == "/1/clouddrive/task":
                return {"status": 200, "data": {"status": 2, "share_id": "share-id"}}
            if path == "/1/clouddrive/share/password":
                return {"status": 200, "data": {"share_url": "https://pan.quark.cn/s/new-id", "title": "资料文件夹"}}
            raise AssertionError(path)

        adapter = QuarkAdapter(request_fn=request, min_interval=0, poll_interval=0)
        share = adapter.create_share(
            QuarkItem(fid="saved-fid", name="资料文件夹", is_dir=True),
            expiry="permanent",
            password_mode="none",
        )

        self.assertEqual(share.share_url, "https://pan.quark.cn/s/new-id")
        self.assertIsNone(share.passcode)
        share_payload = next(payload for method, path, payload in calls if path == "/1/clouddrive/share")
        self.assertEqual(share_payload["url_type"], 1)
        self.assertNotIn("passcode", share_payload)

    def test_save_share_returns_only_new_target_items(self):
        list_calls = 0

        def request(method, url, headers, params, payload, timeout):
            nonlocal list_calls
            path = urlsplit(url).path
            if path.endswith("/sharepage/token"):
                return {"status": 200, "data": {"stoken": "token"}}
            if path.endswith("/sharepage/detail"):
                return {
                    "status": 200,
                    "data": {
                        "is_owner": 0,
                        "list": [{
                            "fid": "source-fid",
                            "file_name": "资料文件夹",
                            "dir": True,
                            "pdir_fid": "0",
                            "share_fid_token": "share-token",
                        }],
                    },
                    "metadata": {"_total": 1, "_size": 50, "_count": 1},
                }
            if path == "/1/clouddrive/file/sort":
                list_calls += 1
                items = [] if list_calls == 1 else [{
                    "fid": "saved-fid",
                    "file_name": "资料文件夹",
                    "dir": True,
                    "pdir_fid": "target",
                }]
                return {
                    "status": 200,
                    "data": {"list": items},
                    "metadata": {"_total": len(items), "_size": 100, "_page": 1},
                }
            if path.endswith("/sharepage/save"):
                return {"status": 200, "data": {"task_id": "save-task"}}
            if path == "/1/clouddrive/task":
                return {"status": 200, "data": {"status": 2}}
            raise AssertionError(path)

        adapter = QuarkAdapter(request_fn=request, min_interval=0, poll_interval=0)
        result = adapter.save_share("https://pan.quark.cn/s/source-id", "target")

        self.assertEqual(result.task_id, "save-task")
        self.assertEqual([item.fid for item in result.items], ["saved-fid"])

    def test_rename_item_posts_fid_and_name(self):
        calls = []

        def request(method, url, headers, params, payload, timeout):
            calls.append((method, urlsplit(url).path, payload))
            return {"code": 0, "data": {}}

        adapter = QuarkAdapter(request_fn=request, min_interval=0)
        adapter.rename_item("folder-fid", "0001_资料")

        self.assertEqual(
            calls,
            [("POST", "/1/clouddrive/file/rename", {"fid": "folder-fid", "file_name": "0001_资料"})],
        )

    def test_calculate_usage_recursively_sums_only_leaf_file_bytes(self):
        calls = []

        children = {
            "root": [
                {"fid": "folder-a", "file_name": "子目录", "dir": True, "pdir_fid": "root", "size": 0},
                {"fid": "file-1", "file_name": "一.mp4", "dir": False, "pdir_fid": "root", "size": 1024},
            ],
            "folder-a": [
                {"fid": "file-2", "file_name": "二.zip", "dir": False, "pdir_fid": "folder-a", "size": 2048},
            ],
        }

        def request(method, url, headers, params, payload, timeout):
            path = urlsplit(url).path
            self.assertEqual(path, "/1/clouddrive/file/sort")
            folder_id = params["pdir_fid"]
            calls.append(folder_id)
            items = children[folder_id]
            return {
                "status": 200,
                "data": {"list": items},
                "metadata": {"_total": len(items), "_size": 100, "_page": 1},
            }

        adapter = QuarkAdapter(request_fn=request, min_interval=0, poll_interval=0)
        usage = adapter.calculate_usage([
            QuarkItem(fid="root", name="资料", is_dir=True),
        ])

        self.assertEqual(usage.total_bytes, 3072)
        self.assertEqual(usage.file_count, 2)
        self.assertEqual(usage.folder_count, 2)
        self.assertEqual(calls, ["root", "folder-a"])

    def test_calculate_usage_resolves_legacy_top_level_file_size_from_parent(self):
        def request(method, url, headers, params, payload, timeout):
            items = [{
                "fid": "file-1",
                "file_name": "资料.zip",
                "dir": False,
                "pdir_fid": "target",
                "size": 4096,
            }]
            return {
                "status": 200,
                "data": {"list": items},
                "metadata": {"_total": 1, "_size": 100, "_page": 1},
            }

        adapter = QuarkAdapter(request_fn=request, min_interval=0, poll_interval=0)
        usage = adapter.calculate_usage([
            QuarkItem(fid="file-1", name="资料.zip", is_dir=False, pdir_fid="target"),
        ])

        self.assertEqual(usage.total_bytes, 4096)
        self.assertEqual(usage.file_count, 1)
        self.assertEqual(usage.folder_count, 0)

    def test_calculate_usage_retries_only_the_transient_folder_read(self):
        attempts = 0
        sleeps = []

        def request(method, url, headers, params, payload, timeout):
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise OSError("temporary TLS failure")
            items = [{
                "fid": "file-1",
                "file_name": "资料.zip",
                "dir": False,
                "pdir_fid": "root",
                "size": 8192,
            }]
            return {
                "status": 200,
                "data": {"list": items},
                "metadata": {"_total": 1, "_size": 100, "_page": 1},
            }

        adapter = QuarkAdapter(
            request_fn=request,
            min_interval=0,
            poll_interval=0,
            sleep_fn=sleeps.append,
        )
        usage = adapter.calculate_usage(
            [QuarkItem(fid="root", name="资料", is_dir=True)],
            folder_retries=3,
            retry_delay_seconds=2,
        )

        self.assertEqual(usage.total_bytes, 8192)
        self.assertEqual(attempts, 3)
        self.assertEqual(sleeps, [2, 2])
