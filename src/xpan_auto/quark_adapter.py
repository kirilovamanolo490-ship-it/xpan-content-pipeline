from __future__ import annotations

import ast
import json
import random
import secrets
import string
import time
from dataclasses import dataclass
from http.client import IncompleteRead
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen


BASE_URL = "https://drive-pc.quark.cn"
SAVE_BASE_URL = "https://drive.quark.cn"
WEB_BASE_URL = "https://pan.quark.cn"
QUARK_WEB_HOSTS = {"pan.quark.cn", "www.pan.quark.cn"}
SHARE_EXPIRY_TYPES = {
    "1d": 2,
    "7d": 3,
    "30d": 4,
    "permanent": 1,
}


class QuarkAPIError(RuntimeError):
    """An error returned by the Quark web API or transport layer."""

    def __init__(self, message: str, *, code: Any = None, status: Any = None):
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class QuarkItem:
    fid: str
    name: str
    is_dir: bool
    pdir_fid: str = "0"
    share_fid_token: str = ""
    include_items: int | str | None = None
    size_bytes: int | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "QuarkItem":
        fid = str(payload.get("fid") or "")
        if not fid:
            raise QuarkAPIError("夸克返回的文件项缺少 fid")
        return cls(
            fid=fid,
            name=str(payload.get("file_name") or payload.get("name") or ""),
            is_dir=bool(payload.get("dir")),
            pdir_fid=str(payload.get("pdir_fid") or "0"),
            share_fid_token=str(payload.get("share_fid_token") or ""),
            include_items=payload.get("include_items"),
            size_bytes=(
                _as_int(payload.get("size"))
                if payload.get("size") is not None
                else (
                    _as_int(payload.get("file_size"))
                    if payload.get("file_size") is not None
                    else None
                )
            ),
        )


@dataclass(frozen=True)
class ShareInfo:
    pwd_id: str
    is_owner: bool
    items: tuple[QuarkItem, ...]


@dataclass(frozen=True)
class SaveResult:
    task_id: str
    target_folder_id: str
    items: tuple[QuarkItem, ...]


@dataclass(frozen=True)
class NewShare:
    fid: str
    title: str
    share_url: str
    passcode: str | None = None


@dataclass(frozen=True)
class UsageSummary:
    total_bytes: int
    file_count: int
    folder_count: int


RequestFn = Callable[
    [str, str, dict[str, str], dict[str, str], dict[str, Any] | None, float],
    dict[str, Any],
]


def load_cookie_header(path: str | Path) -> str:
    """Load a Playwright storage-state file or a plain cookie header.

    The parser also accepts the legacy list representation emitted by
    QuarkPanTool. It never logs or returns the cookie contents to callers.
    """

    cookie_path = Path(path)
    raw = cookie_path.read_text(encoding="utf-8").strip()
    if not raw:
        raise ValueError(f"夸克认证文件为空：{cookie_path}")

    parsed: Any = None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        try:
            parsed = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            parsed = None

    if isinstance(parsed, dict) and isinstance(parsed.get("cookies"), list):
        parsed = parsed["cookies"]

    if isinstance(parsed, list):
        values: dict[str, str] = {}
        for item in parsed:
            if not isinstance(item, dict):
                continue
            domain = str(item.get("domain") or "").lower()
            if domain and "quark.cn" not in domain:
                continue
            name = str(item.get("name") or "")
            if name:
                values[name] = str(item.get("value") or "")
        if values:
            return "; ".join(f"{name}={value}" for name, value in values.items())

    if isinstance(parsed, dict):
        values = {
            str(name): str(value)
            for name, value in parsed.items()
            if str(name) and not isinstance(value, (dict, list))
        }
        if values:
            return "; ".join(f"{name}={value}" for name, value in values.items())

    if "=" in raw:
        return raw
    raise ValueError(f"无法识别夸克认证文件格式：{cookie_path}")


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _random_passcode(length: int = 4) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


class QuarkAdapter:
    """Small, resumable wrapper around the authenticated Quark web API.

    ``request_fn`` is intentionally injectable so all request orchestration can
    be tested without touching a real account. Production calls use urllib and
    the locally stored cookie header.
    """

    def __init__(
        self,
        *,
        cookie_header: str | None = None,
        cookie_file: str | Path | None = None,
        request_fn: RequestFn | None = None,
        timeout: float = 45.0,
        min_interval: float = 0.8,
        poll_interval: float = 1.2,
        read_retries: int = 3,
        retry_delay_seconds: float = 3.0,
        sleep_fn: Callable[[float], None] = time.sleep,
    ):
        if cookie_header is None and cookie_file is not None:
            cookie_header = load_cookie_header(cookie_file)
        if cookie_header is None and request_fn is None:
            raise ValueError("夸克操作需要 cookie_file 或 cookie_header")

        self.cookie_header = cookie_header or ""
        self.request_fn = request_fn
        self.timeout = timeout
        self.min_interval = min_interval
        self.poll_interval = poll_interval
        self.read_retries = max(1, read_retries)
        self.retry_delay_seconds = max(0.0, retry_delay_seconds)
        self.sleep_fn = sleep_fn
        self._last_mutation = 0.0
        self.headers = {
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/94.0.4606.71 Safari/537.36 "
                "Core/1.94.225.400 QQBrowser/12.2.5544.400"
            ),
            "origin": "https://pan.quark.cn",
            "referer": "https://pan.quark.cn/",
            "accept-language": "zh-CN,zh;q=0.9",
            "cookie": self.cookie_header,
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        common_params: bool = True,
        mutation: bool = False,
        base_url: str = BASE_URL,
    ) -> dict[str, Any]:
        if mutation:
            elapsed = time.monotonic() - self._last_mutation
            if elapsed < self.min_interval:
                self.sleep_fn(self.min_interval - elapsed)
            self._last_mutation = time.monotonic()

        request_params: dict[str, Any] = {}
        if common_params:
            request_params.update({"pr": "ucpro", "fr": "pc", "uc_param_str": ""})
        if params:
            request_params.update(params)
        url = f"{base_url}{path}"

        if self.request_fn is not None:
            response = self.request_fn(
                method,
                url,
                dict(self.headers),
                {str(k): str(v) for k, v in request_params.items()},
                payload,
                self.timeout,
            )
            return self._check_response(response)

        query = urlencode(request_params)
        request_url = f"{url}?{query}" if query else url
        body = None
        headers = dict(self.headers)
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(request_url, data=body, headers=headers, method=method)
        attempts = 1 if mutation else self.read_retries
        for attempt in range(attempts):
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    raw = response.read().decode("utf-8", errors="replace")
                break
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                raise QuarkAPIError(f"夸克 HTTP {exc.code}: {detail[:300]}", status=exc.code) from exc
            except (URLError, IncompleteRead, TimeoutError, OSError) as exc:
                if attempt + 1 < attempts:
                    if self.retry_delay_seconds > 0:
                        self.sleep_fn(self.retry_delay_seconds)
                    continue
                reason = getattr(exc, "reason", str(exc))
                raise QuarkAPIError(f"夸克网络请求失败：{reason}") from exc

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise QuarkAPIError(f"夸克返回了非 JSON 内容：{raw[:200]}") from exc
        return self._check_response(parsed)

    @staticmethod
    def _check_response(response: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(response, dict):
            raise QuarkAPIError("夸克返回格式不是对象")
        code = response.get("code")
        status = response.get("status")
        bad_code = code not in (None, 0, "0", "OK", "ok")
        bad_status = status not in (None, 0, 200, "0", "200")
        if bad_code or bad_status:
            message = response.get("message") or response.get("error")
            if not message:
                message = f"夸克接口返回失败 code={code!r} status={status!r}"
            raise QuarkAPIError(
                str(message),
                code=code,
                status=status,
            )
        return response

    def whoami(self) -> str:
        response = self._request(
            "GET",
            "/account/info",
            params={"fr": "pc", "platform": "pc"},
            common_params=False,
            base_url=WEB_BASE_URL,
        )
        data = response.get("data") or {}
        nickname = data.get("nickname")
        if not nickname:
            raise QuarkAPIError("夸克登录状态无效或账号信息为空")
        return str(nickname)

    @staticmethod
    def _pwd_id(share_url: str) -> str:
        parts = urlsplit(share_url)
        if parts.netloc.lower() not in QUARK_WEB_HOSTS:
            raise ValueError("只允许处理 pan.quark.cn 分享链接")
        path_parts = [part for part in parts.path.split("/") if part]
        try:
            share_index = next(index for index, part in enumerate(path_parts) if part.lower() == "s")
        except StopIteration as exc:
            raise ValueError("夸克分享链接缺少 /s/ 分享 ID") from exc
        if share_index + 1 >= len(path_parts):
            raise ValueError("夸克分享链接缺少分享 ID")
        return path_parts[share_index + 1]

    @staticmethod
    def _passcode(share_url: str) -> str:
        query = parse_qs(urlsplit(share_url).query)
        return (query.get("pwd") or query.get("passcode") or [""])[0]

    def _get_stoken(self, pwd_id: str, passcode: str) -> str:
        response = self._request(
            "POST",
            "/1/clouddrive/share/sharepage/token",
            params={"__dt": str(random.randint(100, 9999)), "__t": str(int(time.time() * 1000))},
            payload={"pwd_id": pwd_id, "passcode": passcode},
            mutation=True,
        )
        stoken = str((response.get("data") or {}).get("stoken") or "")
        if not stoken:
            raise QuarkAPIError("夸克分享 token 获取失败，链接可能已失效或需要提取码")
        return stoken

    def _share_detail(self, pwd_id: str, stoken: str, pdir_fid: str = "0") -> tuple[bool, list[QuarkItem]]:
        page = 1
        items: list[QuarkItem] = []
        is_owner = False
        while True:
            response = self._request(
                "GET",
                "/1/clouddrive/share/sharepage/detail",
                params={
                    "pwd_id": pwd_id,
                    "stoken": stoken,
                    "pdir_fid": pdir_fid,
                    "force": "0",
                    "_page": str(page),
                    "_size": "50",
                    "_sort": "file_type:asc,updated_at:desc",
                    "__dt": str(random.randint(200, 9999)),
                    "__t": str(int(time.time() * 1000)),
                },
            )
            data = response.get("data") or {}
            is_owner = bool(data.get("is_owner"))
            page_items = data.get("list") or []
            items.extend(QuarkItem.from_payload(item) for item in page_items)
            metadata = response.get("metadata") or {}
            total = _as_int(metadata.get("_total"), len(items))
            size = _as_int(metadata.get("_size"), 50)
            count = _as_int(metadata.get("_count"), len(page_items))
            if not page_items or len(items) >= total or count < size:
                break
            page += 1
        return is_owner, items

    def inspect_share(self, share_url: str) -> ShareInfo:
        pwd_id = self._pwd_id(share_url)
        stoken = self._get_stoken(pwd_id, self._passcode(share_url))
        is_owner, items = self._share_detail(pwd_id, stoken)
        return ShareInfo(pwd_id=pwd_id, is_owner=is_owner, items=tuple(items))

    def list_folder(self, folder_id: str = "0") -> list[QuarkItem]:
        page = 1
        items: list[QuarkItem] = []
        while True:
            response = self._request(
                "GET",
                "/1/clouddrive/file/sort",
                params={
                    "pdir_fid": folder_id,
                    "_page": str(page),
                    "_size": "100",
                    "_fetch_total": "1",
                    "_fetch_sub_dirs": "1",
                    # Keep API order for directory structure and fallback
                    # evidence. Publish code selects semantic lesson order
                    # after the complete tree has been collected.
                    "_sort": "file_type:asc,updated_at:desc",
                    "__dt": str(random.randint(100, 9999)),
                    "__t": str(int(time.time() * 1000)),
                },
            )
            data = response.get("data") or {}
            page_items = data.get("list") or []
            items.extend(QuarkItem.from_payload(item) for item in page_items)
            metadata = response.get("metadata") or {}
            total = _as_int(metadata.get("_total"), len(items))
            size = _as_int(metadata.get("_size"), 100)
            current_page = _as_int(metadata.get("_page"), page)
            if not page_items or len(items) >= total or size * current_page >= total:
                break
            page += 1
        return items

    def calculate_usage(
        self,
        items: list[QuarkItem] | tuple[QuarkItem, ...],
        *,
        folder_delay_seconds: float = 0.0,
        folder_retries: int = 3,
        retry_delay_seconds: float = 5.0,
    ) -> UsageSummary:
        """Recursively sum leaf-file bytes for saved Quark items.

        Quark reports directory ``size`` as zero, so directory totals must be
        calculated from their descendants. FIDs are de-duplicated to avoid
        double counting if an item appears more than once in a response.
        """

        if folder_delay_seconds < 0:
            raise ValueError("folder_delay_seconds cannot be negative")
        if folder_retries < 1:
            raise ValueError("folder_retries must be positive")
        if retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds cannot be negative")

        pending_dirs: list[QuarkItem] = []
        pending_files: list[QuarkItem] = []
        for item in items:
            (pending_dirs if item.is_dir else pending_files).append(item)

        seen_dirs: set[str] = set()
        seen_files: set[str] = set()
        total_bytes = 0
        folder_cache: dict[str, list[QuarkItem]] = {}

        def folder_children(folder_id: str) -> list[QuarkItem]:
            if folder_id in folder_cache:
                return folder_cache[folder_id]
            if folder_cache and folder_delay_seconds > 0:
                self.sleep_fn(folder_delay_seconds)
            for attempt in range(folder_retries):
                try:
                    children = self.list_folder(folder_id)
                    break
                except (QuarkAPIError, OSError):
                    if attempt == folder_retries - 1:
                        raise
                    if retry_delay_seconds > 0:
                        self.sleep_fn(retry_delay_seconds)
            folder_cache[folder_id] = children
            return children

        while pending_dirs:
            directory = pending_dirs.pop()
            if not directory.fid or directory.fid in seen_dirs:
                continue
            seen_dirs.add(directory.fid)
            for child in folder_children(directory.fid):
                (pending_dirs if child.is_dir else pending_files).append(child)

        for file_item in pending_files:
            if not file_item.fid or file_item.fid in seen_files:
                continue
            resolved = file_item
            if resolved.size_bytes is None:
                resolved = next(
                    (
                        candidate
                        for candidate in folder_children(resolved.pdir_fid or "0")
                        if candidate.fid == resolved.fid
                    ),
                    resolved,
                )
            if resolved.size_bytes is None:
                raise QuarkAPIError(f"夸克文件大小缺失：{resolved.name or resolved.fid}")
            seen_files.add(resolved.fid)
            total_bytes += max(0, resolved.size_bytes)

        return UsageSummary(
            total_bytes=total_bytes,
            file_count=len(seen_files),
            folder_count=len(seen_dirs),
        )

    def _create_folder(self, parent_id: str, name: str) -> str:
        response = self._request(
            "POST",
            "/1/clouddrive/file",
            payload={
                "pdir_fid": parent_id,
                "file_name": name,
                "dir_path": "",
                "dir_init_lock": False,
            },
            mutation=True,
        )
        fid = str((response.get("data") or {}).get("fid") or "")
        if not fid:
            raise QuarkAPIError(f"夸克目录创建失败：{name}")
        return fid

    def ensure_folder(self, folder_path: str) -> str:
        parts = [part for part in folder_path.replace("\\", "/").split("/") if part]
        current = "0"
        for name in parts:
            existing = next(
                (item for item in self.list_folder(current) if item.is_dir and item.name == name),
                None,
            )
            current = existing.fid if existing else self._create_folder(current, name)
        return current

    def rename_item(self, fid: str, file_name: str) -> None:
        if not fid:
            raise ValueError("夸克重命名需要文件或目录 fid")
        if not file_name.strip():
            raise ValueError("夸克重命名需要非空名称")
        self._request(
            "POST",
            "/1/clouddrive/file/rename",
            payload={"fid": fid, "file_name": file_name},
            mutation=True,
        )

    def _task_id(self, response: dict[str, Any]) -> str:
        task_id = str((response.get("data") or {}).get("task_id") or "")
        if not task_id:
            raise QuarkAPIError("夸克未返回任务 ID")
        return task_id

    def wait_task(self, task_id: str, *, max_polls: int = 50) -> dict[str, Any]:
        last: dict[str, Any] = {}
        for retry_index in range(max_polls):
            last = self._request(
                "GET",
                "/1/clouddrive/task",
                params={
                    "task_id": task_id,
                    "retry_index": str(retry_index),
                    "__dt": "21192",
                    "__t": str(int(time.time() * 1000)),
                },
            )
            data = last.get("data") or {}
            status = data.get("status")
            if status in (2, "2", "success", "done", "completed"):
                return last
            if status in (-1, 3, "-1", "3", "failed", "error"):
                raise QuarkAPIError(str(last.get("message") or "夸克任务失败"))
            self.sleep_fn(self.poll_interval)
        raise QuarkAPIError(f"夸克任务超时：{task_id}，最后状态={last.get('data')}")

    def save_share(self, share_url: str, target_folder_id: str) -> SaveResult:
        pwd_id = self._pwd_id(share_url)
        passcode = self._passcode(share_url)
        stoken = self._get_stoken(pwd_id, passcode)
        _is_owner, share_items = self._share_detail(pwd_id, stoken)
        if not share_items:
            raise QuarkAPIError("夸克分享内容为空，无法转存")

        before = self.list_folder(target_folder_id)
        payload = {
            "fid_list": [item.fid for item in share_items],
            "fid_token_list": [item.share_fid_token for item in share_items],
            "to_pdir_fid": target_folder_id,
            "pwd_id": pwd_id,
            "stoken": stoken,
            "pdir_fid": "0",
            "scene": "link",
        }
        response = self._request(
            "POST",
            "/1/clouddrive/share/sharepage/save",
            payload=payload,
            params={"__dt": str(random.randint(600, 9999)), "__t": str(int(time.time() * 1000))},
            mutation=True,
            base_url=SAVE_BASE_URL,
        )
        task_id = self._task_id(response)
        self.wait_task(task_id)

        saved_items: list[QuarkItem] = []
        for _ in range(10):
            after = self.list_folder(target_folder_id)
            before_ids = {item.fid for item in before}
            saved_items = [item for item in after if item.fid not in before_ids]
            if saved_items:
                break
            self.sleep_fn(self.poll_interval)

        return SaveResult(
            task_id=task_id,
            target_folder_id=target_folder_id,
            items=tuple(saved_items),
        )

    def create_share(
        self,
        item: QuarkItem,
        *,
        expiry: str = "permanent",
        password_mode: str = "none",
        password: str | None = None,
    ) -> NewShare:
        if expiry not in SHARE_EXPIRY_TYPES:
            raise ValueError(f"不支持的分享有效期：{expiry}")
        if password_mode not in {"none", "generated", "fixed"}:
            raise ValueError(f"不支持的分享密码模式：{password_mode}")
        passcode = password if password_mode == "fixed" else None
        if password_mode == "generated":
            passcode = _random_passcode()
        url_type = 2 if passcode else 1
        payload: dict[str, Any] = {
            "fid_list": [item.fid],
            "title": item.name,
            "url_type": url_type,
            "expired_type": SHARE_EXPIRY_TYPES[expiry],
        }
        if passcode:
            payload["passcode"] = passcode

        task_response = self._request(
            "POST",
            "/1/clouddrive/share",
            payload=payload,
            mutation=True,
        )
        task_id = self._task_id(task_response)
        task = self.wait_task(task_id)
        task_data = task.get("data") or {}
        share_id = str(task_data.get("share_id") or "")
        if not share_id:
            raise QuarkAPIError("夸克分享任务完成但未返回 share_id")

        response = self._request(
            "POST",
            "/1/clouddrive/share/password",
            payload={"share_id": share_id},
            mutation=True,
        )
        data = response.get("data") or {}
        share_url = str(data.get("share_url") or "")
        if not share_url:
            raise QuarkAPIError("夸克新分享创建成功但未返回 share_url")
        returned_passcode = str(data.get("passcode") or passcode or "") or None
        if returned_passcode and "pwd=" not in share_url:
            share_url = f"{share_url}?{urlencode({'pwd': returned_passcode})}"
        return NewShare(
            fid=item.fid,
            title=str(data.get("title") or item.name),
            share_url=share_url,
            passcode=returned_passcode,
        )

    def validate_share(self, share: NewShare) -> bool:
        """Perform a lightweight public-page reachability check without cookies."""

        request = Request(
            share.share_url,
            headers={"User-Agent": self.headers["user-agent"]},
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return 200 <= int(response.status) < 400
        except (HTTPError, URLError):
            return False
