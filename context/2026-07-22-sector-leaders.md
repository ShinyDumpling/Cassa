# 板块多段上涨趋势强势股分析方案

## 1. 背景

已经确定一个板块之后，需要从板块成分股中找出相对强势、能够在板块上涨阶段反复领先的股票。

最初思路是：

1. 找出板块的一段上涨趋势；
2. 计算板块内所有股票在相同区间内的涨幅；
3. 取涨幅最大的三只股票；
4. 再寻找多段板块上涨趋势，观察每段趋势中的前三名是否重复出现。

这个思路可以成立。它验证的不是某只股票单次能否大涨，而是：

> 当板块多次进入上涨趋势时，哪些股票能够反复取得靠前排名并持续跑赢板块。

如果相同股票多次进入前三，说明板块可能存在稳定核心股；如果每段趋势的前三都不同，说明板块内部更偏轮动；如果某只股票只在一段趋势突然进入前三、其余趋势长期靠后，更接近偶发爆发。

## 2. 为什么新增独立脚本

本功能新增独立脚本：

```text
D:\股神养成plan\Cassa\sector_leaders.py
```

不写入 `business.py`，原因如下：

1. `business.py` 当前主要承担 report 和 thises 数据构建，继续加入板块趋势识别、全成分股批量行情读取和历史排名，会让文件职责继续膨胀；
2. 板块强势股分析是一个可以独立执行、独立保存结果的完整业务；
3. 独立脚本能够保留简单、明确的 CLI，不影响现有 report、thises 和 screen2；
4. 第一版仍复用 `data.py` 的通达信初始化和行情接口，不复制底层数据接入代码；
5. 后续如果需要接入 pool、增加量价分析或生成 Markdown 报告，可以继续围绕该脚本扩展。

本次不新增数据库表，不修改 `data.py`，不修改 `business.py`，不修改 `screen2.py`。

## 3. 第一版范围

第一版只实现：

```text
板块历史日K
→ 识别最近多段上涨趋势
→ 获取当前板块成分股
→ 读取所有成分股同期前复权收盘价
→ 每段趋势计算个股涨幅和超额涨幅
→ 每段取涨幅前三
→ 汇总前三次数、平均排名和平均超额涨幅
→ 分类为稳定核心、轮动候选和偶发爆发
```

第一版不实现：

- 买点判断；
- 成交量分析；
- 最大回撤；
- 个股启动早晚判断；
- 复杂综合评分；
- 历史板块成分股还原；
- 自动加入 pool；
- LLM 分析；
- Markdown 报告；
- 数据库存储。

## 4. CLI 设计

最简执行方式：

```powershell
python sector_leaders.py --sector 证券
```

也支持板块代码：

```powershell
python sector_leaders.py --sector 880675.SH
```

完整参数：

```powershell
python sector_leaders.py `
    --sector 880675.SH `
    --history-count 500 `
    --trend-count 5 `
    --top-count 3 `
    --min-trend-days 5 `
    --min-trend-return 5 `
    --pullback-pct 3 `
    --save
```

参数说明：

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `--sector` | 必填 | 板块代码或板块名称 |
| `--history-count` | 500 | 获取最近多少根日 K |
| `--trend-count` | 5 | 最多分析最近多少段上涨趋势 |
| `--top-count` | 3 | 每段趋势选出涨幅前几名 |
| `--min-trend-days` | 5 | 一段上涨趋势至少持续多少个交易日 |
| `--min-trend-return` | 5.0 | 板块从阶段低点至少上涨多少百分比才进入趋势 |
| `--pullback-pct` | 3.0 | 板块从阶段高点回撤多少百分比视为趋势结束 |
| `--save` | 关闭 | 保存完整 JSON 结果 |
| `--debug` | 关闭 | 在控制台追加打印完整 JSON |

## 5. 数据来源

### 5.1 板块解析

复用：

```python
data.get_sector_list(list_type=1)
```

支持用板块完整代码、纯代码或板块名称匹配。

### 5.2 当前成分股

复用：

```python
data.get_stock_list_in_sector(
    block_code=sector_code,
    block_type=0,
    list_type=1,
)
```

第一版使用当前成分股回看历史趋势，因此存在“当前成分股偏差”。结果中必须明确写入该限制，不能把它描述成严格还原的历史板块成分。

### 5.3 板块和股票日 K

统一复用：

```python
data.get_market_data(
    stock_list=codes,
    period="1d",
    count=history_count,
    field_list=["Close"],
    fill_data=True,
)
```

`data.get_market_data()` 当前已经设置 `dividend_type="front"`，股票价格使用前复权口径。

本功能直接读取板块和成分股行情，不依赖本地 `daily_kline` 是否已经更新，也不会调用 `upsert_daily_kline_rows()`，因此不会写入数据库。

## 6. 上涨趋势定义

“连续上涨趋势”表示从一个阶段低点持续上涨到阶段高点，不要求每天都收阳。

第一版使用状态机识别：

1. 持续寻找阶段最低收盘价；
2. 从阶段低点开始，板块累计涨幅达到 `min_trend_return`，并且持续天数达到 `min_trend_days`，认为上涨趋势成立；
3. 趋势成立后持续更新最高收盘价；
4. 从最高收盘价回撤达到 `pullback_pct`，认为趋势结束；
5. 已结束趋势使用“阶段低点日期 → 阶段高点日期”；
6. 扫描到最后一根 K 线仍未达到结束条件时，记录为进行中趋势，结束日期使用最新 K 线日期。

趋势涨幅：

```python
return_pct = (end_close / start_close - 1) * 100
```

## 7. 个股同期排名

每段趋势中，所有股票必须使用与板块完全相同的起止日期。

个股涨幅：

```python
stock_return_pct = (stock_end_close / stock_start_close - 1) * 100
```

个股超额涨幅：

```python
excess_return_pct = stock_return_pct - sector_return_pct
```

停牌股票使用最后一个有效收盘价向后填充，但禁止向前填充：

```python
aligned_series = stock_series.reindex(
    stock_series.index.union(sector_dates)
).sort_index().ffill().reindex(sector_dates)
```

这样可以满足：

- 区间内停牌时价格保持不变；
- 新股在趋势开始日期之前没有价格时会被排除；
- 不会通过向前填充伪造新股历史价格。

## 8. 多趋势汇总与分类

每只股票汇总：

- 有效参与趋势数；
- 进入前三次数；
- 进入前三比例；
- 最好排名；
- 平均排名；
- 平均排名百分位；
- 平均涨幅；
- 平均超额涨幅。

分类规则保持透明，不使用复杂评分。

### 8.1 稳定核心股

```text
进入前三次数 >= 2
并且进入前三比例 >= 40%
并且平均超额涨幅 > 0
```

### 8.2 轮动候选股

```text
进入前三次数 = 1
并且平均排名百分位 >= 50%
```

### 8.3 偶发爆发股

```text
进入前三次数 = 1
并且平均排名百分位 < 50%
```

没有进入过前三的股票继续保留在 `all_stocks` 中，但不进入以上三类。

## 9. 完整代码

新增文件：

```text
D:\股神养成plan\Cassa\sector_leaders.py
```

完整代码如下：

```python
"""分析板块多段上涨趋势中的强势股票。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from rich.console import Console
from rich.table import Table

import data


PROJECT_ROOT = Path(__file__).resolve().parent
RESULT_DIR = PROJECT_ROOT / "result" / "sector-leaders"
DEFAULT_HISTORY_COUNT = 500
DEFAULT_TREND_COUNT = 5
DEFAULT_TOP_COUNT = 3
DEFAULT_MIN_TREND_DAYS = 5
DEFAULT_MIN_TREND_RETURN_PCT = 5.0
DEFAULT_PULLBACK_PCT = 3.0
DEFAULT_BATCH_SIZE = 500

STOCK_SH_PREFIXES = ("5", "6", "9")
STOCK_SZ_PREFIXES = ("0", "1", "2", "3")
STOCK_BJ_PREFIXES = ("920", "4", "8")

console = Console()


def strip_code_suffix(code):
    """去掉代码市场后缀；输入任意代码，输出纯代码字符串。"""
    return str(code or "").strip().upper().split(".", maxsplit=1)[0]


def normalize_stock_code(code):
    """规整成分股代码；输入通达信或纯数字代码，输出带市场后缀代码。"""
    normalized_code = str(code or "").strip().upper()
    if not normalized_code:
        return ""
    if "." in normalized_code:
        return normalized_code

    pure_code = strip_code_suffix(normalized_code)
    if pure_code.startswith(STOCK_BJ_PREFIXES):
        return f"{pure_code}.BJ"
    if pure_code.startswith(STOCK_SH_PREFIXES):
        return f"{pure_code}.SH"
    if pure_code.startswith(STOCK_SZ_PREFIXES):
        return f"{pure_code}.SZ"
    return ""


def chunk_list(items, chunk_size):
    """把列表按固定大小分批；输入列表和批大小，输出二维列表。"""
    return [
        items[start_index:start_index + chunk_size]
        for start_index in range(0, len(items), chunk_size)
    ]


def calculate_return_pct(start_price, end_price):
    """计算区间涨跌幅；输入起止价格，输出百分比。"""
    if start_price is None or end_price is None or start_price <= 0:
        return None
    return (end_price / start_price - 1) * 100


def round_optional(value, digits=4):
    """安全保留小数；输入数字或空值，输出舍入结果或 None。"""
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)


def resolve_sector_target(sector_input):
    """解析板块输入；输入代码或名称，输出统一板块对象。"""
    normalized_input = str(sector_input or "").strip()
    if not normalized_input:
        raise ValueError("板块代码或名称不能为空。")

    input_key = normalized_input.upper()
    input_pure_code = strip_code_suffix(input_key)
    sector_rows = data.get_sector_list(list_type=1) or []

    for row in sector_rows:
        if not isinstance(row, dict):
            continue
        sector_code = str(row.get("Code", "") or "").strip().upper()
        sector_name = str(row.get("Name", "") or "").strip()
        if not sector_code:
            continue

        candidate_keys = {
            sector_code,
            strip_code_suffix(sector_code),
            sector_name.upper(),
        }
        if input_key in candidate_keys or input_pure_code in candidate_keys:
            return {
                "code": sector_code,
                "name": sector_name,
            }

    raise ValueError(f"未找到板块：{normalized_input}")


def normalize_sector_constituents(raw_rows):
    """整理板块成分股；输入通达信原始列表，输出去重后的代码和名称。"""
    constituent_map = {}
    for row in raw_rows or []:
        if isinstance(row, dict):
            raw_code = row.get("Code", "")
            stock_name = str(row.get("Name", "") or "").strip()
        else:
            raw_code = row
            stock_name = ""

        stock_code = normalize_stock_code(raw_code)
        if not stock_code:
            continue
        constituent_map[stock_code] = {
            "code": stock_code,
            "name": stock_name,
        }

    return [constituent_map[code] for code in sorted(constituent_map)]


def convert_close_frame_to_series_map(close_frame, stock_codes):
    """转换收盘价表；输入 DataFrame 和代码列表，输出 code -> Series。"""
    close_series_map = {}
    if close_frame is None or not isinstance(close_frame, pd.DataFrame):
        return close_series_map

    for stock_code in stock_codes:
        if stock_code not in close_frame.columns:
            continue

        raw_series = pd.to_numeric(
            close_frame[stock_code],
            errors="coerce",
        ).dropna()
        if raw_series.empty:
            continue

        normalized_series = pd.Series(
            raw_series.to_numpy(dtype=float),
            index=[str(value)[:10] for value in raw_series.index],
            dtype=float,
        )
        normalized_series = normalized_series[
            ~normalized_series.index.duplicated(keep="last")
        ]
        normalized_series = normalized_series[
            normalized_series > 0
        ].sort_index()
        if not normalized_series.empty:
            close_series_map[stock_code] = normalized_series

    return close_series_map


def fetch_close_price_map(stock_codes, history_count, batch_size=DEFAULT_BATCH_SIZE):
    """分批读取前复权收盘价；输入代码列表和数量，输出行情字典及缺失代码。"""
    close_series_map = {}
    requested_codes = list(dict.fromkeys(stock_codes))

    for batch_index, stock_batch in enumerate(
        chunk_list(requested_codes, batch_size),
        start=1,
    ):
        console.print(
            f"[数据] 读取日K {batch_index}/"
            f"{len(chunk_list(requested_codes, batch_size))}："
            f"{len(stock_batch)}只"
        )
        market_data = data.get_market_data(
            stock_list=stock_batch,
            period="1d",
            count=history_count,
            field_list=["Close"],
            fill_data=True,
        )
        close_series_map.update(
            convert_close_frame_to_series_map(
                (market_data or {}).get("Close"),
                stock_batch,
            )
        )

    missing_codes = [
        stock_code
        for stock_code in requested_codes
        if stock_code not in close_series_map
    ]
    return close_series_map, missing_codes


def build_trend_record(
    sector_close_series,
    start_index,
    end_index,
    status,
):
    """构造趋势记录；输入板块序列和起止位置，输出趋势字典。"""
    start_date = sector_close_series.index[start_index]
    end_date = sector_close_series.index[end_index]
    start_close = float(sector_close_series.iloc[start_index])
    end_close = float(sector_close_series.iloc[end_index])
    return {
        "status": status,
        "start_date": start_date,
        "end_date": end_date,
        "trading_days": end_index - start_index + 1,
        "sector_start_close": round(start_close, 4),
        "sector_end_close": round(end_close, 4),
        "sector_return_pct": round(
            calculate_return_pct(start_close, end_close),
            4,
        ),
    }


def detect_sector_uptrends(
    sector_close_series,
    min_trend_days,
    min_trend_return_pct,
    pullback_pct,
):
    """识别板块上涨趋势；输入收盘价和阈值，输出按时间排列的趋势列表。"""
    close_series = sector_close_series.dropna().sort_index()
    close_series = close_series[close_series > 0]
    if len(close_series) < min_trend_days:
        return []

    trends = []
    trough_index = 0
    peak_index = 0
    trend_active = False

    for current_index in range(1, len(close_series)):
        current_close = float(close_series.iloc[current_index])

        if not trend_active:
            trough_close = float(close_series.iloc[trough_index])
            if current_close <= trough_close:
                trough_index = current_index
                peak_index = current_index
                continue

            if current_close > float(close_series.iloc[peak_index]):
                peak_index = current_index

            rise_pct = calculate_return_pct(trough_close, current_close)
            duration = current_index - trough_index + 1
            if duration >= min_trend_days and rise_pct >= min_trend_return_pct:
                trend_active = True
                peak_index = current_index
            continue

        peak_close = float(close_series.iloc[peak_index])
        if current_close >= peak_close:
            peak_index = current_index
            peak_close = current_close

        current_pullback_pct = calculate_return_pct(peak_close, current_close)
        if current_pullback_pct > -pullback_pct:
            continue

        trends.append(
            build_trend_record(
                close_series,
                trough_index,
                peak_index,
                "completed",
            )
        )

        pullback_start_index = peak_index + 1
        if pullback_start_index <= current_index:
            pullback_series = close_series.iloc[
                pullback_start_index:current_index + 1
            ]
            lowest_date = pullback_series.idxmin()
            trough_index = close_series.index.get_loc(lowest_date)
        else:
            trough_index = current_index
        peak_index = trough_index
        trend_active = False

    if trend_active:
        trends.append(
            build_trend_record(
                close_series,
                trough_index,
                len(close_series) - 1,
                "ongoing",
            )
        )

    return trends


def align_stock_close_to_sector_dates(stock_close_series, sector_dates):
    """对齐个股和板块交易日；输入个股序列和板块日期，输出仅向后填充的序列。"""
    combined_index = stock_close_series.index.union(sector_dates)
    return (
        stock_close_series.reindex(combined_index)
        .sort_index()
        .ffill()
        .reindex(sector_dates)
    )


def rank_stocks_in_trend(
    trend,
    sector_close_series,
    stock_close_map,
    stock_name_map,
    top_count,
):
    """计算单段趋势排名；输入趋势和行情，输出完整排名及排除数量。"""
    start_date = trend["start_date"]
    end_date = trend["end_date"]
    sector_window = sector_close_series.loc[start_date:end_date]
    sector_dates = sector_window.index
    sector_return_pct = float(trend["sector_return_pct"])
    ranking_rows = []
    excluded_count = 0

    for stock_code, stock_close_series in stock_close_map.items():
        aligned_series = align_stock_close_to_sector_dates(
            stock_close_series,
            sector_dates,
        )
        if aligned_series.empty:
            excluded_count += 1
            continue

        start_close = aligned_series.iloc[0]
        end_close = aligned_series.iloc[-1]
        if pd.isna(start_close) or pd.isna(end_close):
            excluded_count += 1
            continue
        if float(start_close) <= 0 or float(end_close) <= 0:
            excluded_count += 1
            continue

        stock_return_pct = calculate_return_pct(
            float(start_close),
            float(end_close),
        )
        ranking_rows.append({
            "code": stock_code,
            "name": stock_name_map.get(stock_code, ""),
            "start_close": round(float(start_close), 4),
            "end_close": round(float(end_close), 4),
            "return_pct": round(stock_return_pct, 4),
            "sector_return_pct": round(sector_return_pct, 4),
            "excess_return_pct": round(
                stock_return_pct - sector_return_pct,
                4,
            ),
        })

    ranking_rows.sort(
        key=lambda row: (-row["return_pct"], row["code"])
    )
    valid_stock_count = len(ranking_rows)

    for rank, row in enumerate(ranking_rows, start=1):
        if valid_stock_count <= 1:
            rank_percentile = 1.0
        else:
            rank_percentile = 1 - (rank - 1) / (valid_stock_count - 1)
        row["rank"] = rank
        row["valid_stock_count"] = valid_stock_count
        row["rank_percentile"] = round(rank_percentile, 6)
        row["is_top"] = rank <= top_count

    return {
        "rankings": ranking_rows,
        "top_stocks": ranking_rows[:top_count],
        "valid_stock_count": valid_stock_count,
        "excluded_stock_count": excluded_count,
    }


def aggregate_sector_leader_rankings(trends):
    """汇总多段趋势排名；输入带排名的趋势，输出每只股票统计。"""
    stock_samples = {}
    for trend in trends:
        for ranking_row in trend.get("rankings", []):
            stock_code = ranking_row["code"]
            sample = stock_samples.setdefault(
                stock_code,
                {
                    "code": stock_code,
                    "name": ranking_row.get("name", ""),
                    "ranks": [],
                    "rank_percentiles": [],
                    "returns": [],
                    "excess_returns": [],
                    "top_count": 0,
                },
            )
            sample["ranks"].append(ranking_row["rank"])
            sample["rank_percentiles"].append(
                ranking_row["rank_percentile"]
            )
            sample["returns"].append(ranking_row["return_pct"])
            sample["excess_returns"].append(
                ranking_row["excess_return_pct"]
            )
            if ranking_row["is_top"]:
                sample["top_count"] += 1

    stock_summaries = []
    for sample in stock_samples.values():
        valid_trend_count = len(sample["ranks"])
        top_rate = (
            sample["top_count"] / valid_trend_count
            if valid_trend_count else 0
        )
        stock_summaries.append({
            "code": sample["code"],
            "name": sample["name"],
            "valid_trend_count": valid_trend_count,
            "top_count": sample["top_count"],
            "top_rate": round(top_rate, 6),
            "best_rank": min(sample["ranks"]),
            "average_rank": round(
                sum(sample["ranks"]) / valid_trend_count,
                4,
            ),
            "average_rank_percentile": round(
                sum(sample["rank_percentiles"]) / valid_trend_count,
                6,
            ),
            "average_return_pct": round(
                sum(sample["returns"]) / valid_trend_count,
                4,
            ),
            "average_excess_return_pct": round(
                sum(sample["excess_returns"]) / valid_trend_count,
                4,
            ),
        })

    stock_summaries.sort(
        key=lambda row: (
            -row["top_count"],
            -row["top_rate"],
            row["average_rank"],
            -row["average_excess_return_pct"],
            row["code"],
        )
    )
    return stock_summaries


def classify_sector_leaders(stock_summaries, analyzed_trend_count):
    """分类板块强势股；输入汇总结果，输出三类股票和领导结构。"""
    stable_core = []
    rotation_candidates = []
    occasional_breakouts = []

    for stock_summary in stock_summaries:
        if (
            stock_summary["top_count"] >= 2
            and stock_summary["top_rate"] >= 0.4
            and stock_summary["average_excess_return_pct"] > 0
        ):
            stable_core.append(stock_summary)
        elif (
            stock_summary["top_count"] == 1
            and stock_summary["average_rank_percentile"] >= 0.5
        ):
            rotation_candidates.append(stock_summary)
        elif stock_summary["top_count"] == 1:
            occasional_breakouts.append(stock_summary)

    if analyzed_trend_count < 2:
        leadership_pattern = "insufficient_history"
    elif stable_core:
        leadership_pattern = "stable_core"
    else:
        leadership_pattern = "rotating"

    return {
        "leadership_pattern": leadership_pattern,
        "stable_core": stable_core,
        "rotation_candidates": rotation_candidates,
        "occasional_breakouts": occasional_breakouts,
    }


def build_sector_leaders_result(args):
    """执行完整分析；输入 CLI 参数，输出统一结构化结果。"""
    sector = resolve_sector_target(args.sector)
    console.print(
        f"[板块] {sector['name']} {sector['code']}"
    )

    raw_constituents = data.get_stock_list_in_sector(
        block_code=sector["code"],
        block_type=0,
        list_type=1,
    )
    constituents = normalize_sector_constituents(raw_constituents)
    if not constituents:
        raise RuntimeError(f"板块没有有效成分股：{sector['code']}")

    stock_codes = [row["code"] for row in constituents]
    stock_name_map = {
        row["code"]: row["name"]
        for row in constituents
    }

    sector_close_map, missing_sector_codes = fetch_close_price_map(
        [sector["code"]],
        args.history_count,
    )
    if missing_sector_codes or sector["code"] not in sector_close_map:
        raise RuntimeError(f"未获取到板块历史日K：{sector['code']}")
    sector_close_series = sector_close_map[sector["code"]]

    stock_close_map, missing_stock_codes = fetch_close_price_map(
        stock_codes,
        args.history_count,
    )
    if not stock_close_map:
        raise RuntimeError("未获取到任何板块成分股历史日K。")

    all_trends = detect_sector_uptrends(
        sector_close_series,
        args.min_trend_days,
        args.min_trend_return,
        args.pullback_pct,
    )
    selected_trends = all_trends[-args.trend_count:]
    if not selected_trends:
        raise RuntimeError(
            "未识别出符合条件的板块上涨趋势，请增加 history-count或降低趋势阈值。"
        )

    for trend_index, trend in enumerate(selected_trends, start=1):
        ranking_result = rank_stocks_in_trend(
            trend,
            sector_close_series,
            stock_close_map,
            stock_name_map,
            args.top_count,
        )
        trend["trend_id"] = trend_index
        trend.update(ranking_result)

    stock_summaries = aggregate_sector_leader_rankings(selected_trends)
    classification = classify_sector_leaders(
        stock_summaries,
        len(selected_trends),
    )

    total_top_slots = sum(
        len(trend["top_stocks"])
        for trend in selected_trends
    )
    unique_top_stock_count = len({
        row["code"]
        for trend in selected_trends
        for row in trend["top_stocks"]
    })
    repeat_ratio = (
        1 - unique_top_stock_count / total_top_slots
        if total_top_slots else 0
    )

    warnings = [
        "历史分析使用当前板块成分股，未还原历史成分股变化。"
    ]
    if len(selected_trends) < args.trend_count:
        warnings.append(
            f"请求分析{args.trend_count}段趋势，实际只找到"
            f"{len(selected_trends)}段。"
        )
    if missing_stock_codes:
        warnings.append(
            f"{len(missing_stock_codes)}只成分股缺少历史日K，已排除。"
        )
    if data.is_a_share_intraday():
        warnings.append(
            "当前为盘中数据，进行中趋势及个股排名可能随行情变化。"
        )

    return {
        "task": "sector_leaders",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "market_context": {
            "is_intraday": data.is_a_share_intraday(),
        },
        "sector": {
            "code": sector["code"],
            "name": sector["name"],
            "constituent_count": len(constituents),
            "available_kline_count": len(stock_close_map),
        },
        "config": {
            "history_count": args.history_count,
            "trend_count": args.trend_count,
            "top_count": args.top_count,
            "min_trend_days": args.min_trend_days,
            "min_trend_return_pct": args.min_trend_return,
            "pullback_pct": args.pullback_pct,
        },
        "data_scope": {
            "history_start_date": sector_close_series.index[0],
            "history_end_date": sector_close_series.index[-1],
            "constituent_scope": "current",
            "price_adjustment": "front",
            "writes_database": False,
        },
        "trends": selected_trends,
        "summary": {
            "leadership_pattern": classification["leadership_pattern"],
            "analyzed_trend_count": len(selected_trends),
            "unique_top_stock_count": unique_top_stock_count,
            "top_repeat_ratio": round(repeat_ratio, 6),
            "stable_core": classification["stable_core"],
            "rotation_candidates": classification["rotation_candidates"],
            "occasional_breakouts": classification["occasional_breakouts"],
            "all_stocks": stock_summaries,
        },
        "warnings": warnings,
    }


def format_pct(value):
    """格式化百分比；输入数字，输出带符号百分比文本。"""
    if value is None:
        return "-"
    return f"{float(value):+.2f}%"


def leadership_pattern_label(value):
    """转换领导结构标签；输入内部值，输出中文文本。"""
    labels = {
        "stable_core": "存在稳定核心股",
        "rotating": "板块内部轮动",
        "insufficient_history": "有效趋势不足",
    }
    return labels.get(value, str(value))


def print_stock_summary_table(title, rows):
    """打印股票汇总表；输入标题和汇总行，无返回值。"""
    console.print()
    console.print(f"[bold]{title}[/bold]")
    if not rows:
        console.print("无")
        return

    table = Table(show_lines=True)
    table.add_column("代码", style="cyan", no_wrap=True)
    table.add_column("名称", no_wrap=True)
    table.add_column("前三次数", justify="right")
    table.add_column("前三比例", justify="right")
    table.add_column("平均排名", justify="right")
    table.add_column("平均超额", justify="right")

    for row in rows:
        table.add_row(
            row["code"],
            row["name"],
            str(row["top_count"]),
            f"{row['top_rate'] * 100:.1f}%",
            f"{row['average_rank']:.2f}",
            format_pct(row["average_excess_return_pct"]),
        )
    console.print(table)


def print_sector_leaders_result(result, debug=False):
    """打印分析结果；输入结构化结果和调试开关，无返回值。"""
    sector = result["sector"]
    summary = result["summary"]
    data_scope = result["data_scope"]

    console.print()
    console.print(
        f"[bold]板块强势股分析：{sector['name']} {sector['code']}[/bold]"
    )
    console.print(f"当前成分股：{sector['constituent_count']}只")
    console.print(
        f"历史范围：{data_scope['history_start_date']} ～ "
        f"{data_scope['history_end_date']}"
    )
    console.print(f"识别上涨趋势：{summary['analyzed_trend_count']}段")
    console.print(
        "领导结构："
        f"{leadership_pattern_label(summary['leadership_pattern'])}"
    )

    for trend in result["trends"]:
        console.print()
        status_label = "进行中" if trend["status"] == "ongoing" else "已完成"
        console.print(
            f"[bold]趋势 {trend['trend_id']}："
            f"{trend['start_date']} ～ {trend['end_date']}[/bold]"
        )
        console.print(
            f"板块涨幅：{format_pct(trend['sector_return_pct'])}  "
            f"持续：{trend['trading_days']}日  状态：{status_label}"
        )

        table = Table(show_lines=True)
        table.add_column("排名", justify="right")
        table.add_column("代码", style="cyan", no_wrap=True)
        table.add_column("名称", no_wrap=True)
        table.add_column("个股涨幅", justify="right")
        table.add_column("超额涨幅", justify="right")
        for row in trend["top_stocks"]:
            table.add_row(
                str(row["rank"]),
                row["code"],
                row["name"],
                format_pct(row["return_pct"]),
                format_pct(row["excess_return_pct"]),
            )
        console.print(table)

    print_stock_summary_table(
        "稳定核心股",
        summary["stable_core"],
    )
    print_stock_summary_table(
        "轮动候选股",
        summary["rotation_candidates"],
    )
    print_stock_summary_table(
        "偶发爆发股",
        summary["occasional_breakouts"],
    )

    if result["warnings"]:
        console.print()
        console.print("[bold yellow]提示[/bold yellow]")
        for warning in result["warnings"]:
            console.print(f"- {warning}")

    if debug:
        console.print()
        console.print("[bold]=== DEBUG JSON ===[/bold]")
        print(json.dumps(result, ensure_ascii=False, indent=2))


def sanitize_filename_part(value):
    """清理文件名；输入任意值，输出 Windows 可用文件名片段。"""
    text = str(value or "").strip()
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text)
    return text or "unknown"


def save_sector_leaders_result(result):
    """保存完整结果；输入结果字典，输出实际 JSON 路径。"""
    timestamp = datetime.now()
    date_dir = RESULT_DIR / timestamp.strftime("%Y-%m-%d")
    date_dir.mkdir(parents=True, exist_ok=True)

    sector = result["sector"]
    base_name = (
        f"sector-leaders-"
        f"{sanitize_filename_part(sector['code'])}-"
        f"{sanitize_filename_part(sector['name'])}-"
        f"{timestamp.strftime('%Y%m%d-%H%M%S')}"
    )
    candidate_paths = [date_dir / f"{base_name}.json"]
    candidate_paths.extend(
        date_dir / f"{base_name}-{index}.json"
        for index in range(2, 1000)
    )

    for output_path in candidate_paths:
        try:
            with output_path.open("x", encoding="utf-8", newline="\n") as file:
                json.dump(result, file, ensure_ascii=False, indent=2)
                file.write("\n")
            return output_path
        except FileExistsError:
            continue

    raise FileExistsError("无法生成不重复的板块强势股结果文件名。")


def validate_args(args):
    """校验 CLI 参数；输入解析结果，参数非法时抛出异常。"""
    if args.history_count < 30:
        raise ValueError("history-count 不能小于30。")
    if args.trend_count < 1:
        raise ValueError("trend-count 不能小于1。")
    if args.top_count < 1:
        raise ValueError("top-count 不能小于1。")
    if args.min_trend_days < 2:
        raise ValueError("min-trend-days 不能小于2。")
    if args.min_trend_return <= 0:
        raise ValueError("min-trend-return 必须大于0。")
    if args.pullback_pct <= 0:
        raise ValueError("pullback-pct 必须大于0。")


def build_parser():
    """构建 CLI 解析器；无输入，输出 ArgumentParser。"""
    parser = argparse.ArgumentParser(
        description="分析板块多段上涨趋势中的强势股票。"
    )
    parser.add_argument(
        "--sector",
        required=True,
        help="板块代码或名称，例如 880675.SH、证券",
    )
    parser.add_argument(
        "--history-count",
        type=int,
        default=DEFAULT_HISTORY_COUNT,
        help="读取最近多少根日K，默认500",
    )
    parser.add_argument(
        "--trend-count",
        type=int,
        default=DEFAULT_TREND_COUNT,
        help="分析最近多少段上涨趋势，默认5",
    )
    parser.add_argument(
        "--top-count",
        type=int,
        default=DEFAULT_TOP_COUNT,
        help="每段趋势取涨幅前几名，默认3",
    )
    parser.add_argument(
        "--min-trend-days",
        type=int,
        default=DEFAULT_MIN_TREND_DAYS,
        help="趋势至少持续多少个交易日，默认5",
    )
    parser.add_argument(
        "--min-trend-return",
        type=float,
        default=DEFAULT_MIN_TREND_RETURN_PCT,
        help="板块累计上涨多少才进入趋势，默认5%%",
    )
    parser.add_argument(
        "--pullback-pct",
        type=float,
        default=DEFAULT_PULLBACK_PCT,
        help="从高点回撤多少视为趋势结束，默认3%%",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="保存完整JSON结果",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="追加打印完整JSON",
    )
    return parser


def main():
    """执行脚本主流程；无输入，返回进程退出码。"""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = build_parser()
    args = parser.parse_args()

    try:
        validate_args(args)
        data.initialize(Path(__file__))
        result = build_sector_leaders_result(args)
        print_sector_leaders_result(result, debug=args.debug)
        if args.save:
            output_path = save_sector_leaders_result(result)
            console.print(f"[保存] {output_path}")
        return 0
    except Exception as exc:
        console.print(f"[bold red]执行失败：{exc}[/bold red]")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

## 10. 输出结构

保存结果的顶层结构为：

```json
{
  "task": "sector_leaders",
  "generated_at": "2026-07-22 16:30:00",
  "market_context": {
    "is_intraday": false
  },
  "sector": {
    "code": "880675.SH",
    "name": "证券",
    "constituent_count": 49,
    "available_kline_count": 47
  },
  "config": {},
  "data_scope": {
    "history_start_date": "2024-07-15",
    "history_end_date": "2026-07-22",
    "constituent_scope": "current",
    "price_adjustment": "front",
    "writes_database": false
  },
  "trends": [],
  "summary": {
    "leadership_pattern": "stable_core",
    "analyzed_trend_count": 5,
    "unique_top_stock_count": 8,
    "top_repeat_ratio": 0.466667,
    "stable_core": [],
    "rotation_candidates": [],
    "occasional_breakouts": [],
    "all_stocks": []
  },
  "warnings": []
}
```

每个趋势同时保留：

- 趋势起止日期；
- 趋势状态；
- 板块涨幅；
- 有效股票数；
- 排除股票数；
- 前三股票；
- 所有股票完整排名。

## 11. 保存位置

加 `--save` 后保存到：

```text
D:\股神养成plan\Cassa\result\sector-leaders\YYYY-MM-DD\
```

文件名示例：

```text
sector-leaders-880675.SH-证券-20260722-163000.json
```

使用独占创建和时间戳命名，不覆盖旧结果。

## 12. 控制台输出层级

默认控制台依次打印：

1. 板块名称、代码和成分股数量；
2. 历史范围和识别出的趋势数量；
3. 每段趋势的日期、板块涨幅和前三股票；
4. 稳定核心股；
5. 轮动候选股；
6. 偶发爆发股；
7. 数据限制和警告。

只有 `--debug` 才打印完整 JSON。

## 13. 验证方案

### 13.1 语法验证

```powershell
python -m py_compile sector_leaders.py
```

### 13.2 帮助验证

```powershell
python sector_leaders.py --help
```

预期可以看到全部参数和默认值。

### 13.3 板块名称验证

```powershell
python sector_leaders.py --sector 证券
```

预期：

- 正确匹配板块代码；
- 能获取当前成分股；
- 能识别至少一段上涨趋势；
- 每段前三按照个股涨幅降序排列。

### 13.4 板块代码验证

```powershell
python sector_leaders.py --sector 880675.SH
```

板块名称输入和代码输入应得到相同板块。

### 13.5 保存验证

```powershell
python sector_leaders.py --sector 证券 --save
```

检查：

- JSON 位于 `result/sector-leaders/日期/`；
- 文件可以正常解析；
- 连续执行不会覆盖旧文件；
- `trends[].rankings` 包含完整个股排名；
- `summary` 中的前三次数与各趋势结果一致。

### 13.6 计算一致性验证

随机选取一段趋势和一只股票，人工核对：

```text
个股涨幅 = 结束收盘价 / 开始收盘价 - 1
板块涨幅 = 板块结束收盘价 / 板块开始收盘价 - 1
超额涨幅 = 个股涨幅 - 板块涨幅
```

并检查：

- 所有股票使用相同起止日期；
- 前三股票确实是 `return_pct` 最大的三只；
- `top_count` 等于该股票在所有趋势中 `is_top=true` 的次数；
- `top_rate = top_count / valid_trend_count`。

### 13.7 不入库验证

执行前后查询：

```powershell
python -c "import sqlite3; c=sqlite3.connect(r'data/cassa.db'); print(c.execute('SELECT COUNT(*), MAX(updated_at) FROM daily_kline').fetchone())"
```

再执行：

```powershell
python sector_leaders.py --sector 证券
```

之后重复数据库查询。预期两次结果一致，本功能不会写入 `daily_kline`。

### 13.8 盘中验证

盘中执行时：

- `market_context.is_intraday` 为 `true`；
- 控制台明确提示当前结果可能随行情变化；
- 不写数据库；
- 进行中趋势可以使用当天临时收盘价，但不能理解成收盘确认结果。

## 14. 已知限制与 TODO

第一版已知限制：

1. 使用当前成分股回看历史，存在幸存者偏差和成分股变化偏差；
2. 趋势划分受 `5%` 上涨和 `3%` 回撤参数影响，不是唯一正确答案；
3. 只比较收盘价涨幅，没有衡量回撤和持有体验；
4. 只进入一次前三的股票可能是事件驱动，不能直接视为长期核心；
5. 盘中运行时最新 K 尚未完成，进行中趋势排名属于临时结果；
6. 该结果只用于识别强势候选，不构成买入信号。

后续 TODO：

- 增加最大回撤和收益回撤比；
- 判断个股是否早于板块启动；
- 加入量价分析；
- 接入 pool；
- 保存每次分析后比较板块核心股变化；
- 如果能够获得历史成分股数据，再还原每段趋势当时的真实成分股。

## 15. 实施顺序

确认方案后按以下顺序实施：

1. 新增 `sector_leaders.py`；
2. 完整复制第 9 节代码；
3. 执行语法检查；
4. 使用一个板块名称完成集成验证；
5. 使用同一板块代码复验解析一致性；
6. 人工抽查一段趋势的涨幅和排名；
7. 验证 `--save` 文件；
8. 验证执行前后数据库没有变化；
9. 不提交代码，等待用户进一步确认。
