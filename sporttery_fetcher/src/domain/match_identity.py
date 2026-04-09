from __future__ import annotations

"""
match_identity.py
=================
全系统统一比赛 identity 模块。

规则（已确认，不再质疑）:
- issue_date = 销售日（一般是当天上午11点到第二天上午11点的销售窗口）
- match_date = 实际比赛开始日期
- match_key 是全局唯一比赛标识，所有跨模块匹配必须使用它，禁止裸用 match_no

match_key 格式:
    {issue_date}|{match_no}   当 issue_date 和 match_no 均非空时（主格式）
    biz:{issue_date}|{match_no}|{home_team}|{away_team}   兜底（缺少 match_no 时）
"""

import re
from typing import Any


# 全角/噪音符号 → 半角统一映射
_SYMBOL_MAP = str.maketrans(
    {
        "（": "(",
        "）": ")",
        "【": "[",
        "】": "]",
        "—": "-",
        "－": "-",
        "　": "",   # 全角空格
        "\u00a0": "",  # nbsp
    }
)

# 各类空白（包括普通空格）压缩为空
_SPACE_RE = re.compile(r"\s+")


def normalize_team_name(name: str | None) -> str:
    """轻量规范化队名：去空格、统一半角符号、去首尾噪音。

    不做深度别名映射（留给第二轮），只做最低限度的噪音清除，
    目的是让相同队伍的不同表达尽量能对上。
    """
    if not name:
        return ""
    text = str(name).strip()
    text = text.translate(_SYMBOL_MAP)
    text = _SPACE_RE.sub("", text)
    return text


def build_business_key(
    issue_date: str,
    match_no: str,
    home_team: str,
    away_team: str,
) -> str:
    """构造业务 key：biz:{issue_date}|{match_no}|{home}|{away}

    所有参数先经过 normalize_team_name（对 issue_date/match_no 也去空格）。
    """
    d = str(issue_date or "").strip()
    n = str(match_no or "").strip()
    h = normalize_team_name(home_team)
    a = normalize_team_name(away_team)
    return f"biz:{d}|{n}|{h}|{a}"


def build_match_key(record: dict[str, Any]) -> str:
    """从一条比赛记录构造全局唯一 match_key。

    格式：{issue_date}|{match_no}
    当 issue_date 或 match_no 缺失时兜底到 biz: 四字段格式。
    """
    issue_date = str(record.get("issue_date") or "").strip()
    match_no = str(record.get("match_no") or "").strip()
    # "nan" 是 pandas NaN 转字符串的产物，视为空
    if issue_date.lower() == "nan":
        issue_date = ""
    if match_no.lower() == "nan":
        match_no = ""

    if issue_date and match_no:
        return f"{issue_date}|{match_no}"

    # 兜底：缺失 issue_date 或 match_no 时用四字段 biz key
    return build_business_key(
        issue_date=issue_date,
        match_no=match_no,
        home_team=str(record.get("home_team") or ""),
        away_team=str(record.get("away_team") or ""),
    )


def match_keys_equal(key_a: str | None, key_b: str | None) -> bool:
    """判断两个 match_key 是否代表同一场比赛。空值视为不相等。"""
    if not key_a or not key_b:
        return False
    return key_a.strip() == key_b.strip()
