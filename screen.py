"""
Cassa 选股脚本。

第一版先实现箱体判断、放量突破判断，以及从全部 A 股出发的选股扫描入口。
放量突破选股通过 data.load_breakout_kline 获取 K 线。
"""

import argparse
import json
from pathlib import Path

import data


DEFAULT_BOX_RANGE_MAX = 0.30
DEFAULT_VOLUME_RATIO_MIN = 1.5
DEFAULT_BOX_DAYS = 20
DEFAULT_BATCH_SIZE = 500


def print_json(value):
    """按 JSON 打印结果。"""
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def calculate_box_metrics(kline_bars):
    """计算一段 K 线的箱体核心指标。"""
    if not kline_bars:
        return {
            "bar_count": 0,
            "top_price": 0.0,
            "bottom_price": 0.0,
            "range_pct": 0.0,
            "average_volume": 0.0,
        }

    top_price = max(float(bar["high_price"]) for bar in kline_bars)
    bottom_price = min(float(bar["low_price"]) for bar in kline_bars)
    range_pct = ((top_price - bottom_price) / bottom_price) if bottom_price > 0 else 0.0
    average_volume = sum(float(bar["volume"]) for bar in kline_bars) / len(kline_bars)

    return {
        "bar_count": len(kline_bars),
        "top_price": round(top_price, 4),
        "bottom_price": round(bottom_price, 4),
        "range_pct": round(range_pct, 6),
        "average_volume": round(average_volume, 4),
    }


def is_box_consolidation(kline_bars, range_max=DEFAULT_BOX_RANGE_MAX):
    """判断一段 K 线是否是箱体。"""
    if len(kline_bars) < 2:
        return False

    metrics = calculate_box_metrics(kline_bars)
    return metrics["range_pct"] <= float(range_max)


def is_volume_breakout_from_box(
    box_kline_bars,
    breakout_kline,
    range_max=DEFAULT_BOX_RANGE_MAX,
    volume_ratio_min=DEFAULT_VOLUME_RATIO_MIN,
):
    """判断第二个参数 K 线是否放量突破前面箱体。"""
    if not is_box_consolidation(box_kline_bars, range_max=range_max):
        return False

    if not breakout_kline:
        return False

    metrics = calculate_box_metrics(box_kline_bars)
    breakout_close = float(breakout_kline["close_price"])
    breakout_volume = float(breakout_kline["volume"])
    average_volume = float(metrics["average_volume"])

    if average_volume <= 0:
        return False

    is_price_breakout = breakout_close > float(metrics["top_price"])
    is_volume_breakout = breakout_volume >= average_volume * float(volume_ratio_min)
    return is_price_breakout and is_volume_breakout


def analyze_box_consolidation(kline_bars, range_max=DEFAULT_BOX_RANGE_MAX):
    """输出箱体判断结果和指标。"""
    metrics = calculate_box_metrics(kline_bars)
    return {
        "is_box": is_box_consolidation(kline_bars, range_max=range_max),
        "range_max": float(range_max),
        **metrics,
    }


def analyze_volume_breakout_from_box(
    box_kline_bars,
    breakout_kline,
    range_max=DEFAULT_BOX_RANGE_MAX,
    volume_ratio_min=DEFAULT_VOLUME_RATIO_MIN,
):
    """输出放量突破判断结果和指标。"""
    box_metrics = calculate_box_metrics(box_kline_bars)
    breakout_close = float(breakout_kline["close_price"]) if breakout_kline else 0.0
    breakout_volume = float(breakout_kline["volume"]) if breakout_kline else 0.0
    average_volume = float(box_metrics["average_volume"])
    breakout_volume_ratio = (breakout_volume / average_volume) if average_volume > 0 else 0.0

    return {
        "is_box": is_box_consolidation(box_kline_bars, range_max=range_max),
        "is_breakout": is_volume_breakout_from_box(
            box_kline_bars=box_kline_bars,
            breakout_kline=breakout_kline,
            range_max=range_max,
            volume_ratio_min=volume_ratio_min,
        ),
        "range_max": float(range_max),
        "volume_ratio_min": float(volume_ratio_min),
        "breakout_trade_date": breakout_kline.get("trade_date", "") if breakout_kline else "",
        "breakout_close": round(breakout_close, 4),
        "breakout_volume": round(breakout_volume, 4),
        "breakout_volume_ratio": round(breakout_volume_ratio, 6),
        **box_metrics,
    }


def get_all_a_share_codes():
    """获取全部 A 股股票代码。"""
    stock_rows = data.get_stock_list()
    return data.extract_stock_codes_from_stock_list(stock_rows)


def filter_box_consolidation(stock_codes, kline_map, box_days, range_max=DEFAULT_BOX_RANGE_MAX):
    """从股票列表中筛出前 box_days 根 K 线处于箱体的股票。"""
    passed_codes = []
    for stock_code in stock_codes:
        kline_bars = kline_map.get(stock_code, [])
        if len(kline_bars) < box_days + 1:
            continue
        if is_box_consolidation(kline_bars[:-1], range_max=range_max):
            passed_codes.append(stock_code)

    return passed_codes


def filter_current_box_consolidation(stock_codes, kline_map, box_days, range_max=DEFAULT_BOX_RANGE_MAX):
    """从股票列表中筛出最近 box_days 根 K 线处于箱体的股票。"""
    passed_codes = []
    box_detail_map = {}

    for stock_code in stock_codes:
        kline_bars = kline_map.get(stock_code, [])
        if len(kline_bars) < box_days:
            continue

        box_kline_bars = kline_bars[-box_days:]
        if is_box_consolidation(box_kline_bars, range_max=range_max):
            passed_codes.append(stock_code)
            box_detail_map[stock_code] = analyze_box_consolidation(
                box_kline_bars,
                range_max=range_max,
            )

    return passed_codes, box_detail_map


def filter_volume_breakout(
    stock_codes,
    kline_map,
    box_days,
    range_max=DEFAULT_BOX_RANGE_MAX,
    volume_ratio_min=DEFAULT_VOLUME_RATIO_MIN,
):
    """从股票列表中筛出最后一根 K 线放量突破前面箱体的股票。"""
    passed_codes = []
    breakout_detail_map = {}

    for stock_code in stock_codes:
        kline_bars = kline_map.get(stock_code, [])
        if len(kline_bars) < box_days + 1:
            continue

        box_kline_bars = kline_bars[:-1]
        breakout_kline = kline_bars[-1]
        if is_volume_breakout_from_box(
            box_kline_bars=box_kline_bars,
            breakout_kline=breakout_kline,
            range_max=range_max,
            volume_ratio_min=volume_ratio_min,
        ):
            passed_codes.append(stock_code)
            breakout_detail_map[stock_code] = analyze_volume_breakout_from_box(
                box_kline_bars=box_kline_bars,
                breakout_kline=breakout_kline,
                range_max=range_max,
                volume_ratio_min=volume_ratio_min,
            )

    return passed_codes, breakout_detail_map


def run_layer(layer_name, input_codes, filter_func, layer_records):
    """执行一层筛选并记录通过数量。"""
    before_count = len(input_codes)
    output_codes = filter_func(input_codes)
    after_count = len(output_codes)
    removed_count = before_count - after_count

    print(
        f"[选股] {layer_name}: "
        f"输入 {before_count}，通过 {after_count}，淘汰 {removed_count}"
    )

    layer_records.append(
        {
            "layer": layer_name,
            "input_count": before_count,
            "passed_count": after_count,
            "removed_count": removed_count,
        }
    )

    return output_codes


def screen_box_consolidation(
    box_days=DEFAULT_BOX_DAYS,
    breakout_date="",
    range_max=DEFAULT_BOX_RANGE_MAX,
    batch_size=DEFAULT_BATCH_SIZE,
):
    """从全部 A 股中筛选当前仍处于箱体震荡的股票。"""
    all_stock_codes = get_all_a_share_codes()
    if not all_stock_codes:
        raise RuntimeError("未获取到全部 A 股股票列表")

    layer_records = []
    print(f"[选股] 初始股票池：{len(all_stock_codes)}")
    kline_map = data.load_breakout_kline(
        stock_list=all_stock_codes,
        box_days=box_days,
        breakout_date=breakout_date,
        batch_size=batch_size,
    )

    box_codes, box_detail_map = filter_current_box_consolidation(
        stock_codes=all_stock_codes,
        kline_map=kline_map,
        box_days=box_days,
        range_max=range_max,
    )
    final_codes = run_layer(
        layer_name="箱体震荡筛选",
        input_codes=all_stock_codes,
        filter_func=lambda codes: box_codes,
        layer_records=layer_records,
    )

    print(f"[选股] 最终入选：{len(final_codes)}")

    selected_items = []
    for stock_code in final_codes:
        item = {
            "code": stock_code,
            "breakout_date": breakout_date or "",
        }
        item.update(box_detail_map.get(stock_code, {}))
        selected_items.append(item)

    return {
        "strategy": "box_consolidation",
        "breakout_date": breakout_date or "",
        "box_days": int(box_days),
        "range_max": float(range_max),
        "initial_count": len(all_stock_codes),
        "selected_count": len(final_codes),
        "selected_codes": final_codes,
        "selected_items": selected_items,
        "layers": layer_records,
    }


def screen_volume_breakout(
    box_days=DEFAULT_BOX_DAYS,
    breakout_date="",
    range_max=DEFAULT_BOX_RANGE_MAX,
    volume_ratio_min=DEFAULT_VOLUME_RATIO_MIN,
    batch_size=DEFAULT_BATCH_SIZE,
):
    """从全部 A 股中筛选放量突破箱体的股票。"""
    all_stock_codes = get_all_a_share_codes()
    if not all_stock_codes:
        raise RuntimeError("未获取到全部 A 股股票列表")

    layer_records = []
    print(f"[选股] 初始股票池：{len(all_stock_codes)}")
    kline_map = data.load_breakout_kline(
        stock_list=all_stock_codes,
        box_days=box_days,
        breakout_date=breakout_date,
        batch_size=batch_size,
    )

    box_codes = run_layer(
        layer_name="箱体区间筛选",
        input_codes=all_stock_codes,
        filter_func=lambda codes: filter_box_consolidation(
            stock_codes=codes,
            kline_map=kline_map,
            box_days=box_days,
            range_max=range_max,
        ),
        layer_records=layer_records,
    )

    breakout_codes, breakout_detail_map = filter_volume_breakout(
        stock_codes=box_codes,
        kline_map=kline_map,
        box_days=box_days,
        range_max=range_max,
        volume_ratio_min=volume_ratio_min,
    )
    final_codes = run_layer(
        layer_name="放量突破筛选",
        input_codes=box_codes,
        filter_func=lambda codes: breakout_codes,
        layer_records=layer_records,
    )

    print(f"[选股] 最终入选：{len(final_codes)}")

    selected_items = []
    for stock_code in final_codes:
        item = {
            "code": stock_code,
            "breakout_date": breakout_date or "",
        }
        item.update(breakout_detail_map.get(stock_code, {}))
        selected_items.append(item)

    return {
        "strategy": "volume_breakout",
        "breakout_date": breakout_date or "",
        "box_days": int(box_days),
        "kline_count": int(box_days) + 1,
        "range_max": float(range_max),
        "volume_ratio_min": float(volume_ratio_min),
        "initial_count": len(all_stock_codes),
        "selected_count": len(final_codes),
        "selected_codes": final_codes,
        "selected_items": selected_items,
        "layers": layer_records,
    }


def main():
    """支持全 A 股箱体震荡和放量突破扫描。"""
    parser = argparse.ArgumentParser(
        description="Cassa 选股脚本：从全部 A 股扫描箱体震荡和放量突破。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_breakout_parser = subparsers.add_parser(
        "scan-breakout",
        help="从全部 A 股扫描放量突破箱体的股票",
        description=(
            "从全部 A 股出发，先筛出处于箱体区间的股票，"
            "再筛出最后一根 K 线放量突破箱体上沿的股票。"
        ),
    )
    scan_breakout_parser.add_argument(
        "--box-days",
        type=int,
        default=DEFAULT_BOX_DAYS,
        help=f"箱体区间的 K 线根数，默认 {DEFAULT_BOX_DAYS}",
    )
    scan_breakout_parser.add_argument(
        "--breakout-date",
        default="",
        help="突破 K 的交易日，格式 YYYY-MM-DD；不传则使用最新 K 线",
    )
    scan_breakout_parser.add_argument(
        "--range-max",
        type=float,
        default=DEFAULT_BOX_RANGE_MAX,
        help=f"箱体振幅上限，默认 {DEFAULT_BOX_RANGE_MAX}",
    )
    scan_breakout_parser.add_argument(
        "--volume-ratio-min",
        type=float,
        default=DEFAULT_VOLUME_RATIO_MIN,
        help=f"放量倍数下限，默认 {DEFAULT_VOLUME_RATIO_MIN}",
    )
    scan_breakout_parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"每批拉取多少只股票 K 线，默认 {DEFAULT_BATCH_SIZE}",
    )

    scan_box_parser = subparsers.add_parser(
        "scan-box",
        help="从全部 A 股扫描当前仍处于箱体震荡的股票",
        description="从全部 A 股出发，筛出最近 N 根 K 线仍处于箱体震荡的股票。",
    )
    scan_box_parser.add_argument(
        "--box-days",
        type=int,
        default=DEFAULT_BOX_DAYS,
        help=f"箱体区间的 K 线根数，默认 {DEFAULT_BOX_DAYS}",
    )
    scan_box_parser.add_argument(
        "--breakout-date",
        default="",
        help="观察日，格式 YYYY-MM-DD；不传则使用今天/最新 K 线",
    )
    scan_box_parser.add_argument(
        "--range-max",
        type=float,
        default=DEFAULT_BOX_RANGE_MAX,
        help=f"箱体振幅上限，默认 {DEFAULT_BOX_RANGE_MAX}",
    )
    scan_box_parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"每批拉取多少只股票 K 线，默认 {DEFAULT_BATCH_SIZE}",
    )

    args = parser.parse_args()
    data.initialize(Path(__file__))

    if args.command == "scan-breakout":
        result = screen_volume_breakout(
            box_days=args.box_days,
            breakout_date=args.breakout_date,
            range_max=args.range_max,
            volume_ratio_min=args.volume_ratio_min,
            batch_size=args.batch_size,
        )
        print_json(result)
        return

    if args.command == "scan-box":
        result = screen_box_consolidation(
            box_days=args.box_days,
            breakout_date=args.breakout_date,
            range_max=args.range_max,
            batch_size=args.batch_size,
        )
        print_json(result)


if __name__ == "__main__":
    main()
