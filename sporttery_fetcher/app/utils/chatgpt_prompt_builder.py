from __future__ import annotations


CN_HANDICAP_MAP = {
    -1: "让一球",
    1: "受让一球",
    -2: "让两球",
    2: "受让两球",
    -3: "让三球",
    3: "受让三球",
}


def _parse_handicap_value(handicap: str | int | float | None) -> int | None:
    if handicap is None:
        return None
    s = str(handicap).strip()
    if not s:
        return None
    try:
        return int(float(s))
    except Exception:
        return None


def build_handicap_text(home_team: str, handicap: str | int | float | None) -> str:
    value = _parse_handicap_value(handicap)
    if value is None or value == 0:
        return f"{home_team} 平手"
    if value in CN_HANDICAP_MAP:
        return f"{home_team} {CN_HANDICAP_MAP[value]}"
    if value < 0:
        return f"{home_team} 让{abs(value)}球"
    return f"{home_team} 受让{abs(value)}球"


def build_chatgpt_probability_prompt(
    *,
    league: str,
    home_team: str,
    away_team: str,
    kickoff_time: str,
    handicap: str,
    spf_win: str,
    spf_draw: str,
    spf_lose: str,
    rqspf_win: str,
    rqspf_draw: str,
    rqspf_lose: str,
) -> str:
    handicap_text = build_handicap_text(home_team=home_team, handicap=handicap)

    return f"""你现在是一名专业足球比赛精算分析师（Football Quantitative Analyst）。

请对以下比赛进行深度分析，并基于分析推导概率预测。
注意：最终概率必须来源于你的综合分析，不允许直接使用赔率隐含概率作为结果。赔率只能作为参考信息。

⸻

比赛信息

比赛：{home_team} vs {away_team}
联赛：{league}
时间：{kickoff_time}

胜平负赔率

主胜 {spf_win}
平局 {spf_draw}
客胜 {spf_lose}

亚洲盘口

{handicap_text}

让球赔率

让胜 {rqspf_win}
让平 {rqspf_draw}
让负 {rqspf_lose}

⸻

分析步骤

请严格按照以下步骤分析：

第一步：球队实力分析

两队整体实力对比
• 阵容价值
• 联赛排名
• 攻防能力

近期状态
• 最近5场比赛战绩
• 进球数与失球数

主客场表现
• {home_team}主场表现
• {away_team}客场表现

历史交锋
• 过去交锋胜率
• 是否存在心理优势

伤停情况
• 是否有核心球员缺阵

战术风格
• 控球 / 反击 / 防守
• 是否存在战术克制

⸻

第二步：盘口与赔率逻辑

请重点分析：

当前主胜赔率是否合理

当前亚洲盘口的合理性

胜平负赔率与让球盘口之间是否存在矛盾

庄家可能的真实意图

是否存在诱盘或过热方向

⸻

第三步：比赛走势推演

结合球队特点推演：

比赛节奏

进球概率

是否可能出现大胜

是否更容易出现1球小胜

是否存在平局拉扯的可能

⸻

第四步：基于分析推导概率

根据以上分析给出你自己的概率预测（总和必须为100%）。

要求：
1. 【比赛结果概率】三项总和必须为100%
2. 【让球结果概率】三项总和必须为100%
3. 概率必须来源于分析判断，而不是赔率换算
4. 请给出3个最可能比分，并按概率从高到低排序
5. 如果你判断存在主推和次推，请在分析文字中体现，但最终概率输出仍须唯一明确

⸻

输出格式

请严格按照以下格式输出：

【比赛结果概率】
主胜：X%
平局：X%
客胜：X%

【让球结果概率】
让胜：X%
让平：X%
让负：X%

【最可能比分】
X-X
X-X
X-X

【最大概率方向】
一句话说明（只写一个最强方向）

【爆冷概率】
请说明你的定义，并给出对应概率

在上述分析结束后，请再严格补充以下内容，每项单独一行（必须输出，次推缺失时写“无”）：

胜平负主推：<主胜/平局/客胜>
胜平负次推：<主胜/平局/客胜/无>
让球主推：<让胜/让平/让负>
让球次推：<让胜/让平/让负/无>
比分1：<X-X>
比分2：<X-X>
比分3：<X-X>
最大概率方向：<一句话>
爆冷方向定义：<主队不胜/客胜/其他>
爆冷概率数值：<X%>
"""
