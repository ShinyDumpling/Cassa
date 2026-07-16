from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import data
from rich.console import Console
from rich.table import Table
from rich.text import Text


CONSOLE = Console()

SNAPSHOT_KLINE_COUNT = 7
SNAPSHOT_DIR = Path(__file__).resolve().parent / "data" / "snapshot"
EXCLUDE_NAME_KEYWORDS = ("ST", "退")
SNAPSHOT_COLUMNS = [
    "SECUCODE", "code", "name",
    "open_price", "high_price", "low_price", "close_price", "volume",
    "price", "change_pct", "volume_ratio", "amount",
    "turnover_rate", "pe_ratio", "pb_ratio", "total_mv",
    "MAX_TRADE_DATE",
]
SNAPSHOT_REQUIRED_COLUMNS = {
    "code", "name", "open_price", "high_price", "low_price",
    "close_price", "volume", "amount", "MAX_TRADE_DATE",
}


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
        f"[快照筛选] {layer.name}: {layer.input_count} -> {layer.output_count}, "
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
    data_rows = [[row.get(column) for column in SNAPSHOT_COLUMNS] for row in rows]
    return {
        "version": 1,
        "created_at": datetime.utcnow().isoformat() + "+00:00",
        "metadata": {
            "snapshot_source": source,
            "row_count": len(data_rows),
            "columns": SNAPSHOT_COLUMNS,
        },
        "frame": {
            "columns": SNAPSHOT_COLUMNS,
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
    if not isinstance(columns, list) or not isinstance(rows, list):
        raise ValueError(f"快照结构不合法: {path}")
    if not rows:
        raise ValueError(f"快照为空: {path}")
    missing = SNAPSHOT_REQUIRED_COLUMNS - set(columns)
    if missing:
        raise ValueError(f"旧版快照缺少字段: {sorted(missing)}")
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


def fetch_more_info_map(codes):
    """逐只获取通达信扩展信息 more_info，返回 code -> dict。"""
    result = {}
    for code in codes:
        try:
            result[code] = data.get_more_info(code, field_list=[]) or {}
        except Exception as exc:
            print(f"[more_info] {code} 失败: {exc}")
            result[code] = {}
    return result


def build_snapshot_rows(stock_rows, kline_map, more_info_map):
    """组装快照行：仅使用本地 stock_basic + 7 根 K 线 + more_info。"""
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

        more_info = more_info_map.get(code) or {}
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
    """全市场 7 根 K 线 + more_info + 组装 + 落盘，分段计时。"""
    codes = [row["code"] for row in stock_rows if row.get("code")]

    step = time.perf_counter()
    kline_map = data.load_daily_kline(stock_list=codes, count=SNAPSHOT_KLINE_COUNT)
    print(f"[快照] 读取/生成 7 根 K 线: {len(kline_map)} 只, 用时 {time.perf_counter() - step:.2f}s")

    step = time.perf_counter()
    more_info_map = fetch_more_info_map(codes)
    print(f"[快照] 获取全市场 more_info: {len(more_info_map)} 只, 用时 {time.perf_counter() - step:.2f}s")

    step = time.perf_counter()
    rows = build_snapshot_rows(stock_rows, kline_map, more_info_map)
    print(f"[快照] 组装快照: {len(rows)} 只, 用时 {time.perf_counter() - step:.2f}s")
    if not rows:
        raise RuntimeError("未生成任何有效市场快照数据")

    step = time.perf_counter()
    path = snapshot_path()
    write_snapshot(path, rows)
    print(f"[快照] 写入文件: {path}, 用时 {time.perf_counter() - step:.2f}s")
    return rows


def load_or_generate_snapshot(stock_rows, snapshot_mode="local"):
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
    """按涨跌幅过滤。"""
    return [row for row in rows if (safe_float(row.get("change_pct"), -1) or -1) >= min_change_pct]


def filter_snapshot_change_pct_max(rows, max_change_pct):
    """按快照涨跌幅上限过滤。"""
    result = []
    for row in rows:
        value = safe_float(row.get("change_pct"))
        if value is not None and value <= max_change_pct:
            result.append(row)
    return result


# ---------- 日K指标 ----------

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
    """计算指数移动平均序列，adjust=False 冷启动以首个有效值为初始。"""
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
    if len(values) != period or any(v is None for v in values):
        return None
    return _average(values)


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
    """突破前最近连续整理区间的最长天数（不含当前 K 线）。"""
    if len(previous) < 2:
        return None
    for days in range(min(len(previous), 20), 1, -1):
        window = previous[-days:]
        highs = [_positive_float(item.high_price) for item in window]
        lows = [_positive_float(item.low_price) for item in window]
        if any(v is None for v in highs + lows):
            continue
        low = min(lows)
        if low <= 0:
            continue
        range_pct = (max(highs) / low - 1) * 100
        if range_pct <= max_range_pct:
            return days
    return 0


def calculate_kline_indicators(klines):
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
        # 历史不足 35 根统一 neutral（与 AlphaSift 一致）
        if index + 1 < 35:
            current.macd_status = "neutral"
        else:
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
        if len(recent) == 20 and all(v is not None for v in highs + lows) and min(lows) > 0:
            current.range_20d_pct = (max(highs) / min(lows) - 1) * 100
        else:
            current.range_20d_pct = None

        previous_volumes = [_positive_float(item.volume) for item in previous]
        average_volume = _average(previous_volumes)
        current_volume = _positive_float(current.volume)
        if (
            len(previous) == 20
            and all(v is not None for v in previous_volumes)
            and current_volume is not None
            and average_volume
            and average_volume > 0
        ):
            current.volume_ratio_20d = current_volume / average_volume
        else:
            current.volume_ratio_20d = None

        current_open = _positive_float(current.open_price)
        current.body_pct = (
            (current_close / current_open - 1) * 100
            if current_close is not None and current_open is not None else None
        )
        current.consolidation_days_20d = _consolidation_days(previous)


def ensure_kline_indicators(record):
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


def apply_snapshot_latest_fields(record, snapshot_row):
    """把快照中的最新实时字段写入候选记录的最新日K。"""
    if not record.kline:
        return record
    latest = record.kline[-1]
    latest.change_pct = safe_float(snapshot_row.get("change_pct"))
    latest.volume_ratio = safe_float(snapshot_row.get("volume_ratio"))
    return record


# ---------- 日K条件 ----------

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


def run_snapshot_filters(rows, filters):
    """执行固定过滤和 heat 快照条件，返回筛选结果及步骤记录。"""
    layers = []
    started = time.perf_counter()
    filtered = filter_snapshot_excluded_names(rows)
    layers.append(timed_layer("ST/退市", rows, filtered, started))

    for item in filters:
        started = time.perf_counter()
        before = filtered
        filtered = item["function"](filtered, **item.get("params", {}))
        layers.append(timed_layer(item["name"], before, filtered, started))
    return filtered, layers


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
            change_pct=(
                float(row["change_pct"])
                if row.get("change_pct") is not None else None
            ),
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


def serialize_record(record):
    """把 StockRecord 转换为最终 selected 项。"""
    latest = asdict(record.kline[-1]) if record.kline else None
    display = build_display_sector_fields(record.sectors)
    return {
        "code": record.code,
        "name": record.name,
        "change_pct": record.kline[-1].change_pct if record.kline else None,
        "industry": display["industry"],
        "concepts": display["concepts"],
        "sectors": [asdict(item) for item in record.sectors],
        "latest_kline": latest,
    }


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


def print_screen_result(result, debug=False):
    """统一输出任意选股策略的控制台结果。"""
    if debug:
        CONSOLE.print_json(json.dumps(result, ensure_ascii=False))
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

    table = Table(title="选股结果", expand=True, show_lines=True)
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


def run_heat(debug=False, snapshot_mode="local"):
    """执行第一版 heat 选股流程。"""
    started_at = time.perf_counter()
    print("开始执行策略: heat")

    step = time.perf_counter()
    stock_rows = data.load_stock_basic_records()
    print(f"[股票基础信息] 读取本地 stock_basic: {len(stock_rows)} 只, 用时 {time.perf_counter() - step:.2f}s")

    snapshot_rows = load_or_generate_snapshot(stock_rows, snapshot_mode=snapshot_mode)

    snapshot_rows, layers = run_snapshot_filters(
        snapshot_rows, HEAT_CONFIG["snapshot_filters"]
    )

    records = build_stock_records_from_snapshot(snapshot_rows)

    step = time.perf_counter()
    records = ensure_sectors(records)
    print(f"[板块补齐] {len(records)} 只, 用时 {time.perf_counter() - step:.2f}s")

    result = build_result(records, layers, started_at, HEAT_CONFIG)
    print_screen_result(result, debug=debug)
    return result


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


VOLUME_BREAKOUT_CONFIG = {
    "strategy": "volume_breakout",
    "title": "放量突破",
    "kline_count": 120,
    "snapshot_filters": [
        {
            "name": "成交额",
            "function": filter_snapshot_amount,
            "params": {"min_amount": 10_000},
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
        # {
        #     "name": "涨幅上限",
        #     "function": filter_snapshot_change_pct_max,
        #     "params": {"max_change_pct": 9.9},
        # },
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

    snapshot_map = {row["code"]: row for row in snapshot_rows if row.get("code")}
    for record in records:
        apply_snapshot_latest_fields(record, snapshot_map.get(record.code, {}))

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


def build_arg_parser():
    """构建 screen2 子命令解析器。"""
    parser = argparse.ArgumentParser(description="Cassa stock screening")
    subparsers = parser.add_subparsers(dest="command", required=True)

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
    return parser


def main():
    """screen2.py 命令行入口。"""
    parser = build_arg_parser()
    args = parser.parse_args()
    data.initialize(Path(__file__))
    if args.command == "heat":
        run_heat(debug=args.debug, snapshot_mode=args.snapshot_mode)
    elif args.command == "volume-breakout":
        run_volume_breakout(debug=args.debug, snapshot_mode=args.snapshot_mode)


if __name__ == "__main__":
    main()
