from __future__ import annotations

import re
from typing import Literal

import pandas as pd
from src.domain.match_time import infer_issue_date_from_kickoff

TimeMode = Literal["按日", "按月", "按年"]



def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in ["kickoff_time", "scrape_time"]:
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], errors="coerce")

    numeric_cols = [
        "spf_win",
        "spf_draw",
        "spf_lose",
        "rqspf_win",
        "rqspf_draw",
        "rqspf_lose",
    ]
    for col in numeric_cols:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    if "handicap" in out.columns:
        out["handicap"] = out["handicap"].astype("string")

    return out



def apply_filters(
    df: pd.DataFrame,
    leagues: list[str] | None = None,
    keyword: str | None = None,
    only_handicap_non_null: bool = False,
    only_selling: bool = False,
) -> pd.DataFrame:
    out = df.copy()

    if leagues:
        out = out[out["league"].isin(leagues)]

    if keyword:
        kw = keyword.strip().lower()
        if kw:
            home = out.get("home_team", pd.Series([], dtype="string")).fillna("").str.lower()
            away = out.get("away_team", pd.Series([], dtype="string")).fillna("").str.lower()
            out = out[home.str.contains(kw) | away.str.contains(kw)]

    if only_handicap_non_null and "handicap" in out.columns:
        out = out[out["handicap"].notna() & (out["handicap"].astype(str).str.strip() != "")]

    if only_selling and "sell_status" in out.columns:
        out = out[out["sell_status"].astype(str).str.contains("开售", na=False)]

    return out



def sort_matches(df: pd.DataFrame, sort_by: str, ascending: bool = True) -> pd.DataFrame:
    mapping = {
        "开赛时间": "kickoff_time",
        "联赛": "league",
        "场次编号": "match_no",
    }
    col = mapping.get(sort_by, "kickoff_time")
    if col not in df.columns:
        return df
    return df.sort_values(by=col, ascending=ascending, na_position="last")



def ensure_issue_date_columns(df: pd.DataFrame, source_col: str = "issue_date") -> pd.DataFrame:
    out = df.copy()
    if source_col not in out.columns:
        out[source_col] = None

    issue_series = out[source_col].astype("string")
    if "kickoff_time" in out.columns:
        inferred = out["kickoff_time"].map(infer_issue_date_from_kickoff)
        issue_series = issue_series.fillna(inferred)
        issue_series = issue_series.mask(issue_series.str.strip() == "", inferred)

    base = pd.to_datetime(issue_series, errors="coerce")
    out["_date"] = base.dt.strftime("%Y-%m-%d")
    out["_month"] = base.dt.strftime("%Y-%m")
    out["_year"] = base.dt.strftime("%Y")
    return out



def filter_by_time_and_league(df: pd.DataFrame, time_mode: TimeMode, time_value: str, league: str) -> pd.DataFrame:
    out = df.copy()

    col_map = {"按日": "_date", "按月": "_month", "按年": "_year"}
    target_col = col_map[time_mode]
    if target_col in out.columns and time_value:
        out = out[out[target_col].astype(str) == str(time_value)]

    if league != "全部联赛" and "league" in out.columns:
        out = out[out["league"].fillna("").astype(str) == league]

    return out



def parse_match_no_sort_key(match_no: str) -> tuple[str, int, str]:
    text = str(match_no or "")
    m = re.search(r"([0-9]{1,3})", text)
    number = int(m.group(1)) if m else 10**9
    prefix = text[: m.start()] if m else text
    return (prefix, number, text)



def sort_by_match_no(df: pd.DataFrame) -> pd.DataFrame:
    if "match_no" not in df.columns:
        return df
    out = df.copy()
    out["_match_sort_key"] = out["match_no"].map(parse_match_no_sort_key)
    out = out.sort_values(by="_match_sort_key", ascending=True, na_position="last")
    return out.drop(columns=["_match_sort_key"])
