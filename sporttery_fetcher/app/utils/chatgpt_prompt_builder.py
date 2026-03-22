from __future__ import annotations


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
    return f"""你现在是一名 专业足球比赛精算分析师（Football Quantitative Analyst）。

请对以下比赛进行 深度分析，并基于分析推导概率预测。
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

{home_team} {handicap}

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

当前 {spf_win}主胜赔率是否合理

{handicap}盘口的合理性

胜平负赔率与让球盘口之间是否存在 矛盾

庄家可能的 真实意图

是否存在 诱盘或过热方向

⸻

第三步：比赛走势推演

结合球队特点推演：

比赛节奏

进球概率

是否可能出现大胜

是否更容易出现 1球小胜

⸻

第四步：基于分析推导概率

根据以上分析给出 你自己的概率预测（总和必须为100%）。

注意：
概率必须来源于分析判断，而不是赔率换算。

⸻

请以 JSON 返回，键名固定：
{{
  "match_result_prob": {{"home_win": 0, "draw": 0, "away_win": 0}},
  "handicap_result_prob": {{"handicap_win": 0, "handicap_draw": 0, "handicap_lose": 0}},
  "likely_scores": ["0-0", "1-0", "1-1"],
  "top_direction": "主胜",
  "upset_probability_text": "主队不胜概率 xx%",
  "summary": "不超过120字"
}}

要求：
- 概率都用数字（0-100），两组概率各自总和=100
- likely_scores 固定输出3个比分字符串
- 不要输出 Markdown 代码块，只输出 JSON
"""
