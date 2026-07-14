"""
Cassa 业务逻辑脚本。

第一阶段实现 report 结构化数据包和控制台报告输出。
业务入口由 Agent Skill 控制，本脚本只负责返回 JSON 结构化数据。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from py_mini_racer import MiniRacer

import data


PROJECT_ROOT = Path(__file__).resolve().parent
STOCK_SH_PREFIXES = ("5", "6", "9")
STOCK_SZ_PREFIXES = ("0", "1", "2", "3")
STOCK_BJ_PREFIXES = ("920", "4", "8")
MARKET_SUFFIXES = {"SH", "SZ", "BJ"}
REPORT_HISTORY_COUNT = 120
REPORT_WITH_REALTIME_COUNT = REPORT_HISTORY_COUNT + 1

TREND_RSI_OVERBOUGHT = 70
TREND_RSI_OVERSOLD = 30
TREND_VOLUME_SHRINK_RATIO = 0.7
TREND_VOLUME_HEAVY_RATIO = 1.5
TREND_MA_SUPPORT_TOLERANCE = 0.02
TREND_BIAS_THRESHOLD = 5.0
TREND_STRONG_BULL_BIAS_RELAX = 1.5
TREND_STRONG_BULL_STRENGTH_THRESHOLD = 70

CYQ_JS_PATH = PROJECT_ROOT / "cyq_calculator.js"


def safe_float(value, default=None):
    try:
        if value is None or value == "":
            return default
        result = float(value)
        if pd.isna(result):
            return default
        return result
    except (TypeError, ValueError):
        return default


def load_cyq_js_code():
    """读取独立保存的筹码分布 JS 算法文件。"""
    return CYQ_JS_PATH.read_text(encoding="utf-8")


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


def get_kline_value(row, *keys):
    """从不同命名风格的 K 线字典中读取数值。"""
    for key in keys:
        if key in row:
            return safe_float(row.get(key))
    return 0.0


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


def calculate_sma(values, period):
    """计算简单移动平均线，长度与输入一致。"""
    result = []
    for index in range(len(values)):
        if index + 1 < period:
            result.append(0.0)
        else:
            result.append(sum(values[index + 1 - period : index + 1]) / period)
    return result


def calculate_rsi(closes, period):
    """计算 RSI 指标，复刻旧 cassa.py 的 Wilder's EMA / SMMA 口径。"""
    if len(closes) < 2:
        return [50.0] * len(closes)

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(delta, 0.0) for delta in deltas]
    losses = [max(-delta, 0.0) for delta in deltas]
    alpha = 1.0 / period
    avg_gains = [0.0] * len(gains)
    avg_losses = [0.0] * len(losses)

    if gains:
        avg_gains[0] = sum(gains[:period]) / period if len(gains) >= period else gains[0]
        avg_losses[0] = sum(losses[:period]) / period if len(losses) >= period else losses[0]
        for index in range(1, len(gains)):
            avg_gains[index] = alpha * gains[index] + (1 - alpha) * avg_gains[index - 1]
            avg_losses[index] = alpha * losses[index] + (1 - alpha) * avg_losses[index - 1]

    rsi_values = [50.0]
    for index in range(len(gains)):
        if avg_losses[index] == 0:
            rsi_values.append(100.0)
        else:
            rs = avg_gains[index] / avg_losses[index]
            rsi_values.append(100.0 - 100.0 / (1.0 + rs))
    return rsi_values


def extract_close_values(item):
    """从 daily_kline 中提取收盘价序列。"""
    values = [
        get_kline_value(row, "close_price", "Close", "close")
        for row in item.get("daily_kline") or []
    ]
    return [value for value in values if value > 0]


def extract_high_low_values(item):
    """从 daily_kline 中提取高低点序列。"""
    rows = item.get("daily_kline") or []
    highs = [get_kline_value(row, "high_price", "High", "high") for row in rows]
    lows = [get_kline_value(row, "low_price", "Low", "low") for row in rows]
    return [value for value in highs if value > 0], [value for value in lows if value > 0]


def judge_trend_status(ma5, ma10, ma20):
    """根据最新均线值判断趋势状态，对齐旧 cassa.py 逻辑。"""
    if len(ma5) < 6 or ma5[-1] == 0 or ma20[-1] == 0:
        return "盘整", "均线数据不足", 50.0

    cur_ma5, cur_ma10, cur_ma20 = ma5[-1], ma10[-1], ma20[-1]
    prev_ma5, prev_ma20 = ma5[-6], ma20[-6]

    if cur_ma5 > cur_ma10 > cur_ma20:
        prev_spread = (prev_ma5 - prev_ma20) / prev_ma20 * 100 if prev_ma20 > 0 else 0
        curr_spread = (cur_ma5 - cur_ma20) / cur_ma20 * 100
        if curr_spread > prev_spread and curr_spread > 5:
            return "强势多头", "强势多头排列，均线发散上行", 90.0
        return "多头排列", "多头排列 MA5>MA10>MA20", 75.0

    if cur_ma5 > cur_ma10 and cur_ma10 <= cur_ma20:
        return "弱势多头", "弱势多头，MA5>MA10 但 MA10≤MA20", 55.0

    if cur_ma5 < cur_ma10 < cur_ma20:
        prev_spread = (prev_ma20 - prev_ma5) / prev_ma5 * 100 if prev_ma5 > 0 else 0
        curr_spread = (cur_ma20 - cur_ma5) / cur_ma5 * 100
        if curr_spread > prev_spread and curr_spread > 5:
            return "强势空头", "强势空头排列，均线发散下行", 10.0
        return "空头排列", "空头排列 MA5<MA10<MA20", 25.0

    if cur_ma5 < cur_ma10 and cur_ma10 >= cur_ma20:
        return "弱势空头", "弱势空头，MA5<MA10 但 MA10≥MA20", 40.0

    return "盘整", "均线缠绕，趋势不明", 50.0


def calculate_bias(price, ma5, ma10, ma20):
    """计算 MA5 / MA10 / MA20 乖离率。"""
    bias_ma5 = (price - ma5) / ma5 * 100 if ma5 > 0 else 0.0
    bias_ma10 = (price - ma10) / ma10 * 100 if ma10 > 0 else 0.0
    bias_ma20 = (price - ma20) / ma20 * 100 if ma20 > 0 else 0.0
    return bias_ma5, bias_ma10, bias_ma20


def judge_volume_status(closes, volume_ratio):
    """分析量能状态，复刻旧 cassa.py 口径。"""
    if volume_ratio <= 0 or len(closes) < 2:
        return "量能正常", 0.0, "数据不足"

    prev_close = closes[-2]
    price_change = (closes[-1] - prev_close) / prev_close * 100 if prev_close > 0 else 0.0

    if volume_ratio >= TREND_VOLUME_HEAVY_RATIO:
        if price_change > 0:
            return "放量上涨", volume_ratio, "放量上涨，多头力量强劲"
        return "放量下跌", volume_ratio, "放量下跌，注意风险"
    if volume_ratio <= TREND_VOLUME_SHRINK_RATIO:
        if price_change > 0:
            return "缩量上涨", volume_ratio, "缩量上涨，上攻动能不足"
        return "缩量回调", volume_ratio, "缩量回调，洗盘特征明显（好）"
    return "量能正常", volume_ratio, "量能正常"


def judge_support_resistance(item, ma5, ma10, ma20, current_price):
    """分析支撑压力位，复刻旧 cassa.py 逻辑。"""
    support_ma5 = False
    support_ma10 = False
    support_levels = []
    resistance_levels = []

    if ma5 > 0:
        dist = abs(current_price - ma5) / ma5
        if dist <= TREND_MA_SUPPORT_TOLERANCE and current_price >= ma5:
            support_ma5 = True
            support_levels.append(ma5)

    if ma10 > 0:
        dist = abs(current_price - ma10) / ma10
        if dist <= TREND_MA_SUPPORT_TOLERANCE and current_price >= ma10:
            support_ma10 = True
            if ma10 not in support_levels:
                support_levels.append(ma10)

    if ma20 > 0 and current_price >= ma20:
        support_levels.append(ma20)

    highs, _ = extract_high_low_values(item)
    if len(highs) >= 20:
        recent_high = max(highs[-20:])
        if recent_high > current_price:
            resistance_levels.append(recent_high)

    return support_ma5, support_ma10, support_levels, resistance_levels


def judge_macd_status(item):
    """判断 MACD 状态，对齐旧 cassa.py 逻辑。"""
    rows = item.get("macd") or []
    if len(rows) < 2:
        return 0.0, 0.0, 0.0, "多头", "数据不足"

    cur_dif = safe_float(rows[-1].get("dif"))
    cur_dea = safe_float(rows[-1].get("dea"))
    cur_bar = safe_float(rows[-1].get("macd"))
    prev_dif = safe_float(rows[-2].get("dif"))
    prev_dea = safe_float(rows[-2].get("dea"))

    prev_diff = prev_dif - prev_dea
    curr_diff = cur_dif - cur_dea
    is_golden_cross = prev_diff <= 0 and curr_diff > 0
    is_death_cross = prev_diff >= 0 and curr_diff < 0
    is_crossing_up = prev_dif <= 0 and cur_dif > 0
    is_crossing_down = prev_dif >= 0 and cur_dif < 0

    if is_golden_cross and cur_dif > 0:
        return cur_dif, cur_dea, cur_bar, "零轴上金叉", "零轴上金叉，强烈买入信号"
    if is_crossing_up:
        return cur_dif, cur_dea, cur_bar, "上穿零轴", "DIF上穿零轴，趋势转强"
    if is_golden_cross:
        return cur_dif, cur_dea, cur_bar, "金叉", "金叉，趋势向上"
    if is_death_cross:
        return cur_dif, cur_dea, cur_bar, "死叉", "死叉，趋势向下"
    if is_crossing_down:
        return cur_dif, cur_dea, cur_bar, "下穿零轴", "DIF下穿零轴，趋势转弱"
    if cur_dif > 0 and cur_dea > 0:
        return cur_dif, cur_dea, cur_bar, "多头", "多头排列，持续上涨"
    if cur_dif < 0 and cur_dea < 0:
        return cur_dif, cur_dea, cur_bar, "空头", "空头排列，持续下跌"
    return cur_dif, cur_dea, cur_bar, "多头", "MACD 中性区域"


def judge_rsi_status(rsi_6, rsi_12, rsi_24):
    """判断 RSI 状态，对齐旧 cassa.py 逻辑，以 RSI(12) 为主。"""
    if rsi_12 > TREND_RSI_OVERBOUGHT:
        return "超买", f"RSI超买({rsi_12:.1f}>70)，短期回调风险高"
    if rsi_12 > 60:
        return "强势", f"RSI强势({rsi_12:.1f})，多头力量充足"
    if rsi_12 >= 40:
        return "中性", f"RSI中性({rsi_12:.1f})，震荡整理中"
    if rsi_12 >= TREND_RSI_OVERSOLD:
        return "弱势", f"RSI弱势({rsi_12:.1f})，关注反弹"
    return "超卖", f"RSI超卖({rsi_12:.1f}<30)，反弹机会大"


def calculate_signal_score(
    trend_status,
    trend_strength,
    bias_ma5,
    volume_status,
    support_ma5,
    support_ma10,
    macd_status,
    macd_signal,
    rsi_status,
    rsi_signal,
):
    """综合评分，对齐旧 cassa.py 逻辑。"""
    score = 0
    reasons = []
    risks = []

    trend_scores = {
        "强势多头": 30,
        "多头排列": 26,
        "弱势多头": 18,
        "盘整": 12,
        "弱势空头": 8,
        "空头排列": 4,
        "强势空头": 0,
    }
    score += trend_scores.get(trend_status, 12)
    if trend_status in ("强势多头", "多头排列"):
        reasons.append(f"✅ {trend_status}，顺势做多")
    elif trend_status in ("空头排列", "强势空头"):
        risks.append(f"⚠️ {trend_status}，不宜做多")

    is_strong_bull = (
        trend_status == "强势多头"
        and trend_strength >= TREND_STRONG_BULL_STRENGTH_THRESHOLD
    )
    effective_threshold = TREND_BIAS_THRESHOLD * TREND_STRONG_BULL_BIAS_RELAX if is_strong_bull else TREND_BIAS_THRESHOLD

    if bias_ma5 < 0:
        if bias_ma5 > -3:
            score += 20
            reasons.append(f"✅ 价格略低于MA5({bias_ma5:.1f}%)，回踩买点")
        elif bias_ma5 > -5:
            score += 16
            reasons.append(f"✅ 价格回踩MA5({bias_ma5:.1f}%)，观察支撑")
        else:
            score += 8
            risks.append(f"⚠️ 乖离率过大({bias_ma5:.1f}%)，可能破位")
    elif bias_ma5 < 2:
        score += 18
        reasons.append(f"✅ 价格贴近MA5({bias_ma5:.1f}%)，介入好时机")
    elif bias_ma5 < effective_threshold:
        score += 14
        reasons.append(f"⚡ 价格略高于MA5({bias_ma5:.1f}%)，可小仓介入")
    elif bias_ma5 > effective_threshold:
        score += 4
        risks.append(f"❌ 乖离率过高({bias_ma5:.1f}%>{effective_threshold:.1f}%)，严禁追高")
    elif is_strong_bull:
        score += 10
        reasons.append(f"⚡ 强势趋势中乖离率偏高({bias_ma5:.1f}%)，可轻仓追踪")
    else:
        score += 4
        risks.append(f"❌ 乖离率过高({bias_ma5:.1f}%>{TREND_BIAS_THRESHOLD:.1f}%)，严禁追高")

    volume_scores = {
        "缩量回调": 15,
        "放量上涨": 12,
        "量能正常": 10,
        "缩量上涨": 6,
        "放量下跌": 0,
    }
    score += volume_scores.get(volume_status, 8)
    if volume_status == "缩量回调":
        reasons.append("✅ 缩量回调，主力洗盘")
    elif volume_status == "放量下跌":
        risks.append("⚠️ 放量下跌，注意风险")

    if support_ma5:
        score += 5
        reasons.append("✅ MA5支撑有效")
    if support_ma10:
        score += 5
        reasons.append("✅ MA10支撑有效")

    macd_scores = {
        "零轴上金叉": 15,
        "金叉": 12,
        "上穿零轴": 10,
        "多头": 8,
        "空头": 2,
        "下穿零轴": 0,
        "死叉": 0,
    }
    score += macd_scores.get(macd_status, 5)
    if macd_status in ("零轴上金叉", "金叉"):
        reasons.append(f"✅ {macd_signal}")
    elif macd_status in ("死叉", "下穿零轴"):
        risks.append(f"⚠️ {macd_signal}")
    else:
        reasons.append(macd_signal)

    rsi_scores = {
        "超卖": 10,
        "强势": 8,
        "中性": 5,
        "弱势": 3,
        "超买": 0,
    }
    score += rsi_scores.get(rsi_status, 5)
    if rsi_status in ("超卖", "强势"):
        reasons.append(f"✅ {rsi_signal}")
    elif rsi_status == "超买":
        risks.append(f"⚠️ {rsi_signal}")
    else:
        reasons.append(rsi_signal)

    return score, reasons, risks


def judge_buy_signal(score, trend_status):
    """根据评分和趋势状态生成买入信号，对齐旧 cassa.py 逻辑。"""
    if score >= 75 and trend_status in ("强势多头", "多头排列"):
        return "强烈买入"
    if score >= 60 and trend_status in ("强势多头", "多头排列", "弱势多头"):
        return "买入"
    if score >= 45:
        return "持有"
    if score >= 30:
        return "观望"
    if trend_status in ("空头排列", "强势空头"):
        return "强烈卖出"
    return "卖出"


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


def get_latest_kline_close(item, default=0.0):
    """取最新有效日 K 收盘价，作为 report 计算用价格。"""
    closes = extract_close_values(item)
    if closes:
        return closes[-1]
    return safe_float(default, 0.0)


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


def normalize_trade_date(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y%m%d")
    text = str(value).strip()
    if not text:
        return None
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 8:
        return digits[:8]
    return None


def fetch_gb_history(code: str, daily_kline: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """通过 data.py 获取历史股本信息，business.py 不直接调用 tqcenter。"""
    dates = [normalize_trade_date(row.get("date")) for row in daily_kline if isinstance(row, dict)]
    dates = [date for date in dates if date]
    if not dates:
        return []

    try:
        result = data.get_gb_info_by_date(
            stock_code=code,
            start_date=min(dates),
            end_date=max(dates),
        )
    except Exception:
        return []

    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    if isinstance(result, dict):
        if isinstance(result.get("Value"), list):
            return [item for item in result["Value"] if isinstance(item, dict)]
        return [result]
    return []


def pick_effective_float_capital(record: Dict[str, Any]) -> Optional[float]:
    candidate_keys = [
        "ActiveCapital",
        "activecapital",
        "Ltgb",
        "ltgb",
        "Ltg",
        "LTG",
        "ltg",
        "liutongguben",
        "流通股本",
        "流通股",
        "流通股本数",
    ]
    for key in candidate_keys:
        value = safe_float(record.get(key))
        if value and value > 0:
            return float(value)
    return None


def pick_effective_date(record: Dict[str, Any]) -> Optional[str]:
    candidate_keys = [
        "Date",
        "date",
        "Rq",
        "RQ",
        "EndDate",
        "end_date",
        "StartDate",
        "start_date",
        "GQDJR",
        "BGRQ",
    ]
    for key in candidate_keys:
        normalized = normalize_trade_date(record.get(key))
        if normalized:
            return normalized
    return None


def infer_turnover_scale(
    daily_kline: List[Dict[str, Any]],
    current_turnover_rate,
    reference_float_capital,
    snapshot_volume,
) -> float:
    turnover = safe_float(current_turnover_rate)
    float_capital = safe_float(reference_float_capital)
    if not turnover or turnover <= 0 or not float_capital or float_capital <= 0:
        return 100.0

    latest_daily_volume = None
    if daily_kline:
        latest_daily_volume = safe_float(daily_kline[-1].get("volume") or daily_kline[-1].get("Volume"))

    for candidate in (latest_daily_volume, safe_float(snapshot_volume)):
        if not candidate or candidate <= 0:
            continue
        raw_ratio = float(candidate) / float(float_capital)
        if raw_ratio <= 0:
            continue
        scale = float(turnover) / raw_ratio
        if 0.000001 < scale < 1000000:
            return float(scale)
    return 100.0


def compute_daily_turnover_history(
    daily_kline: List[Dict[str, Any]],
    gb_history: List[Dict[str, Any]],
    current_float_capital,
    current_turnover_rate,
    snapshot_volume,
) -> Dict[str, Any]:
    records = []
    for item in gb_history:
        effective_date = pick_effective_date(item)
        float_capital = pick_effective_float_capital(item)
        if effective_date and float_capital:
            records.append({"date": effective_date, "float_capital": float_capital})
    records.sort(key=lambda item: item["date"])

    fallback_float_capital = safe_float(current_float_capital)
    reference_float_capital = records[-1]["float_capital"] if records else fallback_float_capital
    scale = infer_turnover_scale(
        daily_kline=daily_kline,
        current_turnover_rate=current_turnover_rate,
        reference_float_capital=reference_float_capital,
        snapshot_volume=snapshot_volume,
    )

    history = []
    record_idx = 0
    active_float_capital = fallback_float_capital

    for row in daily_kline:
        trade_date = normalize_trade_date(row.get("date") or row.get("Date") or row.get("trade_date"))
        volume = safe_float(row.get("volume") or row.get("Volume"))
        if not trade_date:
            continue

        while record_idx < len(records) and records[record_idx]["date"] <= trade_date:
            active_float_capital = records[record_idx]["float_capital"]
            record_idx += 1

        turnover_rate = None
        if volume is not None and active_float_capital and active_float_capital > 0:
            turnover_rate = round(float(volume) / float(active_float_capital) * scale, 4)

        history.append(
            {
                "date": trade_date,
                "volume": round(float(volume), 4) if volume is not None else None,
                "float_capital": round(float(active_float_capital), 4)
                if active_float_capital is not None
                else None,
                "turnover_rate": turnover_rate,
            }
        )

    return {
        "daily_turnover_history": history,
        "daily_turnover_meta": {
            "formula": "turnover_rate = volume / float_capital * scale",
            "scale": round(scale, 6),
            "gb_record_count": len(records),
            "fallback_float_capital": fallback_float_capital,
        },
    }


def build_cyq_kline_records(
    daily_kline: List[Dict[str, Any]],
    daily_turnover_history: Dict[str, Any],
) -> List[Dict[str, Any]]:
    turnover_map = {
        item.get("date"): item.get("turnover_rate")
        for item in daily_turnover_history.get("daily_turnover_history", [])
        if isinstance(item, dict) and item.get("date")
    }

    records = []
    prev_close = None
    for row in daily_kline:
        trade_date = normalize_trade_date(row.get("date") or row.get("Date") or row.get("trade_date"))
        open_price = safe_float(row.get("open") or row.get("Open") or row.get("open_price"))
        high_price = safe_float(row.get("high") or row.get("High") or row.get("high_price"))
        low_price = safe_float(row.get("low") or row.get("Low") or row.get("low_price"))
        close_price = safe_float(row.get("close") or row.get("Close") or row.get("close_price"))
        volume = safe_float(row.get("volume") or row.get("Volume"))
        amount = safe_float(row.get("amount") or row.get("Amount"))
        hsl = safe_float(turnover_map.get(trade_date))

        values = [open_price, high_price, low_price, close_price, volume, amount, hsl]
        if not trade_date or not all(isinstance(value, (int, float)) for value in values):
            prev_close = close_price if isinstance(close_price, (int, float)) else prev_close
            continue

        amplitude = 0.0
        change_pct = 0.0
        change_amount = 0.0
        if prev_close and prev_close != 0:
            amplitude = (float(high_price) - float(low_price)) / float(prev_close) * 100.0
            change_pct = (float(close_price) / float(prev_close) - 1.0) * 100.0
            change_amount = float(close_price) - float(prev_close)

        records.append(
            {
                "date": trade_date,
                "open": round(float(open_price), 4),
                "close": round(float(close_price), 4),
                "high": round(float(high_price), 4),
                "low": round(float(low_price), 4),
                "volume": round(float(volume), 4),
                "amount": round(float(amount), 4),
                "zf": round(float(amplitude), 4),
                "zdf": round(float(change_pct), 4),
                "zde": round(float(change_amount), 4),
                "hsl": round(float(hsl), 4),
            }
        )
        prev_close = float(close_price)

    return records


def compute_profit_ratio_from_distribution(current_price, x_values, y_values):
    price_now = safe_float(current_price)
    if price_now is None or not x_values or not y_values:
        return None

    total = 0.0
    below = 0.0
    for chip, price in zip(x_values, y_values):
        chip_value = safe_float(chip)
        price_value = safe_float(price)
        if chip_value is None or price_value is None:
            continue
        total += float(chip_value)
        if float(price_value) <= float(price_now):
            below += float(chip_value)

    if total <= 0:
        return None
    return round(below / total, 6)


def chip_status_from_concentration(concentration_90):
    if concentration_90 is None:
        return "未知"
    if concentration_90 < 0.08:
        return "高度集中"
    if concentration_90 < 0.15:
        return "较集中"
    if concentration_90 < 0.25:
        return "中等"
    return "较分散"


def create_chip_unavailable(note: str) -> Dict[str, Any]:
    return {
        "status": "todo",
        "data": None,
        "note": note,
    }


def compute_chip_distribution(
    daily_kline: List[Dict[str, Any]],
    daily_turnover_history: Dict[str, Any],
    current_price,
) -> Dict[str, Any]:
    records = build_cyq_kline_records(daily_kline, daily_turnover_history)
    if len(records) < 30:
        return create_chip_unavailable("筹码分布暂无法计算：有效日线/换手率样本不足 30 条。")

    js_engine = MiniRacer()
    js_engine.eval(load_cyq_js_code())
    result = js_engine.call("CYQCalculator", len(records) - 1, records)

    price_now = safe_float(current_price, safe_float(records[-1].get("close")))
    profit_ratio = compute_profit_ratio_from_distribution(
        price_now,
        result.get("x", []),
        result.get("y", []),
    )
    if profit_ratio is None:
        profit_ratio = safe_float(result.get("benefitPart"))

    percent_90 = result.get("percentChips", {}).get("90", {})
    percent_70 = result.get("percentChips", {}).get("70", {})
    price_range_90 = percent_90.get("priceRange") or [None, None]
    price_range_70 = percent_70.get("priceRange") or [None, None]
    concentration_90 = safe_float(percent_90.get("concentration"))
    concentration_70 = safe_float(percent_70.get("concentration"))

    return {
        "profit_ratio": round(float(profit_ratio), 6) if profit_ratio is not None else None,
        "avg_cost": safe_float(result.get("avgCost")),
        "cost_90_low": safe_float(price_range_90[0]),
        "cost_90_high": safe_float(price_range_90[1]),
        "concentration_90": round(float(concentration_90), 6)
        if concentration_90 is not None
        else None,
        "cost_70_low": safe_float(price_range_70[0]),
        "cost_70_high": safe_float(price_range_70[1]),
        "concentration_70": round(float(concentration_70), 6)
        if concentration_70 is not None
        else None,
        "chip_status": chip_status_from_concentration(concentration_90),
        "sample_count": len(records),
    }


def collect_chip_for_report(item: Dict[str, Any]) -> Dict[str, Any]:
    """计算 report 筹码分布；只消费 item 中的数据，并通过 data.py 补历史股本。"""
    code = item.get("code")
    daily_kline = item.get("daily_kline") or []
    market_snapshot = item.get("market_snapshot") or {}
    more_info = item.get("more_info") or {}
    stock_info = item.get("stock_info") or {}

    if not code:
        return create_chip_unavailable("筹码分布暂无法计算：缺少股票代码。")
    if not daily_kline:
        return create_chip_unavailable("筹码分布暂无法计算：缺少日 K 数据。")

    gb_history = fetch_gb_history(code, daily_kline)
    daily_turnover_history = compute_daily_turnover_history(
        daily_kline=daily_kline,
        gb_history=gb_history,
        current_float_capital=stock_info.get("ActiveCapital"),
        current_turnover_rate=more_info.get("fHSL"),
        snapshot_volume=market_snapshot.get("Volume"),
    )
    calc_price = get_latest_kline_close(item, default=market_snapshot.get("Now"))
    return compute_chip_distribution(
        daily_kline=daily_kline,
        daily_turnover_history=daily_turnover_history,
        current_price=calc_price,
    )


def collect_report_item(target):
    """采集单个 report 目标的结构化数据。"""
    code = target["code"]
    realtime_data = collect_realtime_report_data(code)
    item = {
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
        "chip": None,
    }
    item["chip"] = collect_chip_for_report(item)
    return item


def collect_thises_data(target):
    """收集 thises 量价分析所需的日 K 数据。"""
    code = target["code"]
    return {
        "raw_code": target.get("raw_code", ""),
        "target_type": target.get("target_type", ""),
        "code": code,
        "name": target.get("name", ""),
        "daily_kline": collect_daily_kline_for_report(code),
    }


def build_thises_data(codes):
    """根据股票或板块 code 批量构建 thises 日 K 数据。"""
    targets = resolve_report_codes(codes)
    items = []
    errors = []

    for target in targets:
        try:
            items.append(collect_thises_data(target))
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
        "task": "thises",
        "data_type": "daily_kline",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "items": items,
        "errors": errors,
    }


def simplify_chip_unavailable_note(note):
    """把筹码不可计算原因压缩成控制台可读文本。"""
    text = str(note or "").strip()
    if not text:
        return ""
    prefix = "筹码分布暂无法计算："
    if text.startswith(prefix):
        text = text[len(prefix):]
    return text.strip("。")


def format_chip_line(chip):
    """格式化筹码分布控制台输出。"""
    if not isinstance(chip, dict) or not chip:
        return "筹码: 不可计算"

    if chip.get("status") == "todo":
        reason = simplify_chip_unavailable_note(chip.get("note"))
        if reason:
            return f"筹码: 不可计算（{reason}）"
        return "筹码: 不可计算"

    profit_ratio = safe_float(chip.get("profit_ratio"), 0.0)
    avg_cost = safe_float(chip.get("avg_cost"), 0.0)
    concentration_90 = safe_float(chip.get("concentration_90"), 0.0)
    chip_status = str(chip.get("chip_status") or "未知")

    parts = []
    if profit_ratio > 0:
        parts.append(f"获利盘{profit_ratio * 100:.1f}%")
    if avg_cost > 0:
        parts.append(f"平均成本{avg_cost:.2f}")
    if concentration_90 > 0:
        parts.append(f"90集中度{concentration_90:.3f}")
    parts.append(f"状态: {chip_status}")

    if len(parts) == 1 and chip_status == "未知":
        return "筹码: 不可计算"
    return f"筹码: {'  '.join(parts)}"


def format_report_item(item):
    """格式化单个 report item，业务判断口径对齐旧 cassa.py report。"""
    relation = item.get("relation") or []
    industry, concepts = extract_industry_and_concepts(relation)
    today = calculate_today_quote(item)
    display_price = safe_float(today.get("current_price"), 0.0)
    calc_price = get_latest_kline_close(item, default=display_price)
    closes = extract_close_values(item)
    ma5_series = calculate_sma(closes, 5)
    ma10_series = calculate_sma(closes, 10)
    ma20_series = calculate_sma(closes, 20)
    ma60_series = calculate_sma(closes, 60)

    ma5 = ma5_series[-1] if ma5_series else 0.0
    ma10 = ma10_series[-1] if ma10_series else 0.0
    ma20 = ma20_series[-1] if ma20_series else 0.0
    ma60 = ma60_series[-1] if ma60_series else 0.0
    bias_ma5, bias_ma10, bias_ma20 = calculate_bias(calc_price, ma5, ma10, ma20)

    trend_status, ma_alignment, trend_strength = judge_trend_status(ma5_series, ma10_series, ma20_series)

    more_info = item.get("more_info") or {}
    stock_info = item.get("stock_info") or {}
    volume_ratio = safe_float(more_info.get("fLianB"))
    turnover_rate = safe_float(more_info.get("fHSL"))
    volume_status, volume_ratio, volume_trend = judge_volume_status(closes, volume_ratio)

    support_ma5, support_ma10, support_levels, resistance_levels = judge_support_resistance(
        item, ma5, ma10, ma20, calc_price
    )

    macd_dif, macd_dea, macd_bar, macd_status, macd_signal = judge_macd_status(item)

    rsi_6_series = calculate_rsi(closes, 6)
    rsi_12_series = calculate_rsi(closes, 12)
    rsi_24_series = calculate_rsi(closes, 24)
    rsi_6 = rsi_6_series[-1] if rsi_6_series else 50.0
    rsi_12 = rsi_12_series[-1] if rsi_12_series else 50.0
    rsi_24 = rsi_24_series[-1] if rsi_24_series else 50.0
    rsi_status, rsi_signal = judge_rsi_status(rsi_6, rsi_12, rsi_24)

    signal_score, signal_reasons, risk_factors = calculate_signal_score(
        trend_status,
        trend_strength,
        bias_ma5,
        volume_status,
        support_ma5,
        support_ma10,
        macd_status,
        macd_signal,
        rsi_status,
        rsi_signal,
    )
    buy_signal = judge_buy_signal(signal_score, trend_status)

    total_shares = safe_float(stock_info.get("J_zgb"))
    market_cap = total_shares * calc_price / 10000 if total_shares > 0 and calc_price > 0 else 0.0

    lines = [f"=== {strip_code_suffix(item.get('code', ''))} {item.get('name', '')} ===".rstrip()]
    info_parts = []
    if industry:
        info_parts.append(f"行业: {industry}")
    if concepts:
        info_parts.append(f"概念: {'、'.join(concepts)}")
    if info_parts:
        lines.append("  ".join(info_parts))

    lines.append(
        f"当日: 开{today['today_open']:.2f} 高{today['today_high']:.2f} "
        f"低{today['today_low']:.2f} 收{today['current_price']:.2f} "
        f"{today['price_change_pct']:+.2f}% 振幅{today['amplitude']:.2f}%"
    )
    lines.append(f"趋势: {trend_status} ({trend_strength:.0f}/100)    信号: {buy_signal} ({signal_score}分)")
    lines.append(
        f"现价: {display_price:.2f}  "
        f"MA5: {ma5:.2f}({bias_ma5:+.1f}%)  "
        f"MA10: {ma10:.2f}({bias_ma10:+.1f}%)  "
        f"MA20: {ma20:.2f}({bias_ma20:+.1f}%)"
    )
    turnover_text = f"  换手: {turnover_rate:.1f}%" if turnover_rate > 0 else ""
    lines.append(
        f"量能: {volume_status} ({volume_ratio:.2f})      "
        f"MACD: {macd_status}    RSI: {rsi_status}({rsi_12:.0f})"
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

    lines.append(format_chip_line(item.get("chip")))

    support_text = ", ".join(f"{value:.2f}" for value in support_levels) if support_levels else "无"
    resistance_text = ", ".join(f"{value:.2f}" for value in resistance_levels) if resistance_levels else "无"
    lines.append(f"支撑: {support_text}  压力: {resistance_text}")

    if signal_reasons:
        lines.append(f"理由: {'  '.join(signal_reasons)}")
    if risk_factors:
        lines.append(f"风险: {'  '.join(risk_factors)}")
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


def run_thises(args):
    """执行 thises 子命令。"""
    codes = [code.strip() for code in args.codes.split(",") if code.strip()]
    print_json(build_thises_data(codes))


def main():
    """业务脚本 CLI 入口。"""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

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

    thises_parser = subparsers.add_parser("thises", help="收集 thises 所需数据")
    thises_parser.add_argument(
        "--codes",
        required=True,
        help="股票或板块代码，多个用逗号分隔，例如 600519,000001,880675.SH",
    )
    thises_parser.set_defaults(handler=run_thises)

    args = parser.parse_args()
    data.initialize(Path(__file__))
    args.handler(args)


if __name__ == "__main__":
    main()
