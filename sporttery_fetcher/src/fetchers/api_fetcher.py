from __future__ import annotations

from datetime import datetime
from typing import Any

from config.settings import settings
from src.utils.http import HTTPClient
from src.domain.match_time import derive_match_date, infer_issue_date_from_kickoff
from src.utils.logger import get_logger

logger = get_logger(__name__)


class APIFetcher:
    """基于已确认官方接口 getMatchCalculatorV1.qry 抓取竞彩足球数据。"""

    ENDPOINT = "https://webapi.sporttery.cn/gateway/uniform/football/getMatchCalculatorV1.qry?channel=c&poolCode=hhad,had"

    def __init__(self, http_client: HTTPClient | None = None) -> None:
        self.http = http_client or HTTPClient()
        self.source_page = settings.primary_page_url

    def fetch(self, issue_date: str) -> tuple[list[dict[str, Any]], str | None]:
        try:
            response = self.http.request("GET", self.ENDPOINT)
            payload = response.json()
        except Exception as exc:
            logger.warning("API 抓取失败: %s", exc)
            return [], None

        if not isinstance(payload, dict):
            logger.warning("API 响应格式异常，非 JSON 对象")
            return [], None

        success = payload.get("success")
        if success is False:
            logger.warning("API success=false, errorCode=%s", payload.get("errorCode"))
            return [], None

        records = self._extract_matches(payload, issue_date)
        logger.info("API 抓取完成: endpoint=%s, issue_date=%s, 条数=%s", self.ENDPOINT, issue_date, len(records))
        return records, self.ENDPOINT

    def _extract_matches(self, payload: dict[str, Any], issue_date: str) -> list[dict[str, Any]]:
        value = payload.get("value") or {}
        match_info_list = value.get("matchInfoList") or []

        out: list[dict[str, Any]] = []
        for day_bucket in match_info_list:
            if not isinstance(day_bucket, dict):
                continue
            business_date = self._str_or_none(day_bucket.get("businessDate"))

            sub_list = day_bucket.get("subMatchList") or []
            for item in sub_list:
                if not isinstance(item, dict):
                    continue

                had = item.get("had") or {}
                hhad = item.get("hhad") or {}
                odds_list = item.get("oddsList") or []

                had_odds = self._odds_from_list(odds_list, "HAD")
                hhad_odds = self._odds_from_list(odds_list, "HHAD")

                match_date = self._str_or_none(item.get("matchDate"))
                match_time = self._str_or_none(item.get("matchTime"))
                kickoff_time = self._build_kickoff_time(match_date, match_time)

                # 映射按用户确认规则
                spf_win = self._pick(had, "h") or self._pick(had_odds, "h")
                spf_draw = self._pick(had, "d") or self._pick(had_odds, "d")
                spf_lose = self._pick(had, "a") or self._pick(had_odds, "a")

                rqspf_win = self._pick(hhad, "h") or self._pick(hhad_odds, "h")
                rqspf_draw = self._pick(hhad, "d") or self._pick(hhad_odds, "d")
                rqspf_lose = self._pick(hhad, "a") or self._pick(hhad_odds, "a")

                handicap = (
                    self._pick(hhad, "goalLine")
                    or self._pick(hhad, "goalLineValue")
                    or self._pick(hhad_odds, "goalLine")
                )
                handicap = self._normalize_handicap(handicap)

                match_status = self._str_or_none(item.get("matchStatus"))
                sell_status_raw = item.get("sellStatus")
                sell_status = self._normalize_sell_status(match_status, sell_status_raw)

                inferred_issue_date = infer_issue_date_from_kickoff(kickoff_time)
                resolved_issue_date = business_date or inferred_issue_date or issue_date
                if issue_date and resolved_issue_date and resolved_issue_date != issue_date:
                    continue

                # match_date = 实际比赛自然日
                resolved_match_date = match_date or derive_match_date(kickoff_time)

                out.append(
                    {
                        "issue_date": resolved_issue_date,
                        "issue_date_inferred": inferred_issue_date,
                        "issue_date_source": "businessDate" if business_date else ("inferred" if inferred_issue_date else "request"),
                        "match_date": resolved_match_date,
                        "match_no": self._str_or_none(item.get("matchNumStr")),
                        "league": self._str_or_none(item.get("leagueAllName")) or self._str_or_none(item.get("leagueAbbName")),
                        "home_team": self._str_or_none(item.get("homeTeamAllName")) or self._str_or_none(item.get("homeTeamAbbName")),
                        "away_team": self._str_or_none(item.get("awayTeamAllName")) or self._str_or_none(item.get("awayTeamAbbName")),
                        "kickoff_time": kickoff_time,
                        "handicap": handicap,
                        "sell_status": sell_status,
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
                        "source_url": self.source_page,
                        "scrape_time": datetime.now().isoformat(timespec="seconds"),
                        "raw_id": item.get("matchId"),
                    }
                )

        return out

    @staticmethod
    def _pick(data: dict[str, Any], key: str) -> Any:
        if not isinstance(data, dict):
            return None
        value = data.get(key)
        return value if value not in ("", None) else None

    @staticmethod
    def _str_or_none(value: Any) -> str | None:
        if value in (None, ""):
            return None
        return str(value).strip()

    def _odds_from_list(self, odds_list: list[Any], pool_code: str) -> dict[str, Any]:
        for item in odds_list:
            if not isinstance(item, dict):
                continue
            code = str(item.get("poolCode", "")).upper()
            if code == pool_code:
                return item
        return {}

    def _build_kickoff_time(self, match_date: str | None, match_time: str | None) -> str | None:
        if match_date and match_time:
            return f"{match_date} {match_time[:5]}"
        if match_date:
            return match_date
        return None

    def _normalize_handicap(self, value: Any) -> str | None:
        if value in (None, ""):
            return None
        text = str(value).strip()
        # 仅允许明确数字（可带正负和小数）
        if text.lstrip("+-").replace(".", "", 1).isdigit():
            return text
        return None

    def _normalize_sell_status(self, match_status: str | None, sell_status_raw: Any) -> str | Any | None:
        if match_status == "Selling" or str(sell_status_raw) == "2":
            return "开售"
        if match_status not in (None, ""):
            return match_status
        return sell_status_raw
