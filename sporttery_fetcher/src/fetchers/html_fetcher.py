from __future__ import annotations

import json
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
                logger.info("静态 HTML 未解析到有效比赛数据: %s", url)
            except Exception as exc:
                logger.warning("HTML 抓取失败: %s, 原因: %s", url, exc)

        # 静态 HTML 不可用时尝试 Playwright（动态渲染）。
        matches, used_url = self._fetch_with_playwright(issue_date)
        if matches:
            logger.info("Playwright 抓取成功: %s, 条数=%s", used_url, len(matches))
            return matches, used_url
        return [], None

    def _parse_html(self, html: str, source_url: str, issue_date: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "lxml")

        records = self._parse_from_table_rows(soup, source_url, issue_date)
        if records:
            return records

        # 新页面若是脚本注入，尝试从 script 里提取 JSON。
        script_records = self._parse_from_script_data(soup, source_url, issue_date)
        if script_records:
            return script_records

        return []

    def _parse_from_table_rows(self, soup: BeautifulSoup, source_url: str, issue_date: str) -> list[dict[str, Any]]:
        candidate_rows = soup.select("tr, li")
        records: list[dict[str, Any]] = []

        for row in candidate_rows:
            cols = [c.get_text(" ", strip=True) for c in row.select("th,td,span,div") if c.get_text(strip=True)]
            if len(cols) < 5:
                continue

            merged = " | ".join(cols)
            if not self._looks_like_match_row(merged):
                continue

            match_no = self._extract_match_no(merged)
            home, away = self._extract_teams(merged, cols)
            kickoff = self._extract_time(merged, issue_date)
            if not (home and away and kickoff):
                continue

            records.append(
                {
                    "issue_date": issue_date,
                    "match_no": match_no,
                    "league": self._extract_league(cols),
                    "home_team": home,
                    "away_team": away,
                    "kickoff_time": kickoff,
                    "handicap": self._extract_handicap(merged),
                    "sell_status": self._extract_sell_status(merged),
                    "play_spf": self._extract_play_flag(merged, "胜平负"),
                    "play_rqspf": self._extract_play_flag(merged, "让球胜平负"),
                    "play_score": self._extract_play_flag(merged, "比分"),
                    "play_goals": self._extract_play_flag(merged, "总进球"),
                    "play_half_full": self._extract_play_flag(merged, "半全场"),
                    "source_url": source_url,
                    "raw_id": row.get("data-mid") or row.get("id"),
                    "scrape_time": datetime.now().isoformat(timespec="seconds"),
                }
            )
        return records

    def _parse_from_script_data(self, soup: BeautifulSoup, source_url: str, issue_date: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        scripts = soup.find_all("script")
        for script in scripts:
            text = script.get_text(" ", strip=True)
            if not text:
                continue
            if "match" not in text.lower() and "jczq" not in text.lower():
                continue

            for raw_json in self._extract_json_candidates(text):
                try:
                    payload = json.loads(raw_json)
                except Exception:
                    continue
                for item in self._extract_match_like_items(payload):
                    mapped = self._map_raw_match(item, source_url=source_url, issue_date=issue_date)
                    if mapped.get("home_team") and mapped.get("away_team"):
                        records.append(mapped)
            if records:
                break
        return records

    @staticmethod
    def _extract_json_candidates(text: str) -> list[str]:
        candidates: list[str] = []
        # 捕捉常见 JS 变量赋值：var data = {...}; / window.xxx = [...];
        for pattern in [
            r"=\s*(\{.*?\})\s*;",
            r"=\s*(\[.*?\])\s*;",
        ]:
            matches = re.findall(pattern, text, flags=re.DOTALL)
            candidates.extend(matches)
        return candidates

    def _extract_match_like_items(self, data: Any) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                keys = {str(k).lower() for k in node.keys()}
                has_team = bool({"home", "away", "hometeam", "awayteam", "h_cn", "a_cn"} & keys)
                has_time = bool({"matchtime", "time", "saleendtime", "kickoff_time"} & keys)
                if has_team or has_time:
                    found.append(node)
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(data)
        return found

    def _map_raw_match(self, raw: dict[str, Any], source_url: str, issue_date: str) -> dict[str, Any]:
        def pick(*keys: str) -> Any:
            for key in keys:
                if key in raw and raw[key] not in ("", None):
                    return raw[key]
                for k, v in raw.items():
                    if str(k).lower() == key.lower() and v not in ("", None):
                        return v
            return None

        kickoff_raw = pick("kickoff_time", "matchTime", "saleEndTime", "time")
        kickoff = self._normalize_kickoff(kickoff_raw, issue_date)
        return {
            "issue_date": pick("issue_date", "date", "matchDate") or issue_date,
            "match_no": pick("match_no", "matchNumStr", "week", "matchCode"),
            "league": pick("league", "leagueName", "l_cn_abbr"),
            "home_team": pick("home_team", "home", "h_cn", "homeTeamName"),
            "away_team": pick("away_team", "away", "a_cn", "awayTeamName"),
            "kickoff_time": kickoff,
            "handicap": pick("handicap", "rq", "concede", "letBall"),
            "sell_status": pick("sell_status", "isSale", "status", "sellStatus"),
            "play_spf": pick("play_spf", "spf", "is_single"),
            "play_rqspf": pick("play_rqspf", "rqspf"),
            "play_score": pick("play_score", "bf"),
            "play_goals": pick("play_goals", "jq", "zjq"),
            "play_half_full": pick("play_half_full", "bqc"),
            "source_url": source_url,
            "raw_id": pick("id", "matchId", "mid"),
            "scrape_time": datetime.now().isoformat(timespec="seconds"),
        }

    @staticmethod
    def _looks_like_match_row(merged_text: str) -> bool:
        return bool(
            re.search(
                r"周[一二三四五六日天]\d{3}|\d{4}-\d{2}-\d{2}\s*\d{2}:\d{2}|\d{2}:\d{2}",
                merged_text,
            )
        )

    @staticmethod
    def _extract_match_no(merged_text: str) -> str | None:
        m = re.search(r"(周[一二三四五六日天]\d{3})", merged_text)
        return m.group(1) if m else None

    @staticmethod
    def _extract_league(cols: list[str]) -> str | None:
        for col in cols:
            if any(x in col for x in ["联赛", "杯", "甲", "超", "锦标", "友谊"]):
                return col
        return None

    @staticmethod
    def _extract_teams(merged_text: str, cols: list[str]) -> tuple[str | None, str | None]:
        m = re.search(r"([\w\u4e00-\u9fff·\-]+)\s*(?:VS|vs|v|-)\s*([\w\u4e00-\u9fff·\-]+)", merged_text)
        if m:
            return m.group(1), m.group(2)

        # 兜底：查找“主队/客队”关键词
        for i, c in enumerate(cols):
            if "主队" in c and i + 1 < len(cols):
                home = cols[i + 1]
                away = cols[i + 2] if i + 2 < len(cols) else None
                return home, away

        # 最后兜底：过滤无关列后取两支队伍
        candidates = [
            c
            for c in cols
            if 1 < len(c) < 40 and not re.search(r"\d{2}:\d{2}|周[一二三四五六日天]\d{3}|联赛|开售|停售", c)
        ]
        if len(candidates) >= 2:
            return candidates[-2], candidates[-1]
        return None, None

    @staticmethod
    def _normalize_kickoff(kickoff_raw: Any, issue_date: str) -> str | None:
        if kickoff_raw in (None, ""):
            return None
        text = str(kickoff_raw)
        if re.search(r"\d{4}-\d{2}-\d{2}", text):
            return text
        m = re.search(r"(\d{2}:\d{2})", text)
        if m:
            return f"{issue_date} {m.group(1)}"
        return text

    def _extract_time(self, merged_text: str, issue_date: str) -> str | None:
        m_full = re.search(r"(\d{4}-\d{2}-\d{2}\s*\d{2}:\d{2})", merged_text)
        if m_full:
            return m_full.group(1).replace("  ", " ")
        m_hm = re.search(r"(\d{2}:\d{2})", merged_text)
        if m_hm:
            return f"{issue_date} {m_hm.group(1)}"
        return None

    @staticmethod
    def _extract_handicap(merged_text: str) -> str | None:
        m = re.search(r"([+-]\d+(?:\.\d+)?)", merged_text)
        return m.group(1) if m else None

    @staticmethod
    def _extract_sell_status(merged_text: str) -> str | None:
        if "停售" in merged_text:
            return "停售"
        if "开售" in merged_text:
            return "开售"
        return None

    @staticmethod
    def _extract_play_flag(merged_text: str, play_name: str) -> bool | None:
        if play_name not in merged_text:
            return None
        if any(x in merged_text for x in ["停售", "关闭", "未开"]):
            return False
        return True

    def _fetch_with_playwright(self, issue_date: str) -> tuple[list[dict[str, Any]], str | None]:
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            logger.error("Playwright 未安装：请先执行 playwright install chromium")
            return [], None

        try:
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
        except Exception as exc:
            logger.error("Playwright 抓取失败: %s", exc)
        return [], None
