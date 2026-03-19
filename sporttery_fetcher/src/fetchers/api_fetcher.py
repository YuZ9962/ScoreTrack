from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from config.settings import settings
from src.utils.http import HTTPClient
from src.utils.logger import get_logger

logger = get_logger(__name__)


class APIFetcher:
    """优先尝试站内 API/XHR 的抓取器。"""

    def __init__(self, http_client: HTTPClient | None = None) -> None:
        self.http = http_client or HTTPClient()
        self.candidate_endpoints = self._load_candidate_endpoints()

    def _load_candidate_endpoints(self) -> list[str]:
        # 优先环境变量（手动确认过最可靠）
        raw = os.getenv("SPORTTERY_API_ENDPOINTS", "")
        env_urls = [u.strip() for u in raw.split(",") if u.strip()]
        if env_urls:
            return env_urls

        # 次选 interface_detector 输出，自动筛出 sporttery JSON/XHR URL
        detector_file = settings.data_raw_dir / "detected_xhr.json"
        if detector_file.exists():
            try:
                payload = json.loads(detector_file.read_text(encoding="utf-8"))
                urls: list[str] = []
                for item in payload:
                    url = str(item.get("url", ""))
                    if "sporttery" not in url:
                        continue
                    if any(x in url.lower() for x in [".js", ".css", ".png", ".jpg", ".gif"]):
                        continue
                    if url not in urls:
                        urls.append(url)
                if urls:
                    logger.info("从 detected_xhr.json 加载到 %s 条 API 候选", len(urls))
                    return urls
            except Exception as exc:
                logger.warning("读取 detected_xhr.json 失败: %s", exc)

        return []

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
