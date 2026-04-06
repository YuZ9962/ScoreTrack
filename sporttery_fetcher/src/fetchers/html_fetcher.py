from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup

from config.settings import settings
from src.utils.http import HTTPClient
from src.domain.match_time import derive_match_date, infer_issue_date_from_kickoff
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

        matches, used_url = self._fetch_with_playwright(issue_date)
        if matches:
            logger.info("Playwright 抓取成功: %s, 条数=%s", used_url, len(matches))
            return matches, used_url
        return [], None

    def _parse_html(self, html: str, source_url: str, issue_date: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "lxml")

        records = self._parse_calculator_table(soup, source_url, issue_date)
        if records:
            return records

        # 部分页面通过 script JSON 渲染
        script_records = self._parse_from_script_data(soup, source_url, issue_date)
        if script_records:
            return script_records

        return []

    def _parse_calculator_table(self, soup: BeautifulSoup, source_url: str, issue_date: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        rows = soup.select("tr")

        for row in rows:
            texts = [x.get_text(" ", strip=True) for x in row.select("td")]
            if len(texts) < 6:
                continue

            merged = " | ".join(texts)
            if not self._looks_like_match_row(merged):
                continue

            issue_from_row = self._extract_issue_date(merged)
            handicap = self._extract_handicap_row(row, texts)
            home, away = self._extract_teams(merged, texts)
            kickoff = self._extract_kickoff(merged, issue_date)
            inferred_issue = infer_issue_date_from_kickoff(kickoff)
            issue = issue_from_row or inferred_issue or issue_date

            if not (home and away):
                continue

            spf_win, spf_draw, spf_lose = self._extract_spf_values(row, texts)
            rqspf_win, rqspf_draw, rqspf_lose = self._extract_rqspf_values(row, texts)

            records.append(
                {
                    "issue_date": issue,
                    "issue_date_inferred": inferred_issue,
                    "issue_date_source": "row_text" if issue_from_row else ("inferred" if inferred_issue else "request"),
                    "match_date": derive_match_date(kickoff),
                    "match_no": self._extract_match_no(merged),
                    "league": self._extract_league(texts),
                    "home_team": home,
                    "away_team": away,
                    "kickoff_time": kickoff,
                    "handicap": handicap,
                    "sell_status": self._extract_sell_status(merged),
                    "spf_win": spf_win,
                    "spf_draw": spf_draw,
                    "spf_lose": spf_lose,
                    "rqspf_win": rqspf_win,
                    "rqspf_draw": rqspf_draw,
                    "rqspf_lose": rqspf_lose,
                    "play_spf": None,
                    "play_rqspf": None,
                    "play_score": None,
                    "play_goals": None,
                    "play_half_full": None,
                    "source_url": source_url,
                    "scrape_time": datetime.now().isoformat(timespec="seconds"),
                    "raw_id": row.get("data-matchid") or row.get("data-mid") or row.get("id"),
                }
            )

        return records

    def _parse_from_script_data(self, soup: BeautifulSoup, source_url: str, issue_date: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for script in soup.find_all("script"):
            text = script.get_text(" ", strip=True)
            if not text:
                continue
            if "spf" not in text.lower() and "match" not in text.lower():
                continue

            for raw_json in self._extract_json_candidates(text):
                try:
                    payload = json.loads(raw_json)
                except Exception:
                    continue
                for item in self._extract_match_like_items(payload):
                    record = self._map_from_raw(item, source_url, issue_date)
                    if record.get("home_team") and record.get("away_team"):
                        out.append(record)
            if out:
                break
        return out

    @staticmethod
    def _extract_json_candidates(text: str) -> list[str]:
        out: list[str] = []
        for pattern in [r"=\s*(\{.*?\})\s*;", r"=\s*(\[.*?\])\s*;"]:
            out.extend(re.findall(pattern, text, flags=re.DOTALL))
        return out

    def _extract_match_like_items(self, payload: Any) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                keys = {str(k).lower() for k in node.keys()}
                if {"home", "away", "hometeamallname", "awayteamallname", "matchid"} & keys:
                    out.append(node)
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for i in node:
                    walk(i)

        walk(payload)
        return out

    def _map_from_raw(self, raw: dict[str, Any], source_url: str, issue_date: str) -> dict[str, Any]:
        def pick(*keys: str) -> Any:
            for key in keys:
                for k, v in raw.items():
                    if str(k).lower() == key.lower() and v not in ("", None):
                        return v
            return None

        kickoff_time = pick("matchDate", "matchTime")
        inferred_issue = infer_issue_date_from_kickoff(kickoff_time)
        source_issue = pick("businessDate", "issueDate", "date")
        resolved_issue = source_issue or inferred_issue or issue_date

        return {
            "issue_date": resolved_issue,
            "issue_date_inferred": inferred_issue,
            "issue_date_source": "source_field" if source_issue else ("inferred" if inferred_issue else "request"),
            "match_date": derive_match_date(kickoff_time),
            "match_no": pick("lineNum", "matchNo"),
            "league": pick("leagueAllName", "leagueAbbName", "leagueName"),
            "home_team": pick("homeTeamAllName", "homeTeamAbbName", "homeTeamName"),
            "away_team": pick("awayTeamAllName", "awayTeamAbbName", "awayTeamName"),
            "kickoff_time": kickoff_time,
            "handicap": self._safe_handicap(pick("handicap", "letBall", "concede", "rq", "rqNum")),
            "sell_status": pick("sellStatus", "status"),
            "spf_win": pick("win", "spfWin", "winOdds"),
            "spf_draw": pick("draw", "spfDraw", "drawOdds"),
            "spf_lose": pick("lose", "spfLose", "loseOdds"),
            "rqspf_win": pick("rqWin", "rqspfWin"),
            "rqspf_draw": pick("rqDraw", "rqspfDraw"),
            "rqspf_lose": pick("rqLose", "rqspfLose"),
            "play_spf": None,
            "play_rqspf": None,
            "play_score": None,
            "play_goals": None,
            "play_half_full": None,
            "source_url": source_url,
            "scrape_time": datetime.now().isoformat(timespec="seconds"),
            "raw_id": pick("matchId", "id", "mid"),
        }

    @staticmethod
    def _looks_like_match_row(text: str) -> bool:
        return bool(re.search(r"周[一二三四五六日天]\d{3}|\d{2}:\d{2}|VS|vs", text))

    @staticmethod
    def _extract_issue_date(text: str) -> str | None:
        m = re.search(r"(20\d{2}-\d{2}-\d{2})", text)
        return m.group(1) if m else None

    @staticmethod
    def _extract_match_no(text: str) -> str | None:
        m = re.search(r"(周[一二三四五六日天]\d{3})", text)
        return m.group(1) if m else None

    @staticmethod
    def _extract_league(cols: list[str]) -> str | None:
        for c in cols:
            if any(x in c for x in ["联赛", "杯", "甲", "超", "锦标", "友谊"]):
                return c
        return None

    @staticmethod
    def _extract_teams(merged: str, cols: list[str]) -> tuple[str | None, str | None]:
        m = re.search(r"([\w\u4e00-\u9fff·\-]+)\s*(?:VS|vs|v|-)\s*([\w\u4e00-\u9fff·\-]+)", merged)
        if m:
            return m.group(1), m.group(2)

        candidates = [
            c for c in cols if 1 < len(c) < 40 and not re.search(r"\d|周[一二三四五六日天]|联赛|开售|停售", c)
        ]
        if len(candidates) >= 2:
            return candidates[-2], candidates[-1]
        return None, None

    def _extract_kickoff(self, text: str, issue_date: str) -> str | None:
        m1 = re.search(r"(20\d{2}-\d{2}-\d{2}\s*\d{2}:\d{2})", text)
        if m1:
            return m1.group(1).replace("  ", " ")
        m2 = re.search(r"(\d{2}:\d{2})", text)
        if m2:
            return f"{issue_date} {m2.group(1)}"
        return None

    def _extract_handicap_row(self, row: Any, cols: list[str]) -> str | None:
        # 1) 优先字段属性
        for attr in ["data-rq", "data-handicap", "data-letball"]:
            val = row.get(attr)
            h = self._safe_handicap(val)
            if h is not None:
                return h

        # 2) 仅从带“让球”语义的列中提取，避免赔率数字误判
        tagged_cells = row.select("td[class*='rq'],td[class*='rangqiu'],td[data-type='rq']")
        for cell in tagged_cells:
            h = self._safe_handicap(cell.get_text(" ", strip=True))
            if h is not None:
                return h

        # 3) 从文本里匹配“让球:+1 / 让: -1”模式
        merged = " | ".join(cols)
        m = re.search(r"让球\s*[:：]?\s*([+-]?\d+(?:\.\d+)?)", merged)
        if m:
            return self._safe_handicap(m.group(1))

        return None

    @staticmethod
    def _safe_handicap(value: Any) -> str | None:
        if value in (None, ""):
            return None
        text = str(value).strip()
        m = re.search(r"([+-]?\d+(?:\.\d+)?)", text)
        if not m:
            return None
        number = m.group(1)
        # 严格校验：让球通常为整数/半球等，范围不应过大
        try:
            x = float(number)
        except ValueError:
            return None
        if -10 <= x <= 10:
            return number
        return None

    @staticmethod
    def _extract_spf_values(row: Any, cols: list[str]) -> tuple[Any, Any, Any]:
        # 优先 class 语义
        win = row.select_one("td[class*='win'],span[class*='win']")
        draw = row.select_one("td[class*='draw'],span[class*='draw']")
        lose = row.select_one("td[class*='lose'],span[class*='lose']")
        if win or draw or lose:
            return (
                win.get_text(strip=True) if win else None,
                draw.get_text(strip=True) if draw else None,
                lose.get_text(strip=True) if lose else None,
            )

        # 兜底：从结尾赔率提取前三个数字
        nums = re.findall(r"\b\d{1,2}\.\d{2}\b", " | ".join(cols))
        if len(nums) >= 3:
            return nums[0], nums[1], nums[2]
        return None, None, None

    @staticmethod
    def _extract_rqspf_values(row: Any, cols: list[str]) -> tuple[Any, Any, Any]:
        win = row.select_one("td[class*='rqwin'],span[class*='rqwin']")
        draw = row.select_one("td[class*='rqdraw'],span[class*='rqdraw']")
        lose = row.select_one("td[class*='rqlose'],span[class*='rqlose']")
        if win or draw or lose:
            return (
                win.get_text(strip=True) if win else None,
                draw.get_text(strip=True) if draw else None,
                lose.get_text(strip=True) if lose else None,
            )

        nums = re.findall(r"\b\d{1,2}\.\d{2}\b", " | ".join(cols))
        if len(nums) >= 6:
            return nums[3], nums[4], nums[5]
        return None, None, None

    @staticmethod
    def _extract_sell_status(text: str) -> str | None:
        if "停售" in text:
            return "停售"
        if "开售" in text:
            return "开售"
        return None

    def _fetch_with_playwright(self, issue_date: str) -> tuple[list[dict[str, Any]], str | None]:
        try:
            from src.fetchers.playwright_utils import managed_playwright, stealth_browser_context
        except Exception:
            logger.error("Playwright 未安装：请先执行 playwright install chromium")
            return [], None

        try:
            with managed_playwright() as p:
                browser, context = stealth_browser_context(p, settings.playwright_headless, settings.user_agent)
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
