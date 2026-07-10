# 板块内选股：sector_pick 四维分类 + 成交量 TOP5

## 主题概述

在 `feat/sector-pick` 分支上实现了 `python cassa.py sector_pick --block-code <code>` 命令。对指定板块的成分股，在板块上涨趋势区间内做四维分类（领先启动 / 滞后补涨 / 涨幅前列 / 高弹性）+ 成交量 TOP5，输出控制台摘要和 JSON 文件。

**分支状态**：基于 `main` 创建，无新 commit，`cassa.py` 新增约 952 行。

---

## 新增代码清单（按文件位置从上到下）

### 1. 常量区（第 165-176 行）

**新增前**：无板块选股相关常量。

**新增后**：
```python
# 板块选股常量
SECTOR_PICK_KLINES_LOOKBACK = 120
SECTOR_PICK_MIN_TREND_DAYS = 3
SECTOR_PICK_TREND_BREAK_DAYS = 2
SECTOR_PICK_VOL_MA_PERIOD = 5
SECTOR_PICK_VOL_EXPAND_RATIO = 1.2
SECTOR_PICK_TOP_GAINER_N = 5
SECTOR_PICK_TOP_GAINER_MIN_HITS = 3
SECTOR_PICK_ELASTICITY_RATIO = 0.6
SECTOR_PICK_VOLUME_TOP_N = 5
SECTOR_PICK_VOL_LOOKBACK = 20   # filter_trends_by_volume 回溯窗口
SECTOR_PICK_VOL_MIN_RATIO = 1.0  # filter_trends_by_volume 放量比率阈值
```

其中 `SECTOR_PICK_VOL_LOOKBACK` 和 `SECTOR_PICK_VOL_MIN_RATIO` 是后续审查中补加的（原 `filter_trends_by_volume` 函数签名中硬编码 `lookback: int = 20, ratio: float = 1.0`，已改为引用常量）。

### 2. 数据结构（第 356-403 行）

#### 2.1 TrendPeriod（第 356-369 行）

**新增前**：不存在。

**新增后**：
```python
@dataclass
class TrendPeriod:
    """一段上涨趋势的起止区间。"""
    start_date: str
    end_date: str
    is_active: bool
    start_index: int
    end_index: int
```

#### 2.2 SectorPickResult（第 372-403 行）

**新增前**：不存在。

**第一版**（调试初期，元数据字段较少）：
```python
@dataclass
class SectorPickResult:
    block_code: str
    block_name: str
    block_trend: TrendPeriod | None = None
    leading_starters: list[str] = field(default_factory=list)
    lagging_catchers: list[str] = field(default_factory=list)
    top_gainers: list[str] = field(default_factory=list)
    high_elasticity: list[str] = field(default_factory=list)
    volume_top5: list[str] = field(default_factory=list)
    stock_names: dict[str, str] = field(default_factory=dict)
```

**最终版**（输出优化后补加 6 个元数据字段）：
```python
@dataclass
class SectorPickResult:
    block_code: str
    block_name: str
    block_trend: TrendPeriod | None = None
    leading_starters: list[str] = field(default_factory=list)
    lagging_catchers: list[str] = field(default_factory=list)
    top_gainers: list[str] = field(default_factory=list)
    high_elasticity: list[str] = field(default_factory=list)
    volume_top5: list[str] = field(default_factory=list)
    stock_names: dict[str, str] = field(default_factory=dict)
    # 以下为打印用的元数据
    stock_trend_dates: dict[str, str] = field(default_factory=dict)  # code -> start_date
    gainer_hits: dict[str, int] = field(default_factory=dict)        # code -> hit count
    elasticity_info: dict[str, float] = field(default_factory=dict)  # code -> hit_ratio
    stock_volumes: dict[str, float] = field(default_factory=dict)    # code -> 最新成交量
    stock_avg_gains: dict[str, float] = field(default_factory=dict)   # code -> 趋势期内日均涨幅%
    stock_total_changes: dict[str, float] = field(default_factory=dict)  # code -> 趋势期内累计涨跌幅%
    sector_total_change: float = 0.0  # 板块趋势期内累计涨跌幅%
```

**变更原因**：用户要求优化结果打印，涨幅前列需要显示命中次数+日均涨幅+累计涨跌幅，高弹性需要显示板块涨跌幅和个股涨跌幅。这些数据无法在打印时临时计算，需要预先存储到结果对象中。

### 3. 板块选股模块分隔注释（第 2391-2393 行）

**新增前**：该位置在 `report_module` 函数之后，紧接着是 `CassaDataCenter` 类的定义区域。

**新增后**：
```python
# ============================================================================
# 第六层补充续：板块选股模块 —— 趋势识别 + 四维分类 + 成交量筛选
# ============================================================================
```

**注意**：最初此处有一个多余空行（`# ===\n\n# ===`），已在后续审查中清理。

### 4. detect_trend_up_conditions（第 2396-2479 行，新增约 84 行）

完全新增。对每一天逐一判断是否满足"趋势涨"条件，返回与 K 线等长的 bool 序列。

**第一版函数签名**（调试输出无门控）：
```python
def detect_trend_up_conditions(
    kline_bars: list[KlineBar],
    macd: MacdResult,
    vol_ma_period: int = SECTOR_PICK_VOL_MA_PERIOD,
    vol_expand_ratio: float = SECTOR_PICK_VOL_EXPAND_RATIO,
) -> list[bool]:
```

**最终版函数签名**（审查后补加 `debug: bool = False` 参数）：
```python
def detect_trend_up_conditions(
    kline_bars: list[KlineBar],
    macd: MacdResult,
    vol_ma_period: int = SECTOR_PICK_VOL_MA_PERIOD,
    vol_expand_ratio: float = SECTOR_PICK_VOL_EXPAND_RATIO,
    debug: bool = False,
) -> list[bool]:
```

四条条件逐日判断（前 20 根 K 线因 MA20 未充分计算统一标记 False）：
- 条件1：均线多头 MA5 > MA10 > MA20
- 条件2：收盘价 >= MA20
- 条件3：MACD 多头 DIF > DEA
- 条件4：量能（已改为后置过滤，此处 `cond4 = True` 直接通过）

**调试输出演变**：

第一版（始终打印，违反 AGENTS.md）：
```python
if all_pass:
    true_count += 1
    if true_count <= 10 or true_count % 20 == 0:
        print(f"  [TRUE #{true_count}] {date_str} ...")
elif i >= len(kline_bars) - 5:
    print(f"  [FALSE] {date_str} ...")

print(f"  趋势涨天数: {true_count}/{len(kline_bars)}")  # 始终打印
```

最终版（受 `--debug` 控制）：
```python
if all_pass:
    true_count += 1
    if debug and (true_count <= 10 or true_count % 20 == 0):
        print(f"  [TRUE #{true_count}] {date_str} ...")
elif debug and i >= len(kline_bars) - 5:
    print(f"  [FALSE] {date_str} ...")

if debug:
    print(f"  趋势涨天数: {true_count}/{len(kline_bars)}")
```

### 5. extract_trend_periods（第 2482-2546 行，新增约 65 行）

完全新增。从逐日 bool 序列中提取连续的上涨趋势区间。

扫描规则：
- 连续 True 段长度 >= `min_trend_days`（默认 3）才记为有效趋势
- 连续 `break_days`（默认 2）个 False 视为趋势结束
- 末尾未闭合的趋势标记 `is_active` 取决于最后一根 K 线是否为 True

### 6. find_latest_trend_period（第 2549-2569 行，新增约 21 行）

完全新增。取最近一个趋势区间 —— 优先返回活跃趋势，否则返回按结束日期最晚的那个。

### 7. filter_trends_by_volume（第 2572-2610 行，新增约 39 行）

完全新增。后置量能过滤：对候选趋势段，计算段内日均成交量与启动前 `lookback` 天（默认 20）的均量比较，段内日均量 > 前期日均量 × `ratio`（默认 1.0）才保留。

**第一版函数签名**（硬编码默认值）：
```python
def filter_trends_by_volume(
    periods: list[TrendPeriod],
    kline_bars: list[KlineBar],
    lookback: int = 20,
    ratio: float = 1.0,
) -> list[TrendPeriod]:
```

**最终版函数签名**（审查后改用常量）：
```python
def filter_trends_by_volume(
    periods: list[TrendPeriod],
    kline_bars: list[KlineBar],
    lookback: int = SECTOR_PICK_VOL_LOOKBACK,
    ratio: float = SECTOR_PICK_VOL_MIN_RATIO,
) -> list[TrendPeriod]:
```

### 8. _compute_daily_changes（第 2613-2632 行，新增约 20 行）

完全新增。计算每根 K 线相对于前一根的涨跌幅百分比，`bar[0]` 为 0.0。

### 9. classify_leading_starters（第 2635-2653 行，新增约 19 行）

完全新增。股票趋势启动日严格早于板块趋势启动日 → 领先启动。

### 10. classify_lagging_catchers（第 2656-2682 行，新增约 27 行）

完全新增。股票趋势启动日严格晚于板块趋势启动日 → 滞后补涨。

### 11. classify_top_gainers（第 2685-2737 行，新增约 53 行）

完全新增。趋势期内每天取涨幅前 `top_n` 名（默认 5），命中次数 >= `min_hits`（默认 3）入选。

**关键修复 — 类型标注**：

第一版（错误）：
```python
def classify_top_gainers(...) -> list[str]:
    ...
    return result, hit_counter  # 实际返回 tuple
```

最终版：
```python
def classify_top_gainers(...) -> tuple[list[str], dict[str, int]]:
    ...
    return result, hit_counter
```

### 12. classify_high_elasticity（第 2740-2807 行，新增约 68 行）

完全新增。板块涨时股票涨幅 >= 板块涨幅 → 命中；板块跌时股票跌幅 >= 板块跌幅（更负）→ 命中。命中率 >= `threshold_ratio`（默认 0.6）即视为高弹性。

**关键修复 — 类型标注**：

第一版（错误）：
```python
def classify_high_elasticity(...) -> list[str]:
    ...
    return result, hit_ratios  # 实际返回 tuple
```

最终版：
```python
def classify_high_elasticity(...) -> tuple[list[str], dict[str, float]]:
    ...
    return result, hit_ratios
```

### 13. filter_volume_top5（第 2810-2833 行，新增约 24 行）

完全新增。按最新交易日成交量（股数）排序，取前 `top_n` 名（默认 5）。

### 14. print_sector_pick_result（第 4197-4303 行，新增约 107 行）

完全新增。控制台五段式摘要输出。

**五段格式**：
```
【一、领先启动】个股名(代码) — 启动 YYYY-MM-DD
【二、滞后补涨】个股名(代码) — 启动 YYYY-MM-DD
【三、涨幅前列】个股名(代码) — 命中 N 次，趋势期内日均涨幅 +X.XX%，累计 +X.XX%
【四、高弹性】板块趋势期内累计涨跌幅: +X.XX%  →  个股名(代码) — 命中率 XX%，个股累计 +X.XX%
【五、成交量 TOP5】个股名(代码) — X.XX亿股
```

末尾有跨集合统计（同时出现在 ≥3 个集合和 2 个集合的股票）。

**输出格式演变**：
- 第一版：涨幅前列只显示命中次数；高弹性只显示命中率
- 用户要求优化后（v11）：涨幅前列加日均涨幅+累计涨跌幅；高弹性加板块涨跌幅+个股累计涨跌幅
- v11 触发 f-string 语法错误：`\n` 被写成了字面换行，用正则修复（v11c）

### 15. write_sector_pick_json（第 4306-4350 行，新增约 45 行）

完全新增。将 `SectorPickResult` 序列化为 JSON 落盘到 `result/` 目录，带时间戳。

**JSON 结构**（最终版，审查后补齐了三个字段）：
```json
{
  "scan_time": "20260708_153000",
  "block_code": "881394",
  "block_name": "证券",
  "block_trend": { "start_date": "...", "end_date": "...", "is_active": true, "total_days": 18 },
  "sector_total_change": 18.52,
  "leading_starters": [{ "code": "...", "name": "...", "start_date": "..." }],
  "lagging_catchers": [{ "code": "...", "name": "...", "start_date": "..." }],
  "top_gainers": [{ "code": "...", "name": "...", "hits": 5, "avg_gain": 2.15, "total_change": 28.41 }],
  "high_elasticity": [{ "code": "...", "name": "...", "hit_ratio": 0.75, "total_change": 32.18 }],
  "volume_top5": [{ "code": "...", "name": "...", "volume": 266000000.0 }],
  "stock_names": { "000001": "平安银行", ... }
}
```

审查前缺失字段：`sector_total_change`, `top_gainers[].avg_gain`, `top_gainers[].total_change`, `high_elasticity[].total_change`。审查后全部补齐。

### 16. run_sector_pick（第 4408-4686 行，新增约 279 行）

完全新增。主流程函数，10 步执行：

1. 从 `get_sector_list(list_type=1)` 查找板块代码
2. 拉取板块日K（`get_market_data`，120 根）→ 构造 `KlineBar` 列表
3. 计算板块 MACD → `align_macd_with_kline` 对齐
4. 板块趋势检测 → 量能过滤 → 取最近趋势
5. 获取成分股列表
6. 批量 MACD（`CassaDataCenter.calculate_macd_batch`）
7. 逐只处理：取日K → 截断 → MACD 对齐 → 趋势检测 → 涨跌幅 → 成交量
8. 板块日涨跌幅
9. 四维分类 + 成交量 TOP5 + 计算趋势期内日均涨幅和累计涨跌幅
10. 控制台打印 + JSON 落盘

### 17. CLI 入口（第 6012-6015 行）

**新增前**：`sector_pick` 子命令不存在。

**新增后**：
```python
sector_pick_parser = module_parsers.add_parser("sector_pick", help="板块内选股：四维分类 + 成交量TOP5")
sector_pick_parser.add_argument("--block-code", required=True, help="板块代码，例如 880491（行业）或 BK0738（概念）")
sector_pick_parser.add_argument("--debug", action="store_true", help="输出每只成分股的趋势检测细节")
sector_pick_parser.set_defaults(handler=run_sector_pick)
```

---

## Bug 修复记录

### Bug 1：板块代码后缀推断错误（开发初期）

**现象**：`infer_market_suffix` 根据首位 8 推断 881xxx 代码后缀为 `.BJ`，导致查不到数据。

**根因**：`infer_market_suffix` 是为个股设计的，8 开头推断为北交所对 881 板块代码是错误的。881xxx 板块代码是上交所概念/行业板块，后缀应为 `.SH`。

**修复**：不用 `infer_market_suffix` 推断后缀，改用 `get_sector_list(list_type=1)` 获取全量板块列表，按纯数字匹配已有后缀。

```python
# 修复前（错误）
suffix = infer_market_suffix(block_code_pure)
matched_code = block_code_pure + suffix

# 修复后
all_sectors = client.get_sector_list(list_type=1)
for item in all_sectors:
    if strip_tdx_suffix(item.get("Code", "")) == block_code_pure:
        matched_code = item["Code"]
        break
```

### Bug 2：MACD DIF/DEA 全部为 0（开发初期）

**现象**：趋势检测条件3（DIF > DEA）始终不满足。

**根因**：`align_macd_with_kline` 要求 K 线日期格式为 `YYYY-MM-DD`，但 `pandas.Timestamp.str()` 输出为 `"2026-07-08 00:00:00"`，MACD 公式引擎返回日期为 `YYYYMMDD`。日期格式不匹配导致对齐失败，DIF/DEA 全部为 0。

**修复**：
```python
# 修复前
date_str = str(date_obj)  # "2026-07-08 00:00:00"

# 修复后
date_str = date_obj.strftime("%Y-%m-%d")  # "2026-07-08"
date_str = date_str[:10]  # 防御性截断
```

### Bug 3：NameError: name 'names' is not defined（开发初期）

**现象**：跨集合统计打印时报 `names` 未定义。

**根因**：变量名写错，应为 `code_set_names.get(code, [])` 而非 `names`。

**修复**：将 `names` 改为 `code_set_names.get(code, [])`。

### Bug 4：条件4（量能）误杀趋势（开发中期）

**现象**：每日硬门槛"当日成交量 > MA(VOL,5) × 1.2"把几乎所有真实趋势筛掉。原因是今日放量 → MA5 升高 → 明日门槛更高，形成恶性循环。

**根因**：放量是"突破信号"而非"趋势特征"，每日硬门槛不适合。

**修复**：条件4在 `detect_trend_up_conditions` 中改为 `cond4 = True`（直接通过），新增 `filter_trends_by_volume` 做后置过滤 —— 对整个趋势段做整体量能比较（段内日均量 vs 启动前 20 日均量）。

### Bug 5：f-string 语法错误（v11 输出优化时引入）

**现象**：`SyntaxError: unterminated string literal` at line 4234。

**根因**：fix_v11.py 的 triple-quoted 字符串中 `print(f"\n【三...】")` 的 `\n` 被写成字面换行（即 `print(f"` + 真实换行 + `【三...】"`），导致 f-string 跨行。

**修复**：用正则 `r'    print\(f"\n(【...】...)"'` 匹配被拆分的 f-string，替换回 `r'    print(f"\\n\1'` 单行形式。共修复 3 处。

### Bug 6：AttributeError: 'KlineBar' object has no attribute 'close'

**现象**：
```
AttributeError: 'KlineBar' object has no attribute 'close'
```

**根因**：新增的日均涨幅/累计涨跌幅计算代码中使用了 `sector_bars[si].close`，但 `KlineBar` dataclass 的字段名是 `close_price`。

**修复**：
```python
# 修复前
sector_start_close = sector_bars[si].close
sector_end_close = sector_bars[ei].close

# 修复后
sector_start_close = sector_bars[si].close_price
sector_end_close = sector_bars[ei].close_price
```

### Bug 7：成交量 TOP5 全部显示 0

**现象**：所有股票的成交量显示为 0（如 `中国长城(000066) — 0股`）。

**根因**：`stock_volumes[code] = truncated[-1].volume` 取最后一根 K 线的成交量。当天（2026-07-08）盘中数据在 SQLite 中 `volume=0.0`（收盘价已更新，但成交量尚未出全）。

**修复**：从最后一根往前遍历，取第一个 `volume > 0` 的 K 线：
```python
# 修复前
stock_volumes[code] = truncated[-1].volume

# 修复后
vol = 0.0
for bar in reversed(truncated):
    if bar.volume > 0:
        vol = bar.volume
        break
stock_volumes[code] = vol
```

### Bug 8：类型标注错误（AGENTS.md 审查发现）

**现象**：`classify_top_gainers` 和 `classify_high_elasticity` 标注为 `-> list[str]`，但实际返回 tuple。

**修复**：
```python
# 修复前
def classify_top_gainers(...) -> list[str]:
    ...
    return result, hit_counter  # 类型不匹配

# 修复后
def classify_top_gainers(...) -> tuple[list[str], dict[str, int]]:
    ...
    return result, hit_counter
```
`classify_high_elasticity` 同理改为 `-> tuple[list[str], dict[str, float]]`。

---

## 修改已有代码的位置（非新增，而是对已有代码的小改）

### 空注释块清理（第 2391 行附近）

**修改前**：
```python
# ============================================================================

# ============================================================================
# 第六层补充续：板块选股模块
```

**修改后**：
```python
# ============================================================================
# 第六层补充续：板块选股模块
```

### filter_trends_by_volume 默认值常量化（第 2575-2576 行）

**修改前**：
```python
    lookback: int = 20,
    ratio: float = 1.0,
```

**修改后**：
```python
    lookback: int = SECTOR_PICK_VOL_LOOKBACK,
    ratio: float = SECTOR_PICK_VOL_MIN_RATIO,
```

---

## 数据源与接口坑点

### 板块代码后缀

- 881xxx 板块代码的后缀是 `.SH`（上交所），**不能**用 `infer_market_suffix` 推断（它会根据首位 8 推断为 `.BJ`）
- 正确做法：用 `get_sector_list(list_type=1)` 获取全量板块列表，按纯数字匹配，用匹配到的带后缀代码

### 板块日K 数据

- `get_market_data` 要求 `StockCode` 类型，不能用 `SectorCode`（即使字段完全相同）
- DataFrame 列名是带后缀的代码（如 `881394.SH`），不是纯数字
- 返回的日期索引是 `pandas.Timestamp`，`str()` 输出为 `"2026-07-08 00:00:00"`，需要 `.strftime("%Y-%m-%d")` 转成 `YYYY-MM-DD`
- 成交量字段 `Volume` 单位是**股数**（不是手）

### MACD 对齐

- `align_macd_with_kline` 要求 K 线日期格式为 `YYYY-MM-DD`，MACD 公式引擎返回日期为 `YYYYMMDD`
- 日期格式不匹配会导致 DIF/DEA 全部为 0（静默失败，不报错）

### 成交量盘中问题

- 当天盘中数据在 SQLite 中 `volume=0`（收盘价已更新，成交量未出全）
- 解决方案：从最新一根往前找，取第一个 `volume > 0` 的 K 线

---

## 测试验证

```bash
# 证券板块
python cassa.py sector_pick --block-code 881394

# 半导体板块（带调试输出）
python cassa.py sector_pick --block-code 881319 --debug
```

典型输出示例：

```
板块: 半导体（881319.SH）
成分股总数: 166
有效成分股: 65（K线不足 1，MACD缺失 0）
其中有上涨趋势的: 64

========================================================================
板块内选股结果：半导体(881319)
板块趋势区间：2026-06-15 ~ 2026-07-08（活跃中，共 18 个交易日）
========================================================================

【一、领先启动】（股票趋势先于板块启动）
  上海贝岭(600171)  — 启动 2026-06-12

【二、滞后补涨】（板块启动后股票才跟上）
  北方华创(002371)  — 启动 2026-06-20

【三、涨幅前列】（趋势期内进入日涨幅前5 >= 3 次）
  中芯国际(688981)  — 命中 5 次，趋势期内日均涨幅 +2.15%，累计 +28.41%

【四、高弹性】（板块涨时涨更多，板块跌时跌更狠，命中率 >= 60%）
  板块趋势期内累计涨跌幅: +18.52%
  韦尔股份(603501)  — 命中率 75%，个股累计 +32.18%

【五、成交量 TOP5】（最新交易日成交量排序）
  中国长城(000066)  — 2.66亿股

========================================================================
跨集合统计：
  同时出现在 >= 3 个集合：
    中芯国际(688981)  (领先启动, 涨幅前列, 高弹性)
========================================================================

结果已保存到: result/sector_pick_881319_20260708_153000.json
```

---

## 与已有模块的复用关系

- `CassaDataCenter`：`get_daily_klines`、`calculate_macd_batch`、`get_stock_name`
- `align_macd_with_kline`、`calculate_sma`、`strip_tdx_suffix`、`to_tdx_stock_code`
- `get_sector_list(list_type=1)` 对齐 `collect_sector_heat_snapshot` 的写法
- 与 `screener` 模块（`feat/screener-v1`）和 T034（选股与板块联动）是上下游关系

---

## 关键决策与反思

1. **量能从日门槛改为后置过滤**：放量是"突破信号"而非"趋势特征"，用每日硬门槛会把几乎所有真实趋势筛掉。改为趋势段整体比较后，趋势检测更贴合实际。
2. **板块代码不推断后缀**：`infer_market_suffix` 是为个股设计的，8 开头推断为 BJ 对 881 板块是错的。直接用 `get_sector_list` 匹配更可靠。
3. **盘中 volume=0**：当天数据未出全时回退到前一天，避免成交量排名全部显示 0。
4. **`cond4 = True` 语义**：条件4已彻底改为后置过滤，函数内 `cond4 = True` 是明确的"跳过"，注释已说明了原因。
5. **调试输出统一收编 `--debug`**：原始终打印所有趋势检测细节，违反 AGENTS.md 规范。已改为 `debug` 参数控制，默认静默。

---

## TODO / 未做内容

- [ ] 板块内选股与 `screener` 选股结果的联动（T034）
- [ ] 支持同时传入多个板块代码批量运行
- [ ] 历史日期模式（类似 T029 的 `as_of_date`）
- [ ] 趋势检测条件4（量能放量）是否需要恢复为可选（目前彻底改为后置过滤）
- [ ] 跨板块结果汇总与对比

## 来源会话

- 当前会话（2026-07-08，task-381）
