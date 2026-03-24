from __future__ import annotations

from typing import Any

from config.settings import settings
from src.fetchers.html_fetcher import HTMLFetcher
from src.utils.http import HTTPClient


class MobileFetcher(HTMLFetcher):
    """移动端页面抓取器（复用 HTML 解析逻辑）。"""

    def __init__(self, http_client: HTTPClient | None = None) -> None:
        super().__init__(http_client=http_client)

    def fetch(self, issue_date: str) -> tuple[list[dict[str, Any]], str | None]:
        for url in settings.mobile_urls:
            try:
                html = self.http.request("GET", url).text
                matches = self._parse_html(html, source_url=url, issue_date=issue_date)
                if matches:
                    return matches, url
            except Exception:
                continue
        return [], None
