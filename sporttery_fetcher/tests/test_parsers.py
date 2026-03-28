"""Tests for gemini_parser and chatgpt_parser."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"
for p in [str(ROOT), str(APP_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from services.gemini_parser import parse_gemini_output, parse_manual_raw_text
from services.chatgpt_parser import parse_chatgpt_output


# ---------------------------------------------------------------------------
# gemini_parser
# ---------------------------------------------------------------------------

class TestParseGeminiOutput:
    def test_empty_text_returns_nones(self):
        result = parse_gemini_output("")
        assert result["gemini_match_main_pick"] is None
        assert result["gemini_handicap_main_pick"] is None
        assert result["gemini_score_1"] is None
        assert result["gemini_summary"] is None

    def test_structured_block_parsing(self):
        text = (
            "综合分析表明主队整体实力更强。\n"
            "胜平负主推：主胜\n"
            "胜平负次推：无\n"
            "让球胜平负主推：让胜\n"
            "让球胜平负次推：无\n"
            "比分1：2-0\n"
            "比分2：1-0"
        )
        result = parse_gemini_output(text)
        assert result["gemini_match_main_pick"] == "主胜"
        assert result["gemini_match_secondary_pick"] == "无"
        assert result["gemini_handicap_main_pick"] == "让胜"
        assert result["gemini_score_1"] == "2-0"
        assert result["gemini_score_2"] == "1-0"

    def test_secondary_pick_with_value(self):
        text = (
            "主队让球场景下胜负分析。\n"
            "胜平负主推：平\n"
            "胜平负次推：主胜\n"
            "让球胜平负主推：让平\n"
            "让球胜平负次推：让胜\n"
            "比分1：1-1\n"
            "比分2：2-1"
        )
        result = parse_gemini_output(text)
        assert result["gemini_match_main_pick"] == "平"
        assert result["gemini_match_secondary_pick"] == "主胜"
        assert result["gemini_handicap_main_pick"] == "让平"
        assert result["gemini_handicap_secondary_pick"] == "让胜"

    def test_score_extraction_without_structured_block(self):
        text = "两队对抗激烈，预计比分为 2-1 或 1-1。"
        result = parse_gemini_output(text)
        assert result["gemini_score_1"] == "2-1"
        assert result["gemini_score_2"] == "1-1"

    def test_summary_truncation(self):
        long_text = "A" * 200 + "\n胜平负主推：主胜\n让球胜平负主推：让胜\n比分1：2-0\n比分2：1-0"
        result = parse_gemini_output(long_text)
        assert result["gemini_summary"] is not None
        assert len(result["gemini_summary"]) <= 141  # max_len + "…"

    def test_client_loss_prediction(self):
        text = (
            "客队表现更佳。\n"
            "胜平负主推：客胜\n"
            "胜平负次推：无\n"
            "让球胜平负主推：让负\n"
            "让球胜平负次推：无\n"
            "比分1：0-1\n"
            "比分2：0-2"
        )
        result = parse_gemini_output(text)
        assert result["gemini_match_main_pick"] == "客胜"
        assert result["gemini_handicap_main_pick"] == "让负"


class TestParseManualRawText:
    def test_parses_pick_fields(self):
        text = (
            "主队占据主动。\n"
            "胜平负主推：主胜\n"
            "胜平负次推：无\n"
            "让球胜平负主推：让胜\n"
            "让球胜平负次推：无\n"
            "比分1：2-0\n"
            "比分2：1-0"
        )
        result = parse_manual_raw_text(text)
        assert result["result_prediction"] == "主胜"
        assert result["handicap_prediction"] == "让胜"
        assert result["score_prediction"] == "2-0 / 1-0"

    def test_empty_text(self):
        result = parse_manual_raw_text("")
        assert result["result_prediction"] is None
        assert result["handicap_prediction"] is None

    def test_parse_warning_on_missing_picks(self):
        result = parse_manual_raw_text("无效文本，没有标准格式")
        assert "parse_warning" in result
        assert result["parse_warning"] != ""


# ---------------------------------------------------------------------------
# chatgpt_parser
# ---------------------------------------------------------------------------

SAMPLE_CHATGPT_OUTPUT = """你是专业足球分析师...

【比赛结果概率】
主胜：55%
平局：25%
客胜：20%

【让球结果概率】
让胜：60%
让平：22%
让负：18%

【最可能比分】
2-0
1-0
2-1

【最大概率方向】
主队主场优势明显，主胜路径最合理

【爆冷概率】
主队不胜概率约 45%，赔率存在低估风险

在上述分析结束后，请再严格补充以下内容：

胜平负主推：主胜
胜平负次推：平局
让球主推：让胜
让球次推：无
比分1：2-0
比分2：1-0
比分3：2-1
最大概率方向：主队压制优势明确
爆冷方向定义：主队不胜
爆冷概率数值：45%
"""


class TestParseChatgptOutput:
    def test_empty_text(self):
        result = parse_chatgpt_output("")
        assert result["chatgpt_home_win_prob"] is None
        assert result["chatgpt_match_main_pick"] is None

    def test_full_structured_output(self):
        result = parse_chatgpt_output(SAMPLE_CHATGPT_OUTPUT)
        assert result["chatgpt_home_win_prob"] == 55.0
        assert result["chatgpt_draw_prob"] == 25.0
        assert result["chatgpt_away_win_prob"] == 20.0
        assert result["chatgpt_handicap_win_prob"] == 60.0
        assert result["chatgpt_match_main_pick"] == "主胜"
        assert result["chatgpt_match_secondary_pick"] == "平局"
        assert result["chatgpt_handicap_main_pick"] == "让胜"
        assert result["chatgpt_score_1"] == "2-0"
        assert result["chatgpt_score_2"] == "1-0"
        assert result["chatgpt_score_3"] == "2-1"

    def test_probability_normalization(self):
        # Probabilities that don't sum to 100 should be normalized
        text = (
            "【比赛结果概率】\n主胜：50%\n平局：30%\n客胜：30%\n"
            "【让球结果概率】\n让胜：40%\n让平：30%\n让负：30%\n"
            "胜平负主推：主胜\n胜平负次推：无\n让球主推：让胜\n让球次推：无\n"
            "比分1：1-0\n比分2：0-0\n比分3：2-0\n"
            "最大概率方向：主胜\n爆冷方向定义：客胜\n爆冷概率数值：30%"
        )
        result = parse_chatgpt_output(text)
        total = (result["chatgpt_home_win_prob"] or 0) + (result["chatgpt_draw_prob"] or 0) + (result["chatgpt_away_win_prob"] or 0)
        assert abs(total - 100.0) < 0.1

    def test_secondary_pick_none_becomes_wu(self):
        text = (
            "【比赛结果概率】\n主胜：60%\n平局：25%\n客胜：15%\n"
            "【让球结果概率】\n让胜：65%\n让平：20%\n让负：15%\n"
            "胜平负主推：主胜\n胜平负次推：无\n让球主推：让胜\n让球次推：无\n"
            "比分1：2-0\n比分2：1-0\n比分3：3-1\n"
            "最大概率方向：主胜\n爆冷方向定义：客胜\n爆冷概率数值：15%"
        )
        result = parse_chatgpt_output(text)
        assert result["chatgpt_match_secondary_pick"] == "无"

    def test_score_fallback_from_text(self):
        # No structured blocks, scores extracted from raw text
        text = "预计比分为 1-0，也有可能是 2-1。胜平负主推：主胜\n让球主推：让胜\n比分1：无\n比分2：无\n比分3：无"
        result = parse_chatgpt_output(text)
        # At minimum, scores were found somewhere
        assert result["chatgpt_score_1"] is not None or result["chatgpt_score_2"] is not None
