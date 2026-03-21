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
- **Match Detail**：单场比赛卡片式详情 + Gemini 预测按钮（显示原始输出 + 结构化结果并落库）。
- **Analytics**：按“日/月/年 + 联赛”统一筛选的分析工作台，包含基础比赛统计与 Gemini 推荐表。

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

进入 `Match Detail` 页：
1. 选择一场比赛
2. 点击 `生成 Gemini 预测`
3. 页面主界面优先展示结构化字段：主推/次推、两个比分、摘要、模型、thinking level、生成时间
4. 原始回复与发送提示词默认收起在折叠面板中

失败处理：
- 未配置 key：显示 `未配置 GEMINI_API_KEY`
- 模型配置/API 错误：显示 `Gemini 请求失败，请检查模型配置或 API key`
- 详细异常写日志，不在页面泄露 secret


### 3.5 Gemini 输出二次整理与持久化

每次在 `Match Detail` 点击「生成 Gemini 预测」后，系统会保留并写入两层结果：

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
  - 仅保留“推荐总场次”
  - 推荐表格按 `match_no` 升序排序
  - 表格字段保留主推/次推、比分、摘要、生成时间

说明：原有三个柱状图（每日比赛数、按联赛统计、handicap 分布）和两个赔率分布表已移除。

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
