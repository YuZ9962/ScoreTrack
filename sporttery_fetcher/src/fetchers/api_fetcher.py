from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from src.utils.http import HTTPClient
from src.utils.logger import get_logger

logger = get_logger(__name__)


class APIFetcher:
    """优先尝试站内 API/XHR 的抓取器。"""

    def __init__(self, http_client: HTTPClient | None = None) -> None:
        self.http = http_client or HTTPClient()
        # 默认不再内置已失效旧接口；从环境变量注入（逗号分隔）以便 interface_detector 后快速验证。
        raw = os.getenv("SPORTTERY_API_ENDPOINTS", "")
        self.candidate_endpoints = [u.strip() for u in raw.split(",") if u.strip()]

    def fetch(self, issue_date: str) -> tuple[list[dict[str, Any]], str | None]:
        if not self.candidate_endpoints:
            logger.info("API 抓取跳过：未配置可用接口（请先运行 interface_detector 检查 XHR）")
            return [], None

        for endpoint in self.candidate_endpoints:
            try:
                records = self._fetch_from_endpoint(endpoint, issue_date)
                if records:
                    logger.info("API 抓取成功: %s, 条数=%s", endpoint, len(records))
                    return records, endpoint
                logger.info("API 返回为空: %s", endpoint)
            except Exception as exc:
                logger.warning("API 抓取失败: %s, 原因: %s", endpoint, exc)
        logger.info("API 抓取未命中可用数据，将回退 HTML")
        return [], None

    def _fetch_from_endpoint(self, endpoint: str, issue_date: str) -> list[dict[str, Any]]:
        params = {"date": issue_date, "issue_date": issue_date, "play": "jczq"}
        response = self.http.request("GET", endpoint, params=params)
        ctype = response.headers.get("Content-Type", "")
        if "json" not in ctype.lower() and not response.text.strip().startswith(("{", "[")):
            return []

        data = response.json()
        raw_matches = self._extract_match_like_items(data)
        converted = [self._map_raw_match(item) for item in raw_matches]
        return [row for row in converted if row.get("home_team") and row.get("away_team")]

    def _extract_match_like_items(self, data: Any) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                keys = {k.lower() for k in node.keys()}
                if {"home", "away"} & keys or {"hometeam", "awayteam"} & keys:
                    found.append(node)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(data)
        return found

    @staticmethod
    def _pick(raw: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in raw and raw[key] not in ("", None):
                return raw[key]
            low_key = key.lower()
            for k, v in raw.items():
                if str(k).lower() == low_key and v not in ("", None):
                    return v
        return None

    def _map_raw_match(self, raw: dict[str, Any]) -> dict[str, Any]:
        kickoff = self._pick(raw, "kickoff_time", "matchTime", "saleEndTime", "time")
        return {
            "issue_date": self._pick(raw, "issue_date", "date", "matchDate"),
            "match_no": self._pick(raw, "match_no", "matchNumStr", "week", "matchCode"),
            "league": self._pick(raw, "league", "leagueName", "l_cn_abbr"),
            "home_team": self._pick(raw, "home_team", "home", "h_cn", "homeTeamName"),
            "away_team": self._pick(raw, "away_team", "away", "a_cn", "awayTeamName"),
            "kickoff_time": kickoff,
            "handicap": self._pick(raw, "handicap", "rq", "concede", "letBall"),
            "sell_status": self._pick(raw, "sell_status", "isSale", "status", "sellStatus"),
            "play_spf": self._pick(raw, "play_spf", "spf", "is_single"),
            "play_rqspf": self._pick(raw, "play_rqspf", "rqspf"),
            "play_score": self._pick(raw, "play_score", "bf"),
            "play_goals": self._pick(raw, "play_goals", "jq", "zjq"),
            "play_half_full": self._pick(raw, "play_half_full", "bqc"),
            "raw_id": self._pick(raw, "id", "matchId", "mid"),
            "scrape_time": datetime.now().isoformat(timespec="seconds"),
        }
