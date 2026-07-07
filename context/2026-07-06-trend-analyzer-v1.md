# 个股趋势分析层：第一版

## 主题概述

这份上下文记录的是 Cassa 个股趋势分析模块第一版的目标、设计和实现结论。

核心目标：把 DSA 的个股报告（StockTrendAnalyzer）和个股预期（stock_expectation）合并成一套，先落地纯规则计算的事实采集层，后续再接 LLM 做前瞻判断。

## 设计来源

参考了 DSA 两套系统：

1. **个股报告**（`src/stock_analyzer.py`）：纯规则计算均线/乖离率/量能/支撑压力/MACD/RSI/综合评分，输出买入信号
2. **个股预期**（`stock_expectation_prep.py` + `stock_expectation_prompt_builder.py`）：采集事实 → 拼 prompt → 调 LLM → 输出结构化预期 JSON

Cassa 第一版只做了第一步：纯规则计算 + 接口采集事实，还没接 LLM。

## 当前实现

### 分支

`feat/trend-analyzer`，共 5 个 commit，未合并到 main。

### CLI 入口

```bash
python cassa.py report --codes 000001,600519 [--debug]
```

### 数据流

```
1. 从 SQLite 日K库读 K 线（复用 screener 的 load_daily_kline_from_db）
2. 通达信批量算 MACD（复用 screener 的 calculate_macd_batch + align_macd_with_kline）
3. 纯 Python 算均线/乖离率/量能/支撑压力/RSI
4. 通达信 stock_info / more_info / relation 采集基本信息/基本面/板块
5. 综合评分 + 买入信号
6. 控制台打印
```

### 函数清单

**指标计算（纯函数）**：

| 函数 | 作用 |
|------|------|
| `calculate_sma` | 简单移动平均 |
| `calculate_ema` | 指数移动平均 |
| `calculate_rsi` | RSI（Wilder 口径） |

**分析判断**：

| 函数 | 作用 |
|------|------|
| `judge_trend_status` | 趋势状态（强势多头→强势空头 7 档） |
| `calculate_bias` | 乖离率 |
| `judge_volume_status` | 量能状态（缩量回调/放量上涨等 5 档） |
| `judge_support_resistance` | 支撑压力位（MA5/MA10 支撑 + 近 20 日高点压力） |
| `judge_macd_status` | MACD 状态（零轴上金叉/金叉/死叉等 7 档） |
| `judge_rsi_status` | RSI 状态（超买/强势/中性/弱势/超卖 5 档） |
| `calculate_signal_score` | 综合评分 0-100（趋势30+乖离20+量能15+支撑10+MACD15+RSI10） |
| `judge_buy_signal` | 买入信号（强烈买入→强烈卖出 6 档） |

**采集函数**：

| 函数 | 作用 |
|------|------|
| `extract_today_quote` | 从最后两根 K 线提取当日行情 |
| `collect_stock_info` | 调 stock_info + more_info + relation 采集名称/行业/概念/换手率/PE/PB/主营/资金面 |

**主入口**：

| 函数 | 作用 |
|------|------|
| `analyze_stock_trend` | 串联所有指标计算和判断，返回 TrendAnalysisResult |
| `format_trend_result` | 格式化为控制台文本 |
| `run_report` | CLI handler |

### 数据结构

`TrendAnalysisResult` dataclass，约 40 个字段：

- 基本信息：code / name / industry / concepts
- 趋势：trend_status / ma_alignment / trend_strength
- 均线：ma5 / ma10 / ma20 / ma60 / current_price
- 乖离率：bias_ma5 / bias_ma10 / bias_ma20
- 量能：volume_status / volume_ratio_5d / volume_trend
- 支撑压力：support_ma5 / support_ma10 / resistance_levels / support_levels
- MACD：macd_dif / macd_dea / macd_bar / macd_status / macd_signal
- RSI：rsi_6 / rsi_12 / rsi_24 / rsi_status / rsi_signal
- 信号：buy_signal / signal_score / signal_reasons / risk_factors
- 当日行情：today_open / today_high / today_low / yesterday_close / price_change / price_change_pct / amplitude
- 换手率：turnover_rate
- 基本面：pe_dyna / pe_ttm / pb_mrq / main_business
- 资金面：net_buy_amount / main_net_inflow

### 评分规则（对齐 DSA）

| 维度 | 权重 | 判断标准 |
|------|------|----------|
| 趋势 | 30 | 强势多头30 > 多头26 > 弱势多头18 > 盘整12 > 弱势空头8 > 空头4 > 强势空头0 |
| 乖离率 | 20 | 回踩MA5(+20) > 贴近MA5(+18) > 略高(+14) > 追高(+4)；强势多头放宽阈值×1.5 |
| 量能 | 15 | 缩量回调15 > 放量上涨12 > 正常10 > 缩量上涨6 > 放量下跌0 |
| 支撑 | 10 | MA5支撑+5 / MA10支撑+5 |
| MACD | 15 | 零轴上金叉15 > 金叉12 > 上穿零轴10 > 多头8 > 空头2 > 死叉0 |
| RSI | 10 | 超卖10 > 强势8 > 中性5 > 弱势3 > 超买0 |

买入信号：≥75+多头→强烈买入 / ≥60+多头→买入 / ≥45→持有 / ≥30→观望 / 空头→强烈卖出

### 和 DSA 的区别

| 点 | DSA | Cassa |
|----|-----|-------|
| 依赖 | pandas + numpy | 纯 Python |
| Enum | 5 个 Enum 类 | 字符串常量 |
| MACD | pandas ewm | 通达信公式引擎 |
| 评分 config | get_config() | 常量区 |
| 输入 | pd.DataFrame | list[KlineBar] |
| LLM | 有（报告+预期两步） | 无（第一版纯规则） |

### 接口数据坑点

- `get_relation` 返回字段是 `BlockType` / `BlockName`（首字母大写），类型值是中文"行业"/"概念"
- `FreeLtgb` 单位是万股，和 K 线 volume（股）差 10000 倍，不能自己算换手率
- 换手率直接用 more_info 的 `fHSL` 字段
- `Zjl` 是主买净额（万元），`Zjl_HB` 是主力净流入（万元）
- **snapshot 接口没有日期字段**，追加今日 K 线时用系统日期 `datetime.now()` 判断是否是今天；周末/节假日 snapshot 返回的是上一交易日数据，此时 DB 最后一根已是最新交易日，不会重复追加
- **DB K 线不是实时数据**（每天下午手动更新），`extract_today_quote` 和 `current_price` 等字段必须从实时 snapshot 取，不能从 DB K 线取；均线/RSI/量能等历史指标通过 DB K 线 + `append_today_kline` 追加实时快照后计算

### 数据源方案（2026-07-06 修复）

| 数据 | 来源 | 说明 |
|------|------|------|
| 现价 | snapshot.Now | 实时 |
| 今开/最高/最低/昨收 | snapshot.Open/Max/Min/LastClose | 实时 |
| 涨跌额/涨幅/振幅 | snapshot 计算 | 实时 |
| 换手率 | more_info.fHSL | 实时（一直如此） |
| PE/PB/资金面 | more_info | 实时（一直如此） |
| 名称/行业/概念 | stock_info/relation | 实时（一直如此） |
| MA/RSI/量能/支撑压力 | DB K线 + `append_today_kline` 追加实时快照 | 历史指标用 DB，最新点用实时 |
| MACD | 通达信公式引擎 | 本身实时 |

修复在分支 `fix/report-realtime-snapshot` 完成。

### 验证结果

```bash
python cassa.py report --codes 600030
```

修复前：现价 29.23（DB 中的昨日收盘价）
修复后：现价 28.45（实时快照最新价，实际跌幅 -2.67%）

## TODO

- 筹码分布（获利比例/平均成本/集中度）—— 暂无数据源
- 舆情/新闻/公告 —— 暂无数据源
- 考虑把所有通达信接口的数据都接入（stock_info / more_info / snapshot 等全量字段）
- 接 LLM 做前瞻判断（预期方向/成立信号/失效信号/关键价位/风险）
- JSON 输出模式（`--json` 参数）

## 来源会话

- 当前会话（2026-07-06）
