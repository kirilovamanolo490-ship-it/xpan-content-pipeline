#!/usr/bin/env python3
"""Download the first video returned for an exact Quark Drive directory."""

import argparse
import time
from pathlib import Path

import requests

from quark_auto_save import Config, Quark


VIDEO_EXTENSIONS = {
    ".3gp",
    ".avi",
    ".flv",
    ".m2ts",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".mts",
    ".ts",
    ".webm",
    ".wmv",
}

# Local resilience patch (2026-08-14): Quark CDN intermittently resets SSL
# connections (SSLEOFError). The previous 10 no-progress cap and 60s wall
# clock abandoned downloads that were simply slow; .part files are now
# resumed across many more attempts with longer backoff.
MAX_NO_PROGRESS_FAILURES = 40
DOWNLOAD_RANGE_BYTES = 8 * 1024 * 1024
DOWNLOAD_CHUNK_BYTES = 256 * 1024
DOWNLOAD_RANGE_WALL_SECONDS = 240
DOWNLOAD_RETRY_DELAYS = (2, 4, 8, 12, 20, 30, 45, 60, 60, 60, 60, 60, 60, 60, 60)


class TransientDownloadError(RuntimeError):
    """A retryable interruption while receiving the same original file."""


def parse_args():
    parser = argparse.ArgumentParser(
        description="Download the first video in a Quark Drive directory."
    )
    parser.add_argument("cloud_path", help="Exact directory path in Quark Drive")
    parser.add_argument("output_dir", type=Path, help="Local destination directory")
    parser.add_argument(
        "--fid",
        default="",
        help="Download this exact file FID instead of resolving the first video",
    )
    parser.add_argument(
        "--file-name",
        default="",
        help="Expected filename for --fid (prevents selecting a different file)",
    )
    parser.add_argument(
        "--expected-size",
        type=int,
        default=None,
        help="Expected remote file size in bytes",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/quark_config.json"),
        help="QAS config path (default: config/quark_config.json)",
    )
    return parser.parse_args()


def load_primary_cookie(config_path):
    config = Config.read_json(config_path)
    if isinstance(config.get("cookies"), list):
        return "; ".join(
            f"{item['name']}={item['value']}"
            for item in config["cookies"]
            if isinstance(item, dict)
            and item.get("name")
            and item.get("value") is not None
            and "quark" in str(item.get("domain", ""))
        )
    cookies = Config.get_cookies(config.get("cookie")) or []
    cookie = next(
        (
            value.strip()
            for value in cookies
            if isinstance(value, str)
            and value.strip()
            and not value.startswith("Your pan.quark.cn Cookie")
        ),
        "",
    )
    if not cookie:
        raise RuntimeError(f"No Quark account cookie is configured in {config_path}")
    return cookie


def cloud_path_parts(cloud_path):
    parts = [part for part in cloud_path.replace("\\", "/").split("/") if part]
    if parts and parts[0] == "文件":
        parts = parts[1:]
    if not parts:
        raise ValueError("Cloud directory path is empty")
    return parts


def require_file_list(response, directory_name):
    if response.get("code") != 0:
        message = response.get("message") or response.get("msg") or "unknown error"
        raise RuntimeError(f"Unable to list {directory_name}: {message}")
    return response.get("data", {}).get("list", [])


def resolve_directory(account, cloud_path):
    current_fid = "0"
    traversed = []
    for part in cloud_path_parts(cloud_path):
        children = require_file_list(account.ls_dir(current_fid), "/" + "/".join(traversed))
        matches = [
            item
            for item in children
            if item.get("dir") and item.get("file_name") == part
        ]
        if len(matches) != 1:
            location = "/" + "/".join(traversed)
            raise RuntimeError(
                f"Expected one directory named {part!r} under {location}, found {len(matches)}"
            )
        current_fid = matches[0]["fid"]
        traversed.append(part)
    return current_fid, "/" + "/".join(traversed)


def first_video(account, directory_fid, directory_path):
    children = require_file_list(account.ls_dir(directory_fid), directory_path)
    for item in children:
        filename = item.get("file_name", "")
        if item.get("dir"):
            continue
        if item.get("obj_category") == "video" or Path(filename).suffix.lower() in VIDEO_EXTENSIONS:
            return item
    raise RuntimeError(f"No video file found in {directory_path}")


def get_download_url(account, fid):
    result, response_cookie = account.download([fid])
    if result.get("code") != 0:
        message = result.get("message") or result.get("msg") or "unknown error"
        if any(token in str(message).casefold() for token in ("request error", "ssl", "timeout", "timed out")):
            raise TransientDownloadError(str(message))
        raise RuntimeError(f"Unable to create download URL: {message}")
    downloads = result.get("data") or []
    if not downloads or not downloads[0].get("download_url"):
        message = result.get("message") or result.get("msg") or "Quark Drive returned no download URL"
        if any(token in str(message).casefold() for token in ("request error", "ssl", "timeout", "timed out")):
            raise TransientDownloadError(str(message))
        raise RuntimeError(str(message))
    return downloads[0]["download_url"], response_cookie


def stream_download(account, item, output_dir):
    filename = Path(item["file_name"]).name
    if not filename or filename in {".", ".."}:
        raise RuntimeError("Quark Drive returned an invalid filename")

    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / filename
    expected_size = item.get("size") or item.get("file_size")
    if destination.exists():
        if expected_size and destination.stat().st_size == expected_size:
            print(f"Already downloaded: {destination}")
            return destination
        raise FileExistsError(f"Refusing to overwrite existing file: {destination}")

    stable_partial = destination.with_name(f"{destination.name}.part")
    partial_candidates = [stable_partial, *output_dir.glob(f"{destination.name}.part-*")]
    valid_partials = [
        path
        for path in partial_candidates
        if path.is_file() and (not expected_size or path.stat().st_size <= expected_size)
    ]
    partial = max(valid_partials, key=lambda path: path.stat().st_size) if valid_partials else stable_partial
    downloaded = partial.stat().st_size if partial.exists() else 0
    if downloaded:
        print(f"Resuming from {downloaded} bytes: {partial}", flush=True)

    last_error = None
    no_progress_failures = 0
    download_url = None
    response_cookie = None
    while not expected_size or downloaded < expected_size:
        before_request = downloaded
        try:
            if download_url is None:
                download_url, response_cookie = get_download_url(account, item["fid"])
            headers = {
                "Accept-Encoding": "identity",
                "Cookie": response_cookie or account.cookie,
                "User-Agent": account.USER_AGENT,
            }
            range_end = None
            if expected_size:
                range_end = min(downloaded + DOWNLOAD_RANGE_BYTES - 1, expected_size - 1)
                headers["Range"] = f"bytes={downloaded}-{range_end}"
            range_started = time.monotonic()
            with requests.get(
                download_url,
                headers=headers,
                stream=True,
                timeout=(30, 15),
            ) as response:
                response.raise_for_status()
                append = downloaded > 0
                if expected_size:
                    if response.status_code != 206:
                        raise TransientDownloadError(
                            f"Server did not honor byte range at {downloaded}: HTTP {response.status_code}"
                        )
                    content_range = response.headers.get("Content-Range", "")
                    expected_prefix = f"bytes {downloaded}-"
                    if not content_range.startswith(expected_prefix):
                        raise TransientDownloadError(
                            f"Unexpected Content-Range for resume: {content_range or 'missing'}"
                        )
                with partial.open("ab" if append else "wb") as output:
                    for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_BYTES):
                        if not chunk:
                            continue
                        output.write(chunk)
                        downloaded += len(chunk)
                        if time.monotonic() - range_started > DOWNLOAD_RANGE_WALL_SECONDS:
                            raise TransientDownloadError(
                                f"Byte-range wall timeout at {downloaded} bytes"
                            )
                        if expected_size and downloaded > expected_size:
                            raise RuntimeError(
                                f"Downloaded more bytes than expected: {downloaded} > {expected_size}"
                            )
            downloaded = partial.stat().st_size
            if not expected_size:
                break
            if range_end is not None and downloaded != range_end + 1:
                raise TransientDownloadError(
                    f"Byte range ended early at {downloaded}; expected {range_end + 1}"
                )
            no_progress_failures = 0
            print(f"Downloaded {downloaded} / {expected_size} bytes", flush=True)
        except (requests.RequestException, OSError, TransientDownloadError) as exc:
            downloaded = partial.stat().st_size if partial.exists() else 0
            last_error = exc
            download_url = None
            if downloaded > before_request:
                no_progress_failures = 0
            else:
                no_progress_failures += 1
            if no_progress_failures >= MAX_NO_PROGRESS_FAILURES:
                break
            delay_index = max(0, min(no_progress_failures - 1, len(DOWNLOAD_RETRY_DELAYS) - 1))
            delay = DOWNLOAD_RETRY_DELAYS[delay_index]
            print(
                f"Download interrupted at {downloaded} bytes: {exc}; "
                f"retrying in {delay}s",
                flush=True,
            )
            time.sleep(delay)

    if expected_size and downloaded != expected_size:
        raise RuntimeError(
            f"Downloaded size mismatch after {MAX_NO_PROGRESS_FAILURES} consecutive no-progress failures: "
            f"expected {expected_size}, got {downloaded}; last error: {last_error}"
        )
    partial.replace(destination)

    print(f"Downloaded {downloaded} bytes: {destination}")
    return destination


def main():
    args = parse_args()
    account = Quark(load_primary_cookie(args.config))
    info = account.init()
    if not info:
        raise RuntimeError("Quark Drive authorization is invalid or expired")

    if args.fid:
        if not args.file_name:
            raise ValueError("--file-name is required with --fid")
        directory_path = args.cloud_path
        item = {
            "fid": args.fid,
            "file_name": args.file_name,
            "obj_category": "video",
            "size": args.expected_size,
        }
    else:
        directory_fid, directory_path = resolve_directory(account, args.cloud_path)
        item = first_video(account, directory_fid, directory_path)
    print(f"Account: {account.nickname}")
    print(f"Directory: {directory_path}")
    print(f"First video: {item['file_name']} ({item.get('size', 'unknown')} bytes)")
    stream_download(account, item, args.output_dir)


if __name__ == "__main__":
    main()
