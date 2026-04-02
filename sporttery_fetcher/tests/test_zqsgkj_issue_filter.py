from src.fetchers.zqsgkj_fetcher import _filter_rows_by_issue_window_and_match_no


def test_filter_by_issue_window_and_match_no_weekday_prefix():
    rows = [
        {"match_date": "2026-03-30", "match_no": "周一001"},
        {"match_date": "2026-03-31", "match_no": "周一002"},
        {"match_date": "2026-03-31", "match_no": "周二002"},
        {"match_date": "2026-04-01", "match_no": "周一003"},
    ]

    out, dropped = _filter_rows_by_issue_window_and_match_no("2026-03-30", rows)
    assert [r["match_no"] for r in out] == ["周一001", "周一002"]
    assert dropped == 2
