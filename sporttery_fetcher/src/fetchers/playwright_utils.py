from __future__ import annotations

import asyncio
import sys
from contextlib import contextmanager
from typing import Any, Generator, Tuple

_STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
window.chrome = {runtime: {}};
"""

_STEALTH_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
    "--no-sandbox",
]


@contextmanager
def managed_playwright() -> Generator[Any, None, None]:
    """在非主线程（如 Streamlit handler）也能正常使用 Playwright。

    Windows 上非主线程默认没有事件循环，直接调用 sync_playwright() 会抛出
    NotImplementedError。需要在进入前先设置 WindowsProactorEventLoopPolicy。
    """
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        yield p


def stealth_browser_context(p: Any, headless: bool, user_agent: str) -> Tuple[Any, Any]:
    """启动带反检测配置的 Chromium 浏览器，返回 (browser, context)。

    规避 WAF/bot 检测：隐藏 webdriver 特征、添加真实浏览器指纹、
    设置中文语言和时区。
    """
    browser = p.chromium.launch(
        headless=headless,
        args=_STEALTH_LAUNCH_ARGS,
    )
    context = browser.new_context(
        user_agent=user_agent,
        viewport={"width": 1920, "height": 1080},
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
    )
    context.add_init_script(_STEALTH_INIT_SCRIPT)
    return browser, context
