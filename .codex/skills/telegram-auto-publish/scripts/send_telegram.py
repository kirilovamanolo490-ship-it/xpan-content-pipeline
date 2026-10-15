#!/usr/bin/env python3
"""Dry-run or send one final image/video through Telegram Bot API."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import secrets
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


BOT_API_MAX_MEDIA_BYTES = 50_000_000


def project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="check bot and chat configuration only")
    mode.add_argument("--send", action="store_true", help="perform the external send; without it, run dry-run")
    mode.add_argument("--edit", action="store_true", help="edit an existing channel message caption in place")
    media = parser.add_mutually_exclusive_group()
    media.add_argument("--video", type=Path, help="QA-passed <=10-minute video under 50 MB")
    media.add_argument("--image", type=Path, help="fallback local image path for sendPhoto")
    parser.add_argument("--caption-file", type=Path, help="UTF-8 HTML caption file")
    parser.add_argument("--message-id", type=int, help="existing channel message ID used with --edit")
    parser.add_argument("--env-file", type=Path, help="dotenv file; defaults to project .env")
    parser.add_argument(
        "--transport",
        choices=("bot-api",),
        default="bot-api",
        help="Legacy explicit selector; Bot API is the only supported Telegram transport.",
    )
    parser.add_argument("--api-base", default="https://api.telegram.org")
    parser.add_argument("--timeout", type=float, default=180.0)
    return parser.parse_args()


def load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def resolve_path(value: Path | None) -> Path | None:
    if value is None or value.is_absolute():
        return value
    return project_root() / value


def redact(value: str) -> str:
    if len(value) <= 6:
        return "<redacted>"
    return f"{value[:2]}…{value[-4:]}"


def _normalized_proxy_map(proxies: dict[str, str]) -> dict[str, str]:
    normalized = {str(key).lower(): value for key, value in proxies.items() if value}
    shared = normalized.get("all")
    http_proxy = normalized.get("http") or shared
    https_proxy = normalized.get("https") or shared or http_proxy
    if not http_proxy and not https_proxy:
        return {}
    return {
        "http": http_proxy or https_proxy,
        "https": https_proxy or http_proxy,
    }


def _parse_macos_system_proxy(output: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in output.splitlines():
        match = re.match(r"^\s*([A-Za-z0-9]+)\s*:\s*(.*?)\s*$", raw_line)
        if match:
            values[match.group(1)] = match.group(2)

    for prefix in ("HTTPS", "HTTP"):
        if values.get(f"{prefix}Enable") != "1":
            continue
        host = values.get(f"{prefix}Proxy", "").strip()
        raw_port = values.get(f"{prefix}Port", "").strip()
        if not host or not raw_port.isdigit():
            continue
        port = int(raw_port)
        if not 1 <= port <= 65535:
            continue
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        proxy_url = f"http://{host}:{port}"
        return {"http": proxy_url, "https": proxy_url}
    return {}


def telegram_proxy_config() -> tuple[dict[str, str], str]:
    environment_proxies = _normalized_proxy_map(urllib.request.getproxies())
    if environment_proxies:
        return environment_proxies, "environment-proxy"

    if sys.platform != "darwin":
        return {}, "direct"

    try:
        completed = subprocess.run(
            ["/usr/sbin/scutil", "--proxy"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return {}, "direct"
    if completed.returncode != 0:
        return {}, "direct"

    system_proxies = _parse_macos_system_proxy(completed.stdout)
    if system_proxies:
        return system_proxies, "macos-system-proxy"
    return {}, "direct"


def build_telegram_opener() -> tuple[urllib.request.OpenerDirector, str]:
    proxy_map, network_route = telegram_proxy_config()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxy_map))
    return opener, network_route


def api_call(
    *,
    api_base: str,
    token: str,
    method: str,
    fields: dict[str, str] | None = None,
    file_field: tuple[str, Path] | None = None,
    timeout: float,
    opener: urllib.request.OpenerDirector,
) -> dict[str, object]:
    fields = fields or {}
    url = f"{api_base.rstrip('/')}/bot{token}/{method}"

    if file_field is None:
        if fields:
            request = urllib.request.Request(
                url,
                data=urllib.parse.urlencode(fields).encode("utf-8"),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
        else:
            request = urllib.request.Request(url, method="GET")
        try:
            with opener.open(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                raise RuntimeError(f"Telegram HTTP {exc.code}: {raw[:300]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Telegram network error: {exc.reason}") from exc
        if not payload.get("ok"):
            description = payload.get("description", "unknown Telegram error")
            error_code = payload.get("error_code", "?")
            raise RuntimeError(f"Telegram API {error_code}: {description}")
        return payload

    boundary = f"----xpanTelegram{secrets.token_hex(12)}"
    body = bytearray()

    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(value.encode("utf-8"))
        body.extend(b"\r\n")

    if file_field is not None:
        name, path = file_field
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            f'Content-Disposition: form-data; name="{name}"; filename="{path.name}"\r\n'.encode()
        )
        body.extend(f"Content-Type: {mime}\r\n\r\n".encode())
        body.extend(path.read_bytes())
        body.extend(b"\r\n")

    body.extend(f"--{boundary}--\r\n".encode())
    request = urllib.request.Request(
        url,
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            raise RuntimeError(f"Telegram HTTP {exc.code}: {raw[:300]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Telegram network error: {exc.reason}") from exc

    if not payload.get("ok"):
        description = payload.get("description", "unknown Telegram error")
        error_code = payload.get("error_code", "?")
        raise RuntimeError(f"Telegram API {error_code}: {description}")
    return payload


def required_config(env_values: dict[str, str]) -> tuple[str, str]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or env_values.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID") or env_values.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID in environment/.env")
    return token, chat_id


def main() -> int:
    args = parse_args()
    env_path = resolve_path(args.env_file) or project_root() / ".env"
    env_values = load_dotenv(env_path)
    token, chat_id = required_config(env_values)
    opener, network_route = build_telegram_opener()
    if args.check:
        me = api_call(
            api_base=args.api_base,
            token=token,
            method="getMe",
            timeout=args.timeout,
            opener=opener,
        )
        chat = api_call(
            api_base=args.api_base,
            token=token,
            method="getChat",
            fields={"chat_id": chat_id},
            timeout=args.timeout,
            opener=opener,
        )
        bot = me.get("result", {})
        target = chat.get("result", {})
        bot_id = str(bot.get("id") or "")
        if not bot_id:
            raise RuntimeError("Telegram getMe did not return a bot id")
        member = api_call(
            api_base=args.api_base,
            token=token,
            method="getChatMember",
            fields={"chat_id": chat_id, "user_id": bot_id},
            timeout=args.timeout,
            opener=opener,
        ).get("result", {})
        member_status = str(member.get("status") or "")
        can_post_messages = member.get("can_post_messages")
        if member_status not in {"administrator", "creator"} or can_post_messages is False:
            raise RuntimeError(
                "Telegram bot is not allowed to post messages in the configured channel"
            )
        print(
            json.dumps(
                {
                    "mode": "check",
                    "transport": "bot-api",
                    "network_route": network_route,
                    "bot": {
                        "id": bot.get("id"),
                        "username": bot.get("username"),
                    },
                    "chat": {
                        "id": redact(str(target.get("id", ""))),
                        "type": target.get("type"),
                        "title": target.get("title"),
                        "username": target.get("username"),
                    },
                    "membership": {
                        "status": member_status,
                        "can_post_messages": can_post_messages,
                    },
                },
                ensure_ascii=False,
            )
        )
        return 0

    if args.edit:
        if not args.message_id:
            raise RuntimeError("--message-id is required with --edit")
        caption_file = resolve_path(args.caption_file)
        if caption_file is None or not caption_file.is_file():
            raise RuntimeError("--caption-file is required with --edit")
        caption = caption_file.read_text(encoding="utf-8")
        if not caption.strip():
            raise RuntimeError("Caption is empty")
        if "�" in caption:
            raise RuntimeError("Caption contains the Unicode replacement character; fix encoding before sending")
        if len(caption) > 1024:
            raise RuntimeError(f"Caption is {len(caption)} characters; Telegram media captions must be <= 1024")
        try:
            payload = api_call(
                api_base=args.api_base,
                token=token,
                method="editMessageCaption",
                fields={
                    "chat_id": chat_id,
                    "message_id": str(args.message_id),
                    "caption": caption,
                    "parse_mode": "HTML",
                },
                timeout=args.timeout,
                opener=opener,
            )
        except RuntimeError as exc:
            if "message is not modified" not in str(exc):
                raise
            print(
                json.dumps(
                    {
                        "mode": "unchanged",
                        "transport": args.transport,
                        "network_route": network_route,
                        "chat_id": redact(chat_id),
                        "message_id": args.message_id,
                        "caption_chars": len(caption),
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        message = payload.get("result", {})
        if not message or not message.get("message_id"):
            raise RuntimeError("Telegram caption edit completed without a message_id")
        print(
            json.dumps(
                {
                    "mode": "edited",
                    "transport": args.transport,
                    "network_route": network_route,
                    "chat_id": redact(chat_id),
                    "message_id": message.get("message_id"),
                    "caption_chars": len(caption),
                },
                ensure_ascii=False,
            )
        )
        return 0

    video = resolve_path(args.video)
    image = resolve_path(args.image)
    caption_file = resolve_path(args.caption_file)
    media_path = video or image
    if media_path is None or caption_file is None:
        raise RuntimeError("--video/--image and --caption-file are required unless --check is used")
    if not media_path.is_file():
        raise RuntimeError(f"Media file not found: {media_path}")
    media_size = media_path.stat().st_size
    if media_size == 0:
        raise RuntimeError(f"Media file is empty: {media_path}")
    if media_size >= BOT_API_MAX_MEDIA_BYTES:
        recovery = (
            "shorten the video from the tail before sending"
            if video is not None
            else "regenerate or optimize the final image before sending"
        )
        raise RuntimeError(
            "Telegram Bot API route only accepts images/videos smaller than "
            "50,000,000 bytes; "
            f"{recovery} ({media_size} bytes)"
        )
    if not caption_file.is_file():
        raise RuntimeError(f"Caption file not found: {caption_file}")

    caption = caption_file.read_text(encoding="utf-8")
    if not caption.strip():
        raise RuntimeError("Caption is empty")
    if "�" in caption:
        raise RuntimeError("Caption contains the Unicode replacement character; fix encoding before sending")
    if len(caption) > 1024:
        raise RuntimeError(f"Caption is {len(caption)} characters; Telegram media captions must be <= 1024")

    if not args.send:
        print(
            json.dumps(
                {
                    "mode": "dry-run",
                    "transport": args.transport,
                    "network_route": network_route,
                    "media_type": "video" if video is not None else "image",
                    "media": str(media_path),
                    "caption_file": str(caption_file),
                    "caption_chars": len(caption),
                    "parse_mode": "HTML",
                    "chat_id": redact(chat_id),
                },
                ensure_ascii=False,
            )
        )
        return 0

    is_video = video is not None
    payload = api_call(
        api_base=args.api_base,
        token=token,
        method="sendVideo" if is_video else "sendPhoto",
        fields={
            "chat_id": chat_id,
            "caption": caption,
            "parse_mode": "HTML",
            **({"supports_streaming": "true"} if is_video else {}),
        },
        file_field=("video", video) if is_video else ("photo", image),
        timeout=args.timeout,
        opener=opener,
    )
    message = payload.get("result", {})
    message_id = message.get("message_id")
    if not message_id:
        raise RuntimeError("Telegram send completed without a message_id")
    print(
        json.dumps(
            {
                "mode": "sent",
                "transport": args.transport,
                "network_route": network_route,
                "chat_id": redact(chat_id),
                "message_id": message_id,
                "media_type": "video" if is_video else "image",
                "caption_chars": len(caption),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
