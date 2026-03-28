"""Tests for src/services/result_cleaner.py core logic."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in [str(ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from src.services.result_cleaner import (
    _normalize_score,
    _parse_score,
    _parse_handicap_int,
    _derive_match,
    _derive_handicap_result,
    _is_invalid_date_like_score,
    _normalize_row,
    rebuild_clean_results,
    append_raw_results,
    load_clean_results,
)


class TestNormalizeScore:
    def test_standard_format(self):
        assert _normalize_score("2-1") == "2-1"

    def test_colon_separator(self):
        assert _normalize_score("3:0") == "3-0"

    def test_spaces_around_separator(self):
        assert _normalize_score("1 - 1") == "1-1"

    def test_leading_zeros_stripped(self):
        assert _normalize_score("02-01") == "2-1"

    def test_empty_returns_empty(self):
        assert _normalize_score("") == ""
        assert _normalize_score(None) == ""

    def test_invalid_returns_empty(self):
        assert _normalize_score("invalid") == ""


class TestParseScore:
    def test_valid_score(self):
        assert _parse_score("2-1") == (2, 1)

    def test_zero_zero(self):
        assert _parse_score("0-0") == (0, 0)

    def test_invalid_returns_none(self):
        assert _parse_score("abc") is None
        assert _parse_score(None) is None


class TestParseHandicapInt:
    def test_negative_handicap(self):
        assert _parse_handicap_int("-1") == -1

    def test_positive_handicap(self):
        assert _parse_handicap_int("+2") == 2

    def test_zero(self):
        assert _parse_handicap_int("0") == 0

    def test_text_with_numbers(self):
        assert _parse_handicap_int("让1球") == 1

    def test_none_returns_none(self):
        assert _parse_handicap_int(None) is None

    def test_empty_returns_none(self):
        assert _parse_handicap_int("") is None


class TestDeriveMatch:
    def test_home_win(self):
        assert _derive_match("2-0") == "主胜"

    def test_draw(self):
        assert _derive_match("1-1") == "平"

    def test_away_win(self):
        assert _derive_match("0-2") == "客胜"

    def test_none_score_returns_unopened(self):
        assert _derive_match(None) == "未开奖"

    def test_invalid_score_returns_unopened(self):
        assert _derive_match("abc") == "未开奖"


class TestDeriveHandicapResult:
    def test_home_gives_one_ball_and_wins_by_two(self):
        # home=2, away=0, handicap=-1 → adj=2+(-1)=1 > 0 → 让胜
        assert _derive_handicap_result("2-0", "-1") == "让胜"

    def test_draw_after_handicap(self):
        # home=1, away=0, handicap=-1 → adj=1-1=0 == 0 → 让平
        assert _derive_handicap_result("1-0", "-1") == "让平"

    def test_home_loses_after_handicap(self):
        # home=0, away=1, handicap=-1 → adj=0-1=-1 < 1 → 让负
        assert _derive_handicap_result("0-1", "-1") == "让负"

    def test_missing_score_returns_unopened(self):
        assert _derive_handicap_result(None, "-1") == "未开奖"

    def test_missing_handicap_returns_unopened(self):
        assert _derive_handicap_result("2-0", None) == "未开奖"


class TestIsInvalidDateLikeScore:
    def test_valid_score_is_not_date_like(self):
        assert _is_invalid_date_like_score("2-1") is False

    def test_date_like_score_detected(self):
        # 2026-03 → 26-3 looks like a score but 26 >= 20 and 3 is 1-12
        assert _is_invalid_date_like_score("26-3") is True

    def test_another_date_like(self):
        assert _is_invalid_date_like_score("3-26") is True

    def test_large_legitimate_score_not_flagged(self):
        # 5-0 is fine
        assert _is_invalid_date_like_score("5-0") is False


class TestNormalizeRow:
    def test_valid_full_row(self):
        # score 2-0 with handicap -1: adj = 2 + (-1) = 1 > 0 → 让胜
        row = {
            "issue_date": "2026-03-19",
            "match_no": "001",
            "home_team": "主队",
            "away_team": "客队",
            "full_time_score": "2-0",
            "handicap": "-1",
            "data_source": "auto_result_fetch",
        }
        clean, bad, is_unopened = _normalize_row(row, "auto_result_fetch")
        assert clean is not None
        assert bad is None
        assert clean["result_match"] == "主胜"
        assert clean["result_handicap"] == "让胜"

    def test_missing_issue_date_goes_to_bad(self):
        row = {
            "issue_date": "",
            "match_no": "001",
            "home_team": "主队",
            "away_team": "客队",
            "full_time_score": "2-1",
        }
        clean, bad, is_unopened = _normalize_row(row, "auto_result_fetch")
        assert clean is None
        assert bad is not None
        assert "issue_date" in bad["bad_reason"]

    def test_missing_teams_goes_to_bad(self):
        row = {
            "issue_date": "2026-03-19",
            "match_no": "001",
            "home_team": "",
            "away_team": "",
            "full_time_score": "2-1",
        }
        clean, bad, _ = _normalize_row(row, "auto_result_fetch")
        assert clean is None
        assert bad is not None

    def test_unopened_record(self):
        row = {
            "issue_date": "2026-03-19",
            "match_no": "001",
            "home_team": "主队",
            "away_team": "客队",
            "full_time_score": "",
            "result_match": "未开奖",
            "result_handicap": "未开奖",
        }
        clean, bad, is_unopened = _normalize_row(row, "auto_result_fetch")
        assert is_unopened is True
        assert clean is not None
        assert clean["result_match"] == "未开奖"

    def test_score_normalization(self):
        row = {
            "issue_date": "2026-03-19",
            "match_no": "002",
            "home_team": "A队",
            "away_team": "B队",
            "full_time_score": "3:1",
            "handicap": "0",
        }
        clean, bad, _ = _normalize_row(row, "auto_result_fetch")
        assert clean is not None
        assert clean["full_time_score"] == "3-1"
        assert clean["result_match"] == "主胜"


class TestRebuildAndAppend:
    def test_rebuild_with_empty_base(self, tmp_path):
        stats = rebuild_clean_results(base_dir=tmp_path)
        assert stats["raw_rows"] == 0
        assert stats["clean_rows"] == 0
        assert stats["bad_rows"] == 0

    def test_append_and_rebuild(self, tmp_path):
        records = [
            {
                "issue_date": "2026-03-19",
                "match_no": "001",
                "home_team": "主队",
                "away_team": "客队",
                "full_time_score": "2-0",
                "handicap": "-1",
            }
        ]
        stats = append_raw_results(records, data_source="auto_result_fetch", base_dir=tmp_path)
        assert stats["appended_raw"] == 1
        assert stats["clean_rows"] == 1

    def test_append_invalid_record_goes_to_bad(self, tmp_path):
        records = [
            {
                "issue_date": "",
                "match_no": "001",
                "home_team": "主队",
                "away_team": "客队",
                "full_time_score": "2-0",
            }
        ]
        stats = append_raw_results(records, data_source="auto_result_fetch", base_dir=tmp_path)
        assert stats["bad_rows"] >= 1
        assert stats["clean_rows"] == 0

    def test_load_clean_results_empty(self, tmp_path):
        df = load_clean_results(base_dir=tmp_path)
        assert df.empty

    def test_load_clean_results_after_append(self, tmp_path):
        records = [
            {
                "issue_date": "2026-03-20",
                "match_no": "003",
                "home_team": "X队",
                "away_team": "Y队",
                "full_time_score": "1-1",
                "handicap": "0",
            }
        ]
        append_raw_results(records, data_source="manual_entry", base_dir=tmp_path)
        df = load_clean_results(base_dir=tmp_path)
        assert len(df) == 1
        assert df.iloc[0]["result_match"] == "平"
