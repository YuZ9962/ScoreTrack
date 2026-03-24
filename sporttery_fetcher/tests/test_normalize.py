from src.parsers.normalize import normalize_match


def test_normalize_match_missing_fields():
    row = normalize_match({"home_team": "A", "away_team": "B"}, "2026-03-19", "https://example.com")
    assert row["issue_date"] == "2026-03-19"
    assert row["home_team"] == "A"
    assert row["away_team"] == "B"
    assert row["play_spf"] is None
