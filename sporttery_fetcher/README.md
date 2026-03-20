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
- **Match Detail**：单场比赛卡片式详情。
- **Analytics**：每日趋势、联赛分布、handicap 分布、赔率摘要。

### 2.2 新增交互：前端直接抓取

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

## 3. 安装

```bash
cd sporttery_fetcher
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

---

## 4. 启动前端

```bash
streamlit run app/app.py
```

默认地址：
- `http://localhost:8501`

---

## 5. 前端数据来源规则

- 直接读取：`data/processed/*_matches.csv`
- 默认选择最新日期文件
- 支持手动切换日期文件
- 无文件/空数据均有友好提示

---

## 6. 字段（CSV）

前端默认使用字段：

- issue_date
- match_no
- league
- home_team
- away_team
- kickoff_time
- handicap
- sell_status
- spf_win
- spf_draw
- spf_lose
- rqspf_win
- rqspf_draw
- rqspf_lose
- source_url
- scrape_time
- raw_id

---

## 7. 常见问题

1. **没有数据文件**
   - 可直接在前端点「抓取并加载」
   - 或终端执行 `python -m src.main --date 2026-03-19`

2. **抓取失败**
   - 页面只显示简洁失败提示
   - 详细技术信息查看 `logs/app.log`

3. **Streamlit 启动失败**
   - 确认依赖已安装：`pip install -r requirements.txt`
