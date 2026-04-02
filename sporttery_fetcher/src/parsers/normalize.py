from __future__ import annotations

from datetime import datetime
from typing import Any

from src.domain.match_identity import build_match_key
from src.domain.match_time import derive_match_date, infer_issue_date_from_kickoff


STANDARD_FIELDS = [
    "issue_date",
    "issue_date_inferred",
    "issue_date_source",
    "match_date",   # 实际比赛日期（≠ issue_date 销售日）
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
    "match_key",    # 全局唯一比赛标识，由 match_identity 模块生成
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

    kickoff_time = record.get("kickoff_time")
    source_issue_date = record.get("issue_date") or issue_date
    inferred_issue_date = infer_issue_date_from_kickoff(kickoff_time)
    resolved_issue_date = source_issue_date or inferred_issue_date or issue_date

    # match_date: 实际开赛日期（自然日）
    match_date = record.get("match_date") or derive_match_date(kickoff_time)

    normalized.update(
        {
            "issue_date": resolved_issue_date,
            "issue_date_inferred": inferred_issue_date,
            "issue_date_source": record.get("issue_date_source") or ("source" if record.get("issue_date") else ("inferred" if inferred_issue_date else "request")),
            "match_date": match_date,
            "match_no": record.get("match_no"),
            "league": record.get("league"),
            "home_team": record.get("home_team"),
            "away_team": record.get("away_team"),
            "kickoff_time": kickoff_time,
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
    # match_key 最后计算，确保所有字段已填充
    normalized["match_key"] = record.get("match_key") or build_match_key(normalized)
    return normalized


def normalize_matches(records: list[dict[str, Any]], issue_date: str, source_url: str) -> list[dict[str, Any]]:
    return [normalize_match(r, issue_date=issue_date, source_url=source_url) for r in records]
