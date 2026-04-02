from src.domain.match_time import (
    derive_match_date,
    get_issue_date_window,
    infer_issue_date_from_kickoff,
    kickoff_belongs_to_issue_date,
    parse_kickoff_time,
)


def test_issue_date_window_left_closed_right_open():
    start, end = get_issue_date_window("2026-04-02")
    assert str(start) == "2026-04-02 11:00:00"
    assert str(end) == "2026-04-03 11:00:00"


def test_issue_date_inference_cross_day():
    assert infer_issue_date_from_kickoff("2026-04-03 00:30") == "2026-04-02"
    assert infer_issue_date_from_kickoff("2026-04-02 10:59") == "2026-04-01"
    assert infer_issue_date_from_kickoff("2026-04-03 11:00") == "2026-04-03"


def test_issue_date_belongs_examples():
    assert kickoff_belongs_to_issue_date("2026-04-03 00:30", "2026-04-02")
    assert not kickoff_belongs_to_issue_date("2026-04-02 10:59", "2026-04-02")
    assert not kickoff_belongs_to_issue_date("2026-04-03 11:00", "2026-04-02")


def test_parse_and_derive_match_date():
    assert parse_kickoff_time("2026-04-02 13:00") is not None
    assert derive_match_date("2026-04-03 09:45") == "2026-04-03"
