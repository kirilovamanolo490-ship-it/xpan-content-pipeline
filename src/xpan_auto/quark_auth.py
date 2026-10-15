from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def login_and_save_storage_state(
    storage_path: str | Path,
    *,
    user_data_dir: str | Path | None = None,
    browser: str = "chromium",
    executable_path: str | Path | None = None,
    legacy_cookie_path: str | Path | None = None,
    wait_seconds: int = 600,
) -> Path:
    """Open a local Playwright browser and save the logged-in Quark state.

    Playwright is imported lazily so link parsing and dry-run commands do not
    require a browser installation. The user completes login in the local
    browser; credentials never pass through this program's CLI arguments.
    """

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError(
            "本地登录需要浏览器依赖，请先安装：python -m pip install -e \".[browser]\" "
            "并执行 playwright install chromium"
        ) from exc

    output = Path(storage_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    profile = Path(user_data_dir) if user_data_dir else output.with_name("quark-browser-data")
    profile.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser_type = getattr(playwright, browser, None)
        if browser_type is None:
            raise ValueError(f"不支持的浏览器类型：{browser}")
        launch_options = {
            "headless": False,
            "no_viewport": True,
        }
        if executable_path:
            launch_options["executable_path"] = str(executable_path)
        context = browser_type.launch_persistent_context(str(profile), **launch_options)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://pan.quark.cn/list#/list/all", wait_until="domcontentloaded")
        print("等待夸克登录完成；进入网盘后会自动保存状态。")
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            current_url = page.url
            if "/list" in current_url or "#/list" in current_url:
                break
            time.sleep(1)
        else:
            context.close()
            raise RuntimeError("等待夸克登录超时")
        state = context.storage_state()
        output.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        if legacy_cookie_path:
            legacy = Path(legacy_cookie_path)
            legacy.parent.mkdir(parents=True, exist_ok=True)
            legacy.write_text(repr(state.get("cookies", [])), encoding="utf-8")
        context.close()
    return output


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="在本机完成夸克登录并保存 Playwright 状态")
    parser.add_argument("--storage-state", default="config/quark-storage.json")
    parser.add_argument("--user-data-dir", default=None)
    parser.add_argument("--browser", choices=("chromium", "firefox", "webkit"), default="chromium")
    parser.add_argument("--executable-path", default=None)
    parser.add_argument("--legacy-cookie-file", default="work/QuarkPanTool/config/cookies.txt")
    parser.add_argument("--wait-seconds", type=int, default=600)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    path = login_and_save_storage_state(
        args.storage_state,
        user_data_dir=args.user_data_dir,
        browser=args.browser,
        executable_path=args.executable_path,
        legacy_cookie_path=args.legacy_cookie_file,
        wait_seconds=args.wait_seconds,
    )
    print(f"storage_state={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
