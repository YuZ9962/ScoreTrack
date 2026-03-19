from __future__ import annotations

from datetime import datetime
from typing import Any

from config.settings import settings
from src.utils.http import HTTPClient
from src.utils.logger import get_logger

logger = get_logger(__name__)


class APIFetcher:
    """基于已确认官方接口抓取竞彩足球赛程。"""

    def __init__(self, http_client: HTTPClient | None = None) -> None:
        self.http = http_client or HTTPClient()
        self.endpoint = settings.football_api_url

    def fetch(self, issue_date: str) -> tuple[list[dict[str, Any]], str | None]:
        try:
            response = self.http.request("GET", self.endpoint)
            data = response.json()
        except Exception as exc:
            logger.warning("API 抓取失败: %s", exc)
            return [], None

        if not isinstance(data, dict):
            logger.warning("API 响应不是 JSON 对象")
            return [], None

        if data.get("success") is not True:
            logger.warning("API success!=true, errorCode=%s", data.get("errorCode"))
            return [], None

        matches = self._extract_matches(data, issue_date)
        logger.info("API 抓取完成: endpoint=%s, issue_date=%s, 条数=%s", self.endpoint, issue_date, len(matches))
        return matches, self.endpoint

    def _extract_matches(self, payload: dict[str, Any], issue_date: str) -> list[dict[str, Any]]:
        value = payload.get("value") or {}
        match_info_list = value.get("matchInfoList") or []

        records: list[dict[str, Any]] = []
        for bucket in match_info_list:
            if not isinstance(bucket, dict):
                continue
            business_date = str(bucket.get("businessDate") or "").strip() or None
            sub_list = bucket.get("subMatchList") or []
            for item in sub_list:
                if not isinstance(item, dict):
                    continue

                # 按 issue_date 过滤：优先 businessDate；缺失时回退 matchDate 前 10 位
                match_date = self._safe_str(item.get("matchDate"))
                match_day = match_date[:10] if match_date else None
                effective_date = business_date or match_day
                if issue_date and effective_date and effective_date != issue_date:
                    continue

                kickoff_time = self._build_kickoff_time(item)
                records.append(
                    {
                        "issue_date": effective_date or issue_date,
                        "match_no": item.get("lineNum"),
                        "league": item.get("leagueAllName") or item.get("leagueAbbName"),
                        "home_team": item.get("homeTeamAllName") or item.get("homeTeamAbbName"),
                        "away_team": item.get("awayTeamAllName") or item.get("awayTeamAbbName"),
                        "kickoff_time": kickoff_time,
                        "handicap": None,
                        "sell_status": None,
                        "play_spf": None,
                        "play_rqspf": None,
                        "play_score": None,
                        "play_goals": None,
                        "play_half_full": None,
                        "source_url": "https://www.sporttery.cn/jc/zqszsc/",
                        "scrape_time": datetime.now().isoformat(timespec="seconds"),
                        "raw_id": item.get("matchId"),
                    }
                )

        return records

    @staticmethod
    def _safe_str(value: Any) -> str | None:
        if value in (None, ""):
            return None
        return str(value).strip()

    def _build_kickoff_time(self, match: dict[str, Any]) -> str | None:
        match_date = self._safe_str(match.get("matchDate"))
        if match_date and len(match_date) >= 16:
            return match_date

        for key in ["matchTime", "saleEndTime", "startTime", "startSaleTime"]:
            time_val = self._safe_str(match.get(key))
            if not time_val:
                continue
            if match_date and len(match_date) >= 10 and len(time_val) <= 8 and ":" in time_val:
                return f"{match_date[:10]} {time_val}"
            return time_val

        return match_date
