from __future__ import annotations


def build_wechat_article_prompt(match: dict, gemini: dict, public_account_name: str = "金条玩足球") -> str:
    return f"""你现在是一名专业足球公众号作者，擅长把已有的比赛分析整理成适合微信公众号发布的高质量赛前文案。

请基于以下比赛基础信息与分析素材，生成一篇适合公众号【{public_account_name}】发布的赛前文章。

写作要求：
1. 必须使用公众号文章风格
2. 结构严格为：
   - 标题
   - 开场白
   - 1.基本面分析
   - 2.比赛走势
   - 3.赛果预测
3. 基本面分析中要分主队和客队分别写
4. 比赛走势必须拆成三段，每段第一句加粗，作为核心重点总结
5. 最终要明确给出：
   - 推荐
   - 两个比分
6. 不要输出列表式AI答案，要写成成熟的公众号成文
7. 不要脱离提供的分析素材胡乱编造
8. 禁止出现“根据模型分析/AI判断”这类措辞

请严格按以下格式输出：
【{public_account_name}】主队名VS客队名：标题
“……”一段总述开场白
1. 基本面分析
主队名（加粗）...
客队名（加粗）...
2. 比赛走势
三段分析，每段第一句加粗
3. 赛果预测
综合来看，这场比赛更倾向于：
推荐：XXX
比分：X:X，X:X
最后一段自然语言收尾。

比赛基础信息：
- 联赛：{match.get('league', '')}
- 主队：{match.get('home_team', '')}
- 客队：{match.get('away_team', '')}
- 开赛时间：{match.get('kickoff_time', '')}
- 让球：{match.get('handicap', '')}
- 胜平负赔率：主胜 {match.get('spf_win', '')} / 平 {match.get('spf_draw', '')} / 客胜 {match.get('spf_lose', '')}
- 让球赔率：让胜 {match.get('rqspf_win', '')} / 让平 {match.get('rqspf_draw', '')} / 让负 {match.get('rqspf_lose', '')}

Gemini分析素材（核心输入）：
- 原始分析：{gemini.get('gemini_raw_text', '')}
- 摘要：{gemini.get('gemini_summary', '')}
- 胜平负主次推：{gemini.get('gemini_match_main_pick', '')} / {gemini.get('gemini_match_secondary_pick', '')}
- 让球主次推：{gemini.get('gemini_handicap_main_pick', '')} / {gemini.get('gemini_handicap_secondary_pick', '')}
- 比分建议：{gemini.get('gemini_score_1', '')} / {gemini.get('gemini_score_2', '')}

请生成完整成稿。"""
