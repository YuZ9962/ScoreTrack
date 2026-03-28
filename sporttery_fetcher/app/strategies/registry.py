from __future__ import annotations

from dataclasses import dataclass, asdict

from strategies.configs.structure_edge_v1 import STRATEGY_META as STRUCTURE_EDGE_V1


@dataclass(frozen=True)
class StrategyMeta:
    id: str
    name_cn: str
    name_en: str
    version: str
    short_description: str
    long_description: str
    status: str
    is_default: bool
    applicable_scenarios: list[str]
    not_applicable_scenarios: list[str]
    output_logic: list[str]
    strategy_principles: dict[str, list[str]]
    strategy_output_schema: list[str]


COMING_SOON_PRINCIPLES = {
    "baseline_patterns": ["Coming Soon"],
    "focus_scenarios": ["Coming Soon"],
    "avoidance_rules": ["Coming Soon"],
    "bankroll_notes": ["Coming Soon"],
}


_REGISTRY = {
    "structure_edge_v1": StrategyMeta(**STRUCTURE_EDGE_V1),
    "market_trap_v1": StrategyMeta(
        id="market_trap_v1",
        name_cn="市场陷阱识别模型 V1",
        name_en="Market Trap V1",
        version="v1",
        short_description="识别赔率热度与盘口结构背离形成的市场陷阱，回避热门方向，关注平局或次热门路径。",
        long_description=(
            "当主胜（或客胜）赔率极低，但让球盘口并未同步压深时，说明盘口市场不完全"
            "认同赔率表达的优势幅度。此类场景存在大众追热门而庄家保留的结构性矛盾，"
            "推荐走平局保险或次热门路径。\n\n"
            "核心规则：\n"
            "- 主胜赔率<1.75 且让球盘口>=-0.5：强烈陷阱信号\n"
            "- 让胜赔率与主胜赔率差值>0.25：盘口市场泼冷水\n"
            "- 平局赔率<=3.2：平局路径具备价值"
        ),
        status="active",
        is_default=False,
        applicable_scenarios=[
            "主胜赔率极低但让球盘口较浅（结构不支持大比分优势）",
            "让胜赔率明显高于主胜赔率（盘口冷却热度）",
            "平局赔率在合理范围内（平局是反陷阱路径）",
        ],
        not_applicable_scenarios=[
            "主胜赔率低且同步深盘（结构支持，非陷阱）",
            "双防低进球比赛（平局赔率极低，结构噪音高）",
        ],
        output_logic=[
            "检测赔率热度与让球盘口之间的背离幅度",
            "陷阱越深则推荐走平局保险（平胜/平平）",
            "客队热门陷阱时推荐平胜/胜胜路径",
        ],
        strategy_principles={
            "baseline_patterns": [
                "主胜赔率<1.75且让球>=−0.5：陷阱概率高",
                "让胜赔率与主胜差值>0.25：盘口不认同",
            ],
            "focus_scenarios": [
                "赔口背离型对决",
                "大众过度追捧的强强对话",
            ],
            "avoidance_rules": [
                "主胜低赔且深盘（结构真实）",
                "双防低进球场次",
            ],
            "bankroll_notes": [
                "陷阱场次仓位不宜过重，建议单场≤总资金3%",
                "命中率敏感，需配合实际赛事信息使用",
            ],
        },
        strategy_output_schema=STRUCTURE_EDGE_V1["strategy_output_schema"],
    ),
    "counter_attack_v1": StrategyMeta(
        id="counter_attack_v1",
        name_cn="反击克制模型 V1",
        name_en="Counter Attack V1",
        version="v1",
        short_description="识别控球主场被客队反击克制的场景，关注平局或平胜路径。",
        long_description=(
            "当客队具备反击能力且主队让球较浅时，主场控球压制未必能转化为大比分优势。"
            "此策略在实力接近、让球浅盘的对局中关注平胜或平平路径。\n\n"
            "核心规则：\n"
            "- 客胜赔率<2.8 且主队让球>=-0.5：反击空间存在\n"
            "- 让球赔率双边偏高：盘口认为难分胜负\n"
            "- 主胜赔率<1.65 且深盘：主队压制力过强，反击难度高"
        ),
        status="active",
        is_default=False,
        applicable_scenarios=[
            "实力接近、主队让球浅（反击空间存在）",
            "让球赔率双边偏高（盘口不认为有结构优势）",
            "客队有明确反击战术特点",
        ],
        not_applicable_scenarios=[
            "主队赔率极低且深盘（压制力过强）",
            "杯赛轮换导致战意差异过大",
        ],
        output_logic=[
            "检测客队反击条件：赔率合理+让球浅",
            "排除主队压制力过强场次",
            "推荐平胜/平平路径作为反击结构路径",
        ],
        strategy_principles={
            "baseline_patterns": [
                "客胜赔率<2.8且让球>=-0.5：反击价值合理",
                "让球双边赔率偏高：盘口不认为有绝对优势",
            ],
            "focus_scenarios": [
                "浅盘实力接近对局",
                "控球主场防守漏洞场次",
            ],
            "avoidance_rules": [
                "主胜<1.65且深盘（压制力过强）",
                "杯赛大幅轮换场次",
            ],
            "bankroll_notes": [
                "反击场次不确定性较高，建议保守仓位",
                "单场投入≤总资金4%",
            ],
        },
        strategy_output_schema=STRUCTURE_EDGE_V1["strategy_output_schema"],
    ),
    "cup_rotation_v1": StrategyMeta(
        id="cup_rotation_v1",
        name_cn="杯赛轮换模型 V1",
        name_en="Cup Rotation V1",
        version="v1",
        short_description="杯赛轮换与战意偏差识别（预留）。",
        long_description="Coming Soon",
        status="disabled",
        is_default=False,
        applicable_scenarios=["Coming Soon"],
        not_applicable_scenarios=["Coming Soon"],
        output_logic=["Coming Soon"],
        strategy_principles=COMING_SOON_PRINCIPLES,
        strategy_output_schema=STRUCTURE_EDGE_V1["strategy_output_schema"],
    ),
    "hot_cold_divergence_v1": StrategyMeta(
        id="hot_cold_divergence_v1",
        name_cn="冷热背离模型 V1",
        name_en="Hot-Cold Divergence V1",
        version="v1",
        short_description="识别大众热度赔率与让球盘口背离，挖掘平局等冷门路径价值。",
        long_description=(
            "当某方向赔率极低（大众热门）但让球盘口结构并不支持时，"
            "平局等被市场忽视的「冷」路径往往具备超额价值。\n\n"
            "核心规则：\n"
            "- 主胜赔率<1.80 且让球>=-0.5：冷热背离主信号\n"
            "- 让胜赔率与主胜差>0.20：让球市场泼冷水\n"
            "- 平局赔率<=3.15：平局路径具备冷门价值\n"
            "- 客胜赔率<1.90 且主队受让：反向背离信号"
        ),
        status="active",
        is_default=False,
        applicable_scenarios=[
            "主胜赔率极低但让球较浅（热度与结构背离）",
            "让球赔率与主胜赔率差值明显（盘口冷却）",
            "平局赔率在冷门价值区间内（<= 3.15）",
        ],
        not_applicable_scenarios=[
            "主胜低赔且深盘（热度与结构一致）",
            "双防低进球（平局赔率极低，无价值区间）",
        ],
        output_logic=[
            "计算热度赔率与让球盘口的背离程度",
            "背离越大，冷路径（平局）价值越高",
            "提供平胜/平平作为冷门结构路径",
        ],
        strategy_principles={
            "baseline_patterns": [
                "主胜<1.80且让球>=-0.5：背离信号",
                "让胜与主胜差>0.20：盘口不认同热度",
                "平局赔率<=3.15：冷门价值区间",
            ],
            "focus_scenarios": [
                "大众热捧但盘口保守的对局",
                "平局赔率被低估的均衡型对局",
            ],
            "avoidance_rules": [
                "热度与结构一致的主场压制场次",
                "双防低进球场次（结构噪音高）",
            ],
            "bankroll_notes": [
                "冷门路径波动大，仓位不宜超过总资金3%",
                "全年高背离机会有限，严格筛选后再执行",
            ],
        },
        strategy_output_schema=STRUCTURE_EDGE_V1["strategy_output_schema"],
    ),
}


def list_strategies() -> list[StrategyMeta]:
    return list(_REGISTRY.values())


def get_strategy(strategy_id: str) -> StrategyMeta | None:
    return _REGISTRY.get(strategy_id)


def get_default_strategy() -> StrategyMeta:
    for s in _REGISTRY.values():
        if s.is_default:
            return s
    return list(_REGISTRY.values())[0]


def list_strategy_dicts() -> list[dict]:
    return [asdict(s) for s in list_strategies()]
