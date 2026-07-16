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
