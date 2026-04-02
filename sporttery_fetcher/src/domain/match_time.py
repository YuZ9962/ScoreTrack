from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

ISSUE_DAY_CUTOFF_HOUR = 11


def normalize_issue_date(issue_date: str | date | datetime | None) -> str:
    if issue_date is None:
        return ""
    if isinstance(issue_date, datetime):
        return issue_date.date().isoformat()
    if isinstance(issue_date, date):
        return issue_date.isoformat()
    text = str(issue_date).strip().replace("/", "-").replace(".", "-")
    if not text:
        return ""
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except Exception:
            continue
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except Exception:
        return text[:10]


def parse_kickoff_time(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("/", "-")
    fmts = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d",
    )
    for fmt in fmts:
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


def get_issue_date_window(issue_date: str | date | datetime) -> tuple[datetime, datetime]:
    d = date.fromisoformat(normalize_issue_date(issue_date))
    start = datetime.combine(d, time(hour=ISSUE_DAY_CUTOFF_HOUR))
    end = start + timedelta(days=1)
    return start, end


def infer_issue_date_from_kickoff(kickoff_time: Any) -> str | None:
    dt = parse_kickoff_time(kickoff_time)
    if not dt:
        return None
    cutoff = time(hour=ISSUE_DAY_CUTOFF_HOUR)
    if dt.time() < cutoff:
        return (dt.date() - timedelta(days=1)).isoformat()
    return dt.date().isoformat()


def kickoff_belongs_to_issue_date(kickoff_time: Any, issue_date: str | date | datetime) -> bool:
    dt = parse_kickoff_time(kickoff_time)
    if not dt:
        return False
    start, end = get_issue_date_window(issue_date)
    return start <= dt < end


def derive_match_date(kickoff_time: Any) -> str | None:
    dt = parse_kickoff_time(kickoff_time)
    return dt.date().isoformat() if dt else None
