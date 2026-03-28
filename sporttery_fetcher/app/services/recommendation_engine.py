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


def _apply_model_agreement(
    row: pd.Series,
    fit: int,
    confidence: int,
    warning_tags: list[str],
    rationale_points: list[str],
) -> tuple[int, int]:
    """Adjust fit/confidence based on Gemini vs ChatGPT agreement. Returns updated (fit, confidence)."""
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
    return fit, confidence


def _finalise(
    fit: int,
    confidence: int,
    warning_tags: list[str],
    rationale_points: list[str],
    primary: str,
    secondary: str | None,
    dual_defense_risk: bool,
) -> tuple[int, int, str, str, str, str | None, bool]:
    """Clip scores, derive risk / recommendation_type / skip flag. Returns
    (fit, confidence, risk, rec_type, rec_label_override, primary, secondary, should_skip).
    """
    fit = max(20, min(95, fit))
    confidence = max(20, min(95, confidence))
    risk = _risk_level(confidence)

    should_skip = False
    recommendation_type = "单选"

    if dual_defense_risk:
        should_skip = True
        recommendation_type = "跳过"
        primary, secondary = "平平", None
        rec_label = "不适合介入"
    elif fit < 45 or (risk == "high" and len(warning_tags) >= 2):
        should_skip = True
        recommendation_type = "跳过"
        primary, secondary = "平平", None
        rec_label = "结构噪音偏高"
    elif risk == "high":
        recommendation_type = "防冷"
        rec_label = None
        if secondary is None:
            secondary = "平平"
    elif secondary:
        recommendation_type = "双选"
        rec_label = None
    else:
        rec_label = None

    if primary not in STRUCTURE_PICKS:
        primary = "平胜"
    if secondary and secondary not in STRUCTURE_PICKS:
        secondary = None

    if len(rationale_points) < 2:
        rationale_points.append("建议临场结合阵容、赛前信息二次确认")

    return fit, confidence, risk, recommendation_type, rec_label, primary, secondary, should_skip


# ---------------------------------------------------------------------------
# Strategy: structure_edge_v1
# ---------------------------------------------------------------------------

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

    # 回避场景 C：杯赛/尺度波动
    if "杯" in league:
        warning_tags.append("杯赛尺度波动风险")
        fit -= 8
        confidence -= 6

    fit, confidence = _apply_model_agreement(row, fit, confidence, warning_tags, rationale_points)

    fit, confidence, risk, rec_type, label_override, primary, secondary, should_skip = _finalise(
        fit, confidence, warning_tags, rationale_points, primary, secondary, dual_defense_risk
    )
    if label_override:
        recommendation_label = label_override

    rationale_summary = (
        f"{home_team} vs {away_team}：{recommendation_label}，"
        f"主推 {primary}{'，次选 ' + secondary if secondary else ''}。"
    )
    detailed = {
        "basic_view": f"让球 {handicap:+g}，SPF 主/平/客={spf_win}/{spf_draw}/{spf_lose}",
        "structure_view": f"聚焦路径：{primary}{' / ' + secondary if secondary else ''}",
        "market_view": "盘口与赔率已做分歧检测，偏离越大风险越高",
        "risk_notes": "；".join(dict.fromkeys(warning_tags)) if warning_tags else "暂无显著风险标签",
        "final_verdict": f"{rec_type} | {recommendation_label}",
    }

    return StrategyRecommendation(
        strategy_id=strategy_id,
        match_id=_build_match_id(row),
        fit_score=fit,
        confidence_score=confidence,
        risk_level=risk,
        recommendation_type=rec_type,
        recommendation_label=recommendation_label,
        primary_pick=primary,
        secondary_pick=secondary,
        rationale_summary=rationale_summary,
        rationale_points=rationale_points[:4],
        warning_tags=list(dict.fromkeys(warning_tags)),
        should_skip=should_skip,
        detailed_analysis=detailed,
    )


# ---------------------------------------------------------------------------
# Strategy: market_trap_v1
# ---------------------------------------------------------------------------

def _market_trap_recommendation(row: pd.Series, strategy_id: str) -> StrategyRecommendation:
    """识别赔率热度与结构之间的陷阱场景。

    当主胜赔率极低（大众热度过高）但让球盘口并未同步深盘时，说明庄家不
    完全认同大众方向，存在市场陷阱。此策略推荐回避热门方向，关注"平胜"或
    "平平"路径。
    """
    home_team = str(row.get("home_team", "")).strip()
    away_team = str(row.get("away_team", "")).strip()
    league = str(row.get("league", "")).strip()

    handicap = _parse_handicap(row.get("handicap"))
    spf_win = _safe_float(row.get("spf_win"))
    spf_draw = _safe_float(row.get("spf_draw"))
    spf_lose = _safe_float(row.get("spf_lose"))
    rqspf_win = _safe_float(row.get("rqspf_win"))

    fit = 50
    confidence = 52
    warning_tags: list[str] = []
    rationale_points: list[str] = []
    recommendation_label = "市场待观察"
    primary = "平胜"
    secondary: str | None = "平平"
    trap_detected = False

    # 核心陷阱信号 1: 主胜赔率极低 但 让球盘口并不深 (handicap >= -0.5)
    if spf_win is not None and spf_win < 1.75 and handicap >= -0.5:
        trap_detected = True
        recommendation_label = "大众热门陷阱"
        primary, secondary = "平胜", "平平"
        fit += 20
        confidence += 14
        warning_tags.append("大众热门过度")
        rationale_points.append(f"主胜赔率仅 {spf_win}，但让球 {handicap:+g} 偏浅，盘口未认同赔率热度")

    # 核心陷阱信号 2: 让胜赔率明显高于主胜赔率（赔率与盘口方向分裂）
    if spf_win is not None and rqspf_win is not None and rqspf_win - spf_win > 0.25:
        fit += 10
        confidence += 8
        warning_tags.append("赔口方向分裂")
        rationale_points.append(
            f"让胜赔率({rqspf_win}) 远高于主胜赔率({spf_win})，盘口市场不认同"
        )

    # 平局风险叠加（draw 赔率低说明平局有吸引力）
    if spf_draw is not None and spf_draw <= 3.2:
        confidence += 5
        rationale_points.append("平局赔率偏低，平局兑现概率较高")

    # 杯赛加成
    if "杯" in league:
        warning_tags.append("杯赛战意不稳")
        fit -= 6
        confidence -= 5

    # 若无明显陷阱信号则降低适配度
    if not trap_detected:
        fit -= 15
        confidence -= 10
        recommendation_label = "无明显陷阱信号"

    # 客胜赔率极低时陷阱方向反转（away 是真正热门）
    if spf_lose is not None and spf_lose < 1.80 and handicap > 0:
        warning_tags.append("客队大众热门")
        recommendation_label = "客队热门陷阱"
        primary, secondary = "平胜", "胜胜"
        fit += 8
        rationale_points.append(f"客胜赔率({spf_lose}) 极低但主场让球({handicap:+g})，结构不支持")

    dual_defense_risk = (
        spf_draw is not None and spf_draw <= 2.9
        and spf_win is not None and spf_lose is not None
        and abs(spf_win - spf_lose) <= 0.35
    )
    if dual_defense_risk:
        warning_tags.append("双防低进球风险")
        fit -= 15
        confidence -= 10

    fit, confidence = _apply_model_agreement(row, fit, confidence, warning_tags, rationale_points)

    fit, confidence, risk, rec_type, label_override, primary, secondary, should_skip = _finalise(
        fit, confidence, warning_tags, rationale_points, primary, secondary, dual_defense_risk
    )
    if label_override:
        recommendation_label = label_override

    rationale_summary = (
        f"{home_team} vs {away_team}：{recommendation_label}，"
        f"主推 {primary}{'，次选 ' + secondary if secondary else ''}。"
    )
    detailed = {
        "basic_view": f"让球 {handicap:+g}，SPF 主/平/客={spf_win}/{spf_draw}/{spf_lose}",
        "structure_view": f"陷阱判断：{recommendation_label}，路径：{primary}{' / ' + secondary if secondary else ''}",
        "market_view": "关注赔率热度与盘口之间的裂口，裂口越大陷阱越深",
        "risk_notes": "；".join(dict.fromkeys(warning_tags)) if warning_tags else "暂无明显陷阱信号",
        "final_verdict": f"{rec_type} | {recommendation_label}",
    }

    return StrategyRecommendation(
        strategy_id=strategy_id,
        match_id=_build_match_id(row),
        fit_score=fit,
        confidence_score=confidence,
        risk_level=risk,
        recommendation_type=rec_type,
        recommendation_label=recommendation_label,
        primary_pick=primary,
        secondary_pick=secondary,
        rationale_summary=rationale_summary,
        rationale_points=rationale_points[:4],
        warning_tags=list(dict.fromkeys(warning_tags)),
        should_skip=should_skip,
        detailed_analysis=detailed,
    )


# ---------------------------------------------------------------------------
# Strategy: counter_attack_v1
# ---------------------------------------------------------------------------

def _counter_attack_recommendation(row: pd.Series, strategy_id: str) -> StrategyRecommendation:
    """识别强队被反击克制的场景。

    当客队具备反击能力、主场控球队过于进攻的结构中，客队或平局是更合理的
    结构路径。信号：客胜赔率不高 + 主队让球较少或不让球 + 双方强弱接近。
    """
    home_team = str(row.get("home_team", "")).strip()
    away_team = str(row.get("away_team", "")).strip()
    league = str(row.get("league", "")).strip()

    handicap = _parse_handicap(row.get("handicap"))
    spf_win = _safe_float(row.get("spf_win"))
    spf_draw = _safe_float(row.get("spf_draw"))
    spf_lose = _safe_float(row.get("spf_lose"))
    rqspf_win = _safe_float(row.get("rqspf_win"))
    rqspf_draw = _safe_float(row.get("rqspf_draw"))

    fit = 48
    confidence = 50
    warning_tags: list[str] = []
    rationale_points: list[str] = []
    recommendation_label = "反击场景待确认"
    primary = "平胜"
    secondary: str | None = "平平"
    counter_signal = False

    # 信号 1: 客胜赔率合理 (< 2.8) 且主队不让球或受让（实力接近）
    if spf_lose is not None and spf_lose < 2.8 and handicap >= -0.5:
        counter_signal = True
        recommendation_label = "反击克制结构"
        primary, secondary = "平胜", "平平"
        fit += 18
        confidence += 14
        rationale_points.append(
            f"客胜赔率 {spf_lose}（合理），主队让球 {handicap:+g}（较浅），实力接近，反击空间存在"
        )

    # 信号 2: 让球赔率双边偏高（盘口认为难分胜负）
    if rqspf_win is not None and rqspf_draw is not None and rqspf_win > 1.95 and rqspf_draw > 3.3:
        counter_signal = True
        fit += 10
        confidence += 8
        rationale_points.append("让球赔率双边偏高，盘口不认为有结构优势方")

    # 信号 3: 平局赔率合理（平局保障）
    if spf_draw is not None and spf_draw <= 3.4:
        confidence += 5
        rationale_points.append("平局赔率合理，平局保障较好")

    # 强队压阵风险（主胜极低赔率+深盘 → 反击难度加大）
    if spf_win is not None and spf_win < 1.65 and handicap < -1:
        warning_tags.append("主队压制力过强")
        fit -= 18
        confidence -= 14
        rationale_points.append(f"主胜赔率 {spf_win}，让球 {handicap:+g}，主队压制力过强，反击空间受限")

    # 杯赛战意差异
    if "杯" in league:
        warning_tags.append("杯赛轮换风险")
        fit -= 8
        confidence -= 6

    if not counter_signal:
        fit -= 15
        confidence -= 10
        recommendation_label = "无明显反击信号"

    dual_defense_risk = (
        spf_draw is not None and spf_draw <= 2.9
        and spf_win is not None and spf_lose is not None
        and abs(spf_win - spf_lose) <= 0.35
    )
    if dual_defense_risk:
        warning_tags.append("双防低进球风险")
        fit -= 12
        confidence -= 8

    fit, confidence = _apply_model_agreement(row, fit, confidence, warning_tags, rationale_points)

    fit, confidence, risk, rec_type, label_override, primary, secondary, should_skip = _finalise(
        fit, confidence, warning_tags, rationale_points, primary, secondary, dual_defense_risk
    )
    if label_override:
        recommendation_label = label_override

    rationale_summary = (
        f"{home_team} vs {away_team}：{recommendation_label}，"
        f"主推 {primary}{'，次选 ' + secondary if secondary else ''}。"
    )
    detailed = {
        "basic_view": f"让球 {handicap:+g}，SPF 主/平/客={spf_win}/{spf_draw}/{spf_lose}",
        "structure_view": f"反击路径：{primary}{' / ' + secondary if secondary else ''}",
        "market_view": "关注客队实力与主队让球深度，浅盘对决反击价值更高",
        "risk_notes": "；".join(dict.fromkeys(warning_tags)) if warning_tags else "暂无明显反击风险",
        "final_verdict": f"{rec_type} | {recommendation_label}",
    }

    return StrategyRecommendation(
        strategy_id=strategy_id,
        match_id=_build_match_id(row),
        fit_score=fit,
        confidence_score=confidence,
        risk_level=risk,
        recommendation_type=rec_type,
        recommendation_label=recommendation_label,
        primary_pick=primary,
        secondary_pick=secondary,
        rationale_summary=rationale_summary,
        rationale_points=rationale_points[:4],
        warning_tags=list(dict.fromkeys(warning_tags)),
        should_skip=should_skip,
        detailed_analysis=detailed,
    )


# ---------------------------------------------------------------------------
# Strategy: hot_cold_divergence_v1
# ---------------------------------------------------------------------------

def _hot_cold_divergence_recommendation(row: pd.Series, strategy_id: str) -> StrategyRecommendation:
    """识别大众热度与真实结构背离的场景。

    "热"方向：赔率极低（大众狂热追捧）。
    "冷"结构：让球盘口并未同步反映热度，或 AI 模型对热门方向持保留态度。
    策略推荐走"冷"路径（通常为平局或次热门方向）。
    """
    home_team = str(row.get("home_team", "")).strip()
    away_team = str(row.get("away_team", "")).strip()
    league = str(row.get("league", "")).strip()

    handicap = _parse_handicap(row.get("handicap"))
    spf_win = _safe_float(row.get("spf_win"))
    spf_draw = _safe_float(row.get("spf_draw"))
    spf_lose = _safe_float(row.get("spf_lose"))
    rqspf_win = _safe_float(row.get("rqspf_win"))

    fit = 46
    confidence = 48
    warning_tags: list[str] = []
    rationale_points: list[str] = []
    recommendation_label = "冷热背离待确认"
    primary = "平胜"
    secondary: str | None = "平平"
    divergence_detected = False

    # 背离信号 1: 主胜"热"（<1.80）但让球"冷"（>= -0.5，盘口不认可大比分优势）
    if spf_win is not None and spf_win < 1.80 and handicap >= -0.5:
        divergence_detected = True
        recommendation_label = "主胜热度过高结构背离"
        primary, secondary = "平胜", "平平"
        fit += 22
        confidence += 16
        warning_tags.append("主胜热度背离")
        rationale_points.append(
            f"主胜赔率 {spf_win}（热），让球 {handicap:+g}（冷，盘口不支持大优势），结构背离"
        )

    # 背离信号 2: rqspf_win 远高于 spf_win（让球市场泼冷水）
    if spf_win is not None and rqspf_win is not None and rqspf_win - spf_win > 0.20:
        divergence_detected = True
        fit += 12
        confidence += 10
        rationale_points.append(
            f"让胜赔率({rqspf_win}) 与主胜赔率({spf_win}) 差值 {rqspf_win - spf_win:.2f}，盘口冷却热度"
        )

    # 背离信号 3: 平局赔率低（平局是真正的"冷"价值目标）
    if spf_draw is not None and spf_draw <= 3.15:
        fit += 8
        confidence += 6
        rationale_points.append(f"平局赔率 {spf_draw}，平局路径具备冷门价值")

    # 反向背离：客队热度（spf_lose < 1.90）+ 主队被让球（handicap > 0）
    if spf_lose is not None and spf_lose < 1.90 and handicap > 0:
        divergence_detected = True
        recommendation_label = "客胜热度背离"
        primary, secondary = "平胜", "胜胜"
        warning_tags.append("客胜热度背离")
        rationale_points.append(
            f"客胜赔率 {spf_lose}（热），主队让球 {handicap:+g}（冷），结构不支持客队大优势"
        )

    # 无背离信号时降低适配度
    if not divergence_detected:
        fit -= 15
        confidence -= 10
        recommendation_label = "无明显冷热背离"

    # 杯赛尺度波动
    if "杯" in league:
        warning_tags.append("杯赛随机性高")
        fit -= 7
        confidence -= 5

    dual_defense_risk = (
        spf_draw is not None and spf_draw <= 2.9
        and spf_win is not None and spf_lose is not None
        and abs(spf_win - spf_lose) <= 0.35
    )
    if dual_defense_risk:
        warning_tags.append("双防低进球风险")
        fit -= 12
        confidence -= 8

    fit, confidence = _apply_model_agreement(row, fit, confidence, warning_tags, rationale_points)

    fit, confidence, risk, rec_type, label_override, primary, secondary, should_skip = _finalise(
        fit, confidence, warning_tags, rationale_points, primary, secondary, dual_defense_risk
    )
    if label_override:
        recommendation_label = label_override

    rationale_summary = (
        f"{home_team} vs {away_team}：{recommendation_label}，"
        f"主推 {primary}{'，次选 ' + secondary if secondary else ''}。"
    )
    detailed = {
        "basic_view": f"让球 {handicap:+g}，SPF 主/平/客={spf_win}/{spf_draw}/{spf_lose}",
        "structure_view": f"冷热背离路径：{primary}{' / ' + secondary if secondary else ''}",
        "market_view": "热度赔率与让球盘口越背离，冷门价值越高；平局是最典型的冷门路径",
        "risk_notes": "；".join(dict.fromkeys(warning_tags)) if warning_tags else "暂无冷热背离信号",
        "final_verdict": f"{rec_type} | {recommendation_label}",
    }

    return StrategyRecommendation(
        strategy_id=strategy_id,
        match_id=_build_match_id(row),
        fit_score=fit,
        confidence_score=confidence,
        risk_level=risk,
        recommendation_type=rec_type,
        recommendation_label=recommendation_label,
        primary_pick=primary,
        secondary_pick=secondary,
        rationale_summary=rationale_summary,
        rationale_points=rationale_points[:4],
        warning_tags=list(dict.fromkeys(warning_tags)),
        should_skip=should_skip,
        detailed_analysis=detailed,
    )


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_STRATEGY_HANDLERS = {
    "structure_edge_v1": _structure_edge_recommendation,
    "market_trap_v1": _market_trap_recommendation,
    "counter_attack_v1": _counter_attack_recommendation,
    "hot_cold_divergence_v1": _hot_cold_divergence_recommendation,
}


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
    handler = _STRATEGY_HANDLERS.get(strategy_id)

    recommendations: list[dict] = []
    for _, row in enriched.iterrows():
        if handler is not None:
            rec = handler(row, strategy_id)
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
