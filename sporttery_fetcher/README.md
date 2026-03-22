# sporttery_fetcher

本项目包含两部分：
1. **抓取端**：本地抓取中国体彩竞彩足球数据并保存 CSV/JSON。
2. **前端仪表盘（Streamlit）**：本地查看、筛选、统计每日比赛数据，并可在前端直接触发抓取。

---

## 1. 数据抓取（后端）

主页面：
- `https://www.sporttery.cn/jc/jsq/zqspf/index.html`

API（优先）：
- `https://webapi.sporttery.cn/gateway/uniform/football/getMatchCalculatorV1.qry?channel=c&poolCode=hhad,had`

命令行抓取（仍可用）：

```bash
python -m src.main --date 2026-03-19
```

输出：
- `data/raw/YYYY-MM-DD_matches.json`
- `data/processed/YYYY-MM-DD_matches.csv`

---

## 2. 前端仪表盘（Streamlit）

### 2.1 页面

- **Dashboard（首页）**：总览指标、联赛分布、抓取时间。
- **Matches**：比赛列表、筛选、排序、单场详情。
- **Match Detail**：单场比赛卡片式详情（仅保留基础信息与奖金信息）。
- **Analytics**：按“日/月/年 + 联赛”统一筛选的分析工作台，Gemini 推荐表头为中文展示。
- **Prediction（预测）**：独立预测页，支持单场预测、一键预测当日全部场次、失败场次手动补录。

### 2.2 前端直接抓取

每个页面左侧 sidebar 都有「抓取数据」区域：
- 日期选择器
- `抓取并加载` 按钮
- 简洁状态提示（成功/失败）

点击后会自动执行：

```bash
python -m src.main --date <选中日期>
```

并在成功后自动刷新并加载该日期 CSV。

### 2.3 日志展示策略

- 默认 **不在页面展示技术日志**（API/Fallback/Traceback/调试输出）
- 技术日志写入 `logs/app.log`
- 可选开启「开发者模式（显示调试信息）」，默认关闭

---

## 3. Gemini 预测功能（Match Detail 页）

### 3.1 环境变量

在 `.env` 中配置：

```env
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-3-flash-preview
GEMINI_THINKING_LEVEL=high
```

支持 thinking level：
- minimal
- low
- medium
- high

> 注意：Gemini 3 的 thinking 不是单独模型名，不要写 `gemini-3-thinking`。  
> 使用 Gemini 3 系列模型 + `GEMINI_THINKING_LEVEL` 控制思考强度。

### 3.2 SDK 兼容说明（本次修复）

- 项目使用官方 SDK：`google-genai>=1.0.0`
- 代码会先尝试 `thinking_config`
- 若本地 SDK 版本/接口不支持（如出现 validation/extra_forbidden/thinking_config 错误），会自动回退到**不带 thinking_config**模式，确保尽量返回结果
- 前端会显示：`是否启用 thinking：是/否`

升级依赖：

```bash
pip install -U -r requirements.txt
```

### 3.3 提示词模板（固定风格）

程序使用固定模板（自然语言分析 + 固定格式尾部）：

```text
你是一名足球分析师，针对{league}{home_team}vs{away_team}比赛，分析并且预测胜负结果和主队{handicap_text}胜负结果以及两个最可能打出的比分。

请先给出简洁清晰的分析。

请在分析结尾严格补充以下内容（每项单独一行）：
胜平负主推：<主胜/平/客胜>
胜平负次推：<主胜/平/客胜/无>
让球胜平负主推：<让胜/让平/让负>
让球胜平负次推：<让胜/让平/让负/无>
比分1：<比分>
比分2：<比分>
```

不会加入赔率，不会改成 JSON 模式。

### 3.4 使用方式

进入 `Prediction` 页：
1. 选择日期、联赛、场次
2. 点击 `预测当前场次` 执行单场预测
3. 或点击 `一键预测当日全部场次` 执行批量预测（支持进度提示）
4. 页面展示结构化字段，提示词与原始回复默认折叠

`Match Detail` 页面已移除 Gemini 预测区，仅用于查看比赛详情与奖金信息。

失败处理：
- 未配置 key：显示 `未配置 GEMINI_API_KEY`
- 模型配置/API 错误：显示 `Gemini 请求失败，请检查模型配置或 API key`
- 详细异常写日志，不在页面泄露 secret


### 3.5 Gemini 输出二次整理与持久化

每次在 `Prediction` 页执行单场或批量 Gemini 预测后，系统会保留并写入两层结果：

1. **原始层**
   - `gemini_prompt`
   - `gemini_raw_text`
2. **结构化层（规则解析）**
   - `gemini_match_main_pick` / `gemini_match_secondary_pick`
   - `gemini_handicap_main_pick` / `gemini_handicap_secondary_pick`
   - `gemini_score_1` / `gemini_score_2`
   - `gemini_summary`

并保存到：

- `data/predictions/gemini_predictions.csv`

去重规则：优先按 `issue_date + raw_id` 覆盖，`raw_id` 缺失时按 `issue_date + match_no + home_team + away_team` 覆盖。

### 3.6 Analytics 分析工作台（新版）

Analytics 页面重构为统一筛选 + 简洁统计：

- 顶部统一筛选区：
  - 时间维度：按日 / 按月 / 按年
  - 时间选择：根据维度动态展示可选值
  - 联赛筛选：全部联赛或指定联赛
- 基础分析区：
  - 每日/每月/每年比赛数（单值 summary）
  - 当前联赛比赛数（单值 summary）
- Gemini 推荐分析区：
  - 新增按钮：`更新比赛结果`（抓取官方赛果开奖页并更新本地结果文件；若解析 0 条则提示 warning，不显示成功）
  - 统计概览：推荐总场次、已结束场次数、胜平负命中率、让胜平负命中率
  - 推荐表格按 `match_no` 升序排序
  - 表格列以中文展示：日期时间、比赛序号、联赛、主客队、让球、胜平负、让胜平负、推荐比分、比赛实际比分、胜平负预测结果、让胜平负预测结果

说明：原有三个柱状图（每日比赛数、按联赛统计、handicap 分布）和两个赔率分布表已移除。

### 3.7 手动补录 Gemini 预测（兜底）

当自动预测失败或未预测时，可在 `Prediction` 页面使用「手动补录预测」：

- 支持两种方式：
  1. 结构化字段直接填写
  2. 粘贴 `raw_gemini_text` 后点击「解析原文」自动回填
- 保存后与自动预测共用同一 `data/predictions/gemini_predictions.csv` 数据源
- 新增记录字段：
  - `prediction_source`：`auto_gemini` / `manual_gemini` / `manual_user`
  - `prediction_status`：`success` / `failed` / `manual_filled` / `pending`
  - `is_manual`：是否手动补录
  - `raw_text`：手动粘贴原文

`Prediction` 页面新增「待补录场次」区域，会自动筛出失败或未预测比赛，方便集中处理。


---

## 4. 安装

```bash
cd sporttery_fetcher
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

---

## 5. 启动前端

```bash
streamlit run app/app.py
```

默认地址：
- `http://localhost:8501`

---

## 6. 前端数据来源规则

- 直接读取：`data/processed/*_matches.csv`
- 默认选择最新日期文件
- 支持手动切换日期文件
- 无文件/空数据均有友好提示

---

## 7. 常见问题

1. **没有数据文件**
   - 可直接在前端点「抓取并加载」
   - 或终端执行 `python -m src.main --date 2026-03-19`

2. **抓取失败**
   - 页面只显示简洁失败提示
   - 详细技术信息查看 `logs/app.log`

3. **Gemini 调用失败**
   - 检查 `GEMINI_API_KEY` 是否已配置
   - 检查 `GEMINI_MODEL` 是否有效
   - 先执行 `pip install -U -r requirements.txt`

4. **Streamlit 启动失败**
   - 确认依赖已安装：`pip install -r requirements.txt`


## 8. 赛果回填说明

- 赛果来源：`https://www.sporttery.cn/jc/zqsgkj/`
- 本地文件：`data/results/match_results.csv`
- 关键字段：
  - `full_time_score`（比赛实际比分）
  - `result_match`（主胜/平/客胜）
  - `result_handicap`（让胜/让平/让负，无法解析时可为空）
- Analytics 会将 Gemini 主推与真实结果对比，输出：`命中/未命中/未开奖`。

- 赛果抓取日志写入 `logs/app.log`，包含：开始抓取、请求 URL、解析条数、写入条数、匹配预测条数。

## 9. ChatGPT 概率预测（新增）

### 9.1 环境变量

在 `.env` 中新增：

```env
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-5.4
```

### 9.2 功能说明

- Prediction 页面新增：
  - `生成 ChatGPT 预测`（单场）
  - `一键生成当日全部 ChatGPT 预测`（批量）
- ChatGPT 采用独立提示词模板（与 Gemini 分离）。
- 预测结果写入独立文件：
  - `data/predictions/chatgpt_predictions.csv`

### 9.3 ChatGPT 结果字段

- `chatgpt_prompt`
- `chatgpt_raw_text`
- `chatgpt_home_win_prob` / `chatgpt_draw_prob` / `chatgpt_away_win_prob`
- `chatgpt_handicap_win_prob` / `chatgpt_handicap_draw_prob` / `chatgpt_handicap_lose_prob`
- `chatgpt_score_1` / `chatgpt_score_2` / `chatgpt_score_3`
- `chatgpt_top_direction`
- `chatgpt_upset_probability_text`
- `chatgpt_summary`
- `chatgpt_model`
- `chatgpt_generated_at`

### 9.4 Analytics 新模块

Analytics 页面新增 `ChatGPT 概率预测分析` 模块，联动顶部筛选（按日/按月/按年 + 联赛），展示：

- 预测总场次
- 概率结果表（主胜/平/客胜、让胜/让平/让负、推荐比分、最大概率方向、爆冷概率）
