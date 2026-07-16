# 2026-07-16 screen.py refactor 重构方案

## 第一次修改：heat 重构基础方案

### 1. 本次第一版范围

当前 `screen.py` 有多个旧选股入口，但本次重构第一版只实现 `heat` 策略：

- 生成或读取实时全市场快照。
- 快照落盘到 `Cassa/data/snapshot`。
- 使用快照完成第一轮快速筛选。
- 只为候选股票加载 120 根日 K。
- 构建 `StockRecord`。
- 补齐行业和概念。
- 按统一 JSON 格式输出。
- 默认输出控制台摘要，`--debug` 输出完整 JSON。

以下策略本次暂不修改：

- `scan-breakout`
- `scan-box`
- `scan-breakout-pullback-ma5`

`data.load_breakout_kline()` 也暂不删除，等旧策略全部迁移后再处理。

### 2. 重构原因

旧版每个策略都重复获取股票池、加载 K 线、补数据、分层筛选和组装结果。最耗时的问题是：一开始就为全市场股票加载 120 根日 K，导致大量最终不会入选的股票也被读取。

第一版改成两阶段：

```text
全市场股票
    ↓
实时快照初筛
    ↓
候选股票
    ↓
候选股票 120 根日 K
    ↓
日 K 策略条件
    ↓
统一结果
```

快照不进入 `StockRecord`，只作为独立落盘的中间数据。

### 3. 统一业务流程

```text
1. 判断当前是否盘中。
2. 读取或生成当天全市场快照。
3. 执行固定 ST/退市过滤和 heat 快照条件。
4. 只为剩余股票调用 data.load_daily_kline(count=120)。
5. 构建 StockRecord。
6. 执行 heat 的日 K 条件；第一版 heat 暂无额外日 K 条件。
7. 补齐最终结果需要的行业和概念。
8. 组装统一 JSON。
9. 输出控制台摘要；debug 输出完整 JSON。
```

每一步打印步骤名、输入数量、输出数量、淘汰数量和耗时。

### 4. 实时快照规则

快照文件固定为：

```text
Cassa/data/snapshot/cn_snapshot_YYYY-MM-DD.json
```

当前版本只处理实时/最新行情，不支持历史快照，不支持 `as_of_date`。

盘中时间沿用 `data.is_a_share_intraday()`：

- 上午 09:30-11:30。
- 下午 13:00-15:00。
- 周末视为非盘中。

执行规则：

```text
盘中：每次重新通过通达信生成，并覆盖当天快照。
非盘中：当天文件存在则直接使用；不存在才生成。
```

非交易日生成的文件仍使用当天自然日命名，接口返回的数据是最近一个交易日的数据。

数据源只使用 Cassa 当前的通达信接口和本地数据库，不使用 efinance、AkShare、Tushare 或新浪。

快照字段和来源：

| 字段 | 来源 |
| --- | --- |
| `SECUCODE` | 根据通达信代码生成 |
| `code` | `data.get_stock_list()` |
| `name` | 本地 `stock_basic` 表 |
| `price` | 7 根 K 线的最新收盘价 |
| `change_pct` | 最新收盘价和前一根收盘价计算 |
| `volume_ratio` | `data.get_more_info(code)["fLianB"]` |
| `amount` | 7 根 K 线的最新成交额 |
| `turnover_rate` | `data.get_more_info(code)["fHSL"]` |
| `pe_ratio` | `DynaPE`，缺失时使用 `StaticPE_TTM` |
| `pb_ratio` | `PB_MRQ` |
| `total_mv` | `stock_info.J_zgb * price * 10000` |
| `MAX_TRADE_DATE` | 最新 K 线交易日期 |

`J_zgb` 单位为万股，因此 `total_mv` 按现有快照口径保存为元。`fLianB` 使用通达信官方量比，不用 K 线自行重复计算。

生成快照时使用：

```python
data.load_daily_kline(all_codes, count=7)
```

`data.load_daily_kline()` 已经负责盘中实时 K 线拼接；候选阶段再调用同一函数获取 120 根 K 线。

### 5. 本地股票名称维护

名称维护属于 `data.py update-daily-kline`，不属于选股主流程。新增独立表，不在每根 K 线上重复保存名称：

```sql
CREATE TABLE IF NOT EXISTS stock_basic (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    total_shares REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
)
```

当前 `data.get_stock_list()` 返回纯字符串代码列表，例如 `"000001.SZ"`，不包含名称。因此名称同步必须放在 `update-daily-kline` 数据维护阶段：遍历股票代码调用 `data.get_stock_info(code)`，取得 `Name` 后 upsert `stock_basic`。screen 和快照生成只读取本地表，不逐只调用 `get_stock_info()`。

### 6. 数据结构

```python
@dataclass
class SectorRecord:
    type: str
    name: str
    code: str = ""


@dataclass
class KlineRecord:
    code: str
    trade_date: str
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    amount: float
    volume_ratio: float | None = None


@dataclass
class StockRecord:
    code: str
    name: str
    sectors: list[SectorRecord] = field(default_factory=list)
    kline: list[KlineRecord] = field(default_factory=list)
```

快照字段不加入 `StockRecord`。后续 MA、MACD 等日 K 指标直接作为 `KlineRecord` 字段逐步增加，不设计动态 `indicators` 字典。

### 7. 条件和配置

函数按业务主题组织，名称按职责区分：

```text
calculate_xxx  纯计算
ensure_xxx     读取、计算或复用缓存
filter_xxx     完整条件判断并过滤
```

第一版 heat 的条件全部使用快照字段，因此放在 `snapshot_filters`；`kline_filters` 暂时为空。以后依赖 120 根日 K 的条件才放入 `kline_filters`。

```python
HEAT_CONFIG = {
    "strategy": "heat",
    "title": "资金热度",
    "kline_count": 120,
    "snapshot_filters": [
        {"name": "价格区间", "function": filter_snapshot_price_range,
         "params": {"min_price": 3, "max_price": 220}},
        {"name": "成交额", "function": filter_snapshot_amount,
         "params": {"min_amount": 30000}},
        {"name": "换手率", "function": filter_snapshot_turnover_rate,
         "params": {"min_turnover_rate": 2.0}},
        {"name": "量比", "function": filter_snapshot_volume_ratio,
         "params": {"min_volume_ratio": 1.5}},
        {"name": "涨幅", "function": filter_snapshot_change_pct,
         "params": {"min_change_pct": 1.0}},
    ],
    "kline_filters": [],
}
```

ST / 退市是固定业务过滤，不进入 `HEAT_CONFIG`，也不写入最终 `conditions`。

### 8. `data.py` 必须新增的完整代码

以下代码加入现有 `data.py`。`ensure_database()` 已存在，返回一个打开的 SQLite 连接。

```python
def ensure_stock_basic_table(conn=None):
    """创建或迁移 stock_basic 表，并返回连接及连接所有权。"""
    owns_connection = conn is None
    connection = conn or ensure_database()
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_basic (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            total_shares REAL NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT ''
        )
        """
    )
    columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(stock_basic)").fetchall()
    }
    if "total_shares" not in columns:
        connection.execute(
            "ALTER TABLE stock_basic ADD COLUMN total_shares REAL NOT NULL DEFAULT 0"
        )
    if "updated_at" not in columns:
        connection.execute(
            "ALTER TABLE stock_basic ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''"
        )
    connection.commit()
    return connection, owns_connection


def upsert_stock_basic_rows(stock_rows):
    """批量维护本地股票代码和名称。"""
    if not stock_rows:
        return 0

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn, owns_connection = ensure_stock_basic_table()
    count = 0
    try:
        for row in stock_rows:
            if isinstance(row, dict):
                code = str(row.get("Code", "") or "").strip()
                name = str(row.get("Name", "") or "").strip()
                total_shares = float(row.get("J_zgb", 0) or 0)
            else:
                code = str(row).strip()
                name = ""
                total_shares = 0.0
                try:
                    stock_info = get_stock_info(code, field_list=[])
                    if isinstance(stock_info, dict):
                        name = str(stock_info.get("Name", "") or "").strip()
                        total_shares = float(stock_info.get("J_zgb", 0) or 0)
                except Exception as exc:
                    print(f"[股票基础信息] 获取名称失败: {code}, {exc}")
            if not code:
                continue
            conn.execute(
                """
                INSERT INTO stock_basic(code, name, total_shares, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(code) DO UPDATE SET
                    name = CASE
                        WHEN excluded.name <> '' THEN excluded.name
                    ELSE stock_basic.name
                    END,
                    total_shares = CASE
                        WHEN excluded.total_shares > 0 THEN excluded.total_shares
                        ELSE stock_basic.total_shares
                    END,
                    updated_at = excluded.updated_at
                """,
                (code, name, total_shares, now),
            )
            count += 1
        conn.commit()
    finally:
        if owns_connection:
            conn.close()
    return count


def load_stock_basic_records():
    """读取本地股票基础信息；返回 code/name/total_shares 列表。"""
    conn, owns_connection = ensure_stock_basic_table()
    try:
        rows = conn.execute(
            "SELECT code, name, total_shares FROM stock_basic ORDER BY code"
        ).fetchall()
        return [
            {
                "code": row[0],
                "name": row[1] or "",
                "total_shares": float(row[2] or 0),
            }
            for row in rows
        ]
    finally:
        if owns_connection:
            conn.close()


def get_market_mode_label():
    """返回当前 A 股运行模式标签。"""
    return "盘中" if is_a_share_intraday() else "非盘中"
```

在 `update_daily_kline_after_close()` 获取 `stock_rows = get_stock_list()` 后立即加入：

```python
upsert_stock_basic_rows(stock_rows)
```

这里的逐只 `get_stock_info()` 只发生在日 K 数据维护任务中，不发生在 screen 选股流程中。这样每次选股可以直接读取本地名称，同时保证 ST/退市过滤有可靠的名称数据。

### 9. `screen.py` 第一版完整代码

以下代码是第一版 heat 的完整核心实现。它可以替换旧版 screen 的 heat 主流程；旧策略函数暂时保留在旧代码中，不由本次入口调用。

```python
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import business
import data


DEFAULT_KLINE_COUNT = 120
SNAPSHOT_KLINE_COUNT = 7
SNAPSHOT_DIR = Path(__file__).resolve().parent / "data" / "snapshot"
EXCLUDE_NAME_KEYWORDS = ("ST", "退")
DEFAULT_CONSOLE_CODE_LIMIT = 100


@dataclass
class SectorRecord:
    type: str
    name: str
    code: str = ""


@dataclass
class KlineRecord:
    code: str
    trade_date: str
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    amount: float
    volume_ratio: float | None = None


@dataclass
class StockRecord:
    code: str
    name: str
    sectors: list[SectorRecord] = field(default_factory=list)
    kline: list[KlineRecord] = field(default_factory=list)


@dataclass
class LayerRecord:
    name: str
    input_count: int
    output_count: int
    removed_count: int
    elapsed_seconds: float


def safe_float(value, default=None):
    """安全转换浮点数。"""
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def print_step(layer: LayerRecord):
    """打印一个筛选步骤的数量和耗时。"""
    print(
        f"[{layer.name}] {layer.input_count} -> {layer.output_count}, "
        f"淘汰 {layer.removed_count}, 用时 {layer.elapsed_seconds:.2f}s"
    )


def timed_layer(name: str, before: list[Any], after: list[Any], started: float):
    """构建并打印一条步骤记录。"""
    layer = LayerRecord(
        name=name,
        input_count=len(before),
        output_count=len(after),
        removed_count=len(before) - len(after),
        elapsed_seconds=time.perf_counter() - started,
    )
    print_step(layer)
    return layer


def snapshot_path():
    """返回当天快照路径。"""
    today = datetime.now().strftime("%Y-%m-%d")
    return SNAPSHOT_DIR / f"cn_snapshot_{today}.json"


def to_snapshot_payload(rows: list[dict[str, Any]], source="tdx"):
    """把快照行转换为统一 JSON payload。"""
    columns = [
        "SECUCODE", "code", "name", "open_price", "high_price",
        "low_price", "close_price", "volume", "price", "change_pct",
        "volume_ratio", "amount", "turnover_rate", "pe_ratio",
        "pb_ratio", "total_mv", "MAX_TRADE_DATE",
    ]
    data_rows = [[row.get(column) for column in columns] for row in rows]
    return {
        "version": 1,
        "created_at": datetime.utcnow().isoformat() + "+00:00",
        "metadata": {
            "snapshot_source": source,
            "row_count": len(data_rows),
            "columns": columns,
        },
        "frame": {
            "columns": columns,
            "data": data_rows,
            "index": list(range(len(data_rows))),
        },
    }


def write_snapshot(path: Path, rows: list[dict[str, Any]]):
    """以临时文件加替换方式写入快照，避免中途产生半文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = to_snapshot_payload(rows)
    temp_path = path.with_name(f".{path.name}.{time.time_ns()}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    temp_path.replace(path)


def read_snapshot(path: Path):
    """读取并校验本地快照，返回字典行列表。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != 1:
        raise ValueError(f"不支持的快照版本: {path}")
    frame = payload.get("frame") or {}
    columns = frame.get("columns")
    rows = frame.get("data")
    required_columns = {
        "code", "name", "open_price", "high_price", "low_price",
        "close_price", "volume", "amount", "MAX_TRADE_DATE",
    }
    if not isinstance(columns, list) or not isinstance(rows, list):
        raise ValueError(f"快照结构不合法: {path}")
    missing = required_columns - set(columns)
    if missing:
        raise ValueError(f"旧版快照缺少字段 {sorted(missing)}: {path}")
    if not rows:
        raise ValueError(f"快照为空: {path}")
    return [dict(zip(columns, row)) for row in rows]


def code_to_secucode(code: str):
    """把通达信代码转换为证券代码格式。"""
    pure = str(code).split(".")[0]
    if pure.startswith("6"):
        return pure + ".SH"
    if pure.startswith(("0", "1", "2", "3")):
        return pure + ".SZ"
    if pure.startswith(("4", "8", "9")):
        return pure + ".BJ"
    return str(code)


def build_snapshot_rows(stock_rows, kline_map):
    """结合 7 根 K 线和通达信扩展信息构建实时快照行。"""
    rows = []
    for stock in stock_rows:
        code = str(stock.get("code", "")).strip()
        name = str(stock.get("name", "") or "").strip()
        bars = kline_map.get(code, [])
        latest = bars[-1] if bars else {}
        previous = bars[-2] if len(bars) >= 2 else {}
        price = safe_float(latest.get("close_price"))
        if price is None or price <= 0:
            continue

        previous_close = safe_float(previous.get("close_price"))
        change_pct = None
        if previous_close and previous_close > 0:
            change_pct = round((price / previous_close - 1) * 100, 4)

        more_info = data.get_more_info(code, field_list=[]) or {}
        # stock_basic.total_shares 沿用 J_zgb 原始口径，单位为万股。
        total_shares = safe_float(stock.get("total_shares"), 0.0)
        total_mv = (
            round(total_shares * price * 10000, 2)
            if total_shares and total_shares > 0 else None
        )
        pe_ratio = safe_float(more_info.get("DynaPE"))
        if pe_ratio is None or pe_ratio == 0:
            pe_ratio = safe_float(more_info.get("StaticPE_TTM"))

        rows.append({
            "SECUCODE": code_to_secucode(code),
            "code": code,
            "name": name,
            "open_price": safe_float(latest.get("open_price")),
            "high_price": safe_float(latest.get("high_price")),
            "low_price": safe_float(latest.get("low_price")),
            "close_price": price,
            "volume": safe_float(latest.get("volume")),
            "price": price,
            "change_pct": change_pct,
            "volume_ratio": safe_float(more_info.get("fLianB")),
            "amount": safe_float(latest.get("amount")),
            "turnover_rate": safe_float(more_info.get("fHSL")),
            "pe_ratio": pe_ratio,
            "pb_ratio": safe_float(more_info.get("PB_MRQ")),
            "total_mv": total_mv,
            "MAX_TRADE_DATE": latest.get("trade_date", ""),
        })
    return rows


def generate_market_snapshot(stock_rows):
    """获取全市场 7 根 K 线、通达信基本面字段并覆盖当天快照。"""
    codes = [row["code"] for row in stock_rows if row.get("code")]
    kline_map = data.load_daily_kline(
        stock_list=codes,
        count=SNAPSHOT_KLINE_COUNT,
    )
    rows = build_snapshot_rows(stock_rows, kline_map)
    if not rows:
        raise RuntimeError("未生成任何有效市场快照数据")
    path = snapshot_path()
    write_snapshot(path, rows)
    return rows


def ensure_market_snapshot(stock_rows):
    """盘中覆盖快照，非盘中优先读取当天已有快照。"""
    path = snapshot_path()
    if not data.is_a_share_intraday() and path.is_file():
        try:
            rows = read_snapshot(path)
            print(f"[快照] 非盘中使用本地快照: {path}")
            return rows
        except (OSError, ValueError, TypeError) as exc:
            print(f"[快照] 本地快照不可用，重新生成: {exc}")

    rows = generate_market_snapshot(stock_rows)
    print(f"[快照] 已生成并覆盖: {path}")
    return rows


def filter_snapshot_excluded_names(rows):
    """固定过滤名称包含 ST 或退的股票。"""
    return [
        row for row in rows
        if not any(
            keyword in str(row.get("name", "")).upper()
            for keyword in EXCLUDE_NAME_KEYWORDS
        )
    ]


def filter_snapshot_price_range(rows, min_price, max_price):
    """按快照最新价格过滤。"""
    return [
        row for row in rows
        if min_price <= (safe_float(row.get("price"), -1) or -1) <= max_price
    ]


def filter_snapshot_amount(rows, min_amount):
    """按快照成交额过滤。"""
    return [row for row in rows if (safe_float(row.get("amount"), -1) or -1) >= min_amount]


def filter_snapshot_turnover_rate(rows, min_turnover_rate):
    """按通达信 fHSL 换手率过滤。"""
    return [row for row in rows if (safe_float(row.get("turnover_rate"), -1) or -1) >= min_turnover_rate]


def filter_snapshot_volume_ratio(rows, min_volume_ratio):
    """按通达信 fLianB 量比过滤。"""
    return [row for row in rows if (safe_float(row.get("volume_ratio"), -1) or -1) >= min_volume_ratio]


def filter_snapshot_change_pct(rows, min_change_pct):
    """按快照涨跌幅过滤。"""
    return [row for row in rows if (safe_float(row.get("change_pct"), -1) or -1) >= min_change_pct]


def run_snapshot_filters(rows, filters):
    """执行固定过滤和 heat 快照条件，返回筛选结果及步骤记录。"""
    layers = []
    started = time.perf_counter()
    filtered = filter_snapshot_excluded_names(rows)
    layers.append(timed_layer("快照 ST/退市过滤", rows, filtered, started))

    for item in filters:
        started = time.perf_counter()
        before = filtered
        filtered = item["function"](filtered, **item.get("params", {}))
        layers.append(timed_layer(item["name"], before, filtered, started))
    return filtered, layers


def build_kline_record(row):
    """把 data 返回的 K 线字典转换为 KlineRecord。"""
    return KlineRecord(
        code=row["code"],
        trade_date=str(row["trade_date"]),
        open_price=float(row["open_price"]),
        high_price=float(row["high_price"]),
        low_price=float(row["low_price"]),
        close_price=float(row["close_price"]),
        volume=float(row.get("volume", 0) or 0),
        amount=float(row.get("amount", 0) or 0),
    )


def build_stock_records(snapshot_rows, kline_map):
    """用快照筛选后的股票和 120 根 K 线构建 StockRecord。"""
    records = []
    for row in snapshot_rows:
        code = row["code"]
        records.append(StockRecord(
            code=code,
            name=str(row.get("name", "") or ""),
            kline=[build_kline_record(item) for item in kline_map.get(code, [])],
        ))
    return records


def build_stock_records_from_snapshot(snapshot_rows):
    """只用快照中的最新 K 线构建 heat 结果记录，不加载增强日 K。"""
    kline_map = {}
    for row in snapshot_rows:
        kline_map[row["code"]] = [{
            "code": row["code"],
            "trade_date": row.get("MAX_TRADE_DATE", ""),
            "open_price": row.get("open_price"),
            "high_price": row.get("high_price"),
            "low_price": row.get("low_price"),
            "close_price": row.get("close_price", row.get("price")),
            "volume": row.get("volume"),
            "amount": row.get("amount"),
            "volume_ratio": row.get("volume_ratio"),
        }]
    return build_stock_records(snapshot_rows, kline_map)


def ensure_sectors(records):
    """补齐行业和概念板块，仅保留 industry/concept。"""
    for record in records:
        relations = data.get_relation(record.code) or []
        sectors = []
        for relation in relations:
            mapped_type = business.map_relation_type(relation.get("BlockType"))
            if mapped_type not in {"industry", "concept"}:
                continue
            name = str(relation.get("BlockName", "") or "").strip()
            if not name:
                continue
            sectors.append(SectorRecord(
                type=mapped_type,
                name=name,
                code=str(relation.get("BlockCode", "") or ""),
            ))
        record.sectors = sectors
    return records


def serialize_record(record):
    """把 StockRecord 转换为最终 selected 项。"""
    latest = asdict(record.kline[-1]) if record.kline else None
    return {
        "code": record.code,
        "name": record.name,
        "sectors": [asdict(item) for item in record.sectors],
        "latest_kline": latest,
    }


def build_result(records, layers, started_at):
    """构建 heat 统一 JSON 结果。"""
    return {
        "strategy": "heat",
        "title": "资金热度",
        "run_date": datetime.now().strftime("%Y-%m-%d"),
        "mode": data.get_market_mode_label(),
        "conditions": [
            {"name": item["name"], "params": item.get("params", {})}
            for item in HEAT_CONFIG["snapshot_filters"]
        ],
        "selected": [serialize_record(record) for record in records],
        "layers": [asdict(layer) for layer in layers],
        "summary": {
            "selected_count": len(records),
            "elapsed_seconds": round(time.perf_counter() - started_at, 3),
        },
    }


def print_screen_result(result, debug=False):
    """打印 heat 摘要；debug 时追加完整 JSON。"""
    print("=== 资金热度选股 ===")
    print(f"运行日期: {result['run_date']}")
    print(f"运行模式: {result['mode']}")
    print(f"最终入选: {result['summary']['selected_count']}")
    for item in result["selected"][:DEFAULT_CONSOLE_CODE_LIMIT]:
        latest = item.get("latest_kline") or {}
        print(
            f"{item['code']} {item['name']} "
            f"close={latest.get('close_price')} "
            f"amount={latest.get('amount')}"
        )
    if debug:
        print(json.dumps(result, ensure_ascii=False, indent=2))


def run_heat(debug=False):
    """执行第一版 heat 选股流程。"""
    started_at = time.perf_counter()
    print("开始执行策略: heat")

    step_started = time.perf_counter()
    stock_rows = data.load_stock_basic_records()
    print(f"[股票池] 本地股票基础信息: {len(stock_rows)} 只, 用时 {time.perf_counter() - step_started:.2f}s")

    step_started = time.perf_counter()
    snapshot_rows = ensure_market_snapshot(stock_rows)
    print(f"[快照] 快照数据: {len(snapshot_rows)} 只, 用时 {time.perf_counter() - step_started:.2f}s")

    snapshot_rows, layers = run_snapshot_filters(
        snapshot_rows, HEAT_CONFIG["snapshot_filters"]
    )

    step_started = time.perf_counter()
    records = build_stock_records_from_snapshot(snapshot_rows)
    print(f"[构建结果记录] {len(records)} 只, 用时 {time.perf_counter() - step_started:.2f}s")

    step_started = time.perf_counter()
    records = ensure_sectors(records)
    print(f"[板块补齐] {len(records)} 只, 用时 {time.perf_counter() - step_started:.2f}s")

    result = build_result(records, layers, started_at)
    print_screen_result(result, debug=debug)
    return result


HEAT_CONFIG = {
    "strategy": "heat",
    "title": "资金热度",
    "kline_count": DEFAULT_KLINE_COUNT,
    "snapshot_filters": [
        {"name": "价格区间", "function": filter_snapshot_price_range,
         "params": {"min_price": 3, "max_price": 220}},
        {"name": "成交额", "function": filter_snapshot_amount,
         "params": {"min_amount": 30000}},
        {"name": "换手率", "function": filter_snapshot_turnover_rate,
         "params": {"min_turnover_rate": 2.0}},
        {"name": "量比", "function": filter_snapshot_volume_ratio,
         "params": {"min_volume_ratio": 1.5}},
        {"name": "涨幅", "function": filter_snapshot_change_pct,
         "params": {"min_change_pct": 1.0}},
    ],
    "kline_filters": [],
}


def main():
    """heat CLI 入口；第一版只暴露 heat 和 debug。"""
    parser = argparse.ArgumentParser(description="Cassa heat stock screening")
    parser.add_argument("--debug", action="store_true", help="输出完整 JSON")
    args = parser.parse_args()
    data.initialize(Path(__file__))
    run_heat(debug=args.debug)


if __name__ == "__main__":
    main()
```

### 10. 第一版结果格式

```json
{
  "strategy": "heat",
  "title": "资金热度",
  "run_date": "2026-07-16",
  "mode": "盘中",
  "conditions": [],
  "selected": [],
  "layers": [],
  "summary": {
    "selected_count": 0,
    "elapsed_seconds": 0.0
  }
}
```

`conditions` 只记录 heat 的快照条件，不记录固定 ST/退市过滤。

### 11. 第一版落地顺序

1. 在 `data.py` 增加 `stock_basic` 表、upsert 函数、查询函数和 `get_market_mode_label()`。
2. 在 `update_daily_kline_after_close()` 中调用 `upsert_stock_basic_rows(stock_rows)`。
3. 新建或重构 `screen.py` 的 heat 入口，加入上面的快照读写代码。
4. 用 7 根 K 线生成实时快照，并补充通达信 `more_info` 字段；名称和总股本从本地 `stock_basic` 读取。
5. 跑通快照初筛；第一版 heat 不加载候选股票 120 根日 K。
6. 跑通板块补齐、统一 JSON 和控制台输出。
7. 验证盘中覆盖、非盘中复用、快照损坏重建和 `--debug` 输出。
8. 后续再迁移其他旧策略；全部迁移完成后再删除 `data.load_breakout_kline()`。

本文件描述的是第一版 `heat` 的可执行方案，第一版流程所需的实现均已在上文给出。

## 第二次修改：优化速度

本章节是当前方案的最终执行口径。如果前文代码草案与本章节冲突，以本章节为准。

### 12.1 基础信息维护口径

`data.get_stock_list()` 当前返回纯字符串代码：

```python
["000001.SZ", "000002.SZ", ...]
```

因此 `update_daily_kline_after_close()` 负责维护本地 `stock_basic`：

```sql
CREATE TABLE IF NOT EXISTS stock_basic (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    total_shares REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
)
```

字段口径：

```text
code          通达信股票代码
name          股票名称
total_shares  通达信 J_zgb 原始值，单位为万股
updated_at    最后同步时间
```

由于现有数据库可能已经存在旧版 `stock_basic`，不能只使用
`CREATE TABLE IF NOT EXISTS`。必须先执行迁移：

```python
def migrate_stock_basic_table(conn):
    """创建或迁移 stock_basic，保留现有 code/name 数据。"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_basic (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        )
        """
    )
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(stock_basic)").fetchall()
    }
    if "total_shares" not in columns:
        conn.execute(
            "ALTER TABLE stock_basic ADD COLUMN total_shares REAL NOT NULL DEFAULT 0"
        )
    if "updated_at" not in columns:
        conn.execute(
            "ALTER TABLE stock_basic ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''"
        )
    conn.commit()
```

`upsert_stock_basic_rows()` 和 `load_stock_basic_records()` 每次使用表前都调用
`migrate_stock_basic_table(conn)`。这样已有的 5535 行名称数据会保留，只新增
`total_shares` 列；后续数据维护再逐步填充总股本。

数据维护阶段逐只调用 `get_stock_info()`，但 screen 运行阶段不调用：

```python
def upsert_stock_basic_rows(stock_rows):
    """同步股票名称和总股本到本地 stock_basic。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = ensure_database()
    migrate_stock_basic_table(conn)
    for code in stock_rows:
        code = str(code).strip()
        if not code:
            continue
        name = ""
        total_shares = 0.0
        try:
            stock_info = get_stock_info(code, field_list=[]) or {}
            name = str(stock_info.get("Name", "") or "").strip()
            total_shares = float(stock_info.get("J_zgb", 0) or 0)
        except Exception as exc:
            print(f"[股票基础信息] 获取失败: {code}, {exc}")

        conn.execute(
            """
            INSERT INTO stock_basic(code, name, total_shares, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
                name = CASE
                    WHEN excluded.name <> '' THEN excluded.name
                    ELSE stock_basic.name
                END,
                total_shares = CASE
                    WHEN excluded.total_shares > 0 THEN excluded.total_shares
                    ELSE stock_basic.total_shares
                END,
                updated_at = excluded.updated_at
            """,
            (code, name, total_shares, now),
        )
    conn.commit()
    conn.close()
```

在 `update_daily_kline_after_close()` 中：

```python
stock_rows = get_stock_list()
upsert_stock_basic_rows(stock_rows)
stock_list = extract_stock_codes_from_stock_list(stock_rows)
```

本地读取函数返回：

```python
def load_stock_basic_records():
    """读取本地股票基础信息。"""
    conn = ensure_database()
    migrate_stock_basic_table(conn)
    rows = conn.execute(
        "SELECT code, name, total_shares FROM stock_basic ORDER BY code"
    ).fetchall()
    conn.close()
    return [
        {
            "code": row[0],
            "name": row[1] or "",
            "total_shares": float(row[2] or 0),
        }
        for row in rows
    ]
```

### 12.2 总市值口径

现有 `business.py report` 使用：

```python
total_shares = safe_float(stock_info.get("J_zgb"))
market_cap = total_shares * current_price / 10000
```

其中 `market_cap` 的单位是亿元，用于控制台展示：

```text
总市值 123.4 亿
```

重构后沿用同一口径：

```python
# total_shares：万股
market_cap_yi = total_shares * price / 10000
```

但现有全市场 JSON 快照中的 `total_mv` 按元保存，因此快照字段继续使用元口径：

```python
# total_shares：万股，price：元
total_mv = total_shares * price * 10000
```

两者是同一个总市值的不同单位：

```text
market_cap_yi = total_mv / 100000000
```

第一版 `heat` 不使用总市值作为过滤条件，但快照仍保留 `total_mv`，供后续策略使用。

### 12.3 快照生成阶段不再调用 get_stock_info

快照生成时只读取本地基础数据：

```python
stock_rows = data.load_stock_basic_records()
```

`build_snapshot_rows()` 中禁止出现：

```python
data.get_stock_info(code)
```

总市值改为：

```python
total_shares = safe_float(stock.get("total_shares"), 0.0)
total_mv = (
    round(total_shares * price * 10000, 2)
    if total_shares > 0 and price > 0
    else None
)
```

快照阶段仍需调用 `data.get_more_info(code)`，用于实时获取：

```text
fLianB       volume_ratio
fHSL         turnover_rate
DynaPE       动态市盈率
StaticPE_TTM TTM 市盈率
PB_MRQ       市净率
```

因此第一版快照生成的逐股票接口只剩 `get_more_info()`。

### 12.3.1 快照保存最新 K 线字段

旧快照只有 `price / amount / change_pct` 等摘要字段，无法无损组装
`KlineRecord`。第一版重新生成的快照必须同时保存最新 K 线字段：

```text
open_price
high_price
low_price
close_price
volume
amount
```

新的 `frame.columns` 至少包含：

```python
[
    "SECUCODE", "code", "name",
    "open_price", "high_price", "low_price", "close_price", "volume",
    "price", "change_pct", "volume_ratio", "amount",
    "turnover_rate", "pe_ratio", "pb_ratio", "total_mv",
    "MAX_TRADE_DATE",
]
```

读取本地快照时必须校验这些字段。缺少任意一个必需字段，就视为旧版本快照并重新生成，不能继续复用旧文件：

```python
SNAPSHOT_REQUIRED_COLUMNS = {
    "code", "name", "open_price", "high_price", "low_price",
    "close_price", "volume", "amount", "MAX_TRADE_DATE",
}

missing = SNAPSHOT_REQUIRED_COLUMNS - set(columns)
if missing:
    raise ValueError(f"旧版快照缺少字段: {sorted(missing)}")
```

heat 不加载增强日 K，但仍然可以从快照组装一根完整的最新 K 线：

```python
def build_stock_records_from_snapshot(snapshot_rows):
    """使用快照最新 K 线构建 heat 结果记录。"""
    records = []
    for row in snapshot_rows:
        latest = KlineRecord(
            code=row["code"],
            trade_date=str(row.get("MAX_TRADE_DATE", "")),
            open_price=float(row.get("open_price") or 0),
            high_price=float(row.get("high_price") or 0),
            low_price=float(row.get("low_price") or 0),
            close_price=float(row.get("close_price", row.get("price")) or 0),
            volume=float(row.get("volume") or 0),
            amount=float(row.get("amount") or 0),
            volume_ratio=(
                float(row["volume_ratio"])
                if row.get("volume_ratio") is not None else None
            ),
        )
        records.append(StockRecord(
            code=row["code"],
            name=str(row.get("name", "") or ""),
            kline=[latest],
        ))
    return records
```

### 12.4 heat 不加载 120 根增强日 K

`heat` 的所有条件都来自快照：

```python
HEAT_CONFIG = {
    "strategy": "heat",
    "title": "资金热度",
    "snapshot_filters": [
        {
            "name": "价格区间",
            "function": filter_snapshot_price_range,
            "params": {"min_price": 3, "max_price": 220},
        },
        {
            "name": "成交额",
            "function": filter_snapshot_amount,
            "params": {"min_amount": 30000},
        },
        {
            "name": "换手率",
            "function": filter_snapshot_turnover_rate,
            "params": {"min_turnover_rate": 2.0},
        },
        {
            "name": "量比",
            "function": filter_snapshot_volume_ratio,
            "params": {"min_volume_ratio": 1.5},
        },
        {
            "name": "涨幅",
            "function": filter_snapshot_change_pct,
            "params": {"min_change_pct": 1.0},
        },
    ],
    "kline_filters": [],
}
```

因此 `run_heat()` 的流程是：

```text
1. 读取 stock_basic。
2. 盘中覆盖或非盘中读取全市场快照。
3. 固定过滤 ST/退市。
4. 执行价格、成交额、换手率、量比、涨幅过滤。
5. 不调用 data.load_daily_kline(..., count=120)。
6. 对最终股票补齐板块。
7. 组装结果并输出。
```

快照生成内部仍然使用：

```python
data.load_daily_kline(all_codes, count=7)
```

这 7 根 K 线只用于生成快照的价格、涨幅、成交额和交易日期，不属于候选股票增强日 K 阶段。

由于 heat 不加载增强日 K，`selected` 中的最新行情应直接使用快照字段；不再强制构建带 120 根 K 线的 `StockRecord`。如果统一输出结构需要 `latest_kline`，则由快照行组装一根最新 `KlineRecord`，不代表加载了 120 根历史 K 线。

### 12.5 screen2.py CLI

第一版文件为 `screen2.py`，必须使用子命令，不允许直接执行时默认运行策略：

```bash
python screen2.py heat
python screen2.py heat --debug
```

CLI 代码：

```python
def build_arg_parser():
    """构建 screen2 子命令解析器。"""
    parser = argparse.ArgumentParser(description="Cassa stock screening")
    subparsers = parser.add_subparsers(dest="command", required=True)

    heat_parser = subparsers.add_parser(
        "heat",
        help="执行资金热度选股",
    )
    heat_parser.add_argument(
        "--debug",
        action="store_true",
        help="输出完整 JSON",
    )
    return parser


def main():
    """screen2.py 命令行入口。"""
    parser = build_arg_parser()
    args = parser.parse_args()
    if args.command == "heat":
        run_heat(debug=args.debug)


if __name__ == "__main__":
    main()
```

后续增加策略时，只增加新的子命令和对应执行函数：

```bash
python screen2.py box
python screen2.py breakout
```

不带子命令时由 argparse 输出帮助，不执行任何选股策略。

### 12.6 第一版最终耗时结构

预期日志拆分为：

```text
[股票基础信息] 读取本地 stock_basic：xx.xx s
[快照] 读取/生成 7 根 K 线：xx.xx s
[快照] 获取全市场 more_info：xx.xx s
[快照] 组装快照：xx.xx s
[快照] 写入文件：xx.xx s
[快照筛选] ST/退市：xx.xx s
[快照筛选] 价格区间：xx.xx s
[快照筛选] 成交额：xx.xx s
[快照筛选] 换手率：xx.xx s
[快照筛选] 量比：xx.xx s
[快照筛选] 涨幅：xx.xx s
[板块补齐] xx 只：xx.xx s
```

第一版不应该出现候选股票 120 根日 K 的日志。只有后续策略配置了非空 `kline_filters` 时，才进入增强日 K 阶段。

### 12.7 最终落地顺序

1. 修改 `stock_basic` 表结构，增加 `total_shares`，单位固定为万股。
2. 修改 `update_daily_kline_after_close()`，同步 `Name` 和 `J_zgb`。
3. 修改 `load_stock_basic_records()`，返回 `code/name/total_shares`。
4. 修改快照生成逻辑，移除运行时 `get_stock_info()`。
5. 增加快照内部分段耗时日志。
6. 修改 `run_heat()`，取消候选股票 120 根日 K 加载。
7. 将 CLI 固定为 `python screen2.py heat [--debug]`。
8. 验证盘中快照覆盖、非盘中复用、ST/退市过滤和总市值口径。
9. 后续新增需要历史 K 线的策略时，再接入 `kline_filters` 和 120 根日 K。

## 控制台输出格式优化

### 1. 目标

当前选股结果主要使用普通 `print()` 输出，字段分散，长概念不易阅读。本次优化只调整展示层，不改变选股逻辑、筛选条件和 JSON 数据结构。

目标输出：

```text
代码 | 名称 | 涨幅 | 行业 | 概念
```

概念内容过长时自动换行，完整保留，不截断、不使用省略号。

### 2. 使用 Rich

使用 Python 的 `rich` 包输出终端表格。Rich 的 `Table` 支持列对齐、样式、自动宽度和单元格换行，适合当前选股结果展示。

依赖增加：

```text
rich>=13.0
```

代码统一导入：

```python
from rich.console import Console
from rich.table import Table
from rich.text import Text
```

模块级只创建一个 Console：

```python
CONSOLE = Console()
```

### 3. 公共展示函数

展示函数不针对 `heat` 命名，所有未来策略都复用：

```python
def print_screen_result(
    result: dict[str, Any],
    debug: bool = False,
) -> None:
    """统一输出任意选股策略的控制台结果。"""
```

调用关系保持统一：

```python
result = run_heat()
print_screen_result(result, debug=args.debug)
```

未来策略也使用同一个函数：

```python
result = run_box()
print_screen_result(result, debug=args.debug)
```

不在 `run_heat()`、`run_box()` 等策略函数内部自行拼接表格字符串。

### 4. 统一 selected 字段

公共展示函数依赖各策略都能提供以下基础字段：

```json
{
  "code": "000001.SZ",
  "name": "平安银行",
  "change_pct": 3.2,
  "industry": "银行",
  "concepts": [
    "沪深300",
    "金融科技"
  ]
}
```

字段约定：

- `code`：通达信股票代码。
- `name`：股票名称。
- `change_pct`：涨跌幅，数值单位为百分比。
- `industry`：行业名称；多个行业使用 `、` 拼接后的字符串。
- `concepts`：概念名称列表。

### 4.1 change_pct 的数据归属

`change_pct` 已经存在于实时快照中，第一版 heat 不在输出层重新计算。由于它表示最新一根日 K 的当日涨跌幅，将它加入 `KlineRecord`：

```python
@dataclass
class KlineRecord:
    code: str
    trade_date: str
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    amount: float
    change_pct: float | None = None
    volume_ratio: float | None = None
```

heat 从快照组装最新 K 线时直接赋值：

```python
latest = KlineRecord(
    code=row["code"],
    trade_date=str(row.get("MAX_TRADE_DATE", "")),
    open_price=float(row.get("open_price") or 0),
    high_price=float(row.get("high_price") or 0),
    low_price=float(row.get("low_price") or 0),
    close_price=float(row.get("close_price", row.get("price")) or 0),
    volume=float(row.get("volume") or 0),
    amount=float(row.get("amount") or 0),
    change_pct=(
        float(row["change_pct"])
        if row.get("change_pct") is not None else None
    ),
    volume_ratio=(
        float(row["volume_ratio"])
        if row.get("volume_ratio") is not None else None
    ),
)
```

最终 `selected` 的涨幅直接从最新 K 线读取：

```python
latest = record.kline[-1] if record.kline else None
selected_item = {
    "code": record.code,
    "name": record.name,
    "change_pct": latest.change_pct if latest else None,
    "industry": industry,
    "concepts": concepts,
}
```

展示层只负责格式化和着色，不重新计算涨跌幅。`change_pct` 保留为可选字段，以兼容当前 `data.load_daily_kline()` 原始 K 线暂时没有该字段的情况。

内部的 `sectors` 仍然可以保留，但在构建最终 `selected` 时统一转换为：

```python
def build_display_sector_fields(sectors):
    """把统一板块记录转换为控制台和结果使用的行业/概念字段。"""
    industries = []
    concepts = []
    for sector in sectors:
        if sector.type == "industry" and sector.name not in industries:
            industries.append(sector.name)
        elif sector.type == "concept" and sector.name not in concepts:
            concepts.append(sector.name)
    return {
        "industry": "、".join(industries),
        "concepts": concepts,
    }
```

### 5. 数值格式化

涨跌幅统一使用百分号，并保留两位小数：

```python
def format_change_pct(value) -> Text:
    """格式化涨跌幅，并按涨跌方向着色。"""
    if value is None or value == "":
        return Text("-")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return Text("-")

    text = f"{number:+.2f}%"
    if number > 0:
        return Text(text, style="red")
    if number < 0:
        return Text(text, style="green")
    return Text(text, style="yellow")
```

上涨使用红色、下跌使用绿色，符合 A 股常见视觉习惯。

### 6. Rich 表格实现

完整公共输出函数：

```python
def print_screen_result(
    result: dict[str, Any],
    debug: bool = False,
) -> None:
    """统一输出任意选股策略的控制台结果。"""
    if debug:
        CONSOLE.print_json(
            json.dumps(result, ensure_ascii=False)
        )
        return

    title = result.get("title") or result.get("strategy") or "选股结果"
    run_date = result.get("run_date", "")
    mode = result.get("mode", "")
    summary = result.get("summary") or {}
    selected = result.get("selected") or []

    CONSOLE.print()
    CONSOLE.print(
        f"[bold cyan]{title}[/bold cyan]  "
        f"日期：{run_date}  模式：{mode}  "
        f"入选：{summary.get('selected_count', len(selected))} 只"
    )

    table = Table(
        title="选股结果",
        expand=True,
        show_lines=True,
    )
    table.add_column("代码", no_wrap=True, style="cyan")
    table.add_column("名称", no_wrap=True)
    table.add_column("涨幅", justify="right", no_wrap=True)
    table.add_column("行业", no_wrap=False, overflow="fold")
    table.add_column("概念", no_wrap=False, overflow="fold")

    for item in selected:
        concepts = item.get("concepts") or []
        if isinstance(concepts, str):
            concept_text = concepts
        else:
            concept_text = "、".join(str(value) for value in concepts)

        table.add_row(
            str(item.get("code", "")),
            str(item.get("name", "")),
            format_change_pct(item.get("change_pct")),
            str(item.get("industry", "")),
            concept_text,
        )

    if selected:
        CONSOLE.print(table)
    else:
        CONSOLE.print("[yellow]本次没有筛选出符合条件的股票[/yellow]")
```

`overflow="fold"` 表示单元格内容自动换行，概念不会被截断。不要使用 `overflow="ellipsis"`，也不要手工切片概念字符串。

### 7. 控制台输出示例

```text
资金热度  日期：2026-07-16  模式：盘中  入选：2 只

                         选股结果
┏━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ 代码       ┃ 名称     ┃  涨幅 ┃ 行业   ┃ 概念               ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ 000001.SZ  │ 平安银行 │ +3.20%│ 银行   │ 沪深300、金融科技  │
│ 300750.SZ  │ 宁德时代 │ +5.61%│ 电池   │ 新能源、储能、      │
│            │          │       │        │ 锂电池产业链       │
└────────────┴──────────┴───────┴────────┴────────────────────┘
```

实际换行由终端宽度和 Rich 表格布局决定，不在业务代码中固定换行位置。

### 8. 步骤日志与结果表格分离

筛选过程的步骤日志继续使用普通文本或统一日志函数：

```text
[快照筛选] 价格区间: 5529 -> 4300, 淘汰 1229, 用时 0.01s
```

最终结果使用 Rich 表格。这样不会把过程日志和结果表格混在一起，也方便后续把步骤日志改为 logging。

### 9. debug 行为

默认模式：

```bash
python screen2.py heat
```

输出 Rich 摘要表格。

debug 模式：

```bash
python screen2.py heat --debug
```

输出完整 JSON，不输出表格，便于复制、调试和机器处理。

### 10. 后续策略扩展

新增策略只需要保证最终结果包含公共基础字段：

```text
code
name
change_pct
industry
concepts
```

然后复用：

```python
print_screen_result(result, debug=args.debug)
```

公共展示函数不感知具体策略名称，也不感知策略使用的是快照条件还是日 K 条件。策略额外字段后续如需展示，再通过公共列配置扩展，不为每个策略复制一套打印函数。

## 修改快照拉取逻辑

本章节是快照读取规则的最新方案，覆盖前文根据盘中/非盘中自动决定快照行为的逻辑。

### 1. 修改目标

盘中每次运行都重新拉取全市场快照会导致执行时间过长。快照是否重新拉取不再由当前是否盘中决定，而由 CLI 参数显式控制。

新的核心原则：

```text
不判断盘中/非盘中来决定快照行为。
由 snapshot_mode 明确选择“使用本地”或“强制刷新”。
```

### 2. 快照模式

支持两个模式：

```text
local    强制使用当天本地快照
refresh  强制重新拉取并覆盖当天快照
```

CLI 调用方式：

```bash
python screen2.py heat
python screen2.py heat --snapshot-mode local
python screen2.py heat --snapshot-mode refresh
python screen2.py heat --snapshot-mode refresh --debug
```

默认模式为 `local`，避免重复执行时反复请求全市场接口。

### 3. 当天快照文件匹配

快照仍然使用当天自然日命名：

```text
Cassa/data/snapshot/cn_snapshot_YYYY-MM-DD.json
```

例如当前日期为 2026-07-16 时，只匹配：

```text
Cassa/data/snapshot/cn_snapshot_2026-07-16.json
```

`local` 模式不查找其他日期的快照，也不使用最近日期快照替代当天快照。

### 4. local 模式流程

```text
1. 计算当天快照路径。
2. 检查当天文件是否存在。
3. 文件存在且结构有效：直接读取。
4. 文件不存在：控制台提示，并生成新快照。
5. 文件存在但结构无效或缺少新版字段：控制台提示，并生成新快照。
6. 使用读取或新生成的快照继续筛选。
```

示例日志：

```text
[快照] 使用本地快照: Cassa/data/snapshot/cn_snapshot_2026-07-16.json
```

文件不存在时：

```text
[快照] 当天本地快照不存在: Cassa/data/snapshot/cn_snapshot_2026-07-16.json
[快照] 正在生成当天快照...
```

这里的提示不需要人工确认，程序直接继续生成，避免批处理或自动化执行被阻塞。

### 5. refresh 模式流程

```text
1. 忽略当天是否已有本地快照。
2. 获取全市场股票基础信息。
3. 通过 data.load_daily_kline(all_codes, count=7) 获取快照所需 K 线。
4. 通过 data.get_more_info(code) 补充量比、换手率、PE、PB。
5. 使用本地 stock_basic 的 name 和 total_shares。
6. 组装完整快照。
7. 原子覆盖当天快照文件。
8. 使用新快照继续筛选。
```

refresh 模式无论当前是盘中、非盘中、午间、收盘后还是非交易日，都执行同样的强制刷新逻辑。

### 6. 快照读取函数

删除原来的盘中覆盖判断，新增统一函数：

```python
def load_or_generate_snapshot(
    stock_rows: list[dict[str, Any]],
    snapshot_mode: str = "local",
) -> list[dict[str, Any]]:
    """按显式模式读取或生成当天快照。"""
    mode = str(snapshot_mode or "local").strip().lower()
    if mode not in {"local", "refresh"}:
        raise ValueError(
            f"不支持的快照模式: {snapshot_mode!r}，可选值为 local/refresh"
        )

    path = snapshot_path()

    if mode == "refresh":
        print(f"[快照] 强制刷新: {path}")
        return generate_market_snapshot(stock_rows)

    if path.is_file():
        try:
            rows = read_snapshot(path)
            print(f"[快照] 使用本地快照: {path}")
            return rows
        except (OSError, ValueError, TypeError) as exc:
            print(f"[快照] 本地快照不可用: {exc}")
            print("[快照] 正在重新生成当天快照...")
    else:
        print(f"[快照] 当天本地快照不存在: {path}")
        print("[快照] 正在生成当天快照...")

    return generate_market_snapshot(stock_rows)
```

原来的 `ensure_market_snapshot()` 可以删除，或者改名为上述函数；第一版统一使用 `load_or_generate_snapshot()`，避免同一职责存在两个入口。

### 7. heat 主流程修改

`run_heat()` 增加 `snapshot_mode` 参数：

```python
def run_heat(
    debug: bool = False,
    snapshot_mode: str = "local",
) -> dict[str, Any]:
    """执行 heat 选股流程。"""
    started_at = time.perf_counter()
    stock_rows = data.load_stock_basic_records()
    snapshot_rows = load_or_generate_snapshot(
        stock_rows=stock_rows,
        snapshot_mode=snapshot_mode,
    )
    snapshot_rows, layers = run_snapshot_filters(
        snapshot_rows,
        HEAT_CONFIG["snapshot_filters"],
    )
    records = build_stock_records_from_snapshot(snapshot_rows)
    records = ensure_sectors(records)
    result = build_result(records, layers, started_at)
    print_screen_result(result, debug=debug)
    return result
```

heat 仍然不加载候选股票 120 根增强日 K。

### 8. CLI 修改

`screen2.py` 第一版 CLI：

```python
def build_arg_parser():
    """构建 screen2.py 子命令解析器。"""
    parser = argparse.ArgumentParser(
        description="Cassa stock screening"
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    heat_parser = subparsers.add_parser(
        "heat",
        help="执行资金热度选股",
    )
    heat_parser.add_argument(
        "--snapshot-mode",
        choices=("local", "refresh"),
        default="local",
        help="快照模式：local 使用当天本地快照，refresh 强制重新拉取",
    )
    heat_parser.add_argument(
        "--debug",
        action="store_true",
        help="输出完整 JSON",
    )
    return parser


def main():
    """screen2.py 命令行入口。"""
    parser = build_arg_parser()
    args = parser.parse_args()
    if args.command == "heat":
        run_heat(
            debug=args.debug,
            snapshot_mode=args.snapshot_mode,
        )


if __name__ == "__main__":
    main()
```

### 9. 删除的旧逻辑

快照流程中删除：

- `data.is_a_share_intraday()` 参与快照模式决策。
- 盘中自动覆盖快照。
- 非盘中自动复用快照的隐式分支。
- `ensure_market_snapshot(..., overwrite=...)` 的 `overwrite` 参数。
- 根据午间、收盘、周末决定快照行为的代码。

`data.load_daily_kline()` 内部已有的盘中实时 K 线拼接逻辑暂时保留，因为它属于日 K 数据层；本章只修改“全市场快照是否重新拉取”的策略。

### 10. 预期收益和使用建议

默认执行：

```bash
python screen2.py heat
```

只读取当天快照，不重复请求全市场数据，适合短时间内重复调试筛选条件。

需要获取最新行情时显式执行：

```bash
python screen2.py heat --snapshot-mode refresh
```

这样“重复筛选”和“刷新行情”被明确分离，避免每次盘中运行都触发 5000 多只股票的快照请求。

## 去掉选股过程去获取章节，改为数据库获取

### 1. 目标与边界

选股过程不再逐只调用 `data.get_stock_info(code)` 或 `data.get_relation(code)`。股票名称、总股本、所属行业和概念统一由 `data.py` 在维护数据库时获取并落盘，`screen2.py` 只从本地数据库读取。

本章只改变基础资料和板块资料的获取位置，不改变快照行情字段的来源。快照生成仍可以使用通达信快照接口获取价格、成交额、换手率、量比、PE、PB 等实时字段；其中股票名称、总股本优先来自数据库。

### 2. 数据表设计

#### 2.1 `stock_basic`

```sql
CREATE TABLE IF NOT EXISTS stock_basic (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    total_shares REAL,
    updated_at TEXT NOT NULL
)
```

`total_shares` 继续使用现有约定的“万股”单位，保持与 `business.py` 和 `cassa.py` 一致。总市值换算时：

```python
market_cap_yuan = total_shares * price * 10000
market_cap_yi = total_shares * price / 10000
```

#### 2.2 `stock_sector`

```sql
CREATE TABLE IF NOT EXISTS stock_sector (
    code TEXT NOT NULL,
    sector_type TEXT NOT NULL,
    sector_code TEXT NOT NULL DEFAULT '',
    sector_name TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (code, sector_type, sector_code, sector_name)
)
```

`sector_type` 只保存 `industry` 和 `concept`。板块数据不放入快照文件，也不放入 `StockRecord` 的额外动态字段；`StockRecord.sectors` 在组装时由数据库记录填充。

### 3. 全量刷新与事务边界

每次执行 `data.py update-daily-kline` 时，按以下顺序维护两张表：

1. 获取全市场股票代码。
2. 在内存中获取并整理所有股票的名称、总股本。
3. 在内存中获取并整理所有股票的行业、概念关系。
4. 只有上述网络获取全部成功后，才开启 SQLite 写事务。
5. 在同一个事务中清空 `stock_sector`、`stock_basic`，再批量插入本次完整数据。
6. 全部插入成功后 `COMMIT`；任意异常执行 `ROLLBACK`，保留上一次完整数据。

这里的“全量删掉重新插入”是逻辑上的全量替换，不是先提交删除再写入。网络请求不放在数据库事务中，避免长时间占用写锁；事务只负责短时间内完成两张表的一致性替换。

### 4. `data.py` 执行方案

#### 4.1 建表和兼容旧表

```python
def migrate_stock_tables(conn):
    """创建股票基础信息和板块关系表，并为旧 stock_basic 表补齐缺失列。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_basic (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        )
    """)
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(stock_basic)").fetchall()
    }
    if "total_shares" not in columns:
        conn.execute("ALTER TABLE stock_basic ADD COLUMN total_shares REAL")
    if "updated_at" not in columns:
        conn.execute(
            "ALTER TABLE stock_basic ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''"
        )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_sector (
            code TEXT NOT NULL,
            sector_type TEXT NOT NULL,
            sector_code TEXT NOT NULL DEFAULT '',
            sector_name TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (code, sector_type, sector_code, sector_name)
        )
    """)
    conn.commit()


def collect_stock_basic_rows(stock_codes, updated_at):
    """获取全部股票的名称和总股本，返回可批量写入 stock_basic 的行。"""
    rows = []
    for code in stock_codes:
        info = get_stock_info(code)
        rows.append({
            "code": code,
            "name": info.get("Name", ""),
            "total_shares": info.get("J_zgb"),
            "updated_at": updated_at,
        })
    return rows


def collect_stock_sector_rows(stock_codes, updated_at):
    """获取全部股票的行业和概念关系，返回可批量写入 stock_sector 的行。"""
    rows = []
    relation_type_map = {"行业": "industry", "概念": "concept"}
    for code in stock_codes:
        for relation in get_relation(code) or []:
            sector_type = relation_type_map.get(relation.get("BlockType"))
            sector_name = relation.get("BlockName", "")
            if not sector_type or not sector_name:
                continue
            rows.append({
                "code": code,
                "sector_type": sector_type,
                "sector_code": relation.get("BlockCode", ""),
                "sector_name": sector_name,
                "updated_at": updated_at,
            })
    return rows


def replace_stock_metadata(stock_basic_rows, stock_sector_rows):
    """在一个事务中全量替换股票基础信息和板块关系，失败时回滚。"""
    conn = get_connection()
    try:
        migrate_stock_tables(conn)
        conn.execute("BEGIN")
        conn.execute("DELETE FROM stock_sector")
        conn.execute("DELETE FROM stock_basic")
        conn.executemany(
            """INSERT INTO stock_basic
               (code, name, total_shares, updated_at)
               VALUES (:code, :name, :total_shares, :updated_at)""",
            stock_basic_rows,
        )
        conn.executemany(
            """INSERT INTO stock_sector
               (code, sector_type, sector_code, sector_name, updated_at)
               VALUES (:code, :sector_type, :sector_code, :sector_name, :updated_at)""",
            stock_sector_rows,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def refresh_stock_metadata(stock_codes):
    """先完整获取股票资料，再以事务全量替换本地资料表。"""
    updated_at = datetime.now().isoformat(timespec="seconds")
    basic_rows = collect_stock_basic_rows(stock_codes, updated_at)
    sector_rows = collect_stock_sector_rows(stock_codes, updated_at)
    if len(basic_rows) != len(stock_codes):
        raise RuntimeError("股票基础信息未完整获取，取消本次数据库替换")
    replace_stock_metadata(basic_rows, sector_rows)
    return {"stock_basic": len(basic_rows), "stock_sector": len(sector_rows)}
```

实际项目中的连接函数名以当前 `data.py` 为准；如果现有名称是 `ensure_database()`，则将示例中的 `get_connection()` 替换为该函数。迁移函数必须在首次使用和 `update-daily-kline` 入口执行，确保旧数据库能够自动增加 `total_shares` 列。

#### 4.2 接入 `update-daily-kline`

```python
def update_daily_kline_after_close():
    """收盘后更新日 K，并同步全市场股票基础信息和板块关系。"""
    stock_rows = get_stock_list()
    stock_codes = [extract_stock_code(row) for row in stock_rows]
    stock_codes = [code for code in stock_codes if code]

    metadata_stats = refresh_stock_metadata(stock_codes)
    print(
        f"[股票资料] 已全量更新：基础信息 {metadata_stats['stock_basic']} 只，"
        f"板块关系 {metadata_stats['stock_sector']} 条"
    )

    # 继续执行原有的收盘后日 K 拉取和入库逻辑。
    update_daily_kline(stock_codes)
```

如果基础信息或板块接口在第 2、3 步任意失败，`refresh_stock_metadata()` 不得进入替换事务，旧数据继续可用；日 K 是否继续执行由现有错误处理策略决定，但不能把不完整资料覆盖进数据库。

### 5. `screen2.py` 只读数据库

```python
def load_stock_basic_records():
    """从本地 stock_basic 读取选股所需的代码、名称和总股本。"""
    conn = data.ensure_database()
    try:
        data.migrate_stock_tables(conn)
        rows = conn.execute(
            """SELECT code, name, total_shares
               FROM stock_basic ORDER BY code"""
        ).fetchall()
        return {
            row["code"]: {
                "code": row["code"],
                "name": row["name"],
                "total_shares": row["total_shares"],
            }
            for row in rows
        }
    finally:
        conn.close()


def load_stock_sectors(code):
    """从本地 stock_sector 读取一只股票的行业和概念。"""
    conn = data.ensure_database()
    try:
        rows = conn.execute(
            """SELECT sector_type, sector_name, sector_code
               FROM stock_sector WHERE code = ?
               ORDER BY sector_type, sector_name""",
            (code,),
        ).fetchall()
        return [
            SectorRecord(
                type=row["sector_type"],
                name=row["sector_name"],
                code=row["sector_code"],
            )
            for row in rows
        ]
    finally:
        conn.close()


def ensure_sectors(records):
    """为 StockRecord 补齐本地数据库中的行业和概念关系。"""
    for record in records:
        record.sectors = load_stock_sectors(record.code)
    return records
```

筛选过程中禁止出现以下网络调用：

```python
data.get_stock_info(code)
data.get_relation(code)
```

`screen2.py` 只读取 `stock_basic` 和 `stock_sector`。快照生成时使用 `stock_basic.total_shares` 计算总市值；`get_more_info()` 仅在快照确实需要 PE、PB 等实时补充字段时保留，不能用于补股票名称或板块。

### 6. 一致性和验证要求

1. 迁移旧库：已有 `stock_basic.name` 数据必须保留，并自动增加 `total_shares` 列。
2. 正常刷新：两张表在同一个事务中替换，提交后行数和更新时间对应同一批数据。
3. 异常回滚：在第二张表插入阶段制造异常，确认两张表都恢复到刷新前状态，不能出现一张新、一张旧。
4. 全量覆盖：本次接口已删除的板块关系在刷新后必须从 `stock_sector` 消失，不能残留旧关系。
5. 选股验证：执行 `python screen2.py heat` 时不调用 `get_stock_info()`、`get_relation()`，板块补齐耗时应明显下降。
6. 数据缺失：数据库没有对应股票资料时只记录警告并按既有缺失数据策略处理；不在选股阶段临时回源请求接口。

最终流程为：

```text
update-daily-kline
  -> 网络获取全量股票资料（内存）
  -> 事务全量替换 stock_basic + stock_sector
  -> 更新日 K

screen2.py heat
  -> 读取本地 stock_basic
  -> 读取本地 stock_sector
  -> 生成/读取快照并执行筛选
  -> 组装 StockRecord 和控制台结果
```

### 7. 执行决策收敛与代码修正

本节覆盖本章前面示例代码中的接口差异，具有最高执行优先级。

#### 7.1 `total_shares` 保持现有非空约束

现有数据库中的 `stock_basic.total_shares` 已经是 `REAL NOT NULL DEFAULT 0`，第一版不重建表、不降级约束。迁移代码应保持如下定义：

```sql
total_shares REAL NOT NULL DEFAULT 0
```

采集时将缺失或非法的 `J_zgb` 统一转换成 `0.0`，确保单只股票资料缺失不会因为 `NULL` 触发事务失败：

```python
def parse_total_shares(value):
    """将 J_zgb 转成万股；缺失或非法值按 0 处理。"""
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


# collect_stock_basic_rows() 内
"total_shares": parse_total_shares(info.get("J_zgb")),
```

因此 `migrate_stock_tables()` 中新增列的 SQL 必须是：

```python
conn.execute(
    "ALTER TABLE stock_basic ADD COLUMN total_shares REAL NOT NULL DEFAULT 0"
)
```

缺失总股本只影响该股票的总市值计算，不阻断名称、板块和其他股票资料的更新。

#### 7.2 新增查询代码使用 tuple 位置索引

当前 `ensure_database()` 返回默认的 SQLite tuple 行，不能在新增代码中使用 `row["code"]`。第一版不修改全局 `row_factory`，避免影响 `data.py` 既有查询；新增查询统一使用位置索引：

```python
def load_stock_basic_records():
    """从本地 stock_basic 读取股票基础信息。"""
    conn = data.ensure_database()
    try:
        data.migrate_stock_tables(conn)
        rows = conn.execute(
            "SELECT code, name, total_shares FROM stock_basic ORDER BY code"
        ).fetchall()
        return {
            row[0]: {
                "code": row[0],
                "name": row[1],
                "total_shares": float(row[2] or 0),
            }
            for row in rows
        }
    finally:
        conn.close()


def load_stock_sectors(code):
    """从本地 stock_sector 读取一只股票的行业和概念。"""
    conn = data.ensure_database()
    try:
        rows = conn.execute(
            """SELECT sector_type, sector_name, sector_code
               FROM stock_sector WHERE code = ?
               ORDER BY sector_type, sector_name""",
            (code,),
        ).fetchall()
        return [
            SectorRecord(type=row[0], name=row[1], code=row[2])
            for row in rows
        ]
    finally:
        conn.close()
```

#### 7.3 板块关系在采集阶段去重

选择 C1：在写入前按主键字段去重，避免源接口偶发重复关系导致整个事务失败。保留第一次出现的记录：

```python
def collect_stock_sector_rows(stock_codes, updated_at):
    """获取行业和概念关系，并按 stock_sector 主键去重。"""
    unique_rows = {}
    relation_type_map = {"行业": "industry", "概念": "concept"}
    for code in stock_codes:
        for relation in get_relation(code) or []:
            sector_type = relation_type_map.get(relation.get("BlockType"))
            sector_name = str(relation.get("BlockName") or "").strip()
            if not sector_type or not sector_name:
                continue
            sector_code = str(relation.get("BlockCode") or "").strip()
            key = (code, sector_type, sector_code, sector_name)
            unique_rows.setdefault(key, {
                "code": code,
                "sector_type": sector_type,
                "sector_code": sector_code,
                "sector_name": sector_name,
                "updated_at": updated_at,
            })
    return list(unique_rows.values())
```

不使用 `INSERT OR IGNORE` 掩盖数据问题；去重逻辑放在采集层，便于后续统计和排查源数据质量。

#### 7.4 `load_stock_basic_records()` 保留在 `data.py`

选择 D2：`load_stock_basic_records()` 作为数据访问函数保留在 `data.py`，`screen2.py` 继续调用：

```python
stock_rows = data.load_stock_basic_records()
```

`screen2.py` 只负责选股业务和 `StockRecord` 组装，不直接编写股票基础表 SQL。板块读取同理，建议最终由 `data.load_stock_sectors(code)` 暴露数据访问接口，`screen2.py` 的 `ensure_sectors()` 只负责把查询结果赋给记录。

#### 7.5 收盘更新入口使用实际代码接口

`get_stock_list()` 当前返回 `list[str]`，因此不再使用不存在的 `extract_stock_code(row)`：

```python
stock_rows = get_stock_list()
stock_codes = [str(code).strip() for code in stock_rows if code]
refresh_stock_metadata(stock_codes)
```

现有 `update_daily_kline_after_close()` 中的：

```python
upsert_stock_basic_rows(stock_rows)
```

必须删除，避免旧的逐行 upsert 逻辑与新的事务全量替换逻辑重复执行。`upsert_stock_basic_rows()` 和旧的 `migrate_stock_basic_table()` 不再作为运行入口；完成迁移后删除，或暂时保留为明确标注“废弃、禁止调用”的兼容代码，但不能被 `update-daily-kline` 或 `screen2.py` 调用。最终保留的正式接口为：

```text
migrate_stock_tables
collect_stock_basic_rows
collect_stock_sector_rows
replace_stock_metadata
refresh_stock_metadata
load_stock_basic_records
load_stock_sectors
```

这样可以同时解决旧表约束、SQLite 行格式、源数据重复、数据层职责和实际代码接口五类问题，并保持“网络采集完成后，事务全量替换；选股阶段只读数据库”的总体设计不变。

### 9. 为 `update-daily-kline` 添加执行日志

#### 9.1 目标

当前执行：

```bash
python data.py update-daily-kline --count 1
```

在输出“正在获取全市场股票列表”后，可能长时间没有新日志。实际流程中不仅会获取日 K，还会顺序获取全市场股票基础信息和板块关系；如果没有进度输出，用户无法判断程序是在等待接口、采集资料，还是已经异常卡死。

本次只增加可观测性，不改变现有数据来源、全量刷新方式和事务边界。`--count 1` 仍然表示每只股票拉取 1 根日 K，不代表只处理 1 只股票；股票列表、基础信息和板块关系仍按全市场执行。

#### 9.2 统一阶段划分

`update_daily_kline_after_close()` 的控制台日志统一按以下阶段输出：

```text
[日K更新] 阶段 1/4：获取全市场股票列表
[日K更新] 阶段 2/4：获取股票基础信息
[日K更新] 阶段 3/4：获取股票行业和概念
[日K更新] 阶段 4/4：拉取并写入日K
```

阶段名称必须在阶段开始时打印，阶段结束时打印数量、成功数、失败数和耗时。所有耗时使用 `time.perf_counter()` 计算，保留一位小数。

#### 9.3 股票列表阶段日志

现有代码：

```python
print("[日K更新] 正在获取全市场股票列表...")
stock_rows = get_stock_list()
stock_list = extract_stock_codes_from_stock_list(stock_rows)
```

改为：

```python
stage_started_at = time.perf_counter()
print("[日K更新] 阶段 1/4：正在获取全市场股票列表...")

stock_rows = get_stock_list()
stock_list = extract_stock_codes_from_stock_list(stock_rows)

stage_seconds = time.perf_counter() - stage_started_at
print(
    f"[日K更新] 阶段 1/4 完成：获取 {len(stock_list)} 只股票，"
    f"耗时 {stage_seconds:.1f}s"
)
```

如果列表为空，必须明确打印：

```text
[日K更新] 阶段 1/4 失败：未获取到股票列表，结束本次更新
```

空列表不能继续执行资料清空或数据库替换。

#### 9.4 基础信息采集进度

`collect_stock_basic_rows()` 当前会逐只调用 `get_stock_info()`。函数内部需要增加批量进度日志，但不需要为每只成功股票打印一行，避免日志过多。

```python
def collect_stock_basic_rows(stock_codes, updated_at, progress_interval=500):
    """获取全部股票名称和总股本，并按固定间隔输出进度。"""
    started_at = time.perf_counter()
    total = len(stock_codes)
    rows = []
    failed_count = 0

    print(f"[股票基础信息] 开始获取：共 {total} 只")

    for index, code in enumerate(stock_codes, 1):
        try:
            info = get_stock_info(code, field_list=[]) or {}
        except Exception as exc:
            failed_count += 1
            info = {}
            print(f"[股票基础信息] 获取失败：{code}，{exc}")

        rows.append({
            "code": code,
            "name": str(info.get("Name", "") or "").strip(),
            "total_shares": parse_total_shares(info.get("J_zgb")),
            "updated_at": updated_at,
        })

        if index % progress_interval == 0 or index == total:
            elapsed = time.perf_counter() - started_at
            print(
                f"[股票基础信息] 进度：{index}/{total}，"
                f"失败 {failed_count} 只，耗时 {elapsed:.1f}s"
            )

    elapsed = time.perf_counter() - started_at
    print(
        f"[股票基础信息] 获取完成：{total} 只，"
        f"失败 {failed_count} 只，耗时 {elapsed:.1f}s"
    )
    return rows
```

单只股票接口异常仍按现有策略记录为空资料并继续；只有基础信息行数量不完整时，才禁止进入数据库替换事务。进度日志中的失败数必须与最终汇总一致。

#### 9.5 板块关系采集进度

`collect_stock_sector_rows()` 同样逐只调用 `get_relation()`，增加与基础信息阶段一致的进度统计：

```python
def collect_stock_sector_rows(stock_codes, updated_at, progress_interval=500):
    """获取行业和概念关系，并输出全量采集进度。"""
    started_at = time.perf_counter()
    total = len(stock_codes)
    failed_count = 0
    unique_rows = {}

    print(f"[板块关系] 开始获取：共 {total} 只")

    for index, code in enumerate(stock_codes, 1):
        try:
            relations = get_relation(code) or []
        except Exception as exc:
            failed_count += 1
            relations = []
            print(f"[板块关系] 获取失败：{code}，{exc}")

        for relation in relations:
            sector_type = {"行业": "industry", "概念": "concept"}.get(
                relation.get("BlockType")
            )
            sector_name = str(relation.get("BlockName") or "").strip()
            if not sector_type or not sector_name:
                continue
            sector_code = str(relation.get("BlockCode") or "").strip()
            key = (code, sector_type, sector_code, sector_name)
            unique_rows.setdefault(key, {
                "code": code,
                "sector_type": sector_type,
                "sector_code": sector_code,
                "sector_name": sector_name,
                "updated_at": updated_at,
            })

        if index % progress_interval == 0 or index == total:
            elapsed = time.perf_counter() - started_at
            print(
                f"[板块关系] 进度：{index}/{total}，"
                f"已整理 {len(unique_rows)} 条，失败 {failed_count} 只，"
                f"耗时 {elapsed:.1f}s"
            )

    elapsed = time.perf_counter() - started_at
    print(
        f"[板块关系] 获取完成：{total} 只，"
        f"整理 {len(unique_rows)} 条，失败 {failed_count} 只，"
        f"耗时 {elapsed:.1f}s"
    )
    return list(unique_rows.values())
```

#### 9.6 事务替换日志

网络资料全部获取完成后，进入数据库事务前明确打印：

```python
print(
    f"[股票资料] 网络获取完成，准备开启事务："
    f"stock_basic={len(stock_basic_rows)}，"
    f"stock_sector={len(stock_sector_rows)}"
)
```

事务函数中增加开始、提交和回滚日志：

```python
def replace_stock_metadata(stock_basic_rows, stock_sector_rows):
    """在一个事务中全量替换两张资料表，失败时回滚。"""
    conn = ensure_database()
    transaction_started_at = time.perf_counter()
    try:
        migrate_stock_tables(conn)
        print("[股票资料] 开始事务：清空并写入 stock_basic、stock_sector")
        conn.execute("BEGIN")
        conn.execute("DELETE FROM stock_sector")
        conn.execute("DELETE FROM stock_basic")
        # executemany 插入两张表的完整数据。
        insert_stock_basic_rows(conn, stock_basic_rows)
        insert_stock_sector_rows(conn, stock_sector_rows)
        conn.commit()
        elapsed = time.perf_counter() - transaction_started_at
        print(
            f"[股票资料] 事务提交完成：stock_basic={len(stock_basic_rows)}，"
            f"stock_sector={len(stock_sector_rows)}，耗时 {elapsed:.1f}s"
        )
    except Exception as exc:
        conn.rollback()
        elapsed = time.perf_counter() - transaction_started_at
        print(
            f"[股票资料] 事务失败，已回滚并保留旧数据：{exc}，"
            f"耗时 {elapsed:.1f}s"
        )
        raise
```

`insert_stock_basic_rows()` 和 `insert_stock_sector_rows()` 代表现有的 `executemany()` 插入代码，不改变事务逻辑。由于 `ensure_database()` 返回全局连接，本函数不能调用 `conn.close()`。

#### 9.7 日 K 批次阶段日志

完成资料维护后打印：

```text
[日K更新] 阶段 3/4 完成：股票资料更新完成
[日K更新] 阶段 4/4：开始拉取日K，共 5535 只，12 批，count=1
```

保留现有每批开始和完成日志，并在批次失败时打印股票范围、异常信息和累计耗时：

```text
[日K更新] 第 3/12 批开始：500 只，002501.SZ ~ 300006.SZ
[日K更新] 第 3/12 批完成：写入 500 行，本批耗时 5.2s，总耗时 28.4s
```

全部完成后输出完整汇总：

```text
[日K更新] 阶段 4/4 完成：股票 5535 只，写入/覆盖 5535 行，耗时 62.6s
[日K更新] 全部完成：总耗时 248.7s
```

#### 9.8 预期日志示例

```text
[日K更新] 开始更新全部A股日K：count=1, batch_size=500
[日K更新] 阶段 1/4：正在获取全市场股票列表...
[日K更新] 阶段 1/4 完成：获取 5535 只股票，耗时 2.3s
[日K更新] 阶段 2/4：正在获取股票基础信息...
[股票基础信息] 开始获取：共 5535 只
[股票基础信息] 进度：500/5535，失败 1 只，耗时 18.6s
[股票基础信息] 获取完成：5535 只，失败 6 只，耗时 184.2s
[日K更新] 阶段 3/4：正在获取股票行业和概念...
[板块关系] 进度：500/5535，已整理 4200 条，失败 2 只，耗时 35.1s
[板块关系] 获取完成：5535 只，整理 48000 条，失败 12 只，耗时 392.4s
[股票资料] 网络获取完成，准备开启事务：stock_basic=5535，stock_sector=48000
[股票资料] 事务提交完成：stock_basic=5535，stock_sector=48000，耗时 0.8s
[日K更新] 阶段 4/4：开始拉取日K，共 5535 只，12 批，count=1
[日K更新] 阶段 4/4 完成：股票 5535 只，写入/覆盖 5535 行，耗时 62.6s
[日K更新] 全部完成：总耗时 642.1s
```

通过阶段耗时可以明确区分：股票列表接口耗时、基础信息接口耗时、板块关系接口耗时、数据库事务耗时和日 K 接口耗时。后续如果需要优化速度，也可以根据日志直接定位最慢阶段，而不是把所有时间都归因于日 K 拉取。

### 8. `SectorRecord` 归属与数据库连接约束

#### 8.1 `SectorRecord` 保留在 `screen2.py`

`SectorRecord` 是选股业务层的数据结构，继续定义在 `screen2.py`。`data.py` 不得导入 `screen2.py`，避免形成 `screen2 -> data -> screen2` 循环依赖。

因此 `data.load_stock_sectors(code)` 只返回普通字典列表，不直接构造 `SectorRecord`：

```python
def load_stock_sectors(code):
    """从 stock_sector 查询一只股票的行业和概念，返回普通字典列表。"""
    conn = ensure_database()
    rows = conn.execute(
        """SELECT sector_type, sector_name, sector_code
           FROM stock_sector WHERE code = ?
           ORDER BY sector_type, sector_name""",
        (code,),
    ).fetchall()
    return [
        {
            "type": row[0],
            "name": row[1],
            "code": row[2],
        }
        for row in rows
    ]
```

`screen2.py` 的 `ensure_sectors()` 负责把字典转换为业务对象：

```python
def ensure_sectors(records):
    """从本地数据库读取板块关系并转换为 StockRecord.sectors。"""
    for record in records:
        record.sectors = [
            SectorRecord(
                type=sector["type"],
                name=sector["name"],
                code=sector["code"],
            )
            for sector in data.load_stock_sectors(record.code)
        ]
    return records
```

这样数据层只处理数据库记录，业务层只处理 `StockRecord` 和 `SectorRecord`，职责清晰且没有循环依赖。

#### 8.2 全局数据库连接不在刷新函数中关闭

当前 `ensure_database()` 返回全局共享的 `_CONN` 单例。因此 `replace_stock_metadata()` 不得调用 `conn.close()`；否则会关闭仍被其他数据函数使用的全局连接，导致后续查询出现 `Cannot operate on a closed database`。

刷新函数只负责事务边界：

```python
def replace_stock_metadata(stock_basic_rows, stock_sector_rows):
    """在一个事务中全量替换两张资料表，失败时回滚。"""
    conn = ensure_database()
    migrate_stock_tables(conn)
    try:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM stock_sector")
        conn.execute("DELETE FROM stock_basic")
        conn.executemany(
            """INSERT INTO stock_basic
               (code, name, total_shares, updated_at)
               VALUES (?, ?, ?, ?)""",
            [
                (
                    row["code"],
                    row["name"],
                    row["total_shares"],
                    row["updated_at"],
                )
                for row in stock_basic_rows
            ],
        )
        conn.executemany(
            """INSERT INTO stock_sector
               (code, sector_type, sector_code, sector_name, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            [
                (
                    row["code"],
                    row["sector_type"],
                    row["sector_code"],
                    row["sector_name"],
                    row["updated_at"],
                )
                for row in stock_sector_rows
            ],
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
```

连接的生命周期由应用程序或现有数据库模块统一管理；本函数既不创建独立连接，也不关闭 `_CONN`。后续如果重构数据库连接管理，再单独评估使用 `sqlite3.connect(DB_PATH)` 的独立事务连接，当前版本不引入该变化。

## 迁移放量突破策略

### 1. 迁移范围

将 `alphasift-fork` 的 `volume_breakout` 迁移到 Cassa 的 `screen2.py`，但第一版不迁移 `signal_score`、LLM 排序、后置分析和原项目评分体系。

保留的硬筛条件为：

```text
快照：排除 ST/退、成交额、换手率、量比、涨幅区间
日K：站上 MA20、MACD 状态、20 日突破形态
```

20 日突破形态内部包含：突破幅度、20 日区间振幅、20 日量能比、当日实体涨幅、突破前横盘天数。

完整流程为：

```text
读取 stock_basic
  -> 读取/生成当天快照
  -> 快照硬筛
  -> 对候选股票读取 120 根日K
  -> 统一计算并缓存指标
  -> 日K条件逐层筛选
  -> 从 stock_sector 读取板块
  -> 组装 result 并输出
```

日 K 必须在快照初筛之后读取，不能对全市场直接请求 120 根日 K。

### 2. KlineRecord 增加指标字段

MA、MACD 和形态指标都直接加入 `KlineRecord`。单根 K 线不能计算 MA 或 MACD，计算函数的入参必须是一只股票按交易日期升序排列的完整 K 线列表。

```python
@dataclass
class KlineRecord:
    """一根日K及其可复用技术指标。"""
    code: str
    trade_date: str
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    amount: float
    change_pct: float | None = None
    volume_ratio: float | None = None

    # 公共指标
    ma5: float | None = None
    ma20: float | None = None
    ma60: float | None = None
    macd_diff: float | None = None
    macd_dea: float | None = None
    macd_status: str | None = None

    # 放量突破指标
    prev_high_20d: float | None = None
    breakout_20d_pct: float | None = None
    range_20d_pct: float | None = None
    volume_ratio_20d: float | None = None
    body_pct: float | None = None
    consolidation_days_20d: int | None = None
```

### 3. 公共指标计算函数

所有日 K 派生指标统一由一个公共函数计算；策略函数只读取字段并判断条件。后续策略需要 RSI、KDJ、ATR 等指标时，继续扩展这个函数，不在每个策略中重复计算。

```python
def _positive_float(value):
    """将值转换为正数浮点数，无效值返回 None。"""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _average(values):
    """计算非空数值平均值。"""
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def _ema(values, period):
    """计算指数移动平均序列。"""
    alpha = 2 / (period + 1)
    result = []
    current = None
    for value in values:
        if value is None:
            result.append(None)
            continue
        current = value if current is None else alpha * value + (1 - alpha) * current
        result.append(current)
    return result


def _ma(klines, index, period):
    """计算截至指定 K 线的简单移动平均。"""
    if index + 1 < period:
        return None
    values = [
        _positive_float(item.close_price)
        for item in klines[index - period + 1:index + 1]
    ]
    return _average(values) if len(values) == period and all(v is not None for v in values) else None


def _macd_series(klines):
    """计算 DIF、DEA 序列。"""
    closes = [_positive_float(item.close_price) for item in klines]
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    diff = [
        left - right if left is not None and right is not None else None
        for left, right in zip(ema12, ema26)
    ]
    return diff, _ema(diff, 9)


def _macd_status(diff, dea):
    """将 DIF/DEA 转换为 bullish、neutral、bearish。"""
    if diff is None or dea is None:
        return "neutral"
    if diff > dea and diff > 0:
        return "bullish"
    if diff < dea and diff < 0:
        return "bearish"
    return "neutral"


def _consolidation_days(previous, max_range_pct=12.0):
    """计算突破前最长横盘整理天数。"""
    if len(previous) < 2:
        return None
    for days in range(min(len(previous), 20), 1, -1):
        window = previous[-days:]
        highs = [_positive_float(item.high_price) for item in window]
        lows = [_positive_float(item.low_price) for item in window]
        if not all(value is not None for value in highs + lows):
            continue
        low = min(lows)
        range_pct = (max(highs) / low - 1) * 100 if low > 0 else None
        if range_pct is not None and range_pct <= max_range_pct:
            return days
    return 0


def calculate_kline_indicators(klines: list[KlineRecord]) -> None:
    """一次性计算并写回一只股票全部日K的公共指标和突破指标。"""
    if not klines:
        return

    klines.sort(key=lambda item: item.trade_date)
    diff, dea = _macd_series(klines)

    for index, current in enumerate(klines):
        current.ma5 = _ma(klines, index, 5)
        current.ma20 = _ma(klines, index, 20)
        current.ma60 = _ma(klines, index, 60)
        current.macd_diff = diff[index]
        current.macd_dea = dea[index]
        current.macd_status = _macd_status(diff[index], dea[index])

        previous = klines[max(0, index - 20):index]
        recent = klines[max(0, index - 19):index + 1]
        previous_highs = [_positive_float(item.high_price) for item in previous]
        current_close = _positive_float(current.close_price)
        if len(previous) == 20 and all(v is not None for v in previous_highs):
            current.prev_high_20d = max(previous_highs)
            current.breakout_20d_pct = (
                (current_close / current.prev_high_20d - 1) * 100
                if current_close is not None else None
            )
        else:
            current.prev_high_20d = None
            current.breakout_20d_pct = None

        highs = [_positive_float(item.high_price) for item in recent]
        lows = [_positive_float(item.low_price) for item in recent]
        if len(recent) == 20 and all(v is not None for v in highs + lows):
            current.range_20d_pct = (max(highs) / min(lows) - 1) * 100
        else:
            current.range_20d_pct = None

        previous_volumes = [_positive_float(item.volume) for item in previous]
        average_volume = _average(previous_volumes)
        current_volume = _positive_float(current.volume)
        current.volume_ratio_20d = (
            current_volume / average_volume
            if len(previous) == 20 and all(v is not None for v in previous_volumes)
            and current_volume is not None and average_volume and average_volume > 0
            else None
        )

        current_open = _positive_float(current.open_price)
        current.body_pct = (
            (current_close / current_open - 1) * 100
            if current_close is not None and current_open is not None else None
        )
        current.consolidation_days_20d = _consolidation_days(previous)
```

规则口径与原策略保持一致：前高不包含当前 K 线；20 日量能比为当前成交量除以前 20 根 K 线平均成交量；横盘区间默认不超过 12%。

### 4. 指标缓存与日K组装

```python
def ensure_kline_indicators(record: StockRecord) -> StockRecord:
    """确保一只股票的日K指标已计算，重复调用直接复用。"""
    if not record.kline:
        return record
    latest = record.kline[-1]
    if latest.ma20 is None or latest.macd_status is None:
        calculate_kline_indicators(record.kline)
    return record


def ensure_kline_records(records):
    """批量确保候选股票完成日K指标计算。"""
    for record in records:
        ensure_kline_indicators(record)
    return records


def kline_row_to_record(row):
    """把 data.load_daily_kline 返回的一行转换为 KlineRecord。"""
    return KlineRecord(
        code=str(row.get("code", "")),
        trade_date=str(row.get("trade_date", "")),
        open_price=float(row.get("open_price") or 0),
        high_price=float(row.get("high_price") or 0),
        low_price=float(row.get("low_price") or 0),
        close_price=float(row.get("close_price") or 0),
        volume=float(row.get("volume") or 0),
        amount=float(row.get("amount") or 0),
        change_pct=(float(row["change_pct"]) if row.get("change_pct") is not None else None),
        volume_ratio=(float(row["volume_ratio"]) if row.get("volume_ratio") is not None else None),
    )


def build_stock_records_with_daily_kline(snapshot_rows, kline_map):
    """为快照候选股票组装日K；没有日K的股票不进入技术筛选。"""
    records = []
    missing_count = 0
    for row in snapshot_rows:
        klines = [kline_row_to_record(item) for item in kline_map.get(row["code"], [])]
        if not klines:
            missing_count += 1
            continue
        records.append(StockRecord(
            code=row["code"],
            name=str(row.get("name", "") or ""),
            kline=klines,
        ))
    print(f"[日K候选] 组装完成：成功 {len(records)} 只，缺失日K {missing_count} 只")
    return records

### 5. 放量突破条件函数

条件函数只负责判断，不重复计算指标；指标缺失时统一调用 `ensure_kline_indicators()`，缺失数据按不通过处理。

```python
def filter_price_above_ma20(records):
    """过滤最新收盘价没有站上 MA20 的股票。"""
    result = []
    for record in records:
        ensure_kline_indicators(record)
        latest = record.kline[-1] if record.kline else None
        if latest and latest.ma20 is not None and latest.close_price >= latest.ma20:
            result.append(record)
    return result


def filter_macd_status(records, allowed_statuses):
    """过滤 MACD 状态不在允许集合中的股票。"""
    allowed = set(allowed_statuses)
    result = []
    for record in records:
        ensure_kline_indicators(record)
        latest = record.kline[-1] if record.kline else None
        if latest and latest.macd_status in allowed:
            result.append(record)
    return result


def filter_breakout_shape(
    records,
    breakout_min_pct,
    range_max_pct,
    volume_ratio_min,
    body_min_pct,
    consolidation_days_min,
):
    """按突破幅度、区间、量能、实体和横盘天数过滤。"""
    result = []
    for record in records:
        ensure_kline_indicators(record)
        latest = record.kline[-1] if record.kline else None
        if latest is None:
            continue
        values = (
            latest.breakout_20d_pct,
            latest.range_20d_pct,
            latest.volume_ratio_20d,
            latest.body_pct,
            latest.consolidation_days_20d,
        )
        if any(value is None for value in values):
            continue
        if (
            latest.breakout_20d_pct >= breakout_min_pct
            and latest.range_20d_pct <= range_max_pct
            and latest.volume_ratio_20d >= volume_ratio_min
            and latest.body_pct >= body_min_pct
            and latest.consolidation_days_20d >= consolidation_days_min
        ):
            result.append(record)
    return result


def run_kline_filters(records, filters):
    """按配置逐层执行日K条件并记录数量和耗时。"""
    layers = []
    filtered = records
    for item in filters:
        started = time.perf_counter()
        before = filtered
        filtered = item["function"](filtered, **item.get("params", {}))
        layers.append(timed_layer(item["name"], before, filtered, started))
    return filtered, layers
```

这样不需要分别创建 `filter_breakout_20d`、`filter_range_20d`、`filter_volume_ratio_20d`、`filter_body_pct` 和 `filter_consolidation_days_20d` 五个函数；它们仍然是独立条件，只是在同一个“突破形态”业务函数中执行。

### 6. 策略配置

配置放在 `screen2.py` 顶部常量区，所有条件函数不写死阈值：

```python
VOLUME_BREAKOUT_CONFIG = {
    "strategy": "volume_breakout",
    "title": "放量突破",
    "kline_count": 120,
    "snapshot_filters": [
        {
            "name": "成交额",
            "function": filter_snapshot_amount,
            "params": {"min_amount": 100_000_000},
        },
        {
            "name": "换手率",
            "function": filter_snapshot_turnover_rate,
            "params": {"min_turnover_rate": 3.0},
        },
        {
            "name": "量比",
            "function": filter_snapshot_volume_ratio,
            "params": {"min_volume_ratio": 2.0},
        },
        {
            "name": "涨幅下限",
            "function": filter_snapshot_change_pct,
            "params": {"min_change_pct": 2.0},
        },
        {
            "name": "涨幅上限",
            "function": filter_snapshot_change_pct_max,
            "params": {"max_change_pct": 9.9},
        },
    ],
    "kline_filters": [
        {
            "name": "站上MA20",
            "function": filter_price_above_ma20,
            "params": {},
        },
        {
            "name": "MACD状态",
            "function": filter_macd_status,
            "params": {"allowed_statuses": ("bullish", "neutral")},
        },
        {
            "name": "放量突破形态",
            "function": filter_breakout_shape,
            "params": {
                "breakout_min_pct": -1.0,
                "range_max_pct": 35.0,
                "volume_ratio_min": 1.3,
                "body_min_pct": 0.5,
                "consolidation_days_min": 8,
            },
        },
    ],
}
```

新增快照涨幅上限函数：

```python
def filter_snapshot_change_pct_max(rows, max_change_pct):
    """按快照涨跌幅上限过滤。"""
    result = []
    for row in rows:
        value = safe_float(row.get("change_pct"))
        if value is not None and value <= max_change_pct:
            result.append(row)
    return result
```

`min_amount` 必须使用当前 Cassa 快照 `amount` 字段的实际单位。若快照金额以元保存，使用 `100_000_000`；若现有快照统一保存为万元，则配置应换算为 `10_000`。单位只在配置处确定，过滤函数不做隐式换算。

### 7. 通用 result 和策略执行函数

现有 `build_result()` 不能继续把 `strategy` 和 `title` 写死为 heat，改成接收策略配置：

```python
def build_result(records, layers, started_at, strategy_config):
    """构建任意选股策略的统一 JSON 结果。"""
    all_filters = (
        strategy_config.get("snapshot_filters", [])
        + strategy_config.get("kline_filters", [])
    )
    return {
        "strategy": strategy_config["strategy"],
        "title": strategy_config["title"],
        "run_date": datetime.now().strftime("%Y-%m-%d"),
        "mode": data.get_market_mode_label(),
        "conditions": [
            {"name": item["name"], "params": item.get("params", {})}
            for item in all_filters
        ],
        "selected": [serialize_record(record) for record in records],
        "layers": [asdict(layer) for layer in layers],
        "summary": {
            "selected_count": len(records),
            "elapsed_seconds": round(time.perf_counter() - started_at, 3),
        },
    }


def run_volume_breakout(debug=False, snapshot_mode="local"):
    """执行放量突破选股。"""
    started_at = time.perf_counter()
    print("开始执行策略: volume_breakout")

    step = time.perf_counter()
    stock_rows = data.load_stock_basic_records()
    print(
        f"[股票基础信息] 读取本地 stock_basic：{len(stock_rows)} 只，"
        f"用时 {time.perf_counter() - step:.2f}s"
    )

    snapshot_rows = load_or_generate_snapshot(
        stock_rows,
        snapshot_mode=snapshot_mode,
    )
    snapshot_rows, snapshot_layers = run_snapshot_filters(
        snapshot_rows,
        VOLUME_BREAKOUT_CONFIG["snapshot_filters"],
    )

    codes = [row["code"] for row in snapshot_rows]
    step = time.perf_counter()
    kline_map = data.load_daily_kline(
        codes,
        count=VOLUME_BREAKOUT_CONFIG["kline_count"],
    )
    print(
        f"[日K读取] 候选 {len(codes)} 只，"
        f"用时 {time.perf_counter() - step:.2f}s"
    )

    records = build_stock_records_with_daily_kline(snapshot_rows, kline_map)
    step = time.perf_counter()
    records = ensure_kline_records(records)
    print(
        f"[日K指标] 计算完成：{len(records)} 只，"
        f"用时 {time.perf_counter() - step:.2f}s"
    )
    records, kline_layers = run_kline_filters(
        records,
        VOLUME_BREAKOUT_CONFIG["kline_filters"],
    )

    step = time.perf_counter()
    records = ensure_sectors(records)
    print(
        f"[板块补齐] {len(records)} 只，"
        f"用时 {time.perf_counter() - step:.2f}s"
    )

    result = build_result(
        records,
        snapshot_layers + kline_layers,
        started_at,
        VOLUME_BREAKOUT_CONFIG,
    )
    print_screen_result(result, debug=debug)
    return result
```

`run_heat()` 同时改为向新的 `build_result()` 传入 `HEAT_CONFIG`，避免通用结果函数仍然固定输出 `strategy="heat"`。

### 8. CLI 入口

在 `build_arg_parser()` 增加独立命令：

```python
volume_parser = subparsers.add_parser(
    "volume-breakout",
    help="执行放量突破选股",
)
volume_parser.add_argument(
    "--snapshot-mode",
    choices=("local", "refresh"),
    default="local",
    help="local 使用当天快照，refresh 强制重新拉取",
)
volume_parser.add_argument(
    "--debug",
    action="store_true",
    help="输出完整 JSON",
)
```

在 `main()` 中增加：

```python
elif args.command == "volume-breakout":
    run_volume_breakout(
        debug=args.debug,
        snapshot_mode=args.snapshot_mode,
    )
```

执行命令：

```bash
python screen2.py volume-breakout
python screen2.py volume-breakout --snapshot-mode refresh
python screen2.py volume-breakout --debug
```

### 9. 旧逻辑清理与验证

1. 删除 `screen2.py` 对 `data.load_breakout_kline()` 的调用；统一使用 `data.load_daily_kline(codes, count=120)`。
2. 后续删除 `data.load_breakout_kline()` 及其专用辅助逻辑，避免两套日 K 读取口径并存。
3. 确认 `screen2.py` 不调用 `data.get_stock_info()`、`data.get_relation()`。
4. 确认 `signal_score` 没有加入 `KlineRecord`、配置和结果。
5. 使用固定 K 线验证 MA20、MACD、前 20 日最高价和量能比，确认前高不包含当前 K 线。
6. 不足 20 根 K 线时，突破、区间、量能和横盘指标必须为缺失并过滤掉；不足 60 根时 `ma60` 可以缺失，但本策略不依赖 `ma60`。
7. 多个条件函数连续调用 `ensure_kline_indicators()` 时，只允许第一次真正计算，后续复用字段。
8. 验证快照筛选后才拉取日 K，不能对全市场请求 120 根日 K。
9. 验证 `python screen2.py heat` 原有流程不受影响。
10. 验证 `python screen2.py volume-breakout --debug` 的 `strategy`、`conditions`、`layers`、`selected` 字段正确。

最终函数分工：

```text
calculate_kline_indicators  公共日K指标计算
ensure_kline_indicators     公共指标缓存
filter_price_above_ma20     站上 MA20 条件
filter_macd_status          MACD 条件
filter_breakout_shape       放量突破形态条件
run_kline_filters            通用逐层执行器
run_volume_breakout          策略 CLI 执行入口
```

### 10. 实施前核对结论

本节是对本章方案实施前疑问的最终确认，后续代码以本节为准。

#### 10.1 `load_daily_kline()` 的返回字段已经确认

当前 `data.load_daily_kline_rows_from_db()` 查询 `daily_kline` 表的字段为：

```python
code
trade_date
open_price
high_price
low_price
close_price
volume
amount
```

数据库表结构与返回字典字段一致：

```sql
CREATE TABLE daily_kline (
    code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open_price REAL NOT NULL,
    high_price REAL NOT NULL,
    low_price REAL NOT NULL,
    close_price REAL NOT NULL,
    volume REAL NOT NULL DEFAULT 0,
    amount REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (code, trade_date)
)
```

因此 `kline_row_to_record()` 只从日 K 数据读取以上 8 个字段。`change_pct` 和 `volume_ratio` 不属于 `daily_kline` 表，不能从数据库日 K 行读取；它们的处理方式为：

1. 基础日 K 记录中的 `change_pct`、`volume_ratio` 初始保持 `None`。
2. 组装放量突破候选记录时，将快照中的最新 `change_pct` 和实时 `volume_ratio` 写入最新一根 `KlineRecord`。
3. `volume_ratio_20d` 是基于日 K 成交量历史重新计算的指标，与快照的实时 `volume_ratio` 是两个不同字段，不能混用。

示例：

```python
def apply_snapshot_latest_fields(record, snapshot_row):
    """把快照中的最新实时字段写入候选记录的最新日K。"""
    if not record.kline:
        return record
    latest = record.kline[-1]
    latest.change_pct = safe_float(snapshot_row.get("change_pct"))
    latest.volume_ratio = safe_float(snapshot_row.get("volume_ratio"))
    return record
```

#### 10.2 快照成交额单位已经确认

当前 Cassa 快照中的 `amount` 单位是“万元”，与现有 `HEAT_CONFIG` 保持一致。数据库样本中：

```text
volume = 70065312
amount = 70782.95
```

该成交额约等于 7.08 亿元，因此不是以元保存。

放量突破要求成交额至少 1 亿元，配置必须写成：

```python
"params": {"min_amount": 10_000}
```

现有 heat 的：

```python
"params": {"min_amount": 30_000}
```

表示成交额至少 3 亿元。禁止在 `filter_snapshot_amount()` 内部再次换算单位；金额单位只由快照数据定义和策略配置共同约定。

#### 10.3 ST/退过滤是固定业务过滤，不属于策略配置

`run_snapshot_filters()` 当前执行顺序是：

```text
先固定执行 filter_snapshot_excluded_names
再执行具体策略的 snapshot_filters
```

因此 `VOLUME_BREAKOUT_CONFIG["snapshot_filters"]` 不重复加入 ST/退条件。为了避免文档和代码产生歧义，最终方案明确：

- ST/退过滤始终执行；
- 它不由策略配置控制；
- 它不属于放量突破的可配置策略条件；
- `layers` 仍然记录一层“ST/退市”，用于控制台日志和 JSON 结果。

#### 10.4 MACD EMA 口径对齐 AlphaSift

AlphaSift 原实现使用：

```python
ema12 = close.ewm(span=12, adjust=False).mean()
ema26 = close.ewm(span=26, adjust=False).mean()
diff = ema12 - ema26
dea = diff.ewm(span=9, adjust=False).mean()
```

`adjust=False` 的 EMA 冷启动以第一根有效收盘价作为初始值。Cassa 的 `_ema()` 必须保持同样口径；不能改成 SMA 初始值，也不能使用 `adjust=True`。

MACD 状态规则保持一致：

```text
DIF > DEA 且 DIF > 0  -> bullish
DIF < DEA 且 DIF < 0  -> bearish
其他                  -> neutral
历史不足 35 根          -> neutral
```

由于第一版读取 120 根日 K，正常情况下 MACD 有足够历史数据；不足 35 根时仍按 `neutral` 处理，与 AlphaSift 原策略一致。

#### 10.5 横盘天数口径对齐 AlphaSift

`consolidation_days_20d` 的计算范围是当前 K 线之前的最多 20 根 K 线，不包含当前突破 K 线：

```python
previous = klines[max(0, index - 20):index]
```

然后从 20 天向下检查到 2 天，每次只取距离当前最近的 `days` 根：

```python
for days in range(min(len(previous), 20), 1, -1):
    window = previous[-days:]
    if range_pct(window) <= 12.0:
        return days
return 0
```

这与 AlphaSift 的 `_consolidation_days()` 实现一致。它表达的是“突破前最近一段连续整理区间的最长天数”，不是在 20 天历史中任意寻找一个满足条件的窗口。

#### 10.6 `KlineRecord` 指标字段均为本轮新增

当前 Cassa `screen2.py` 的 `KlineRecord` 只有基础 OHLC、成交量、成交额，以及：

```python
change_pct
volume_ratio
```

当前不存在以下字段，本轮需要新增：

```python
ma5
ma20
ma60
macd_diff
macd_dea
macd_status
prev_high_20d
breakout_20d_pct
range_20d_pct
volume_ratio_20d
body_pct
consolidation_days_20d
```

这些字段全部设置默认值 `None`，不影响 heat：heat 不调用日 K 指标计算函数，也不依赖这些字段。

#### 10.7 `run_heat()` 本轮同步改造

通用化 `build_result()` 后，`run_heat()` 必须同步传入 `HEAT_CONFIG`：

```python
result = build_result(
    records,
    layers,
    started_at,
    HEAT_CONFIG,
)
```

这样 heat 和 volume-breakout 都使用同一套 result 结构，但各自输出正确的 `strategy`、`title` 和 `conditions`。

#### 10.8 `load_breakout_kline()` 本轮保留

本轮不删除 `data.load_breakout_kline()`。原因是旧版 `screen.py` 仍有多处调用，直接删除会影响尚未迁移的旧策略。

本轮只做以下约束：

- 新的 `screen2.py volume-breakout` 统一调用 `data.load_daily_kline(codes, count=120)`；
- `screen2.py` 不再调用 `data.load_breakout_kline()`；
- 旧 `screen.py` 继续使用现有接口；
- 待旧策略全部迁移、旧入口退役后，再单独删除 `load_breakout_kline()` 及其专用辅助逻辑。

#### 10.9 快照实时字段回填必须接入主流程

`apply_snapshot_latest_fields()` 不能只作为孤立辅助函数，必须接入 `run_volume_breakout()` 主流程。调用位置固定在：

```text
build_stock_records_with_daily_kline
  -> 构建 snapshot_map
  -> apply_snapshot_latest_fields
  -> ensure_kline_records
  -> 执行日K条件过滤
```

完整代码如下：

```python
records = build_stock_records_with_daily_kline(
    snapshot_rows,
    kline_map,
)

snapshot_map = {
    row["code"]: row
    for row in snapshot_rows
    if row.get("code")
}

for record in records:
    apply_snapshot_latest_fields(
        record,
        snapshot_map.get(record.code, {}),
    )

records = ensure_kline_records(records)
```

`apply_snapshot_latest_fields()` 写入的是最新 K 线的原始实时字段，不会修改 MA、MACD 或 20 日形态指标；因此放在 `ensure_kline_records()` 前后都不会影响指标计算，但统一规定放在指标计算前，便于保证候选记录组装完成后再进入指标阶段。

该回填步骤解决两个问题：

1. `change_pct` 和实时 `volume_ratio` 不属于 `daily_kline` 数据库表，必须从快照补入。
2. `serialize_record()` 和控制台输出读取最新 `KlineRecord`，否则放量突破结果中的最新涨幅会一直是 `None`。

如果某个候选股票在 `snapshot_map` 中不存在，使用空字典并保留 `None`，不能按缺失数据伪造默认涨幅或量比。

## 股票资料更新开关

### 1. 目标

当前 `update-daily-kline` 每次都会顺序调用全市场股票基础信息接口和板块关系接口：

```text
股票基础信息：约 50 秒
板块关系：约 286 秒
日K：正常执行
```

板块关系不是每次日 K 更新都必须刷新，因此为两类资料增加独立开关。参数只使用 `on` 和 `off` 两种值，不引入额外的正反参数。

默认值：

```text
stock_basic=on
sectors=off
```

默认执行日 K 更新时，继续维护股票名称和总股本，但完全跳过行业、概念接口请求和 `stock_sector` 写入。

### 2. CLI 参数

新增参数：

```python
update_daily_kline_parser.add_argument(
    "--stock-basic",
    choices=("on", "off"),
    default="on",
    help="是否更新股票名称和总股本：on/off，默认 on",
)
update_daily_kline_parser.add_argument(
    "--sectors",
    choices=("on", "off"),
    default="off",
    help="是否更新股票行业和概念：on/off，默认 off",
)
```

执行示例：

```bash
# 默认：更新 stock_basic，跳过 stock_sector
python data.py update-daily-kline --count 1

# 更新基础信息和板块关系
python data.py update-daily-kline --count 1 --stock-basic on --sectors on

# 只更新板块关系，保留旧 stock_basic
python data.py update-daily-kline --count 1 --stock-basic off --sectors on

# 两类资料都跳过，只更新日K
python data.py update-daily-kline --count 1 --stock-basic off --sectors off
```

参数解析后转换为布尔值：

```python
update_stock_basic = stock_basic_mode == "on"
update_sectors = sectors_mode == "on"
```

### 3. 数据维护函数

#### 3.1 支持按开关采集资料

`refresh_stock_metadata()` 必须先根据开关决定是否调用接口。关闭的资料不得请求接口，也不得清空或写入对应数据表。

```python
def refresh_stock_metadata(
    stock_codes,
    *,
    update_stock_basic=True,
    update_sectors=False,
):
    """按开关获取资料，并事务替换已开启的资料表。"""
    if not update_stock_basic and not update_sectors:
        print("[股票资料] stock_basic=off，sectors=off，跳过资料更新")
        return {"stock_basic": 0, "stock_sector": 0}

    updated_at = datetime.now().isoformat(timespec="seconds")
    basic_rows = None
    sector_rows = None

    print(
        f"[股票资料] stock_basic={'on' if update_stock_basic else 'off'}，"
        f"sectors={'on' if update_sectors else 'off'}"
    )

    if update_stock_basic:
        basic_rows = collect_stock_basic_rows(stock_codes, updated_at)
    else:
        print("[股票基础信息] 已关闭，跳过网络请求和数据库写入")

    if update_sectors:
        sector_rows = collect_stock_sector_rows(stock_codes, updated_at)
    else:
        print("[板块关系] 已关闭，跳过网络请求和数据库写入")

    replace_stock_metadata(
        stock_basic_rows=basic_rows,
        stock_sector_rows=sector_rows,
        update_stock_basic=update_stock_basic,
        update_sectors=update_sectors,
    )
    return {
        "stock_basic": len(basic_rows or []),
        "stock_sector": len(sector_rows or []),
    }
```

#### 3.2 事务只替换开启的表

全量替换仍然使用事务，但关闭的表必须保持原数据：

```python
def replace_stock_metadata(
    stock_basic_rows=None,
    stock_sector_rows=None,
    *,
    update_stock_basic=True,
    update_sectors=False,
):
    """在一个事务中替换已开启的资料表，失败时回滚。"""
    conn = ensure_database()
    migrate_stock_tables(conn)
    started_at = time.perf_counter()

    try:
        print(
            "[股票资料] 开始事务："
            f"stock_basic={'替换' if update_stock_basic else '保留'}，"
            f"stock_sector={'替换' if update_sectors else '保留'}"
        )
        conn.execute("BEGIN")

        if update_stock_basic:
            conn.execute("DELETE FROM stock_basic")
            conn.executemany(
                """INSERT INTO stock_basic
                   (code, name, total_shares, updated_at)
                   VALUES (?, ?, ?, ?)""",
                [
                    (
                        row["code"],
                        row["name"],
                        row["total_shares"],
                        row["updated_at"],
                    )
                    for row in (stock_basic_rows or [])
                ],
            )

        if update_sectors:
            conn.execute("DELETE FROM stock_sector")
            conn.executemany(
                """INSERT INTO stock_sector
                   (code, sector_type, sector_code, sector_name, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                [
                    (
                        row["code"],
                        row["sector_type"],
                        row["sector_code"],
                        row["sector_name"],
                        row["updated_at"],
                    )
                    for row in (stock_sector_rows or [])
                ],
            )

        conn.commit()
        elapsed = time.perf_counter() - started_at
        print(
            f"[股票资料] 事务提交完成："
            f"stock_basic={'已替换' if update_stock_basic else '保留'}，"
            f"stock_sector={'已替换' if update_sectors else '保留'}，"
            f"耗时 {elapsed:.1f}s"
        )
    except Exception as exc:
        conn.rollback()
        elapsed = time.perf_counter() - started_at
        print(
            f"[股票资料] 事务失败，已回滚并保留旧数据：{exc}，"
            f"耗时 {elapsed:.1f}s"
        )
        raise
```

该函数沿用 `ensure_database()` 返回的全局连接，不调用 `conn.close()`。关闭开关表示保留原表数据，而不是删除原表数据。

### 4. `update_daily_kline_after_close()` 完整调整

更新函数增加两个参数，并在股票列表获取完成后调用资料刷新：

```python
def update_daily_kline_after_close(
    count=DAILY_KLINE_UPDATE_DAYS,
    batch_size=DAILY_KLINE_UPDATE_BATCH_SIZE,
    stock_basic_mode="on",
    sectors_mode="off",
):
    """按开关更新股票资料，并更新全部 A 股最近 N 天日K。"""
    started_at = time.perf_counter()

    update_stock_basic = stock_basic_mode == "on"
    update_sectors = sectors_mode == "on"

    print(
        f"[日K更新] 开始更新全部A股日K：count={count}，"
        f"batch_size={batch_size}"
    )
    print(
        f"[股票资料] stock_basic={stock_basic_mode}，"
        f"sectors={sectors_mode}"
    )

    print("[日K更新] 阶段 1/3：获取全市场股票列表...")
    list_started_at = time.perf_counter()
    stock_rows = get_stock_list()
    stock_list = extract_stock_codes_from_stock_list(stock_rows)
    print(
        f"[日K更新] 阶段 1/3 完成：获取 {len(stock_list)} 只股票，"
        f"耗时 {time.perf_counter() - list_started_at:.1f}s"
    )

    if not stock_list:
        print("[日K更新] 未获取到股票列表，结束本次更新")
        return {
            "stock_count": 0,
            "updated_rows": 0,
            "count": count,
            "batch_size": batch_size,
        }

    print("[日K更新] 阶段 2/3：更新股票资料...")
    metadata_started_at = time.perf_counter()
    try:
        stats = refresh_stock_metadata(
            stock_list,
            update_stock_basic=update_stock_basic,
            update_sectors=update_sectors,
        )
        print(
            f"[日K更新] 阶段 2/3 完成："
            f"stock_basic={stats['stock_basic']}，"
            f"stock_sector={stats['stock_sector']}，"
            f"耗时 {time.perf_counter() - metadata_started_at:.1f}s"
        )
    except Exception as exc:
        print(f"[股票资料] 更新失败，旧资料保留：{exc}")
        print("[日K更新] 继续执行日K更新")

    print("[日K更新] 阶段 3/3：开始拉取日K...")
    kline_started_at = time.perf_counter()
    batches = chunk_list(stock_list, batch_size)
    total_updated_rows = 0

    for batch_index, stock_batch in enumerate(batches, 1):
        batch_started_at = time.perf_counter()
        first_code = stock_batch[0]
        last_code = stock_batch[-1]
        print(
            f"[日K更新] 第 {batch_index}/{len(batches)} 批开始："
            f"{len(stock_batch)} 只，{first_code} ~ {last_code}"
        )
        try:
            market_data = get_market_data(
                stock_list=stock_batch,
                period="1d",
                count=count,
                field_list=["Open", "High", "Low", "Close", "Volume", "Amount"],
                fill_data=True,
            )
            rows = market_data_to_daily_kline_rows(market_data, stock_batch)
            updated_rows = upsert_daily_kline_rows(rows)
        except Exception as exc:
            print(
                f"[日K更新] 第 {batch_index}/{len(batches)} 批失败："
                f"{first_code} ~ {last_code}，错误：{exc}"
            )
            raise

        total_updated_rows += updated_rows
        print(
            f"[日K更新] 第 {batch_index}/{len(batches)} 批完成："
            f"写入 {updated_rows} 行，本批耗时 "
            f"{time.perf_counter() - batch_started_at:.1f}s，"
            f"日K累计耗时 {time.perf_counter() - kline_started_at:.1f}s"
        )

    elapsed = time.perf_counter() - started_at
    print(
        f"[日K更新] 全部完成：股票 {len(stock_list)} 只，"
        f"写入/覆盖 {total_updated_rows} 行，总耗时 {elapsed:.1f}s"
    )
    return {
        "stock_count": len(stock_list),
        "updated_rows": total_updated_rows,
        "count": count,
        "batch_size": batch_size,
        "stock_basic": stock_basic_mode,
        "sectors": sectors_mode,
        "elapsed_seconds": round(elapsed, 1),
    }
```

实际落地时保留现有日 K 批次实现，只把函数签名、阶段日志和资料刷新参数接入；不要重复维护两套日 K 拉取循环。

### 5. CLI 完整接入

在 `update-daily-kline` 子命令中加入参数：

```python
update_daily_kline_parser.add_argument(
    "--stock-basic",
    choices=("on", "off"),
    default="on",
    help="是否更新股票名称和总股本：on/off，默认 on",
)
update_daily_kline_parser.add_argument(
    "--sectors",
    choices=("on", "off"),
    default="off",
    help="是否更新股票行业和概念：on/off，默认 off",
)
```

在命令分发处传入参数：

```python
elif args.command == "update-daily-kline":
    print_json(
        update_daily_kline_after_close(
            count=args.count,
            batch_size=args.batch_size,
            stock_basic_mode=args.stock_basic,
            sectors_mode=args.sectors,
        )
    )
```

帮助文本和示例同步增加：

```text
python data.py update-daily-kline --count 1
python data.py update-daily-kline --count 1 --stock-basic on --sectors on
python data.py update-daily-kline --count 1 --stock-basic off --sectors on
python data.py update-daily-kline --count 1 --stock-basic off --sectors off
```

### 6. 验证要求

1. 不传参数时，确认 `stock_basic=on`、`sectors=off`。
2. 默认执行日志中不能出现 `get_relation()` 的逐股请求，也不能出现板块采集进度。
3. `--sectors on` 时，两张表按现有事务逻辑更新，成功提交、失败回滚。
4. `--stock-basic off --sectors on` 时，只替换 `stock_sector`，`stock_basic` 保持不变。
5. `--stock-basic off --sectors off` 时，两张资料表都不修改，只更新日 K。
6. 关闭某个开关不能清空对应表，旧数据必须保留。
7. 资料更新失败后，保留旧资料并继续执行日 K 更新，沿用当前错误处理策略。
8. 最终汇总需要显示两个开关状态，便于确认本次到底执行了哪些工作。

### 7. 与现有执行日志的最终合并口径

本节解决本章与前一章“为 `update-daily-kline` 添加执行日志”之间的阶段编号和日志内容冲突，实施时以本节为准。

#### 7.1 保留四阶段结构

不回退到“资料合并为一个阶段”的三阶段结构，继续保留四阶段日志，因为基础信息和板块关系是两个耗时差异明显、开关也独立的工作：

```text
阶段 1/4：获取全市场股票列表
阶段 2/4：获取股票基础信息
阶段 3/4：获取股票行业和概念
阶段 4/4：拉取并写入日K
```

开关关闭时，阶段仍然打印，但明确标记跳过，不发起接口请求：

```text
[日K更新] 阶段 2/4：股票基础信息更新已关闭，跳过
[日K更新] 阶段 3/4：板块关系更新已关闭，跳过
```

这样每次运行的日志结构稳定，同时可以直接看出耗时来自哪个阶段。

#### 7.2 删除旧的重复阶段头

`refresh_stock_metadata()` 只负责按开关采集和替换数据表，不再打印以下阶段头：

```python
print("[日K更新] 阶段 2/4：正在获取股票基础信息...")
print("[日K更新] 阶段 3/4：正在获取股票行业和概念...")
```

这两行必须删除。阶段头统一由 `update_daily_kline_after_close()` 外层打印，采集函数内部只打印自己的进度：

```text
[股票基础信息] 开始获取：共 5535 只
[股票基础信息] 进度：500/5535...
[板块关系] 开始获取：共 5535 只
[板块关系] 进度：500/5535...
```

不能让内层函数继续打印 `[日K更新] 阶段 X/4`，否则会出现阶段日志重复和编号错乱。

#### 7.3 完整性检查只针对已开启的表

保留完整性检查，但只检查本次实际开启更新的资料表。

基础信息开启时必须满足：

```python
if update_stock_basic and len(basic_rows or []) != len(stock_codes):
    raise RuntimeError("股票基础信息未完整获取，取消本次数据库替换")
```

板块关系开启时必须至少确认采集函数正常完成；板块接口允许某些股票没有行业或概念关系，因此不能用“关系行数等于股票数”作为完整性条件。可以检查返回对象不是 `None`：

```python
if update_sectors and sector_rows is None:
    raise RuntimeError("板块关系未完成获取，取消本次板块表替换")
```

当开关关闭时，不执行对应检查：

```python
basic_rows = None
sector_rows = None

if update_stock_basic:
    basic_rows = collect_stock_basic_rows(stock_codes, updated_at)
    if len(basic_rows) != len(stock_codes):
        raise RuntimeError("股票基础信息未完整获取，取消本次数据库替换")

if update_sectors:
    sector_rows = collect_stock_sector_rows(stock_codes, updated_at)
    if sector_rows is None:
        raise RuntimeError("板块关系未完成获取，取消本次板块表替换")
```

不能执行以下无条件检查：

```python
if len(basic_rows) != len(stock_codes):
    ...
```

因为 `stock_basic=off` 时 `basic_rows` 必须是 `None`，且数据库中的旧基础资料应被保留。

#### 7.4 四阶段主流程日志

外层 `update_daily_kline_after_close()` 使用以下日志结构：

```python
print("[日K更新] 阶段 1/4：正在获取全市场股票列表...")
# get_stock_list()
print("[日K更新] 阶段 1/4 完成：获取 N 只股票，耗时 X.Xs")

if update_stock_basic:
    print("[日K更新] 阶段 2/4：正在更新股票基础信息...")
    # collect_stock_basic_rows() + 事务内写入 stock_basic
    print("[日K更新] 阶段 2/4 完成：stock_basic=N，耗时 X.Xs")
else:
    print("[日K更新] 阶段 2/4：股票基础信息更新已关闭，跳过")

if update_sectors:
    print("[日K更新] 阶段 3/4：正在更新股票行业和概念...")
    # collect_stock_sector_rows() + 事务内写入 stock_sector
    print("[日K更新] 阶段 3/4 完成：stock_sector=N，耗时 X.Xs")
else:
    print("[日K更新] 阶段 3/4：板块关系更新已关闭，跳过")

print("[日K更新] 阶段 4/4：开始拉取日K...")
# 日K批次循环
print("[日K更新] 阶段 4/4 完成：股票 N 只，写入/覆盖 M 行，耗时 X.Xs")
print("[日K更新] 全部完成：总耗时 X.Xs")
```

资料表的全量替换仍然要求：网络采集先完成，之后在事务中写入已开启的表。若基础信息和板块同时开启，可以在同一个资料事务中完成两张表替换；日志仍按两个业务阶段分别输出采集进度，事务提交日志统一输出一次。

#### 7.5 日 K 阶段必须打印完成日志

接受增加明确的阶段完成日志，不能只输出“全部完成”：

```text
[日K更新] 阶段 4/4 完成：股票 5535 只，写入/覆盖 5535 行，耗时 62.6s
[日K更新] 全部完成：总耗时 120.4s
```

“阶段 4/4 完成”只统计日 K 阶段耗时；“全部完成”统计从股票列表开始到日 K 结束的全流程耗时。

#### 7.6 保留每批累计写入行数

保留现有每批日志中的累计行数，同时增加“日 K 阶段累计耗时”：

```python
print(
    f"[日K更新] 第 {batch_index}/{total_batches} 批完成："
    f"本批写入 {updated_rows} 行，累计 {total_updated_rows} 行，"
    f"本批耗时 {batch_seconds:.1f}s，"
    f"日K累计耗时 {time.perf_counter() - kline_started_at:.1f}s"
)
```

这里保留两个不同的累计概念：

- `累计 N 行`：日 K 已经写入或覆盖的总行数；
- `日K累计耗时 X.Xs`：从阶段 4/4 开始到当前批次结束的耗时。

最终阶段日志中同时输出总行数和日 K 阶段耗时，避免把资料更新耗时误认为日 K 接口耗时。

#### 7.7 当前 CLI 入口的实际改动点

现有 `data.py` 已经有 `update-daily-kline` 子命令，并且已有：

```python
update_daily_kline_parser.add_argument("--count", ...)
update_daily_kline_parser.add_argument("--batch-size", ...)
```

本轮只在这两个参数后增加：

```python
update_daily_kline_parser.add_argument(
    "--stock-basic",
    choices=("on", "off"),
    default="on",
    help="是否更新股票名称和总股本：on/off，默认 on",
)
update_daily_kline_parser.add_argument(
    "--sectors",
    choices=("on", "off"),
    default="off",
    help="是否更新股票行业和概念：on/off，默认 off",
)
```

现有分发代码是：

```python
elif args.command == "update-daily-kline":
    print_json(update_daily_kline_after_close(args.count, args.batch_size))
```

改为关键字传参，避免新增参数位置错位：

```python
elif args.command == "update-daily-kline":
    print_json(
        update_daily_kline_after_close(
            count=args.count,
            batch_size=args.batch_size,
            stock_basic_mode=args.stock_basic,
            sectors_mode=args.sectors,
        )
    )
```

这样解决四个日志决策：保留四阶段、删除内层重复阶段头、增加阶段 4/4 完成日志、保留每批累计写入行数。
