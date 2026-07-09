"""
Cassa 业务逻辑脚本。

第一阶段只实现 report 结构化数据包。
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
    # 当前 data.load_daily_kline 会读取本地 DB，并用通达信最近 K 线覆盖或追加返回结果。
    # 后续如果 data.py 新增 report 专用函数，应切换为更精确的 120 历史 + 1 实时口径。
    kline_by_code = data.load_daily_kline([code], count=history_count)
    return kline_by_code.get(code, [])


def convert_macd_result_to_array(raw_macd, code):
    """把 formula_process_mul_zb 的 MACD 返回结果转换成数组。

    当前先按通达信常见返回结构做保守转换；后续写代码时必须真实调用验证。
    """
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

        trade_date = (
            dif_item.get("Date")
            or dea_item.get("Date")
            or macd_item.get("Date")
            or ""
        )
        result.append(
            {
                "date": trade_date,
                "dif": dif_item.get("Value"),
                "dea": dea_item.get("Value"),
                "macd": macd_item.get("Value"),
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


def print_json(value):
    """把结构化结果按 JSON 打印。"""
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def main():
    """业务脚本 CLI 入口。"""
    parser = argparse.ArgumentParser(description="Cassa 业务逻辑脚本。")
    subparsers = parser.add_subparsers(dest="command", required=True)

    report_parser = subparsers.add_parser("report", help="生成 report 结构化数据包")
    report_parser.add_argument(
        "--codes",
        required=True,
        help="股票或板块代码，多个用逗号分隔，例如 600519,000001,880675.SH",
    )

    args = parser.parse_args()

    data.initialize(Path(__file__))

    if args.command == "report":
        codes = [code.strip() for code in args.codes.split(",") if code.strip()]
        print_json(build_report_data(codes))


if __name__ == "__main__":
    main()
