from __future__ import annotations

STRATEGY_META = {
    "id": "structure_edge_v1",
    "name_cn": "比赛结构优势模型 V1",
    "name_en": "Structure Edge V1",
    "version": "v1",
    "status": "active",
    "is_default": True,
    "short_description": "识别结构清晰型比赛，聚焦胜胜/平胜/平平路径，并对高风险场次过滤。",
    "long_description": (
        "该策略以比赛结构为核心，不盲目追高赔。"
        "当主胜赔率低且主队具备结构优势时，优先考虑胜胜/平胜路径；"
        "在拉扯型对局中关注平平或平胜，并结合盘赔分歧与模型一致性进行风险过滤。\n\n"
        "资金管理展示（3:3:3:1）：\n"
        "- 30% 稳守：主胜<=1.85场次，主打胜胜/平胜，目标年化12%-15%\n"
        "- 30% 均衡：防反、杯赛等中波动场景\n"
        "- 30% 弹性：全年仅8-12次高赔机会，严格设限\n"
        "- 10% 保留：极端情况下补仓或空仓\n"
        "附加：单场投入<=总资金5%；仅在 胜率×赔率>1.2 时出手"
    ),
    "applicable_scenarios": [
        "控球压制型主场（结构集中于胜胜/平胜）",
        "高节奏但防守不稳的对决（平胜/平平需要并行评估）",
        "防守反击 vs 控球主导（可参与但需提高风险阈值）",
    ],
    "not_applicable_scenarios": [
        "双防型低进球比赛（平平概率过高，结构性不足）",
        "密集赛程下的强队客场（轮换与体能风险高）",
        "裁判尺度不稳 / VAR 频繁打断节奏的比赛（结构随机性上升）",
    ],
    "output_logic": [
        "先计算 fit_score（结构适配）再计算 confidence_score（执行置信度）",
        "输出 recommendation_type、recommendation_label、primary/secondary 结构路径",
        "若命中回避条件则降低 fit_score 并可推荐跳过",
    ],
    "strategy_principles": {
        "baseline_patterns": [
            "主胜初始赔率<1.85时，历史上胜胜/平胜/平平集中度较高",
            "强弱分明场次应优先追结构主路径，不盲追高赔逆转",
        ],
        "focus_scenarios": [
            "控球压制型主场",
            "高节奏但防守不稳",
            "防反克制控球主导",
        ],
        "avoidance_rules": [
            "双防型低进球",
            "密集赛程强队客场",
            "裁判尺度/VAR波动联赛",
        ],
        "bankroll_notes": [
            "3:3:3:1 资金管理模型（展示用途）",
            "单场投入<=总资金5%",
            "仅在 胜率×赔率>1.2 时考虑执行",
        ],
    },
    "strategy_output_schema": [
        "strategy_id",
        "match_id",
        "fit_score",
        "confidence_score",
        "risk_level",
        "recommendation_type",
        "recommendation_label",
        "primary_pick",
        "secondary_pick",
        "rationale_summary",
        "rationale_points",
        "warning_tags",
        "should_skip",
        "detailed_analysis",
    ],
}
