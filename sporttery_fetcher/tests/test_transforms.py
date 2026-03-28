"""Tests for app/services/transforms.py utility functions."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"
for p in [str(ROOT), str(APP_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from services.transforms import (
    normalize_dataframe,
    apply_filters,
    sort_matches,
    ensure_issue_date_columns,
    filter_by_time_and_league,
    parse_match_no_sort_key,
    sort_by_match_no,
)


def _make_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "league": "英超",
                "home_team": "曼城",
                "away_team": "利物浦",
                "kickoff_time": "2026-03-20 20:00",
                "spf_win": "1.75",
                "spf_draw": "3.50",
                "spf_lose": "4.20",
                "rqspf_win": "1.85",
                "rqspf_draw": "3.40",
                "rqspf_lose": "4.00",
                "handicap": "-1",
                "sell_status": "开售",
                "match_no": "001",
                "issue_date": "2026-03-20",
            },
            {
                "league": "西甲",
                "home_team": "皇马",
                "away_team": "巴萨",
                "kickoff_time": "2026-03-21 22:00",
                "spf_win": "2.10",
                "spf_draw": "3.20",
                "spf_lose": "3.10",
                "rqspf_win": "2.00",
                "rqspf_draw": "3.30",
                "rqspf_lose": "3.50",
                "handicap": None,
                "sell_status": "停售",
                "match_no": "002",
                "issue_date": "2026-03-21",
            },
        ]
    )


class TestNormalizeDataframe:
    def test_numeric_cols_converted(self):
        df = _make_df()
        out = normalize_dataframe(df)
        assert out["spf_win"].dtype.kind == "f"
        assert out["spf_draw"].dtype.kind == "f"

    def test_kickoff_time_is_datetime(self):
        df = _make_df()
        out = normalize_dataframe(df)
        assert pd.api.types.is_datetime64_any_dtype(out["kickoff_time"])

    def test_handicap_is_string_dtype(self):
        df = _make_df()
        out = normalize_dataframe(df)
        assert out["handicap"].dtype == pd.StringDtype() or out["handicap"].dtype.name == "string"


class TestApplyFilters:
    def test_league_filter(self):
        df = _make_df()
        out = apply_filters(df, leagues=["英超"])
        assert len(out) == 1
        assert out.iloc[0]["league"] == "英超"

    def test_keyword_filter_home_team(self):
        df = _make_df()
        out = apply_filters(df, keyword="曼城")
        assert len(out) == 1
        assert out.iloc[0]["home_team"] == "曼城"

    def test_keyword_filter_away_team(self):
        df = _make_df()
        out = apply_filters(df, keyword="巴萨")
        assert len(out) == 1

    def test_only_handicap_non_null(self):
        df = _make_df()
        out = apply_filters(df, only_handicap_non_null=True)
        assert len(out) == 1
        assert out.iloc[0]["handicap"] == "-1"

    def test_only_selling(self):
        df = _make_df()
        out = apply_filters(df, only_selling=True)
        assert len(out) == 1
        assert out.iloc[0]["sell_status"] == "开售"

    def test_no_filter_returns_all(self):
        df = _make_df()
        out = apply_filters(df)
        assert len(out) == 2

    def test_empty_keyword_returns_all(self):
        df = _make_df()
        out = apply_filters(df, keyword="")
        assert len(out) == 2


class TestSortMatches:
    def test_sort_by_kickoff_time_ascending(self):
        df = _make_df()
        out = sort_matches(df, "开赛时间", ascending=True)
        assert out.iloc[0]["league"] == "英超"

    def test_sort_by_kickoff_time_descending(self):
        df = _make_df()
        out = sort_matches(df, "开赛时间", ascending=False)
        assert out.iloc[0]["league"] == "西甲"

    def test_sort_by_league(self):
        df = _make_df()
        out = sort_matches(df, "联赛", ascending=True)
        assert out.iloc[0]["league"] == "英超"

    def test_unknown_sort_key_returns_df(self):
        df = _make_df()
        out = sort_matches(df, "unknown_key")
        assert len(out) == len(df)


class TestEnsureIssueDateColumns:
    def test_adds_date_month_year_cols(self):
        df = _make_df()
        out = ensure_issue_date_columns(df)
        assert "_date" in out.columns
        assert "_month" in out.columns
        assert "_year" in out.columns

    def test_date_values(self):
        df = _make_df()
        out = ensure_issue_date_columns(df)
        assert out.iloc[0]["_date"] == "2026-03-20"
        assert out.iloc[0]["_month"] == "2026-03"
        assert out.iloc[0]["_year"] == "2026"


class TestFilterByTimeAndLeague:
    def test_filter_by_day(self):
        df = _make_df()
        df = ensure_issue_date_columns(df)
        out = filter_by_time_and_league(df, "按日", "2026-03-20", "全部联赛")
        assert len(out) == 1
        assert out.iloc[0]["league"] == "英超"

    def test_filter_by_month(self):
        df = _make_df()
        df = ensure_issue_date_columns(df)
        out = filter_by_time_and_league(df, "按月", "2026-03", "全部联赛")
        assert len(out) == 2

    def test_filter_by_year(self):
        df = _make_df()
        df = ensure_issue_date_columns(df)
        out = filter_by_time_and_league(df, "按年", "2026", "全部联赛")
        assert len(out) == 2

    def test_filter_by_league(self):
        df = _make_df()
        df = ensure_issue_date_columns(df)
        out = filter_by_time_and_league(df, "按月", "2026-03", "英超")
        assert len(out) == 1

    def test_no_match_returns_empty(self):
        df = _make_df()
        df = ensure_issue_date_columns(df)
        out = filter_by_time_and_league(df, "按日", "2025-01-01", "全部联赛")
        assert len(out) == 0


class TestParseMatchNoSortKey:
    def test_numeric_match_no(self):
        prefix, num, text = parse_match_no_sort_key("001")
        assert num == 1

    def test_prefix_and_number(self):
        prefix, num, text = parse_match_no_sort_key("A12")
        assert prefix == "A"
        assert num == 12

    def test_no_number(self):
        prefix, num, text = parse_match_no_sort_key("ABC")
        assert num == 10 ** 9


class TestSortByMatchNo:
    def test_sorts_numerically(self):
        df = pd.DataFrame({"match_no": ["010", "002", "005"]})
        out = sort_by_match_no(df)
        assert list(out["match_no"]) == ["002", "005", "010"]

    def test_empty_df_returned_unchanged(self):
        df = pd.DataFrame(columns=["match_no"])
        out = sort_by_match_no(df)
        assert out.empty

    def test_no_match_no_column_returned_unchanged(self):
        df = pd.DataFrame({"league": ["英超", "西甲"]})
        out = sort_by_match_no(df)
        assert "league" in out.columns
