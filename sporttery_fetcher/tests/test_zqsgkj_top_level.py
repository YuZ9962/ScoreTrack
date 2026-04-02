import src.fetchers.zqsgkj_fetcher as mod


def test_fetch_zqsgkj_matches_returns_final_filtered_rows(monkeypatch):
    monkeypatch.setattr(mod, "_get_result_candidate_urls", lambda: ["http://fake"])

    raw_rows = [
        {"match_date": "2026-03-31", "match_no": "周一002"},
        {"match_date": "2026-03-31", "match_no": "周二001"},
    ]
    monkeypatch.setattr(mod, "_fetch_zqsgkj_from_url", lambda issue_date, url: raw_rows)

    rows = mod.fetch_zqsgkj_matches("2026-03-30")
    assert len(rows) == 1
    assert rows[0]["match_no"] == "周一002"
