from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup

from config.settings import settings
from src.utils.http import HTTPClient
from src.utils.logger import get_logger
from src.utils.save import save_html_snapshot

logger = get_logger(__name__)


class HTMLFetcher:
    def __init__(self, http_client: HTTPClient | None = None) -> None:
        self.http = http_client or HTTPClient()

    def fetch(self, issue_date: str) -> tuple[list[dict[str, Any]], str | None]:
        for url in settings.schedule_urls:
            try:
                html = self.http.request("GET", url).text
                if settings.save_html_snapshot:
                    save_html_snapshot(html, f"schedule_{issue_date}")
                matches = self._parse_html(html, source_url=url, issue_date=issue_date)
                if matches:
                    logger.info("HTML 抓取成功: %s, 条数=%s", url, len(matches))
                    return matches, url
            except Exception as exc:
                logger.warning("HTML 抓取失败: %s, 原因: %s", url, exc)

        # 静态 HTML 不可用时尝试 Playwright。
        try:
            matches, used_url = self._fetch_with_playwright(issue_date)
            if matches:
                logger.info("Playwright 抓取成功: %s, 条数=%s", used_url, len(matches))
                return matches, used_url
        except Exception as exc:
            logger.error("Playwright 抓取失败: %s", exc)
        return [], None

    def _parse_html(self, html: str, source_url: str, issue_date: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "lxml")
        rows = soup.select("tr")

        records: list[dict[str, Any]] = []
        for row in rows:
            cols = [c.get_text(" ", strip=True) for c in row.select("td")]
            if len(cols) < 5:
                continue

            if not self._looks_like_match_row(cols):
                continue

            match_no = self._extract_match_no(cols)
            home, away = self._extract_teams(cols)
            kickoff = self._extract_time(cols, issue_date)

            records.append(
                {
                    "issue_date": issue_date,
                    "match_no": match_no,
                    "league": self._extract_league(cols),
                    "home_team": home,
                    "away_team": away,
                    "kickoff_time": kickoff,
                    "handicap": self._extract_handicap(cols),
                    "sell_status": self._extract_sell_status(cols),
                    "play_spf": self._extract_play_flag(cols, "胜平负"),
                    "play_rqspf": self._extract_play_flag(cols, "让球胜平负"),
                    "play_score": self._extract_play_flag(cols, "比分"),
                    "play_goals": self._extract_play_flag(cols, "总进球"),
                    "play_half_full": self._extract_play_flag(cols, "半全场"),
                    "source_url": source_url,
                    "raw_id": row.get("data-mid") or row.get("id"),
                    "scrape_time": datetime.now().isoformat(timespec="seconds"),
                }
            )

        return records

    @staticmethod
    def _looks_like_match_row(cols: list[str]) -> bool:
        line = " | ".join(cols)
        return bool(re.search(r"周[一二三四五六日天]\d{3}|\d{2}:\d{2}", line))

    @staticmethod
    def _extract_match_no(cols: list[str]) -> str | None:
        line = " ".join(cols)
        m = re.search(r"(周[一二三四五六日天]\d{3})", line)
        return m.group(1) if m else None

    @staticmethod
    def _extract_league(cols: list[str]) -> str | None:
        for col in cols:
            if any(x in col for x in ["联赛", "杯", "甲", "超", "锦标"]):
                return col
        return None

    @staticmethod
    def _extract_teams(cols: list[str]) -> tuple[str | None, str | None]:
        line = " ".join(cols)
        # 常见格式：主队 VS 客队 / 主队-客队
        m = re.search(r"([\w\u4e00-\u9fff·\-]+)\s*(?:VS|vs|v|-)\s*([\w\u4e00-\u9fff·\-]+)", line)
        if m:
            return m.group(1), m.group(2)
        # 兜底：取长度较大的两个文本列
        candidates = [c for c in cols if 1 < len(c) < 40 and not re.match(r"\d|周[一二三四五六日天]", c)]
        if len(candidates) >= 2:
            return candidates[-2], candidates[-1]
        return None, None

    @staticmethod
    def _extract_time(cols: list[str], issue_date: str) -> str | None:
        line = " ".join(cols)
        m = re.search(r"(\d{2}:\d{2})", line)
        if not m:
            return None
        return f"{issue_date} {m.group(1)}"

    @staticmethod
    def _extract_handicap(cols: list[str]) -> str | None:
        line = " ".join(cols)
        m = re.search(r"([+-]\d+(?:\.\d+)?)", line)
        return m.group(1) if m else None

    @staticmethod
    def _extract_sell_status(cols: list[str]) -> str | None:
        line = " ".join(cols)
        if "停售" in line:
            return "停售"
        if "开售" in line:
            return "开售"
        return None

    @staticmethod
    def _extract_play_flag(cols: list[str], play_name: str) -> bool | None:
        line = " ".join(cols)
        if play_name not in line:
            return None
        if any(x in line for x in ["停售", "关闭", "未开"]):
            return False
        return True

    def _fetch_with_playwright(self, issue_date: str) -> tuple[list[dict[str, Any]], str | None]:
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            raise RuntimeError("未安装 playwright，请先执行: playwright install chromium") from exc

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=settings.playwright_headless)
            context = browser.new_context(user_agent=settings.user_agent)
            page = context.new_page()
            for url in settings.schedule_urls + settings.mobile_urls:
                page.goto(url, wait_until="networkidle", timeout=settings.request_timeout * 1000)
                html = page.content()
                if settings.save_html_snapshot:
                    save_html_snapshot(html, f"playwright_{issue_date}")
                matches = self._parse_html(html, source_url=url, issue_date=issue_date)
                if matches:
                    browser.close()
                    return matches, url
            browser.close()
        return [], None
