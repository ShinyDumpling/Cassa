"""
Cassa 业务逻辑脚本。

第一阶段实现 report 结构化数据包和控制台报告输出。
业务入口由 Agent Skill 控制，本脚本只负责返回 JSON 结构化数据。
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

import data


PROJECT_ROOT = Path(__file__).resolve().parent
STOCK_SH_PREFIXES = ("5", "6", "9")
STOCK_SZ_PREFIXES = ("0", "1", "2", "3")
STOCK_BJ_PREFIXES = ("920", "4", "8")
MARKET_SUFFIXES = {"SH", "SZ", "BJ"}
REPORT_HISTORY_COUNT = 120
REPORT_WITH_REALTIME_COUNT = REPORT_HISTORY_COUNT + 1


def has_market_suffix(code):
    """判断 code 是否已经带通达信市场后缀。"""
    normalized_code = str(code).strip().upper()
    if "." not in normalized_code:
        return False
    _, suffix = normalized_code.rsplit(".", maxsplit=1)
    return suffix in MARKET_SUFFIXES


def strip_code_suffix(code):
    """去掉 code 的市场后缀，返回纯代码部分。"""
    normalized_code = str(code).strip().upper()
    if "." in normalized_code:
        return normalized_code.split(".", maxsplit=1)[0]
    return normalized_code


def infer_stock_market_suffix(internal_code):
    """根据纯数字股票代码推断通达信市场后缀。"""
    if not internal_code:
        raise ValueError("股票代码不能为空。")
    if not str(internal_code).isdigit():
        raise ValueError(f"股票代码必须是纯数字：{internal_code}")

    if str(internal_code).startswith(STOCK_BJ_PREFIXES):
        return "BJ"
    if str(internal_code).startswith(STOCK_SH_PREFIXES):
        return "SH"
    if str(internal_code).startswith(STOCK_SZ_PREFIXES):
        return "SZ"

    raise ValueError(f"无法根据股票代码推断市场后缀：{internal_code}")


def normalize_stock_code(code):
    """把用户输入的个股代码规整为带后缀的通达信代码。"""
    normalized_code = str(code).strip().upper()
    if has_market_suffix(normalized_code):
        return normalized_code

    internal_code = strip_code_suffix(normalized_code)
    suffix = infer_stock_market_suffix(internal_code)
    return f"{internal_code}.{suffix}"


def build_sector_lookup(sector_rows):
    """把通达信板块列表转换成便于按原始输入匹配的索引。"""
    lookup = {}
    for row in sector_rows or []:
        sector_code = str(row.get("Code", "")).strip().upper()
        sector_name = str(row.get("Name", "")).strip()
        if not sector_code:
            continue

        pure_code = strip_code_suffix(sector_code)
        sector_item = {
            "target_type": "sector",
            "code": sector_code,
            "pure_code": pure_code,
            "name": sector_name,
            "source": "sector_list",
            "raw_sector": row,
        }

        lookup[sector_code] = sector_item
        lookup[pure_code] = sector_item
        if sector_name:
            lookup[sector_name.upper()] = sector_item

    return lookup


def resolve_report_code(code, sector_lookup):
    """判断单个 code 是板块还是个股，并返回统一目标结构。"""
    raw_code = str(code).strip()
    normalized_key = raw_code.upper()
    pure_key = strip_code_suffix(normalized_key)

    sector_item = sector_lookup.get(normalized_key) or sector_lookup.get(pure_key)
    if sector_item is not None:
        return {
            "raw_code": raw_code,
            "target_type": "sector",
            "code": sector_item["code"],
            "name": sector_item["name"],
            "source": sector_item["source"],
            "raw_sector": sector_item["raw_sector"],
        }

    stock_code = normalize_stock_code(raw_code)
    return {
        "raw_code": raw_code,
        "target_type": "stock",
        "code": stock_code,
        "name": "",
        "source": "stock_prefix_rule",
    }


def resolve_report_codes(codes):
    """批量解析 report 输入 code。"""
    sector_rows = data.get_sector_list(list_type=1)
    sector_lookup = build_sector_lookup(sector_rows)
    return [resolve_report_code(code, sector_lookup) for code in codes]


def safe_float(value, default=0.0):
    """把接口返回值尽量转换成 float。"""
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def format_number(value, digits=2):
    """格式化普通数字。"""
    return f"{safe_float(value):.{digits}f}"


def format_signed_percent(value):
    """格式化带正负号的百分比。"""
    return f"{safe_float(value):+.2f}%"


def get_kline_value(row, *keys):
    """从不同命名风格的 K 线字典中读取数值。"""
    for key in keys:
        if key in row:
            return safe_float(row.get(key))
    return 0.0


def calculate_average(values, period):
    """计算最近 period 个值的平均数。"""
    if len(values) < period or period <= 0:
        return 0.0
    return sum(values[-period:]) / period


def calculate_bias(current_price, average_price):
    """计算价格相对均线的乖离率。"""
    if average_price <= 0:
        return 0.0
    return (current_price - average_price) / average_price * 100


def map_relation_type(block_type):
    """把通达信 BlockType 映射成稳定英文类型。"""
    block_type_text = str(block_type or "").strip()
    mapping = {
        "行业": "industry",
        "概念": "concept",
        "地域": "region",
        "风格": "style",
    }
    return mapping.get(block_type_text, "other")


def map_relation_rows(relation_rows):
    """给 get_relation 返回的所属板块数组补充 mapped_type 字段。"""
    mapped_rows = []
    for row in relation_rows or []:
        mapped_row = dict(row)
        mapped_row["mapped_type"] = map_relation_type(mapped_row.get("BlockType"))
        mapped_rows.append(mapped_row)
    return mapped_rows


def extract_industry_and_concepts(relation_rows):
    """从所属板块数组中提取行业和概念名称。"""
    industries = []
    concepts = []
    for row in relation_rows or []:
        block_name = str(row.get("BlockName", "") or "").strip()
        if not block_name:
            continue
        mapped_type = row.get("mapped_type") or map_relation_type(row.get("BlockType"))
        if mapped_type == "industry" and block_name not in industries:
            industries.append(block_name)
        elif mapped_type == "concept" and block_name not in concepts:
            concepts.append(block_name)
    return "、".join(industries), concepts


def collect_realtime_report_data(code):
    """采集 report 所需实时数据。"""
    market_snapshot = data.get_market_snapshot(code)
    stock_info = data.get_stock_info(code, field_list=[])
    more_info = data.get_more_info(code, field_list=[])
    relation = map_relation_rows(data.get_relation(code))

    name = ""
    if isinstance(stock_info, dict):
        name = str(stock_info.get("Name", "") or "").strip()
    if not name and isinstance(more_info, dict):
        name = str(more_info.get("Name", "") or "").strip()

    return {
        "name": name,
        "market_snapshot": market_snapshot,
        "stock_info": stock_info,
        "more_info": more_info,
        "relation": relation,
    }


def collect_daily_kline_for_report(code, history_count=REPORT_HISTORY_COUNT):
    """采集 120 根历史日 K，并拼接或覆盖最新 1 根实时 K。"""
    kline_by_code = data.load_daily_kline([code], count=history_count)
    return kline_by_code.get(code, [])


def convert_macd_result_to_array(raw_macd, code):
    """把 formula_process_mul_zb 的 MACD 返回结果转换成数组。"""
    if not isinstance(raw_macd, dict):
        return []
    code_macd = raw_macd.get(code)
    if not isinstance(code_macd, dict):
        return []

    dif_rows = code_macd.get("DIF", []) or []
    dea_rows = code_macd.get("DEA", []) or []
    macd_rows = code_macd.get("MACD", []) or []
    max_len = max(len(dif_rows), len(dea_rows), len(macd_rows))

    result = []
    for index in range(max_len):
        dif_item = dif_rows[index] if index < len(dif_rows) else {}
        dea_item = dea_rows[index] if index < len(dea_rows) else {}
        macd_item = macd_rows[index] if index < len(macd_rows) else {}
        result.append(
            {
                "date": dif_item.get("Date") or dea_item.get("Date") or macd_item.get("Date") or "",
                "dif": safe_float(dif_item.get("Value")),
                "dea": safe_float(dea_item.get("Value")),
                "macd": safe_float(macd_item.get("Value")),
            }
        )
    return result


def collect_macd_for_report(code, count=REPORT_WITH_REALTIME_COUNT):
    """采集 report 所需 MACD 数组，默认 120 根历史 + 最新 1 根。"""
    raw_macd = data.formula_process_mul_zb(
        formula_name="MACD",
        formula_arg="12,26,9",
        stock_list=[code],
        stock_period="1d",
        count=count,
        return_count=count,
        return_date=True,
    )
    return convert_macd_result_to_array(raw_macd, code)


def create_chip_placeholder():
    """返回筹码分布 TODO 占位。"""
    return {
        "status": "todo",
        "data": None,
        "note": "筹码分布待接入",
    }


def collect_report_item(target):
    """采集单个 report 目标的结构化数据。"""
    code = target["code"]
    realtime_data = collect_realtime_report_data(code)
    return {
        "raw_code": target.get("raw_code", ""),
        "target_type": target.get("target_type", ""),
        "code": code,
        "name": realtime_data["name"] or target.get("name", ""),
        "market_snapshot": realtime_data["market_snapshot"],
        "stock_info": realtime_data["stock_info"],
        "more_info": realtime_data["more_info"],
        "relation": realtime_data["relation"],
        "daily_kline": collect_daily_kline_for_report(code),
        "macd": collect_macd_for_report(code),
        "chip": create_chip_placeholder(),
    }


def build_report_data(codes):
    """构建 report 结构化数据包。"""
    targets = resolve_report_codes(codes)
    items = []
    errors = []

    for target in targets:
        try:
            items.append(collect_report_item(target))
        except Exception as exc:
            errors.append(
                {
                    "raw_code": target.get("raw_code", ""),
                    "code": target.get("code", ""),
                    "target_type": target.get("target_type", ""),
                    "error": str(exc),
                }
            )

    return {
        "task": "report",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "items": items,
        "errors": errors,
    }


def calculate_today_quote(item):
    """从 market_snapshot 中计算当日行情。"""
    snapshot = item.get("market_snapshot") or {}
    today_open = safe_float(snapshot.get("Open"))
    today_high = safe_float(snapshot.get("Max"))
    today_low = safe_float(snapshot.get("Min"))
    current_price = safe_float(snapshot.get("Now"))
    yesterday_close = safe_float(snapshot.get("LastClose"))
    price_change = current_price - yesterday_close if current_price > 0 and yesterday_close > 0 else 0.0
    price_change_pct = price_change / yesterday_close * 100 if yesterday_close > 0 else 0.0
    amplitude = (today_high - today_low) / yesterday_close * 100 if yesterday_close > 0 else 0.0
    return {
        "today_open": today_open,
        "today_high": today_high,
        "today_low": today_low,
        "current_price": current_price,
        "yesterday_close": yesterday_close,
        "price_change": price_change,
        "price_change_pct": price_change_pct,
        "amplitude": amplitude,
    }


def calculate_moving_average(item, current_price):
    """从 daily_kline 中计算均线和乖离率。"""
    close_values = [
        get_kline_value(row, "close_price", "Close", "close")
        for row in item.get("daily_kline") or []
    ]
    close_values = [value for value in close_values if value > 0]
    ma5 = calculate_average(close_values, 5)
    ma10 = calculate_average(close_values, 10)
    ma20 = calculate_average(close_values, 20)
    ma60 = calculate_average(close_values, 60)
    return {
        "ma5": ma5,
        "ma10": ma10,
        "ma20": ma20,
        "ma60": ma60,
        "bias_ma5": calculate_bias(current_price, ma5),
        "bias_ma10": calculate_bias(current_price, ma10),
        "bias_ma20": calculate_bias(current_price, ma20),
        "bias_ma60": calculate_bias(current_price, ma60),
    }


def calculate_macd_status(item):
    """从 macd 数组中判断最新 MACD 状态。"""
    rows = item.get("macd") or []
    if not rows:
        return {"status": "无数据", "signal": "无数据", "dif": 0.0, "dea": 0.0, "bar": 0.0}
    latest = rows[-1]
    previous = rows[-2] if len(rows) >= 2 else {}
    dif = safe_float(latest.get("dif"))
    dea = safe_float(latest.get("dea"))
    bar = safe_float(latest.get("macd"))
    previous_dif = safe_float(previous.get("dif"))
    previous_dea = safe_float(previous.get("dea"))
    previous_bar = safe_float(previous.get("macd"))

    if previous_dif <= previous_dea and dif > dea:
        status = "金叉"
    elif previous_dif >= previous_dea and dif < dea:
        status = "死叉"
    elif dif > dea and bar > 0:
        status = "多头"
    elif dif < dea and bar < 0:
        status = "空头"
    else:
        status = "震荡"

    if bar >= 0 and bar >= previous_bar:
        signal = "红柱放大"
    elif bar >= 0:
        signal = "红柱缩小"
    elif bar < previous_bar:
        signal = "绿柱放大"
    else:
        signal = "绿柱缩小"

    return {"status": status, "signal": signal, "dif": dif, "dea": dea, "bar": bar}


def calculate_support_resistance(item, current_price, ma_values):
    """基于均线和近 20 日高低点计算支撑压力。"""
    support = []
    resistance = []
    for key in ["ma5", "ma10", "ma20", "ma60"]:
        value = safe_float(ma_values.get(key))
        if value <= 0:
            continue
        if current_price > 0 and value <= current_price:
            support.append(value)
        elif current_price > 0:
            resistance.append(value)

    recent_rows = (item.get("daily_kline") or [])[-20:]
    lows = [get_kline_value(row, "low_price", "Low", "low") for row in recent_rows]
    highs = [get_kline_value(row, "high_price", "High", "high") for row in recent_rows]
    lows = [value for value in lows if value > 0]
    highs = [value for value in highs if value > 0]
    if lows:
        support.append(min(lows))
    if highs:
        resistance.append(max(highs))
    return sorted({round(value, 2) for value in support}, reverse=True)[:4], sorted({round(value, 2) for value in resistance})[:4]


def calculate_trend_signal(today_quote, ma_values, volume_status, macd_status):
    """计算控制台展示用趋势、信号、理由和风险。"""
    score = 50
    reasons = []
    risks = []
    current_price = safe_float(today_quote.get("current_price"))
    ma20 = safe_float(ma_values.get("ma20"))

    if current_price > ma20 > 0:
        score += 10
        reasons.append("价格站上MA20")
    else:
        score -= 10
        risks.append("价格未站上MA20")

    if macd_status.get("status") in {"金叉", "多头"}:
        score += 10
        reasons.append(f"MACD{macd_status.get('status')}")
    elif macd_status.get("status") in {"死叉", "空头"}:
        score -= 10
        risks.append(f"MACD{macd_status.get('status')}")

    if volume_status in {"温和放量", "明显放量"}:
        score += 5
        reasons.append(volume_status)
    elif volume_status == "缩量":
        score -= 5
        risks.append("缩量")

    if safe_float(today_quote.get("price_change_pct")) > 7:
        risks.append("短线涨幅较大")
    if safe_float(today_quote.get("amplitude")) > 8:
        risks.append("日内振幅较大")

    score = max(0, min(100, score))
    if score >= 80:
        buy_signal = "可关注"
    elif score >= 60:
        buy_signal = "观察"
    elif score >= 40:
        buy_signal = "谨慎观察"
    else:
        buy_signal = "暂不参与"

    if score >= 75:
        trend_status = "强势上涨"
    elif score >= 60:
        trend_status = "震荡上行"
    elif score >= 40:
        trend_status = "震荡"
    else:
        trend_status = "弱势下跌"

    return trend_status, score, buy_signal, reasons, risks


def format_report_item(item):
    """格式化单个 report item，风格对齐旧 cassa.py report。"""
    relation = item.get("relation") or []
    industry, concepts = extract_industry_and_concepts(relation)
    today = calculate_today_quote(item)
    current_price = safe_float(today.get("current_price"))
    ma_values = calculate_moving_average(item, current_price)
    macd_status = calculate_macd_status(item)
    support, resistance = calculate_support_resistance(item, current_price, ma_values)
    more_info = item.get("more_info") or {}
    stock_info = item.get("stock_info") or {}
    volume_ratio = safe_float(more_info.get("fLianB"))
    turnover_rate = safe_float(more_info.get("fHSL"))

    if volume_ratio >= 2.0:
        volume_status = "明显放量"
    elif volume_ratio >= 1.2:
        volume_status = "温和放量"
    elif 0 < volume_ratio < 0.8:
        volume_status = "缩量"
    else:
        volume_status = "平量"

    trend_status, score, buy_signal, reasons, risks = calculate_trend_signal(
        today, ma_values, volume_status, macd_status
    )

    total_shares = safe_float(stock_info.get("J_zgb"))
    market_cap = total_shares * current_price / 10000 if total_shares > 0 and current_price > 0 else 0.0

    lines = [f"=== {item.get('code', '')} {item.get('name', '')} ===".rstrip()]
    info_parts = []
    if industry:
        info_parts.append(f"行业: {industry}")
    if concepts:
        info_parts.append(f"概念: {'、'.join(concepts)}")
    if info_parts:
        lines.append("  ".join(info_parts))

    lines.append(
        f"当日: 开{format_number(today['today_open'])} 高{format_number(today['today_high'])} "
        f"低{format_number(today['today_low'])} 收{format_number(today['current_price'])} "
        f"{format_signed_percent(today['price_change_pct'])} 振幅{format_number(today['amplitude'])}%"
    )
    lines.append(f"趋势: {trend_status} ({score}/100)    信号: {buy_signal} ({score}分)")
    lines.append(
        f"现价: {format_number(current_price)}  "
        f"MA5: {format_number(ma_values['ma5'])}({format_signed_percent(ma_values['bias_ma5'])})  "
        f"MA10: {format_number(ma_values['ma10'])}({format_signed_percent(ma_values['bias_ma10'])})  "
        f"MA20: {format_number(ma_values['ma20'])}({format_signed_percent(ma_values['bias_ma20'])})"
    )
    turnover_text = f"  换手: {turnover_rate:.1f}%" if turnover_rate > 0 else ""
    lines.append(
        f"量能: {volume_status} ({volume_ratio:.2f})      "
        f"MACD: {macd_status['status']}    RSI: 待接入"
        f"{turnover_text}"
    )

    valuation_parts = []
    if safe_float(more_info.get("DynaPE")) > 0 or safe_float(more_info.get("PB_MRQ")) > 0:
        valuation_parts.append(
            f"PE(动){safe_float(more_info.get('DynaPE')):.1f}  "
            f"PE(TTM){safe_float(more_info.get('StaticPE_TTM')):.1f}  "
            f"PB{safe_float(more_info.get('PB_MRQ')):.2f}"
        )
    if market_cap > 0:
        valuation_parts.append(f"总市值{market_cap:.1f}亿")
    if valuation_parts:
        lines.append(f"基本面: {'  '.join(valuation_parts)}")

    net_buy_amount = safe_float(more_info.get("Zjl"))
    main_net_inflow = safe_float(more_info.get("Zjl_HB"))
    if net_buy_amount != 0 or main_net_inflow != 0:
        lines.append(f"资金: 主买净额{net_buy_amount:.0f}万  主力净流入{main_net_inflow:.0f}万")

    support_text = ", ".join(format_number(value) for value in support) if support else "无"
    resistance_text = ", ".join(format_number(value) for value in resistance) if resistance else "无"
    lines.append(f"支撑: {support_text}  压力: {resistance_text}")

    if reasons:
        lines.append(f"理由: {'  '.join(reasons)}")
    if risks:
        lines.append(f"风险: {'  '.join(risks)}")
    return "\n".join(lines)


def render_console_report(payload):
    """渲染完整控制台报告文本。"""
    items = payload.get("items") or []
    lines = [f"个股趋势报告：{len(items)} 只股票", ""]
    for index, item in enumerate(items):
        lines.append(format_report_item(item))
        if index < len(items) - 1:
            lines.append("")

    errors = payload.get("errors") or []
    if errors:
        lines.append("")
        lines.append(f"跳过 {len(errors)} 只:")
        for error in errors:
            lines.append(f"  - {error.get('raw_code', '') or error.get('code', '')}: {error.get('error', '')}")
    return "\n".join(lines)


def print_json(value):
    """把结构化结果按 JSON 打印。"""
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def run_report(args):
    """执行 report 子命令。"""
    codes = [code.strip() for code in args.codes.split(",") if code.strip()]
    payload = build_report_data(codes)
    print(render_console_report(payload))
    if args.debug:
        print()
        print("=== DEBUG JSON ===")
        print_json(payload)


def main():
    """业务脚本 CLI 入口。"""
    parser = argparse.ArgumentParser(description="Cassa 业务逻辑脚本。")
    subparsers = parser.add_subparsers(dest="command", required=True)

    report_parser = subparsers.add_parser("report", help="生成 report 控制台输出")
    report_parser.add_argument(
        "--codes",
        required=True,
        help="股票或板块代码，多个用逗号分隔，例如 600519,000001,880675.SH",
    )
    report_parser.add_argument("--debug", action="store_true", help="追加打印完整 JSON")
    report_parser.set_defaults(handler=run_report)

    args = parser.parse_args()
    data.initialize(Path(__file__))
    args.handler(args)


if __name__ == "__main__":
    main()
