from __future__ import annotations

import pandas as pd


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
