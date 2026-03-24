from __future__ import annotations

STRATEGY_META = {
    "id": "structure_edge_v1",
    "name_cn": "比赛结构优势模型 V1",
    "name_en": "Structure Edge V1",
    "version": "v1",
    "short_description": "从比赛结构与主导路径出发，优先识别胜胜/平胜/平平三类结构机会。",
    "long_description": "该策略优先识别强弱关系明确、结构路径清晰的比赛，再结合盘口/赔率分歧与模型一致性做风险过滤，输出主推、次选、置信度与风险标签。",
    "status": "active",
    "is_default": True,
    "applicable_scenarios": [
        "控球压制型主场",
        "高节奏但防守不稳的对决",
        "防守反击 vs 控球主导",
    ],
    "not_applicable_scenarios": [
        "双防型低进球比赛",
        "密集赛程下的强队客场",
        "裁判尺度不稳 / VAR 频繁打断节奏的比赛",
    ],
    "output_logic": [
        "先评估结构适配度 fit_score，再评估置信度 confidence_score",
        "输出推荐方向、主推/次推、风险等级与风险标签",
        "高风险且结构不匹配时可建议跳过",
    ],
}
