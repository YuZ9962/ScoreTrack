from __future__ import annotations

"""
Column schema definitions for the src layer.

These lists define the canonical column order for CSV files written by the
src pipeline.  Import from here rather than hardcoding column lists inline.
"""

PROCESSED_MATCH_COLUMNS: list[str] = [
    "issue_date",
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
]
