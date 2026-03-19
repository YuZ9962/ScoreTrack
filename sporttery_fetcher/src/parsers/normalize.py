from __future__ import annotations

from datetime import datetime
from typing import Any


STANDARD_FIELDS = [
    "issue_date",
    "match_no",
    "league",
    "home_team",
    "away_team",
    "kickoff_time",
    "handicap",
    "sell_status",
    "spf_win",
    "spf_draw",
    "spf_lose",
    "rqspf_win",
    "rqspf_draw",
    "rqspf_lose",
    "play_spf",
    "play_rqspf",
    "play_score",
    "play_goals",
    "play_half_full",
    "source_url",
    "scrape_time",
    "raw_id",
]


def to_bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "开", "开售", "已开售", "是"}:
        return True
    if text in {"0", "false", "no", "n", "关", "停售", "未开售", "否"}:
        return False
    return None


def normalize_match(record: dict[str, Any], issue_date: str, source_url: str) -> dict[str, Any]:
    normalized: dict[str, Any] = {k: None for k in STANDARD_FIELDS}
    normalized.update(
        {
            "issue_date": record.get("issue_date") or issue_date,
            "match_no": record.get("match_no"),
            "league": record.get("league"),
            "home_team": record.get("home_team"),
            "away_team": record.get("away_team"),
            "kickoff_time": record.get("kickoff_time"),
            "handicap": record.get("handicap"),
            "sell_status": record.get("sell_status"),
            "spf_win": record.get("spf_win"),
            "spf_draw": record.get("spf_draw"),
            "spf_lose": record.get("spf_lose"),
            "rqspf_win": record.get("rqspf_win"),
            "rqspf_draw": record.get("rqspf_draw"),
            "rqspf_lose": record.get("rqspf_lose"),
            "play_spf": to_bool_or_none(record.get("play_spf")),
            "play_rqspf": to_bool_or_none(record.get("play_rqspf")),
            "play_score": to_bool_or_none(record.get("play_score")),
            "play_goals": to_bool_or_none(record.get("play_goals")),
            "play_half_full": to_bool_or_none(record.get("play_half_full")),
            "source_url": record.get("source_url") or source_url,
            "scrape_time": record.get("scrape_time") or datetime.now().isoformat(timespec="seconds"),
            "raw_id": record.get("raw_id"),
        }
    )
    return normalized


def normalize_matches(records: list[dict[str, Any]], issue_date: str, source_url: str) -> list[dict[str, Any]]:
    return [normalize_match(r, issue_date=issue_date, source_url=source_url) for r in records]
