from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from config.settings import settings
from src.utils.http import HTTPClient
from src.utils.logger import get_logger

logger = get_logger(__name__)


class APIFetcher:
    """优先尝试从主页面关联的 JSON/XHR 接口抓取数据。"""

    def __init__(self, http_client: HTTPClient | None = None) -> None:
        self.http = http_client or HTTPClient()
        self.source_page = settings.primary_page_url

    def fetch(self, issue_date: str) -> tuple[list[dict[str, Any]], str | None]:
        endpoints = self._load_candidate_endpoints()
        if not endpoints:
            logger.info("API 抓取跳过：未发现可用候选接口（可先运行 interface_detector）")
            return [], None

        for endpoint in endpoints:
            try:
                response = self.http.request("GET", endpoint)
                payload = response.json()
                records = self._extract_matches(payload, issue_date)
                if records:
                    logger.info("API 抓取成功: endpoint=%s, 条数=%s", endpoint, len(records))
                    return records, endpoint
                logger.info("API 返回成功但无匹配数据: %s", endpoint)
            except Exception as exc:
                logger.warning("API 抓取失败: %s, 原因: %s", endpoint, exc)
        return [], None

    def _load_candidate_endpoints(self) -> list[str]:
        # 1) 环境变量
        if settings.api_candidate_urls:
            return list(settings.api_candidate_urls)

        # 2) interface_detector 产物
        detector_file = settings.data_raw_dir / "detected_xhr.json"
        if detector_file.exists():
            try:
                data = json.loads(detector_file.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("读取 detected_xhr.json 失败: %s", exc)
                return []

            urls: list[str] = []
            for item in data:
                url = str(item.get("url", "")).strip()
                if not url:
                    continue
                if "sporttery" not in url and "webapi.sporttery.cn" not in url:
                    continue
                if any(x in url.lower() for x in [".js", ".css", ".png", ".jpg", ".gif", ".svg"]):
                    continue
                if url not in urls:
                    urls.append(url)
            return urls

        return []

    def _extract_matches(self, payload: Any, issue_date: str) -> list[dict[str, Any]]:
        candidates = self._find_match_items(payload)
        out: list[dict[str, Any]] = []

        for item in candidates:
            issue = self._pick(item, "businessDate", "issueDate", "date")
            match_date = self._pick(item, "matchDate", "matchTime", "startTime")
            match_day = str(match_date)[:10] if match_date else None
            effective_issue = issue or match_day

            if issue_date and effective_issue and str(effective_issue) != issue_date:
                continue

            handicap = self._extract_handicap(item)
            record = {
                "issue_date": effective_issue or issue_date,
                "match_no": self._pick(item, "lineNum", "matchNo", "matchNumStr"),
                "league": self._pick(item, "leagueAllName", "leagueAbbName", "leagueName"),
                "home_team": self._pick(item, "homeTeamAllName", "homeTeamAbbName", "homeTeamName"),
                "away_team": self._pick(item, "awayTeamAllName", "awayTeamAbbName", "awayTeamName"),
                "kickoff_time": self._build_kickoff(item),
                "handicap": handicap,
                "sell_status": self._pick(item, "sellStatus", "status", "isSale"),
                "spf_win": self._pick(item, "win", "h", "spfWin", "winOdds"),
                "spf_draw": self._pick(item, "draw", "d", "spfDraw", "drawOdds"),
                "spf_lose": self._pick(item, "lose", "a", "spfLose", "loseOdds"),
                "rqspf_win": self._pick(item, "rqWin", "rqspfWin"),
                "rqspf_draw": self._pick(item, "rqDraw", "rqspfDraw"),
                "rqspf_lose": self._pick(item, "rqLose", "rqspfLose"),
                "play_spf": None,
                "play_rqspf": None,
                "play_score": None,
                "play_goals": None,
                "play_half_full": None,
                "source_url": self.source_page,
                "scrape_time": datetime.now().isoformat(timespec="seconds"),
                "raw_id": self._pick(item, "matchId", "id", "mid"),
            }

            if record["home_team"] and record["away_team"]:
                out.append(record)

        return out

    def _find_match_items(self, payload: Any) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []

        def walk(node: Any, parent_issue: str | None = None) -> None:
            if isinstance(node, dict):
                issue = self._pick(node, "businessDate", "issueDate", "date") or parent_issue
                keys = {str(k).lower() for k in node.keys()}
                looks_like_match = bool(
                    {"hometeamallname", "awayteamallname", "hometeamabbname", "awayteamabbname", "matchid"} & keys
                )
                if looks_like_match:
                    if issue and "businessDate" not in node:
                        node = {**node, "businessDate": issue}
                    out.append(node)

                for v in node.values():
                    walk(v, issue)
            elif isinstance(node, list):
                for i in node:
                    walk(i, parent_issue)

        walk(payload)
        return out

    @staticmethod
    def _pick(raw: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            for k, v in raw.items():
                if str(k).lower() == key.lower() and v not in ("", None):
                    return v
        return None

    def _build_kickoff(self, raw: dict[str, Any]) -> str | None:
        match_date = self._pick(raw, "matchDate")
        if match_date:
            return str(match_date)

        date_part = self._pick(raw, "businessDate", "issueDate")
        time_part = self._pick(raw, "matchTime", "startTime")
        if date_part and time_part:
            return f"{date_part} {time_part}"
        return str(date_part) if date_part else None

    def _extract_handicap(self, raw: dict[str, Any]) -> str | None:
        # 仅从明确字段抓让球，避免把赔率误识别为让球
        val = self._pick(raw, "handicap", "letBall", "concede", "rq", "rqNum")
        if val in (None, ""):
            return None
        text = str(val).strip()
        if text.lstrip("+-").replace(".", "", 1).isdigit():
            return text
        return None
