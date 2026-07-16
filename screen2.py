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
        "SECUCODE", "code", "name", "price", "change_pct",
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
    if not isinstance(columns, list) or not isinstance(rows, list):
        raise ValueError(f"快照结构不合法: {path}")
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

        stock_info = data.get_stock_info(code, field_list=[]) or {}
        more_info = data.get_more_info(code, field_list=[]) or {}
        total_shares = safe_float(stock_info.get("J_zgb"))
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

    codes = [row["code"] for row in snapshot_rows]
    step_started = time.perf_counter()
    kline_map = data.load_daily_kline(
        stock_list=codes,
        count=HEAT_CONFIG["kline_count"],
    )
    print(f"[候选日K] {len(kline_map)} 只, 用时 {time.perf_counter() - step_started:.2f}s")
    records = build_stock_records(snapshot_rows, kline_map)

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
