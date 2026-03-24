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


_REGISTRY = {
    "structure_edge_v1": StrategyMeta(**STRUCTURE_EDGE_V1),
    "market_trap_v1": StrategyMeta(
        id="market_trap_v1",
        name_cn="市场陷阱识别模型 V1",
        name_en="Market Trap V1",
        version="v1",
        short_description="识别盘口与赔率的人气陷阱场景（预留）。",
        long_description="Coming Soon",
        status="beta",
        is_default=False,
        applicable_scenarios=["Coming Soon"],
        not_applicable_scenarios=["Coming Soon"],
        output_logic=["Coming Soon"],
    ),
    "counter_attack_v1": StrategyMeta(
        id="counter_attack_v1",
        name_cn="反击克制模型 V1",
        name_en="Counter Attack V1",
        version="v1",
        short_description="识别控球方被反击克制场景（预留）。",
        long_description="Coming Soon",
        status="beta",
        is_default=False,
        applicable_scenarios=["Coming Soon"],
        not_applicable_scenarios=["Coming Soon"],
        output_logic=["Coming Soon"],
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
    ),
    "hot_cold_divergence_v1": StrategyMeta(
        id="hot_cold_divergence_v1",
        name_cn="冷热背离模型 V1",
        name_en="Hot-Cold Divergence V1",
        version="v1",
        short_description="大众热度与真实结构背离识别（预留）。",
        long_description="Coming Soon",
        status="beta",
        is_default=False,
        applicable_scenarios=["Coming Soon"],
        not_applicable_scenarios=["Coming Soon"],
        output_logic=["Coming Soon"],
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
