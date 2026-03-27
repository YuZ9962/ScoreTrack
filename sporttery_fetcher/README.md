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

## 10. 本次增强（ChatGPT 主推/次推 + 手动删除 + 推荐页）

### 10.1 ChatGPT 主推/次推

- ChatGPT 结构化字段新增：
  - `chatgpt_match_main_pick` / `chatgpt_match_secondary_pick`
  - `chatgpt_handicap_main_pick` / `chatgpt_handicap_secondary_pick`
- parser 优先从固定尾部提取：
  - 胜平负主推/次推
  - 让球主推/次推
  - 比分1/2/3
  - 爆冷方向定义/爆冷概率数值
- 提取失败时回退旧 JSON 兼容逻辑。

### 10.2 Analytics ChatGPT 模块增强

- 新增统计概览：
  - 推荐总场次
  - 已结束场次
  - 胜平负预测命中率
  - 让胜平负预测命中率
- 表格列对齐 Gemini 风格并新增“概率”列。
- 新增两个饼状图：
  - 胜平负概率分布
  - 让胜平负概率分布
- 命中结果图标化：
  - 命中 ✅
  - 未命中 ❌
  - 未开奖 ⏳

### 10.3 手动删除比赛场次

在 Prediction 页面新增“手动删除比赛场次”区域：

- 支持多选比赛后删除
- 删除当前日期 processed CSV 中对应比赛
- 同步删除 Gemini / ChatGPT 预测记录
- 支持删除确认，避免误删

### 10.4 新页面：推荐

新增 `app/pages/recommendation.py`：

- 日期/联赛筛选
- Gemini / ChatGPT 结果预览
- 推荐方案占位区（单关/串关/稳健/激进）

## 11. 推荐中心（多策略可切换）

`Recommendation` 页面已升级为 **Strategy Recommendation Hub**，支持“策略注册 + 策略切换 + 每场推荐输出”。

### 11.1 当前策略

当前已上线策略：

- `structure_edge_v1`
  - 中文名：比赛结构优势模型 V1
  - 英文名：Structure Edge V1
  - 版本：v1
  - 状态：active（默认）

并预留策略位：

- `market_trap_v1`（beta）
- `counter_attack_v1`（beta）
- `cup_rotation_v1`（disabled）
- `hot_cold_divergence_v1`（beta）

### 11.2 代码结构

- `app/strategies/registry.py`
  - 策略注册中心（列出全部策略、获取默认策略、按 ID 获取）
- `app/strategies/configs/structure_edge_v1.py`
  - Structure Edge V1 元信息与业务定义
- `app/services/recommendation_engine.py`
  - 推荐引擎（第一版规则 + 统一输出结构）
- `app/pages/recommendation.py`
  - 推荐中心主页面（筛选、策略选择、策略说明、推荐卡片）

### 11.3 统一推荐输出字段

每场比赛输出字段至少包含：

- `strategy_id`
- `match_id`
- `fit_score`
- `confidence_score`
- `risk_level`
- `recommendation_type`
- `recommendation_label`
- `primary_pick`
- `secondary_pick`
- `rationale_summary`
- `rationale_points`
- `warning_tags`
- `should_skip`
- `detailed_analysis`

### 11.4 Structure Edge V1（MVP）规则说明

第一版基于现有字段 + 简单规则生成可用推荐结果：

1. 主胜赔率较低且主队让球（负值） -> 偏“强势主导结构”
2. 胜负赔率接近 -> 偏“平局拉扯结构”
3. 深盘但赔率不匹配 -> 增加风险
4. Gemini/ChatGPT 主方向一致 -> 提升置信度
5. Gemini/ChatGPT 主方向分歧 -> 增加风险标签

该版本重点是搭建“可扩展策略框架”，后续可替换为更复杂算法或模型推理。

### 11.5 Structure Edge V1 正式业务规则（接入版）

- 核心定位：比赛结构优势模型（非纯赔率模型），聚焦 `胜胜 / 平胜 / 平平`。
- 关键规则：
  1. `spf_win < 1.85` 且主队让球（负值）时，提高 fit/confidence，优先 `胜胜`，次选 `平胜`。
  2. 主胜赔率偏低但平局风险明显时，倾向 `平胜/平平`，并标记“半场拉扯下半场兑现”。
  3. 深盘但赔率不匹配时，打上 `盘口分歧`、`强队热度风险` 标签并下调评分。
  4. Gemini/ChatGPT 方向一致则提高置信度，分歧则降置信度并提示风险。
  5. 命中回避条件（双防低进球、密集赛程强队客场、杯赛/尺度波动）时降低 fit；双防低进球场次可直接 `should_skip=true`。

- 输出结构（统一）：
  - `strategy_id, match_id, fit_score, confidence_score, risk_level`
  - `recommendation_type, recommendation_label, primary_pick, secondary_pick`
  - `rationale_summary, rationale_points, warning_tags, should_skip, detailed_analysis`

## 12. 本次修复（推荐页交互 + ChatGPT 主次推 + 单场概率饼图）

### 12.1 推荐页策略选择
- 策略选择已改为**可搜索下拉菜单**（`st.selectbox`）。
- 策略说明区改为 `expander`，默认收起。

### 12.2 ChatGPT 主推 / 次推
- ChatGPT 提示词固定尾部新增：
  - 胜平负主推/次推
  - 让球主推/次推
  - 比分1/2/3
  - 最大概率方向
  - 爆冷方向定义/概率
- parser 优先按固定尾部提取，兼容 `无/null/空` 为“无”。
- 持久化字段继续写入：
  - `chatgpt_match_main_pick`
  - `chatgpt_match_secondary_pick`
  - `chatgpt_handicap_main_pick`
  - `chatgpt_handicap_secondary_pick`

### 12.3 Analytics 单场概率饼图
- ChatGPT 模块新增单场比赛选择器。
- 两个饼图由“全场汇总”改为“当前选中单场”概率分布。
- 保持主/平/客语义颜色统一，并在扇区显示概率且突出最大值。
- 修复 `胜平负` / `让胜平负` 列出现 `nan/nan` 的问题（空值归一处理）。

## 13. 公众号文案页（【金条玩足球】）

新增页面：`app/pages/wechat_article.py`

### 13.1 能力
- 按日期选择比赛，支持 1~3 场多选（超过 3 场会拦截提示）。
- 自动读取当日对应场次 Gemini 分析作为文案素材。
- 若缺少 Gemini 分析，支持手动补录摘要，不会报错崩溃。
- 一键生成公众号赛前文案，逐篇展示并支持编辑与导出（Markdown/TXT）。

### 13.2 生成结构
文案固定按以下结构输出：
1. 标题
2. 开场白
3. 基本面分析（主队/客队）
4. 比赛走势（三段，首句加粗）
5. 赛果预测（推荐 + 两个比分）
6. 收尾自然语言

### 13.3 数据来源与保存
- 输入：比赛基础字段 + Gemini 分析字段（`gemini_raw_text` 优先）。
- 保存：
  - `data/articles/wechat_articles.csv`
  - `data/articles/YYYY-MM-DD_主队_vs_客队.md`

主要新增文件：
- `app/utils/wechat_prompt_builder.py`
- `app/services/wechat_writer.py`
- `app/services/article_store.py`
- `app/pages/wechat_article.py`

## 14. 微信公众号草稿上传（MVP）

新增服务：`app/services/wechat_api.py`

### 14.1 能力
- 通过 `WECHAT_APP_ID` + `WECHAT_APP_SECRET` 动态获取 `access_token`
- 本地缓存 token（临近过期自动刷新）
- 创建公众号草稿（draft/add）
- 预留发布接口（未启用）

### 14.2 公众号页面联动
在 `app/pages/wechat_article.py` 中：
- 每篇文章支持“上传到公众号草稿”
- 支持“批量上传今天生成的全部文章”
- 回显上传状态：
  - `未上传`
  - `已上传草稿`
  - `上传失败`
- 回写字段：
  - `wechat_upload_status`
  - `wechat_draft_id`
  - `wechat_uploaded_at`
  - `wechat_error_message`

### 14.3 环境变量
请在 `.env` 配置：

```env
WECHAT_APP_ID=your_wechat_app_id_here
WECHAT_APP_SECRET=your_wechat_app_secret_here
WECHAT_AUTHOR=金条玩足球
WECHAT_DEFAULT_DIGEST=
WECHAT_ENABLE_DRAFT_UPLOAD=true
```

> 注意：不要在日志或代码中打印真实 `app_secret` 与 `access_token`。

## 15. 历史补录页面（新增）

新增页面：`app/pages/history_entry.py`（左侧导航：历史补录）。

### 15.1 可补录内容

1. 比赛基础信息（写入统一比赛数据源）
   - 保存到：`data/manual/history_matches.csv`
   - 关键字段：`issue_date, match_no, home_team, away_team`（可选 `raw_id`）
2. Gemini 预测结果
   - 保存到：`data/predictions/gemini_predictions.csv`
3. 比赛真实结果（可后补）
   - 保存到：`data/results/match_results.csv`

所有补录数据默认带来源标记：`data_source=manual`。

### 15.2 覆盖更新规则（避免重复追加）

对同一场比赛执行 Upsert（覆盖更新），键为：

- `issue_date + match_no + home_team + away_team`
- 若提供 `raw_id`，也会参与匹配

当检测到已有场次时，页面提示：`该场次已存在，将执行覆盖更新`。

### 15.3 Analytics 联动

- Analytics 的比赛数据读取：`data/processed/*_matches.csv` + `data/manual/history_matches.csv`
- Gemini 预测读取：`data/predictions/gemini_predictions.csv`
- 赛果读取：`data/results/match_results.csv`

因此手动补录后可直接进入 Gemini 命中率统计：
- 已结束场次数
- 胜平负预测命中率（主推/次推命中均算命中）
- 让胜平负预测命中率（主推/次推命中均算命中）

## 16. Analytics 与历史补录职责边界（本次调整）

### 16.1 Analytics 页面职责（恢复）
- 保留原有分析/展示能力：
  - 时间与联赛筛选
  - Gemini 推荐分析与命中率统计
  - ChatGPT 概率分析、表格、饼图
  - `更新比赛结果` 按钮（不再承载历史 issue_date 抓取入口）
- Analytics 只做展示与统计，不承担历史补录操作。

### 16.2 History Entry 页面职责（集中）
`app/pages/history_entry.py` 统一承担历史补录能力：
- 手动补录历史比赛基础信息
- 手动补录 Gemini 预测
- 手动补录真实赛果
- 按 issue_date 抓取官方历史赛果（zqsgkj）并预览后写入

### 16.3 按 issue_date 抓取规则
- 官方页面：`https://www.sporttery.cn/jc/zqsgkj/`
- 使用 Playwright：
  1. 填 `#start_date = issue_date`
  2. 填 `#end_date = issue_date + 1 day`
  3. 点击“开始查询”
  4. 滚动到底直到高度稳定
  5. 解析比赛行并按 `周X` 编号前缀过滤
- 输出字段固定：
  `issue_date,match_date,match_no,league,home_team,away_team,handicap,half_score,full_score,spf_win,spf_draw,spf_lose,source_url,scrape_time`

### 16.4 数据写入
- 手动补录比赛基础信息：`data/manual/history_matches.csv`
- 手动补录 Gemini 预测：`data/predictions/gemini_predictions.csv`
- 手动/抓取赛果：`data/results/match_results.csv`
- 来源标记：
  - 手动补录：`data_source=manual`
  - 历史抓取写入：`data_source=history_fetch`

## 17. 赛果存储分层与清洗（新增）

为解决 `match_results.csv` 重复、空字段和异常比分问题，赛果改为三层：

1. 原始赛果表：`data/results/raw_match_results.csv`
2. 标准化赛果表：`data/results/clean_match_results.csv`
3. 错误记录表：`data/results/bad_match_results.csv`

### 17.1 标准化字段
`clean_match_results.csv` 固定字段：
- `issue_date`
- `match_no`
- `home_team`
- `away_team`
- `raw_id`
- `full_time_score`
- `result_match`
- `result_handicap`
- `data_source`
- `updated_at`

### 17.2 唯一键优先级
- `raw_id`
- `match_no + issue_date`
- `match_no + home_team + away_team`

### 17.3 关键清洗规则
- `full_time_score` 必须匹配 `^\d{1,2}-\d{1,2}$`
- 类似 `26-03 / 03-22` 这类疑似日期片段记入 bad，不进入 clean
- `result_match` 仅允许：`主胜 / 平 / 客胜 / 未开奖`
- `result_handicap` 仅允许：`让胜 / 让平 / 让负 / 未开奖`
- `data_source` 仅允许：
  - `auto_result_fetch`
  - `manual_entry`
  - `history_fetch`
  - `repair_script`

### 17.4 清洗入口
新增：`app/services/result_cleaner.py`
- `rebuild_clean_results(base_dir, source_mode)`：将旧 `match_results.csv` 或 raw 数据重建为 clean/bad
- `append_raw_results(records, data_source, base_dir)`：先写 raw 再自动重建 clean/bad

### 17.5 Analytics 读取
`app/services/loader.py` 已改为优先读取 `clean_match_results.csv`，若为空再回退旧 `match_results.csv`。
