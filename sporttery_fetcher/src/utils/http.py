from __future__ import annotations

from typing import Any

import requests
from requests import Response, Session
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from config.settings import settings


class HTTPClient:
    def __init__(self) -> None:
        self.session: Session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": settings.user_agent,
                "Accept": "text/html,application/json,application/xhtml+xml,*/*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Connection": "keep-alive",
            }
        )

    @retry(
        stop=stop_after_attempt(settings.request_retries),
        wait=wait_fixed(settings.retry_wait_seconds),
        retry=retry_if_exception_type((requests.RequestException,)),
        reraise=True,
    )
    def request(self, method: str, url: str, **kwargs: Any) -> Response:
        kwargs.setdefault("timeout", settings.request_timeout)
        response = self.session.request(method=method.upper(), url=url, **kwargs)
        response.raise_for_status()
        if not response.encoding:
            response.encoding = response.apparent_encoding or "utf-8"
        return response
