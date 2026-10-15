from __future__ import annotations

import json
import mimetypes
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class TypefullyAPIError(RuntimeError):
    """Raised when Typefully rejects an API request or the network fails."""

    def __init__(self, message: str, *, status: int | None = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass(frozen=True)
class TypefullyDraft:
    draft_id: str
    status: str
    private_url: str = ""
    share_url: str = ""
    published_url: str = ""
    raw: Mapping[str, Any] | None = None


Transport = Callable[[Request, float], Any]


class TypefullyClient:
    """Small Typefully API v2 client for one-account personal workflows."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.typefully.com",
        timeout: float = 60.0,
        transport: Transport | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        if not api_key.strip():
            raise ValueError("Typefully API key cannot be empty")
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport or (lambda request, timeout: urlopen(request, timeout=timeout))
        self.sleeper = sleeper

    def _request_json(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = None
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method.upper(),
        )
        try:
            response = self.transport(request, self.timeout)
            raw = response.read()
            status = getattr(response, "status", 200)
        except HTTPError as exc:
            raw = exc.read()
            text = raw.decode("utf-8", errors="replace")
            raise TypefullyAPIError(
                f"Typefully API request failed with HTTP {exc.code}",
                status=exc.code,
                body=text,
            ) from exc
        except URLError as exc:
            raise TypefullyAPIError(f"Typefully API network error: {exc.reason}") from exc
        except OSError as exc:
            raise TypefullyAPIError(f"Typefully API network error: {exc}") from exc

        text = raw.decode("utf-8", errors="replace")
        if status < 200 or status >= 300:
            raise TypefullyAPIError(
                f"Typefully API request failed with HTTP {status}",
                status=status,
                body=text,
            )
        if not text.strip():
            return {}
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise TypefullyAPIError("Typefully API returned invalid JSON", status=status, body=text) from exc
        if not isinstance(value, dict):
            raise TypefullyAPIError("Typefully API returned a non-object JSON response", status=status, body=text)
        return value

    def create_media_upload(self, social_set_id: str, file_name: str) -> dict[str, Any]:
        return self._request_json(
            "POST",
            f"/v2/social-sets/{social_set_id}/media/upload",
            {"file_name": file_name},
        )

    def list_social_sets(self) -> dict[str, Any]:
        return self._request_json("GET", "/v2/social-sets")

    def upload_media(self, social_set_id: str, media_path: str | Path) -> str:
        path = Path(media_path)
        if not path.is_file():
            raise FileNotFoundError(f"Media file not found: {path}")
        upload = self.create_media_upload(str(social_set_id), path.name)
        media_id = str(upload.get("media_id") or "")
        upload_url = str(upload.get("upload_url") or "")
        if not media_id or not upload_url:
            raise TypefullyAPIError("Typefully media upload response is missing media_id or upload_url")

        request = Request(upload_url, data=path.read_bytes(), method="PUT")
        try:
            response = self.transport(request, self.timeout)
            response.read()
            status = getattr(response, "status", 200)
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise TypefullyAPIError(
                f"Typefully media upload failed with HTTP {exc.code}",
                status=exc.code,
                body=body,
            ) from exc
        except (URLError, OSError) as exc:
            raise TypefullyAPIError(f"Typefully media upload failed: {exc}") from exc
        if status < 200 or status >= 300:
            raise TypefullyAPIError(f"Typefully media upload failed with HTTP {status}", status=status)
        return media_id

    def get_media(self, social_set_id: str, media_id: str) -> dict[str, Any]:
        return self._request_json(
            "GET",
            f"/v2/social-sets/{social_set_id}/media/{media_id}",
        )

    def wait_for_media(
        self,
        social_set_id: str,
        media_id: str,
        *,
        max_polls: int = 20,
        poll_interval: float = 2.0,
    ) -> dict[str, Any]:
        last: dict[str, Any] = {}
        for poll_index in range(max_polls):
            last = self.get_media(str(social_set_id), media_id)
            status = str(last.get("status") or "").lower()
            if status in {"ready", "completed", "succeeded"}:
                return last
            if status in {"failed", "error"}:
                reason = str(last.get("error_reason") or "unknown media processing error")
                raise TypefullyAPIError(f"Typefully media processing failed: {reason}")
            if poll_index + 1 < max_polls:
                self.sleeper(poll_interval)
        raise TypefullyAPIError(
            f"Typefully media did not become ready after {max_polls} polls",
            body=json.dumps(last, ensure_ascii=False),
        )

    def create_draft(
        self,
        social_set_id: str,
        *,
        text: str,
        media_ids: tuple[str, ...] = (),
        draft_title: str | None = None,
        publish_at: str | None = None,
        share: bool = False,
    ) -> TypefullyDraft:
        post: dict[str, Any] = {"text": text}
        if media_ids:
            post["media_ids"] = list(media_ids)
        payload: dict[str, Any] = {
            "platforms": {
                "x": {
                    "enabled": True,
                    "posts": [post],
                }
            }
        }
        if draft_title:
            payload["draft_title"] = draft_title
        if publish_at is not None:
            payload["publish_at"] = publish_at
        if share:
            payload["share"] = True

        response = self._request_json(
            "POST",
            f"/v2/social-sets/{social_set_id}/drafts",
            payload,
        )
        draft_id = str(response.get("id") or "")
        if not draft_id:
            raise TypefullyAPIError("Typefully draft response is missing id", body=json.dumps(response, ensure_ascii=False))
        return TypefullyDraft(
            draft_id=draft_id,
            status=str(response.get("status") or "draft"),
            private_url=str(response.get("private_url") or ""),
            share_url=str(response.get("share_url") or ""),
            published_url=str(response.get("x_published_url") or ""),
            raw=response,
        )

    def create_x_draft(
        self,
        social_set_id: str,
        *,
        text: str,
        media_path: str | Path | None = None,
        image_path: str | Path | None = None,
        draft_title: str | None = None,
        publish_at: str | None = None,
        share: bool = False,
    ) -> TypefullyDraft:
        if media_path and image_path:
            raise ValueError("Pass media_path or legacy image_path, not both")
        media_ids: list[str] = []
        selected_media = media_path or image_path
        if selected_media:
            media_id = self.upload_media(social_set_id, selected_media)
            self.wait_for_media(social_set_id, media_id)
            media_ids.append(media_id)
        return self.create_draft(
            social_set_id,
            text=text,
            media_ids=tuple(media_ids),
            draft_title=draft_title,
            publish_at=publish_at,
            share=share,
        )


def guess_media_type(path: str | Path) -> str:
    """Return a best-effort MIME type for diagnostics and future validation."""

    return mimetypes.guess_type(str(path))[0] or "application/octet-stream"
