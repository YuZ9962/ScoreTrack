from __future__ import annotations

from dataclasses import dataclass, asdict

import pandas as pd


@dataclass
class StrategyRecommendation:
    strategy_id: str
    match_id: str
    fit_score: int
    confidence_score: int
    risk_level: str
    recommendation_type: str
    recommendation_label: str
    primary_pick: str
    secondary_pick: str | None
    rationale_summary: str
    rationale_points: list[str]
    warning_tags: list[str]
    should_skip: bool
    detailed_analysis: dict[str, str]


def _safe_float(v: object) -> float | None:
    if v is None:
        return None
    try:
        return float(str(v).strip())
    except Exception:
        return None


def _parse_handicap(v: object) -> float:
    s = str(v or "").strip().replace("球", "")
    if not s:
        return 0.0
    s = s.replace("+", "")
    try:
        return float(s)
    except Exception:
        return 0.0


def _risk_level(score: int) -> str:
    if score >= 70:
        return "low"
    if score >= 50:
        return "medium"
    return "high"


def _pick_with_fallback(values: list[tuple[str, float]]) -> tuple[str, str | None]:
    ranked = sorted(values, key=lambda x: x[1])
    primary = ranked[0][0]
    secondary = ranked[1][0] if len(ranked) > 1 and abs(ranked[1][1] - ranked[0][1]) <= 0.22 else None
    return primary, secondary


def _build_match_id(row: pd.Series) -> str:
    raw_id = str(row.get("raw_id", "") or "").strip()
    if raw_id:
        return raw_id
    return f"{row.get('issue_date', '')}_{row.get('match_no', '')}_{row.get('home_team', '')}_{row.get('away_team', '')}"


def _merge_predictions(matches_df: pd.DataFrame, gemini_df: pd.DataFrame, chatgpt_df: pd.DataFrame) -> pd.DataFrame:
    out = matches_df.copy()

    def _prep(df: pd.DataFrame, cols: list[str], prefix: str) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame(columns=["raw_id", "match_no", "home_team", "away_team", *cols])
        keep = [c for c in ["raw_id", "match_no", "home_team", "away_team", *cols] if c in df.columns]
        renamed = {c: f"{prefix}{c}" for c in keep if c not in ["raw_id", "match_no", "home_team", "away_team"]}
        base = df[keep].copy().rename(columns=renamed)
        return base.drop_duplicates(subset=["raw_id", "match_no", "home_team", "away_team"], keep="last")

    g = _prep(
        gemini_df,
        ["gemini_match_main_pick", "gemini_match_secondary_pick", "gemini_handicap_main_pick"],
        "",
    )
    c = _prep(
        chatgpt_df,
        [
            "chatgpt_match_main_pick",
            "chatgpt_match_secondary_pick",
            "chatgpt_home_win_prob",
            "chatgpt_draw_prob",
            "chatgpt_away_win_prob",
        ],
        "",
    )

    if not g.empty:
        out = out.merge(g, on=["raw_id", "match_no", "home_team", "away_team"], how="left")
    if not c.empty:
        out = out.merge(c, on=["raw_id", "match_no", "home_team", "away_team"], how="left")
    return out


def _structure_edge_recommendation(row: pd.Series, strategy_id: str) -> StrategyRecommendation:
    home_team = str(row.get("home_team", "")).strip()
    away_team = str(row.get("away_team", "")).strip()
    handicap = _parse_handicap(row.get("handicap"))

    spf_win = _safe_float(row.get("spf_win"))
    spf_draw = _safe_float(row.get("spf_draw"))
    spf_lose = _safe_float(row.get("spf_lose"))

    values = [
        ("主胜", spf_win if spf_win is not None else 9.99),
        ("平", spf_draw if spf_draw is not None else 9.99),
        ("客胜", spf_lose if spf_lose is not None else 9.99),
    ]
    primary, secondary = _pick_with_fallback(values)

    fit = 58
    confidence = 55
    warning_tags: list[str] = []
    rationale_points: list[str] = []

    # 结构判断
    if spf_win is not None and handicap < 0 and spf_win <= 1.95:
        recommendation_label = "强势主导结构（偏胜胜/平胜）"
        primary = "主胜"
        secondary = "平"
        fit += 24
        confidence += 18
        rationale_points.append("主胜赔率较低且主队让球，结构上偏主导路径")
    elif spf_draw is not None and spf_win is not None and spf_lose is not None and abs(spf_win - spf_lose) <= 0.3:
        recommendation_label = "拉扯均衡结构（偏平平/平胜）"
        primary = "平"
        secondary = "主胜"
        fit += 15
        confidence += 10
        rationale_points.append("胜负赔率接近，比赛更可能进入拉扯结构")
    else:
        recommendation_label = "常规结构"
        rationale_points.append("赔率结构无明显单边倾斜，走常规推荐路径")

    # 盘口分歧风险
    if handicap <= -1 and spf_win is not None and spf_win > 2.1:
        warning_tags.append("深盘分歧")
        confidence -= 12
        fit -= 8
        rationale_points.append("主队让球较深但主胜赔率不够压低，盘赔存在分歧")

    # 模型一致性
    gemini_pick = str(row.get("gemini_match_main_pick", "") or "").strip()
    chatgpt_pick = str(row.get("chatgpt_match_main_pick", "") or "").strip()
    if gemini_pick and chatgpt_pick:
        if gemini_pick == chatgpt_pick:
            confidence += 10
            rationale_points.append("Gemini 与 ChatGPT 主方向一致，提升置信度")
        else:
            confidence -= 8
            warning_tags.append("模型分歧")
            rationale_points.append("Gemini 与 ChatGPT 主方向分歧，需防冷")

    # 不适配过滤
    if handicap == 0 and spf_draw is not None and spf_draw <= min(v for _, v in values):
        warning_tags.append("低比分闷战风险")
    if "模型分歧" in warning_tags and "深盘分歧" in warning_tags:
        warning_tags.append("建议保守处理")

    confidence = max(20, min(95, confidence))
    fit = max(20, min(95, fit))
    risk_level = _risk_level(confidence)
    should_skip = risk_level == "high" and fit < 55

    if should_skip:
        recommendation_type = "跳过"
    elif secondary:
        recommendation_type = "双选"
    else:
        recommendation_type = "单选"

    if len(rationale_points) < 2:
        rationale_points.append("建议结合临场阵容与赛前资讯做二次确认")

    rationale_summary = f"{home_team} vs {away_team}：{recommendation_label}，主推 {primary}" + (
        f"，次选 {secondary}" if secondary else ""
    )

    detailed = {
        "basic_view": f"主队 {home_team}，客队 {away_team}，让球 {handicap:+g}",
        "structure_view": recommendation_label,
        "market_view": f"SPF 主/平/客: {spf_win}/{spf_draw}/{spf_lose}",
        "risk_notes": "；".join(warning_tags) if warning_tags else "暂无显著风险",
        "final_verdict": f"{recommendation_type} - {primary}" + (f" + {secondary}" if secondary else ""),
    }

    return StrategyRecommendation(
        strategy_id=strategy_id,
        match_id=_build_match_id(row),
        fit_score=fit,
        confidence_score=confidence,
        risk_level=risk_level,
        recommendation_type=recommendation_type,
        recommendation_label=recommendation_label,
        primary_pick=primary,
        secondary_pick=secondary,
        rationale_summary=rationale_summary,
        rationale_points=rationale_points[:4],
        warning_tags=warning_tags,
        should_skip=should_skip,
        detailed_analysis=detailed,
    )


def generate_strategy_recommendations(
    *,
    strategy_id: str,
    matches_df: pd.DataFrame,
    gemini_df: pd.DataFrame,
    chatgpt_df: pd.DataFrame,
) -> pd.DataFrame:
    if matches_df.empty:
        return pd.DataFrame()

    enriched = _merge_predictions(matches_df, gemini_df, chatgpt_df)

    recommendations: list[dict] = []
    for _, row in enriched.iterrows():
        if strategy_id == "structure_edge_v1":
            rec = _structure_edge_recommendation(row, strategy_id)
        else:
            rec = StrategyRecommendation(
                strategy_id=strategy_id,
                match_id=_build_match_id(row),
                fit_score=0,
                confidence_score=0,
                risk_level="high",
                recommendation_type="Coming Soon",
                recommendation_label="策略开发中",
                primary_pick="-",
                secondary_pick=None,
                rationale_summary="该策略尚未开放。",
                rationale_points=["Coming Soon"],
                warning_tags=["strategy_not_active"],
                should_skip=True,
                detailed_analysis={
                    "basic_view": "-",
                    "structure_view": "-",
                    "market_view": "-",
                    "risk_notes": "-",
                    "final_verdict": "Coming Soon",
                },
            )
        rec_dict = asdict(rec)
        rec_dict["match_no"] = row.get("match_no")
        rec_dict["league"] = row.get("league")
        rec_dict["home_team"] = row.get("home_team")
        rec_dict["away_team"] = row.get("away_team")
        rec_dict["kickoff_time"] = row.get("kickoff_time")
        recommendations.append(rec_dict)

    return pd.DataFrame(recommendations)
