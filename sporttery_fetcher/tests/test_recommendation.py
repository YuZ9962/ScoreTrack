"""Tests for the recommendation engine strategies."""
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

from services.recommendation_engine import (
    generate_strategy_recommendations,
    _structure_edge_recommendation,
    _market_trap_recommendation,
    _counter_attack_recommendation,
    _hot_cold_divergence_recommendation,
    STRUCTURE_PICKS,
)


def _make_match_row(**kwargs) -> pd.Series:
    defaults = {
        "raw_id": "m001",
        "match_no": "001",
        "issue_date": "2026-03-20",
        "league": "英超",
        "home_team": "主队",
        "away_team": "客队",
        "kickoff_time": "2026-03-20 20:00",
        "handicap": "-1",
        "spf_win": 1.80,
        "spf_draw": 3.40,
        "spf_lose": 4.20,
        "rqspf_win": 1.90,
        "rqspf_draw": 3.50,
        "rqspf_lose": 3.80,
        "gemini_match_main_pick": None,
        "chatgpt_match_main_pick": None,
    }
    defaults.update(kwargs)
    return pd.Series(defaults)


def _make_matches_df(**kwargs) -> pd.DataFrame:
    return pd.DataFrame([_make_match_row(**kwargs).to_dict()])


# ---------------------------------------------------------------------------
# Common invariants
# ---------------------------------------------------------------------------

STRATEGIES = [
    "structure_edge_v1",
    "market_trap_v1",
    "counter_attack_v1",
    "hot_cold_divergence_v1",
]


class TestStrategyOutputSchema:
    @pytest.mark.parametrize("strategy_id", STRATEGIES)
    def test_returns_dataframe(self, strategy_id):
        df = generate_strategy_recommendations(
            strategy_id=strategy_id,
            matches_df=_make_matches_df(),
            gemini_df=pd.DataFrame(),
            chatgpt_df=pd.DataFrame(),
        )
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 1

    @pytest.mark.parametrize("strategy_id", STRATEGIES)
    def test_required_columns_present(self, strategy_id):
        df = generate_strategy_recommendations(
            strategy_id=strategy_id,
            matches_df=_make_matches_df(),
            gemini_df=pd.DataFrame(),
            chatgpt_df=pd.DataFrame(),
        )
        for col in ["fit_score", "confidence_score", "risk_level", "primary_pick", "should_skip"]:
            assert col in df.columns

    @pytest.mark.parametrize("strategy_id", STRATEGIES)
    def test_primary_pick_in_valid_set(self, strategy_id):
        df = generate_strategy_recommendations(
            strategy_id=strategy_id,
            matches_df=_make_matches_df(),
            gemini_df=pd.DataFrame(),
            chatgpt_df=pd.DataFrame(),
        )
        assert df.iloc[0]["primary_pick"] in STRUCTURE_PICKS

    @pytest.mark.parametrize("strategy_id", STRATEGIES)
    def test_scores_in_range(self, strategy_id):
        df = generate_strategy_recommendations(
            strategy_id=strategy_id,
            matches_df=_make_matches_df(),
            gemini_df=pd.DataFrame(),
            chatgpt_df=pd.DataFrame(),
        )
        row = df.iloc[0]
        assert 0 <= row["fit_score"] <= 100
        assert 0 <= row["confidence_score"] <= 100

    @pytest.mark.parametrize("strategy_id", STRATEGIES)
    def test_empty_matches_returns_empty_df(self, strategy_id):
        df = generate_strategy_recommendations(
            strategy_id=strategy_id,
            matches_df=pd.DataFrame(),
            gemini_df=pd.DataFrame(),
            chatgpt_df=pd.DataFrame(),
        )
        assert df.empty

    def test_unknown_strategy_returns_skip(self):
        df = generate_strategy_recommendations(
            strategy_id="nonexistent_strategy_v99",
            matches_df=_make_matches_df(),
            gemini_df=pd.DataFrame(),
            chatgpt_df=pd.DataFrame(),
        )
        assert bool(df.iloc[0]["should_skip"]) is True


# ---------------------------------------------------------------------------
# structure_edge_v1 specific
# ---------------------------------------------------------------------------

class TestStructureEdgeV1:
    def test_strong_home_favorite_high_fit(self):
        row = _make_match_row(spf_win=1.70, handicap="-1")
        rec = _structure_edge_recommendation(row, "structure_edge_v1")
        assert rec.fit_score > 60
        assert rec.primary_pick in STRUCTURE_PICKS

    def test_dual_defense_triggers_skip(self):
        row = _make_match_row(spf_win=2.50, spf_draw=2.80, spf_lose=2.55, handicap="0")
        rec = _structure_edge_recommendation(row, "structure_edge_v1")
        assert rec.should_skip is True
        assert "双防型低进球风险" in rec.warning_tags

    def test_cup_league_penalised(self):
        row_normal = _make_match_row(league="英超")
        row_cup = _make_match_row(league="足总杯")
        rec_normal = _structure_edge_recommendation(row_normal, "structure_edge_v1")
        rec_cup = _structure_edge_recommendation(row_cup, "structure_edge_v1")
        assert rec_cup.fit_score <= rec_normal.fit_score

    def test_model_agreement_boosts_confidence(self):
        row_agree = _make_match_row(
            gemini_match_main_pick="主胜",
            chatgpt_match_main_pick="主胜",
        )
        row_disagree = _make_match_row(
            gemini_match_main_pick="主胜",
            chatgpt_match_main_pick="客胜",
        )
        rec_agree = _structure_edge_recommendation(row_agree, "structure_edge_v1")
        rec_disagree = _structure_edge_recommendation(row_disagree, "structure_edge_v1")
        assert rec_agree.confidence_score > rec_disagree.confidence_score

    def test_deep_handicap_mismatch_penalised(self):
        row = _make_match_row(handicap="-1.5", spf_win=2.20)
        rec = _structure_edge_recommendation(row, "structure_edge_v1")
        assert "盘口分歧" in rec.warning_tags


# ---------------------------------------------------------------------------
# market_trap_v1 specific
# ---------------------------------------------------------------------------

class TestMarketTrapV1:
    def test_shallow_handicap_with_low_odds_triggers_trap(self):
        row = _make_match_row(spf_win=1.65, handicap="0")
        rec = _market_trap_recommendation(row, "market_trap_v1")
        assert "大众热门过度" in rec.warning_tags
        assert rec.fit_score > 55

    def test_normal_match_no_trap(self):
        row = _make_match_row(spf_win=2.10, handicap="-1")
        rec = _market_trap_recommendation(row, "market_trap_v1")
        assert rec.fit_score < 60

    def test_rqspf_divergence_increases_fit(self):
        row_diverge = _make_match_row(spf_win=1.70, rqspf_win=2.05)
        row_normal = _make_match_row(spf_win=1.70, rqspf_win=1.72)
        rec_diverge = _market_trap_recommendation(row_diverge, "market_trap_v1")
        rec_normal = _market_trap_recommendation(row_normal, "market_trap_v1")
        assert rec_diverge.fit_score >= rec_normal.fit_score

    def test_away_trap_detected(self):
        row = _make_match_row(spf_lose=1.75, handicap="0.5")
        rec = _market_trap_recommendation(row, "market_trap_v1")
        assert "客队大众热门" in rec.warning_tags


# ---------------------------------------------------------------------------
# counter_attack_v1 specific
# ---------------------------------------------------------------------------

class TestCounterAttackV1:
    def test_competitive_away_team_shallow_handicap(self):
        row = _make_match_row(spf_lose=2.50, handicap="0")
        rec = _counter_attack_recommendation(row, "counter_attack_v1")
        assert rec.fit_score > 55
        assert rec.primary_pick in STRUCTURE_PICKS

    def test_dominant_home_team_penalised(self):
        row = _make_match_row(spf_win=1.55, handicap="-1.5")
        rec = _counter_attack_recommendation(row, "counter_attack_v1")
        assert "主队压制力过强" in rec.warning_tags
        assert rec.fit_score < 55

    def test_equal_odds_both_sides(self):
        row = _make_match_row(spf_win=2.20, spf_lose=2.30, handicap="0")
        rec = _counter_attack_recommendation(row, "counter_attack_v1")
        assert rec.fit_score > 50

    def test_cup_league_penalised(self):
        row_normal = _make_match_row(spf_lose=2.50, handicap="0", league="英超")
        row_cup = _make_match_row(spf_lose=2.50, handicap="0", league="足总杯")
        rec_normal = _counter_attack_recommendation(row_normal, "counter_attack_v1")
        rec_cup = _counter_attack_recommendation(row_cup, "counter_attack_v1")
        assert rec_cup.fit_score <= rec_normal.fit_score


# ---------------------------------------------------------------------------
# hot_cold_divergence_v1 specific
# ---------------------------------------------------------------------------

class TestHotColdDivergenceV1:
    def test_hot_odds_cold_handicap_divergence(self):
        row = _make_match_row(spf_win=1.70, handicap="0")
        rec = _hot_cold_divergence_recommendation(row, "hot_cold_divergence_v1")
        assert "主胜热度背离" in rec.warning_tags
        assert rec.fit_score > 55

    def test_no_divergence_low_fit(self):
        row = _make_match_row(spf_win=2.20, handicap="-1")
        rec = _hot_cold_divergence_recommendation(row, "hot_cold_divergence_v1")
        assert rec.fit_score < 60

    def test_rqspf_gap_increases_fit(self):
        row_gap = _make_match_row(spf_win=1.75, rqspf_win=2.00, handicap="0")
        row_no_gap = _make_match_row(spf_win=1.75, rqspf_win=1.77, handicap="0")
        rec_gap = _hot_cold_divergence_recommendation(row_gap, "hot_cold_divergence_v1")
        rec_no_gap = _hot_cold_divergence_recommendation(row_no_gap, "hot_cold_divergence_v1")
        assert rec_gap.fit_score >= rec_no_gap.fit_score

    def test_low_draw_odds_boosts_confidence(self):
        row_low_draw = _make_match_row(spf_win=1.75, spf_draw=3.10, handicap="0")
        row_high_draw = _make_match_row(spf_win=1.75, spf_draw=3.60, handicap="0")
        rec_low = _hot_cold_divergence_recommendation(row_low_draw, "hot_cold_divergence_v1")
        rec_high = _hot_cold_divergence_recommendation(row_high_draw, "hot_cold_divergence_v1")
        assert rec_low.confidence_score >= rec_high.confidence_score

    def test_away_hot_divergence_detected(self):
        row = _make_match_row(spf_lose=1.85, handicap="0.5")
        rec = _hot_cold_divergence_recommendation(row, "hot_cold_divergence_v1")
        assert "客胜热度背离" in rec.warning_tags
