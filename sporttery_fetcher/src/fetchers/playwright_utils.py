from __future__ import annotations

import asyncio
import sys
from contextlib import contextmanager
from typing import Any, Generator


@contextmanager
def managed_playwright() -> Generator[Any, None, None]:
    """在非主线程（如 Streamlit handler）也能正常使用 Playwright。

    Windows 上非主线程默认没有事件循环，直接调用 sync_playwright() 会抛出
    NotImplementedError。需要在进入前先设置 WindowsSelectorEventLoopPolicy。
    """
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        yield p
