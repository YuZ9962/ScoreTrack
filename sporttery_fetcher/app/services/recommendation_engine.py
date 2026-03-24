from __future__ import annotations

from dataclasses import dataclass, asdict

import pandas as pd


STRUCTURE_PICKS = ["胜胜", "平胜", "平平"]


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
    if score >= 75:
        return "low"
    if score >= 55:
        return "medium"
    return "high"


def _build_match_id(row: pd.Series) -> str:
    raw_id = str(row.get("raw_id", "") or "").strip()
    if raw_id:
        return raw_id
    return f"{row.get('issue_date', '')}_{row.get('match_no', '')}_{row.get('home_team', '')}_{row.get('away_team', '')}"


def _merge_predictions(matches_df: pd.DataFrame, gemini_df: pd.DataFrame, chatgpt_df: pd.DataFrame) -> pd.DataFrame:
    out = matches_df.copy()

    def _prep(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame(columns=["raw_id", "match_no", "home_team", "away_team", *cols])
        keep = [c for c in ["raw_id", "match_no", "home_team", "away_team", *cols] if c in df.columns]
        base = df[keep].copy()
        return base.drop_duplicates(subset=["raw_id", "match_no", "home_team", "away_team"], keep="last")

    g = _prep(gemini_df, ["gemini_match_main_pick", "gemini_match_secondary_pick"])
    c = _prep(
        chatgpt_df,
        [
            "chatgpt_match_main_pick",
            "chatgpt_match_secondary_pick",
            "chatgpt_home_win_prob",
            "chatgpt_draw_prob",
            "chatgpt_away_win_prob",
        ],
    )

    if not g.empty:
        out = out.merge(g, on=["raw_id", "match_no", "home_team", "away_team"], how="left")
    if not c.empty:
        out = out.merge(c, on=["raw_id", "match_no", "home_team", "away_team"], how="left")
    return out


def _map_direction_to_structure(pick: str) -> set[str]:
    p = str(pick or "").strip()
    if p == "主胜":
        return {"胜胜", "平胜"}
    if p == "平":
        return {"平平", "平胜"}
    return set()


def _structure_edge_recommendation(row: pd.Series, strategy_id: str) -> StrategyRecommendation:
    home_team = str(row.get("home_team", "")).strip()
    away_team = str(row.get("away_team", "")).strip()
    league = str(row.get("league", "")).strip()

    handicap = _parse_handicap(row.get("handicap"))
    spf_win = _safe_float(row.get("spf_win"))
    spf_draw = _safe_float(row.get("spf_draw"))
    spf_lose = _safe_float(row.get("spf_lose"))

    fit = 56
    confidence = 58
    warning_tags: list[str] = []
    rationale_points: list[str] = []

    recommendation_label = "结构待观察"
    primary = "平胜"
    secondary: str | None = "平平"

    # Rule 1: 主胜低赔率 + 主让球
    if spf_win is not None and spf_win < 1.85 and handicap < 0:
        recommendation_label = "结构优势明确"
        primary, secondary = "胜胜", "平胜"
        fit += 24
        confidence += 16
        rationale_points.append("主胜赔率<1.85 且主队让球，优势兑现路径更集中")

    # Rule 2: 主胜赔率偏低但平局风险明显
    if (
        spf_win is not None
        and spf_draw is not None
        and spf_win < 1.95
        and spf_draw <= 3.10
    ):
        recommendation_label = "半场拉扯下半场兑现"
        primary, secondary = "平胜", "平平"
        fit += 6
        confidence -= 3
        warning_tags.append("平局风险")
        rationale_points.append("主胜赔率较低但平局赔率同样偏低，需防半场僵持")

    # Rule 3: 深盘分歧
    if handicap <= -1 and spf_win is not None and spf_win > 2.05:
        warning_tags.extend(["盘口分歧", "强队热度风险"])
        fit -= 12
        confidence -= 12
        rationale_points.append("盘口较深但主胜赔率未同步压低，盘赔分歧明显")

    # 回避场景 A：双防型对决（低进球结构）
    dual_defense_risk = False
    if (
        spf_draw is not None
        and spf_draw <= 2.9
        and spf_win is not None
        and spf_lose is not None
        and abs(spf_win - spf_lose) <= 0.35
    ):
        dual_defense_risk = True
        warning_tags.append("双防型低进球风险")
        fit -= 22
        confidence -= 14

    # 回避场景 B：强队客场密集赛程风险（近似：客胜低赔+主受让）
    if handicap > 0.5 and spf_lose is not None and spf_lose < 2.0:
        warning_tags.append("强队客场体能轮换风险")
        fit -= 12
        confidence -= 10

    # 回避场景 C：杯赛/尺度波动（近似：杯赛关键词）
    if "杯" in league:
        warning_tags.append("杯赛尺度波动风险")
        fit -= 8
        confidence -= 6

    # Rule 4/5: Gemini + ChatGPT 一致性
    gemini_pick = str(row.get("gemini_match_main_pick", "") or "").strip()
    chatgpt_pick = str(row.get("chatgpt_match_main_pick", "") or "").strip()
    if gemini_pick and chatgpt_pick:
        g_struct = _map_direction_to_structure(gemini_pick)
        c_struct = _map_direction_to_structure(chatgpt_pick)
        if g_struct and c_struct and g_struct.intersection(c_struct):
            confidence += 10
            rationale_points.append("Gemini 与 ChatGPT 方向存在交集，提升置信度")
        elif gemini_pick != chatgpt_pick:
            confidence -= 9
            warning_tags.append("模型分歧")
            rationale_points.append("Gemini 与 ChatGPT 方向分歧，需控制仓位")

    # 裁剪区间
    fit = max(20, min(95, fit))
    confidence = max(20, min(95, confidence))
    risk = _risk_level(confidence)

    should_skip = False
    recommendation_type = "单选"

    if dual_defense_risk:
        should_skip = True
        recommendation_type = "跳过"
        primary, secondary = "平平", None
        recommendation_label = "不适合介入"
    elif fit < 45 or (risk == "high" and len(warning_tags) >= 2):
        should_skip = True
        recommendation_type = "跳过"
        primary, secondary = "平平", None
        recommendation_label = "结构噪音偏高"
    elif risk == "high":
        recommendation_type = "防冷"
        if secondary is None:
            secondary = "平平"
    elif secondary:
        recommendation_type = "双选"

    if len(rationale_points) < 2:
        rationale_points.append("建议临场结合阵容、赛前信息二次确认")

    if primary not in STRUCTURE_PICKS:
        primary = "平胜"
    if secondary and secondary not in STRUCTURE_PICKS:
        secondary = None

    rationale_summary = (
        f"{home_team} vs {away_team}：{recommendation_label}，"
        f"主推 {primary}{'，次选 ' + secondary if secondary else ''}。"
    )

    detailed = {
        "basic_view": f"让球 {handicap:+g}，SPF 主/平/客={spf_win}/{spf_draw}/{spf_lose}",
        "structure_view": f"聚焦路径：{primary}{' / ' + secondary if secondary else ''}",
        "market_view": "盘口与赔率已做分歧检测，偏离越大风险越高",
        "risk_notes": "；".join(dict.fromkeys(warning_tags)) if warning_tags else "暂无显著风险标签",
        "final_verdict": f"{recommendation_type} | {recommendation_label}",
    }

    return StrategyRecommendation(
        strategy_id=strategy_id,
        match_id=_build_match_id(row),
        fit_score=fit,
        confidence_score=confidence,
        risk_level=risk,
        recommendation_type=recommendation_type,
        recommendation_label=recommendation_label,
        primary_pick=primary,
        secondary_pick=secondary,
        rationale_summary=rationale_summary,
        rationale_points=rationale_points[:4],
        warning_tags=list(dict.fromkeys(warning_tags)),
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
                recommendation_type="跳过",
                recommendation_label="策略开发中",
                primary_pick="平平",
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
