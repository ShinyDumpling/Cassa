"""
Cassa 独立市场分析入口。

该脚本从原 `cassa.py market` 流程中拆分市场分析能力。所有行情、板块和
成分股数据统一通过同级 `data.py` 获取，不直接访问 `tqcenter`。K 线复权
口径沿用 `data.py.get_market_data()` 的默认前复权。
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

import requests

import data as data_source



# ============================================================================
# 配置与常量区
# ============================================================================

PROJECT_ROOT = Path(__file__).resolve().parent

BLOCK_TYPE_MAP_PATH = PROJECT_ROOT / "tdx_block_type_map.json"

MARKET_INDEX_CONFIGS = [
    {"name": "上证指数", "code": "000001.SH", "note": "沪市整体冷暖，被银行石油等大块头主导，比较迟钝"},
    {"name": "深证成指", "code": "399001.SZ", "note": "深市整体，科技制造股多，比上证活跃"},
    {"name": "创业板指", "code": "399006.SZ", "note": "成长股代表（新能源、医药、科技制造）"},
    {"name": "科创50", "code": "000688.SH", "note": "硬科技代表（半导体、AI、芯片），弹性最大"},
    {"name": "沪深300", "code": "000300.SH", "note": "大盘蓝筹，机构主战场，它强=资金抱团偏防御"},
    {"name": "中证1000", "code": "000852.SH", "note": "小盘股，题材股土壤，它强=游资活跃风险偏好高"},
]

BLOCK_LOOKBACK_BARS = 120

BLOCK_RANK_TOP_N = 15

BLOCK_STRATEGY_DISPLAY_LIMIT = 10

SECTOR_BATCH_SIZE = 120

BLOCK_TYPE_LABELS = {
    "industry": "【行业】",
    "region": "【地域】",
    "theme": "【概念】",
    "style": "【风格】",
    "holding": "【持仓】",
    "event": "【事件】",
    "unknown": "【未分类】",
}

RANKABLE_BLOCK_TYPES = {"industry", "theme"}

KEY_BLOCKS_PER_BUCKET = 2

LEADER_CANDIDATE_COUNT = 3

MIDDLE_ARMY_CANDIDATE_COUNT = 3

LIMIT_UP_THRESHOLD = 9.5

LIMIT_DOWN_THRESHOLD = -9.5

SH_CODE_PREFIXES = ("5", "6", "9")

SZ_CODE_PREFIXES = ("0", "1", "2", "3")

BJ_CODE_PREFIXES = ("920", "4", "8")

LLM_API_KEY_ENV_NAME = "CASSA_LLM_API_KEY"

LLM_BASE_URL_ENV_NAME = "CASSA_LLM_BASE_URL"

LLM_MODEL_ENV_NAME = "CASSA_LLM_MODEL"

DEFAULT_LLM_TIMEOUT_SECONDS = 60


# ============================================================================
# 数据结构区
# ============================================================================

@dataclass(frozen=True)
class StockCode:
    """统一描述项目内部股票代码与通达信股票代码的双重口径。"""

    raw_code: str
    internal_code: str
    market_suffix: str
    tdx_code: str

@dataclass(frozen=True)
class LlmConfig:
    """统一描述项目内部使用的 LLM 接入配置。"""

    api_key: str
    base_url: str
    model: str
    timeout_seconds: int = DEFAULT_LLM_TIMEOUT_SECONDS

class OpenAiCompatibleLlmClient:
    """封装 OpenAI 兼容格式的文本生成调用。"""

    def __init__(self, config: LlmConfig) -> None:
        """
        创建一个可复用的 LLM 客户端。

        Args:
            config: 已校验完成的 LLM 配置对象。

        Returns:
            无返回值。
        """
        self.config = config

    def chat(
        self,
        user_prompt: str,
        system_prompt: str = "",
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        """
        发起一次 OpenAI 兼容格式的聊天请求。

        Args:
            user_prompt: 用户提示词。
            system_prompt: 可选的系统提示词。
            temperature: 生成温度。

        Returns:
            模型原始返回 JSON。
        """
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        response = requests.post(
            url=f"{self.config.base_url.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.config.model,
                "messages": messages,
                "temperature": temperature,
            },
            timeout=self.config.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()


# ============================================================================
# 基础工具与 LLM 接入区
# ============================================================================

def get_env_value(env_name: str) -> str:
    """
    读取环境变量，并在 Windows 下兼容读取用户级持久化环境变量。

    Args:
        env_name: 环境变量名。

    Returns:
        读取到的环境变量值；如果不存在则返回空字符串。
    """
    current_value = os.getenv(env_name, "").strip()
    if current_value:
        return current_value

    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Environment",
        ) as registry_key:
            registry_value, _ = winreg.QueryValueEx(registry_key, env_name)
            return str(registry_value).strip()
    except Exception:
        return ""

def load_llm_config_from_env() -> LlmConfig:
    """
    从环境变量中加载 LLM 配置。

    Args:
        无。

    Returns:
        已完成基础校验的 LLM 配置对象。

    Raises:
        RuntimeError: 当环境变量缺失时抛出。
    """
    api_key = get_env_value(LLM_API_KEY_ENV_NAME)
    base_url = get_env_value(LLM_BASE_URL_ENV_NAME)
    model = get_env_value(LLM_MODEL_ENV_NAME)

    missing_env_names = [
        env_name
        for env_name, env_value in (
            (LLM_API_KEY_ENV_NAME, api_key),
            (LLM_BASE_URL_ENV_NAME, base_url),
            (LLM_MODEL_ENV_NAME, model),
        )
        if not env_value
    ]
    if missing_env_names:
        missing_text = "、".join(missing_env_names)
        raise RuntimeError(f"LLM 环境变量缺失：{missing_text}")

    return LlmConfig(
        api_key=api_key,
        base_url=base_url.rstrip("/"),
        model=model,
    )

def build_llm_client() -> OpenAiCompatibleLlmClient:
    """
    基于环境变量构建公共 LLM 客户端。

    Args:
        无。

    Returns:
        可复用的 OpenAI 兼容格式客户端。
    """
    return OpenAiCompatibleLlmClient(load_llm_config_from_env())

def load_block_type_map() -> dict[str, dict[str, Any]]:
    """
    读取板块分类映射表。

    Args:
        无。

    Returns:
        以通达信板块代码为键的分类映射字典。

    Raises:
        RuntimeError: 当映射文件不存在或 JSON 非法时抛出。
    """
    try:
        with BLOCK_TYPE_MAP_PATH.open("r", encoding="utf-8") as file:
            loaded = json.load(file)
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"板块分类映射文件不存在：{BLOCK_TYPE_MAP_PATH}。"
        ) from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"板块分类映射文件不是合法 JSON：{BLOCK_TYPE_MAP_PATH}。"
        ) from exc

    if not isinstance(loaded, dict):
        raise RuntimeError(f"板块分类映射格式错误：{BLOCK_TYPE_MAP_PATH} 顶层必须是对象。")
    return loaded

def get_block_type(block_code: str, block_type_map: dict[str, dict[str, Any]]) -> str:
    """
    优先按本地映射表判断板块类型。

    Args:
        block_code: 通达信板块代码。
        block_type_map: 已加载的板块分类映射表。

    Returns:
        板块类型代码，例如 `industry`、`theme`、`style`。
    """
    meta = block_type_map.get(block_code)
    if not isinstance(meta, dict):
        return "unknown"
    raw_type = meta.get("type", "unknown")
    return raw_type if isinstance(raw_type, str) and raw_type else "unknown"

def get_block_type_display(block_code: str, block_type_map: dict[str, dict[str, Any]]) -> str:
    """
    获取适合展示的人类可读板块类型标签。

    Args:
        block_code: 通达信板块代码。
        block_type_map: 已加载的板块分类映射表。

    Returns:
        中文类型标签。
    """
    type_code = get_block_type(block_code, block_type_map)
    return BLOCK_TYPE_LABELS.get(type_code, f"【{type_code}】")

def strip_stock_code_suffix(raw_code: str) -> str:
    """
    去掉股票代码里的市场后缀，只保留纯数字部分。

    Args:
        raw_code: 用户输入的原始股票代码，允许包含 `.SH`、`.SZ`、`.BJ` 后缀。

    Returns:
        只包含数字的股票代码字符串。
    """
    normalized_code = raw_code.strip().upper()
    if "." in normalized_code:
        normalized_code = normalized_code.split(".", maxsplit=1)[0]
    return normalized_code

def extract_market_suffix(raw_code: str) -> str | None:
    """
    从原始代码中提取显式传入的市场后缀。

    Args:
        raw_code: 用户输入或外部返回的原始代码。

    Returns:
        若原始代码包含 `.SH`、`.SZ`、`.BJ` 形式的后缀，则返回大写后缀；
        否则返回 `None`。
    """
    normalized_code = raw_code.strip().upper()
    if "." not in normalized_code:
        return None
    _, suffix = normalized_code.split(".", maxsplit=1)
    return suffix or None

def infer_market_suffix(internal_code: str) -> str:
    """
    根据纯数字股票代码推断通达信所需的市场后缀。

    Args:
        internal_code: 项目内部使用的纯数字股票代码。

    Returns:
        通达信市场后缀，例如 `SH`、`SZ`、`BJ`。

    Raises:
        ValueError: 当代码为空、不是纯数字，或当前规则无法识别时抛出。
    """
    if not internal_code:
        raise ValueError("股票代码不能为空。")
    if not internal_code.isdigit():
        raise ValueError(f"股票代码必须是纯数字，当前收到：{internal_code}")

    # 北交所当前正式代码已包含 920 开头的新号段，需要优先于沪市 9 开头规则判断。
    if internal_code.startswith(BJ_CODE_PREFIXES):
        return "BJ"
    if internal_code.startswith(SH_CODE_PREFIXES):
        return "SH"
    if internal_code.startswith(SZ_CODE_PREFIXES):
        return "SZ"

    raise ValueError(f"暂时无法根据代码推断市场后缀：{internal_code}")

def to_internal_stock_code(raw_code: str) -> str:
    """
    把用户输入的股票代码统一转换成项目内部使用的纯数字代码。

    Args:
        raw_code: 用户输入的股票代码，允许纯数字或带后缀。

    Returns:
        规整后的纯数字股票代码。

    Raises:
        ValueError: 当输入为空或规整后不是纯数字时抛出。
    """
    internal_code = strip_stock_code_suffix(raw_code)
    if not internal_code:
        raise ValueError("股票代码不能为空。")
    if not internal_code.isdigit():
        raise ValueError(f"股票代码规整失败，只支持纯数字代码：{raw_code}")
    return internal_code

def normalize_stock_code(raw_code: str) -> StockCode:
    """
    统一构建股票代码对象，供项目内部和通达信接口同时使用。

    Args:
        raw_code: 用户输入或外部传入的股票代码。

    Returns:
        同时包含纯数字代码与通达信代码的股票代码对象。
    """
    internal_code = to_internal_stock_code(raw_code)
    market_suffix = extract_market_suffix(raw_code) or infer_market_suffix(internal_code)
    return StockCode(
        raw_code=raw_code,
        internal_code=internal_code,
        market_suffix=market_suffix,
        tdx_code=f"{internal_code}.{market_suffix}",
    )

def extract_llm_text_from_response(response_payload: dict[str, Any]) -> str:
    """
    从 OpenAI 兼容响应中提取主文本内容。

    Args:
        response_payload: 模型原始响应 JSON。

    Returns:
        提取出的文本内容。

    Raises:
        RuntimeError: 当响应结构异常时抛出。
    """
    try:
        choices = response_payload["choices"]
        first_choice = choices[0]
        message = first_choice["message"]
        content = message["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("LLM 返回结构异常，无法提取文本内容。") from exc

    if not isinstance(content, str):
        raise RuntimeError("LLM 返回的文本内容不是字符串。")
    return content.strip()

def call_llm_text(
    user_prompt: str,
    system_prompt: str = "",
    temperature: float = 0.2,
) -> dict[str, Any]:
    """
    通过公共接入层发起一次文本生成调用。

    Args:
        user_prompt: 用户提示词。
        system_prompt: 可选的系统提示词。
        temperature: 生成温度。

    Returns:
        统一封装后的调用结果。
    """
    client = build_llm_client()
    raw_response = client.chat(
        user_prompt=user_prompt,
        system_prompt=system_prompt,
        temperature=temperature,
    )
    return {
        "model": client.config.model,
        "base_url": client.config.base_url,
        "text": extract_llm_text_from_response(raw_response),
        "raw_response": raw_response,
    }

def try_parse_json_object(text: str) -> dict[str, Any] | None:
    """
    尽量从模型返回文本中解析出一个 JSON 对象。

    Args:
        text: 模型返回的原始文本。

    Returns:
        解析成功返回字典，否则返回 `None`。
    """
    cleaned_text = text.strip()
    if cleaned_text.startswith("```"):
        cleaned_text = cleaned_text.removeprefix("```json").removeprefix("```").strip()
        if cleaned_text.endswith("```"):
            cleaned_text = cleaned_text[:-3].strip()

    try:
        parsed = json.loads(cleaned_text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start_index = cleaned_text.find("{")
    end_index = cleaned_text.rfind("}")
    if start_index == -1 or end_index == -1 or end_index <= start_index:
        return None

    candidate = cleaned_text[start_index:end_index + 1]
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None

def safe_float(value: Any) -> float | None:
    """
    尽量把值安全转换成浮点数。

    Args:
        value: 待转换的原始值。

    Returns:
        转换成功返回浮点数，否则返回 `None`。
    """
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None

def calculate_percentage_change(current_value: float, previous_value: float) -> float | None:
    """
    计算两个数之间的百分比涨跌幅。

    Args:
        current_value: 当前值。
        previous_value: 对比基准值。

    Returns:
        百分比涨跌幅；如果无法计算则返回 `None`。
    """
    try:
        return (float(current_value) / float(previous_value) - 1) * 100
    except (ZeroDivisionError, TypeError, ValueError):
        return None

def calculate_rolling_mean(values: Any, window: int) -> float | None:
    """
    计算滚动窗口均值。

    Args:
        values: 支持 `iloc` 和 `mean` 的序列对象。
        window: 窗口大小。

    Returns:
        窗口均值；如果数据不足则返回 `None`。
    """
    if len(values) < window or window <= 0:
        return None
    subset = values.iloc[-window:]
    if len(subset) < window:
        return None
    return float(subset.mean())

def classify_trend_slope(current_value: float | None, previous_value: float | None, eps: float = 0.3) -> str | None:
    """
    根据前后两个均值判断均线方向。

    Args:
        current_value: 当前窗口均值。
        previous_value: 参考窗口均值。
        eps: 视为走平的容忍阈值。

    Returns:
        `向上`、`向下`、`走平` 或 `None`。
    """
    if current_value is None or previous_value is None:
        return None
    delta = current_value - previous_value
    if delta > eps:
        return "向上"
    if delta < -eps:
        return "向下"
    return "走平"

def calculate_max_drawdown_pct(values: Any) -> float | None:
    """
    计算序列的最大回撤百分比。

    Args:
        values: 支持 `cummax` 的价格序列。

    Returns:
        最大回撤百分比；如果数据不足则返回 `None`。
    """
    if len(values) < 2:
        return None
    running_high = values.cummax()
    drawdowns = values / running_high - 1
    return float(drawdowns.min()) * 100

def strip_tdx_suffix(code: str) -> str:
    """
    去掉通达信代码里的市场后缀，保留纯数字部分。

    Args:
        code: 带或不带后缀的代码。

    Returns:
        纯数字代码字符串。
    """
    return code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")

def get_sort_key_desc(value: float | None, default: float = -999999) -> float:
    """
    为降序排序生成稳定的 key。

    Args:
        value: 原始排序值。
        default: 当值为空时使用的兜底值。

    Returns:
        可用于排序的数值。
    """
    return value if value is not None else default

def chunk_list(items: list[Any], chunk_size: int) -> list[list[Any]]:
    """
    把列表切成固定大小的多个分片。

    Args:
        items: 原始列表。
        chunk_size: 每个分片的最大长度。

    Returns:
        分片后的二维列表。
    """
    return [items[index : index + chunk_size] for index in range(0, len(items), chunk_size)]


# ============================================================================
# 板块趋势与策略计算区
# ============================================================================

def summarize_block_trend(close_series: Any, amount_series: Any) -> dict[str, Any]:
    """
    根据板块日 K 和成交额序列，生成中期趋势摘要。

    Args:
        close_series: 板块收盘价序列。
        amount_series: 板块成交额序列。

    Returns:
        适合后续热度榜与判断层使用的趋势摘要字典。
    """
    values = close_series.astype(float).dropna().tail(BLOCK_LOOKBACK_BARS)
    amount_values = amount_series.astype(float).dropna().tail(BLOCK_LOOKBACK_BARS)
    if len(values) < 2 or len(amount_values) < 1:
        return {
            "5日涨幅%": None,
            "20日涨幅%": None,
            "60日涨幅%": None,
            "120日涨幅%": None,
            "MA20": None,
            "MA60": None,
            "MA120": None,
            "收盘站上MA20": None,
            "收盘站上MA60": None,
            "MA20方向": None,
            "MA60方向": None,
            "距120日新高回撤%": None,
            "近20日最大回撤%": None,
            "近10日活跃天数": None,
            "近20日放量天数": None,
            "中期趋势": "数据不足",
            "阶段判断": "数据不足",
        }

    last_close = float(values.iloc[-1])
    ma20 = calculate_rolling_mean(values, 20)
    ma60 = calculate_rolling_mean(values, 60)
    ma120 = calculate_rolling_mean(values, 120)
    prev_ma20 = calculate_rolling_mean(values.iloc[:-5], 20) if len(values) >= 25 else None
    prev_ma60 = calculate_rolling_mean(values.iloc[:-5], 60) if len(values) >= 65 else None
    ma20_slope = classify_trend_slope(ma20, prev_ma20)
    ma60_slope = classify_trend_slope(ma60, prev_ma60)
    change5 = calculate_percentage_change(values.iloc[-1], values.iloc[-6]) if len(values) >= 6 else None
    change20 = calculate_percentage_change(values.iloc[-1], values.iloc[-21]) if len(values) >= 21 else None
    change60 = calculate_percentage_change(values.iloc[-1], values.iloc[-61]) if len(values) >= 61 else None
    change120 = calculate_percentage_change(values.iloc[-1], values.iloc[0]) if len(values) >= 120 else None
    high120 = float(values.max()) if len(values) >= 1 else None
    drawdown_from_high = calculate_percentage_change(last_close, high120) if high120 else None
    drawdown20 = calculate_max_drawdown_pct(values.tail(20)) if len(values) >= 20 else None
    avg_amount20 = calculate_rolling_mean(amount_values, 20)
    active_days10 = int((values.pct_change().tail(10) > 0.02).sum()) if len(values) >= 10 else None
    strong_amount_days20 = (
        int((amount_values.tail(20) > avg_amount20 * 1.2).sum())
        if avg_amount20 and len(amount_values) >= 20
        else None
    )

    if (
        ma20 is not None
        and ma60 is not None
        and last_close >= ma20 >= ma60
        and ma20_slope == "向上"
        and ma60_slope in ("向上", "走平")
    ):
        trend_stage = "中期上升"
    elif ma20 is not None and ma60 is not None and last_close >= ma20 and ma20_slope == "向上":
        trend_stage = "上升回流"
    elif ma20 is not None and ma60 is not None and last_close >= ma20 and last_close < ma60:
        trend_stage = "反抽修复"
    elif ma20 is not None and ma60 is not None and last_close < ma20 and last_close >= ma60:
        trend_stage = "高位整理"
    else:
        trend_stage = "偏弱震荡"

    if (
        change60 is not None
        and change120 is not None
        and change60 >= 15
        and change120 >= 20
        and drawdown_from_high is not None
        and drawdown_from_high >= -12
    ):
        mid_term_trend = "主线候选"
    elif change60 is not None and change60 >= 8 and ma20_slope == "向上":
        mid_term_trend = "趋势活跃"
    elif change20 is not None and change20 > 0:
        mid_term_trend = "短线活跃"
    else:
        mid_term_trend = "趋势一般"

    return {
        "5日涨幅%": round(change5, 2) if change5 is not None else None,
        "20日涨幅%": round(change20, 2) if change20 is not None else None,
        "60日涨幅%": round(change60, 2) if change60 is not None else None,
        "120日涨幅%": round(change120, 2) if change120 is not None else None,
        "MA20": round(ma20, 2) if ma20 is not None else None,
        "MA60": round(ma60, 2) if ma60 is not None else None,
        "MA120": round(ma120, 2) if ma120 is not None else None,
        "收盘站上MA20": ma20 is not None and last_close >= ma20,
        "收盘站上MA60": ma60 is not None and last_close >= ma60,
        "MA20方向": ma20_slope,
        "MA60方向": ma60_slope,
        "距120日新高回撤%": round(drawdown_from_high, 2) if drawdown_from_high is not None else None,
        "近20日最大回撤%": round(drawdown20, 2) if drawdown20 is not None else None,
        "近10日活跃天数": active_days10,
        "近20日放量天数": strong_amount_days20,
        "中期趋势": mid_term_trend,
        "阶段判断": trend_stage,
    }


# ============================================================================
# 板块趋势与策略计算区
# ============================================================================

def _safe_non_negative(value: Any) -> float:
    """
    将缺失值或非法值转换为可用于排序的非负浮点数。

    Args:
        value: 待转换的原始值。

    Returns:
        转换后的浮点数；缺失、非法或负数按 0 处理。
    """
    try:
        if value is None:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0

def _safe_negative_floor(value: Any, fallback: float = -999.0) -> float:
    """
    将缺失值或非法值转换为排序用的负向兜底值。

    Args:
        value: 待转换的原始值。
        fallback: 转换失败时使用的兜底值。

    Returns:
        转换后的浮点数，转换失败时返回 ``fallback``。
    """
    try:
        if value is None:
            return fallback
        return float(value)
    except (TypeError, ValueError):
        return fallback

def match_continuous_strength_block(row: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    识别持续走强、并非单日脉冲的板块。

    Args:
        row: 单个板块的趋势摘要。

    Returns:
        是否命中策略，以及用于解释命中的依据列表。
    """
    change5 = row.get("5日涨幅%")
    change20 = row.get("20日涨幅%")
    change60 = row.get("60日涨幅%")
    drawdown = row.get("距120日新高回撤%")
    drawdown20 = row.get("近20日最大回撤%")
    if (
        change5 is None
        or change20 is None
        or change60 is None
        or change5 <= 0
        or change20 <= 0
        or change60 <= 0
        or not row.get("收盘站上MA20")
        or not row.get("收盘站上MA60")
        or row.get("MA20方向") != "向上"
        or row.get("MA60方向") not in ("向上", "走平")
        or drawdown is None
        or drawdown < -15
        or drawdown20 is None
        or drawdown20 < -12
    ):
        return False, []

    return True, [
        "5日/20日/60日涨幅均为正",
        "收盘站上MA20和MA60",
        "MA20向上，MA60未走坏",
        f"距120日高点回撤 {drawdown:+.2f}%",
    ]

def match_oversold_rebound_block(row: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    识别中期跌深后开始修复的板块。

    Args:
        row: 单个板块的趋势摘要。

    Returns:
        是否命中策略，以及用于解释命中的依据列表。
    """
    change5 = row.get("5日涨幅%")
    drawdown = row.get("距120日新高回撤%")
    change60 = row.get("60日涨幅%")
    change120 = row.get("120日涨幅%")
    stage = row.get("阶段判断")
    if (
        change5 is None
        or change5 <= 0
        or drawdown is None
        or drawdown > -20
        or change60 is None
        or change60 > 8
        or (change120 is not None and change120 > 5)
        or row.get("MA20方向") not in ("向上", "走平")
        or stage not in ("反抽修复", "上升回流")
        or not row.get("收盘站上MA20")
    ):
        return False, []

    return True, [
        f"距120日高点回撤 {drawdown:+.2f}%",
        f"近5日修复 {change5:+.2f}%",
        "重新站上MA20，处于修复阶段",
    ]

def match_volume_breakout_block(row: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    识别带量启动或带量突破的板块。

    Args:
        row: 单个板块的趋势摘要。

    Returns:
        是否命中策略，以及用于解释命中的依据列表。
    """
    change5 = row.get("5日涨幅%")
    change20 = row.get("20日涨幅%")
    drawdown = row.get("距120日新高回撤%")
    strong_amount_days20 = row.get("近20日放量天数")
    if (
        change5 is None
        or change20 is None
        or change5 <= 2
        or change20 <= 0
        or strong_amount_days20 is None
        or strong_amount_days20 < 3
        or not row.get("收盘站上MA20")
        or row.get("MA20方向") != "向上"
        or drawdown is None
        or drawdown < -10
    ):
        return False, []

    return True, [
        f"近5日上涨 {change5:+.2f}%",
        f"近20日放量天数 {strong_amount_days20} 天",
        f"距120日高点回撤仅 {drawdown:+.2f}%",
        "站上MA20且MA20向上",
    ]

def match_shrink_pullback_block(row: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    识别趋势未坏、回踩不重的板块。

    Args:
        row: 单个板块的趋势摘要。

    Returns:
        是否命中策略，以及用于解释命中的依据列表。
    """
    change5 = row.get("5日涨幅%")
    change20 = row.get("20日涨幅%")
    change60 = row.get("60日涨幅%")
    drawdown = row.get("距120日新高回撤%")
    drawdown20 = row.get("近20日最大回撤%")
    strong_amount_days20 = row.get("近20日放量天数")
    if (
        change20 is None
        or change60 is None
        or change20 <= 0
        or change60 <= 0
        or change5 is None
        or change5 < -3
        or not row.get("收盘站上MA60")
        or row.get("MA20方向") != "向上"
        or drawdown is None
        or drawdown > -3
        or drawdown < -18
        or drawdown20 is None
        or drawdown20 < -12
        or strong_amount_days20 is None
        or strong_amount_days20 > 4
    ):
        return False, []

    return True, [
        f"20日/60日涨幅分别为 {change20:+.2f}% / {change60:+.2f}%",
        f"距120日高点回撤 {drawdown:+.2f}%",
        f"近20日放量天数仅 {strong_amount_days20} 天",
        "中期趋势仍在，回踩更像整理",
    ]

def match_near_high_block(row: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    识别仍处于强势区、接近近 120 日高点的板块。

    Args:
        row: 单个板块的趋势摘要。

    Returns:
        是否命中策略，以及用于解释命中的依据列表。
    """
    drawdown = row.get("距120日新高回撤%")
    change20 = row.get("20日涨幅%")
    change60 = row.get("60日涨幅%")
    if (
        drawdown is None
        or drawdown < -5
        or change20 is None
        or change20 <= 0
        or change60 is None
        or change60 <= 0
        or not row.get("收盘站上MA20")
        or not row.get("收盘站上MA60")
    ):
        return False, []

    return True, [
        f"距120日高点回撤仅 {drawdown:+.2f}%",
        f"20日/60日涨幅分别为 {change20:+.2f}% / {change60:+.2f}%",
        "收盘仍站在MA20和MA60之上",
    ]

def match_deep_drawdown_block(row: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    识别已经从阶段高位深度回撤的板块。

    Args:
        row: 单个板块的趋势摘要。

    Returns:
        是否命中策略，以及用于解释命中的依据列表。
    """
    drawdown = row.get("距120日新高回撤%")
    if drawdown is None or drawdown > -25:
        return False, []

    reasons = [f"距120日高点回撤 {drawdown:+.2f}%"]
    change5 = row.get("5日涨幅%")
    if change5 is not None and change5 > 0:
        reasons.append(f"近5日开始修复 {change5:+.2f}%")
    else:
        reasons.append("短线仍未形成明显修复")
    return True, reasons

def match_sustained_active_block(row: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    识别最近反复活跃、持续有资金参与的板块。

    Args:
        row: 单个板块的趋势摘要。

    Returns:
        是否命中策略，以及用于解释命中的依据列表。
    """
    active_days10 = row.get("近10日活跃天数")
    strong_amount_days20 = row.get("近20日放量天数")
    change20 = row.get("20日涨幅%")
    if (
        active_days10 is None
        or active_days10 < 3
        or strong_amount_days20 is None
        or strong_amount_days20 < 2
        or change20 is None
        or change20 <= -3
    ):
        return False, []

    return True, [
        f"近10日活跃天数 {active_days10} 天",
        f"近20日放量天数 {strong_amount_days20} 天",
        f"20日涨幅 {change20:+.2f}%",
    ]

def match_low_vol_start_block(row: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    识别此前不活跃、近期开始低波转强的板块。

    Args:
        row: 单个板块的趋势摘要。

    Returns:
        是否命中策略，以及用于解释命中的依据列表。
    """
    active_days10 = row.get("近10日活跃天数")
    change5 = row.get("5日涨幅%")
    change20 = row.get("20日涨幅%")
    drawdown20 = row.get("近20日最大回撤%")
    drawdown = row.get("距120日新高回撤%")
    if (
        active_days10 is None
        or active_days10 > 2
        or change5 is None
        or change5 <= 0
        or change20 is None
        or change20 < -2
        or not row.get("收盘站上MA20")
        or row.get("MA20方向") not in ("向上", "走平")
        or drawdown20 is None
        or drawdown20 < -8
        or drawdown is None
        or drawdown <= -30
    ):
        return False, []

    return True, [
        f"近10日活跃天数仅 {active_days10} 天",
        f"近5日上涨 {change5:+.2f}%",
        "站上MA20，趋势开始改善",
        f"近20日最大回撤 {drawdown20:+.2f}%",
    ]

BLOCK_STRATEGY_DEFINITIONS = [
    {
        "name": "连续走强板块",
        "summary": "5/20/60日涨幅均为正，站上MA20/MA60，MA20向上，且距离120日高点不远。",
        "matcher": match_continuous_strength_block,
        "sort_key": lambda row: (
            _safe_non_negative(row.get("60日涨幅%")),
            _safe_non_negative(row.get("20日涨幅%")),
            _safe_negative_floor(row.get("距120日新高回撤%")),
        ),
    },
    {
        "name": "超跌反弹板块",
        "summary": "中期跌深后，近5日转强并重新站上MA20，阶段上更接近修复而不是主升。",
        "matcher": match_oversold_rebound_block,
        "sort_key": lambda row: (
            _safe_non_negative(-_safe_negative_floor(row.get("距120日新高回撤%"), 0)),
            _safe_non_negative(row.get("5日涨幅%")),
            _safe_negative_floor(row.get("20日涨幅%")),
        ),
    },
    {
        "name": "放量突破板块",
        "summary": "近5日明显走强，近20日放量天数较多，站上MA20且接近阶段高位。",
        "matcher": match_volume_breakout_block,
        "sort_key": lambda row: (
            _safe_non_negative(row.get("近20日放量天数")),
            _safe_non_negative(row.get("20日涨幅%")),
            _safe_negative_floor(row.get("距120日新高回撤%")),
        ),
    },
    {
        "name": "缩量回踩板块",
        "summary": "20/60日趋势仍强，站在MA60之上，回撤可控且近20日放量天数不多。",
        "matcher": match_shrink_pullback_block,
        "sort_key": lambda row: (
            _safe_non_negative(row.get("60日涨幅%")),
            _safe_negative_floor(row.get("距120日新高回撤%")),
            -_safe_non_negative(row.get("近20日放量天数")),
        ),
    },
    {
        "name": "接近新高板块",
        "summary": "距离120日高点回撤很小，20/60日趋势仍强，收盘保持在MA20和MA60之上。",
        "matcher": match_near_high_block,
        "sort_key": lambda row: (
            _safe_negative_floor(row.get("距120日新高回撤%")),
            _safe_non_negative(row.get("60日涨幅%")),
            _safe_non_negative(row.get("20日涨幅%")),
        ),
    },
    {
        "name": "深度回撤板块",
        "summary": "相对120日高点已经回撤较深，用来观察哪些板块仍在深坑区或刚开始修复。",
        "matcher": match_deep_drawdown_block,
        "sort_key": lambda row: (
            _safe_non_negative(-_safe_negative_floor(row.get("距120日新高回撤%"), 0)),
            _safe_negative_floor(row.get("5日涨幅%")),
        ),
    },
    {
        "name": "持续活跃板块",
        "summary": "近10日活跃天数和近20日放量天数都较高，说明最近反复有资金参与。",
        "matcher": match_sustained_active_block,
        "sort_key": lambda row: (
            _safe_non_negative(row.get("近10日活跃天数")),
            _safe_non_negative(row.get("近20日放量天数")),
            _safe_non_negative(row.get("20日涨幅%")),
        ),
    },
    {
        "name": "低波启动板块",
        "summary": "此前不太活跃，但近5日转强、站上MA20，且回撤不大，像低波起势。",
        "matcher": match_low_vol_start_block,
        "sort_key": lambda row: (
            _safe_non_negative(row.get("5日涨幅%")),
            _safe_negative_floor(row.get("20日涨幅%")),
            -_safe_non_negative(row.get("近10日活跃天数")),
        ),
    },
]


def build_block_strategy_snapshot(sector_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """
    基于全部板块摘要，筛出多组板块策略结果。

    Args:
        sector_rows: 全部可排名板块摘要行。

    Returns:
        各策略的命中列表与命中理由。
    """
    strategy_results: dict[str, list[dict[str, Any]]] = {}
    for strategy in BLOCK_STRATEGY_DEFINITIONS:
        matched_rows: list[dict[str, Any]] = []
        for row in sector_rows:
            matched, reasons = strategy["matcher"](row)
            if not matched:
                continue
            copied_row = dict(row)
            copied_row["命中理由"] = reasons
            matched_rows.append(copied_row)
        matched_rows.sort(key=strategy["sort_key"], reverse=True)
        strategy_results[strategy["name"]] = matched_rows

    return {
        "全部板块数": len(sector_rows),
        "策略结果": strategy_results,
    }

def pick_key_blocks(industry_top: list[dict[str, Any]], concept_top: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    从行业和概念热度榜中挑出少量重点板块，供后续成分股验证。

    Args:
        industry_top: 行业热度榜头部板块。
        concept_top: 概念热度榜头部板块。

    Returns:
        重点板块列表。
    """
    ordered_rows: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    row_groups = [
        ("行业Top", industry_top[:KEY_BLOCKS_PER_BUCKET]),
        ("概念Top", concept_top[:KEY_BLOCKS_PER_BUCKET]),
    ]
    for source_name, rows in row_groups:
        for row in rows:
            code = row["代码"]
            if code in seen_codes:
                continue
            seen_codes.add(code)
            copied_row = dict(row)
            copied_row["来源榜单"] = source_name
            ordered_rows.append(copied_row)
    return ordered_rows

def classify_block_action(block_row: dict[str, Any], member_rows: list[dict[str, Any]]) -> tuple[str, list[str]]:
    """
    根据板块涨跌与成分股广度，给重点板块一个简化状态判断。

    Args:
        block_row: 板块摘要行。
        member_rows: 成分股摘要行列表。

    Returns:
        一个状态标签和对应判断依据列表。
    """
    board_change = block_row.get("当日涨幅%")
    board_net_inflow = block_row.get("主力净流入亿")
    total_members = len(member_rows)
    if total_members == 0:
        return "数据不足", ["成分股数据为空，无法判断板块内部结构"]

    up_count = sum(1 for row in member_rows if (row.get("涨跌幅%") or 0) > 0)
    down_count = sum(1 for row in member_rows if (row.get("涨跌幅%") or 0) < 0)
    flat_count = total_members - up_count - down_count
    limit_up_count = sum(
        1 for row in member_rows if (row.get("涨跌幅%") or -999) >= LIMIT_UP_THRESHOLD
    )
    limit_down_count = sum(
        1 for row in member_rows if (row.get("涨跌幅%") or 999) <= LIMIT_DOWN_THRESHOLD
    )
    up_ratio = up_count / total_members if total_members else 0
    down_ratio = down_count / total_members if total_members else 0

    reasons = [
        f"成分股上涨 {up_count} 家，下跌 {down_count} 家，平盘 {flat_count} 家",
        f"涨停 {limit_up_count} 家，跌停 {limit_down_count} 家",
    ]
    if board_net_inflow is not None:
        reasons.append(f"板块主力净流入 {board_net_inflow:+.2f} 亿")

    if board_change is None:
        return "数据不足", reasons

    if board_change >= 0:
        if up_ratio >= 0.6 and (board_net_inflow is None or board_net_inflow >= 0) and limit_up_count >= 1:
            return "真上涨", reasons
        if up_ratio <= 0.45 or (board_net_inflow is not None and board_net_inflow < 0):
            return "疑似虚涨", reasons
        if up_ratio >= 0.5:
            return "分化上涨", reasons
        return "偏弱上涨", reasons

    if down_ratio >= 0.6 and (board_net_inflow is None or board_net_inflow <= 0):
        return "真下跌", reasons
    if up_ratio >= 0.35:
        return "分化下跌", reasons
    if board_net_inflow is not None and board_net_inflow > 0:
        return "疑似承接下跌", reasons
    return "偏弱下跌", reasons


# ============================================================================
# 市场数据采集与整理区
# ============================================================================

def collect_market_index_snapshot() -> dict[str, Any]:
    """
    采集宽基指数摘要，作为大盘模块的第一层基础输入。

    Args:
        无。数据由统一的 ``data.py`` 数据访问层提供。

    Returns:
        包含 6 大宽基指数摘要与总成交额的结构化结果。
    """
    index_codes = [normalize_stock_code(item["code"]) for item in MARKET_INDEX_CONFIGS]
    market_data = data_source.get_market_data(
        stock_list=[stock_code.tdx_code for stock_code in index_codes],
        period="1d",
        count=21,
        field_list=["Close", "Amount"],
    )
    close_data = market_data["Close"]
    amount_data = market_data["Amount"]
    index_rows: list[dict[str, Any]] = []
    as_of_date = ""

    for config in MARKET_INDEX_CONFIGS:
        stock_code = normalize_stock_code(config["code"])
        if stock_code.tdx_code not in close_data.columns or stock_code.tdx_code not in amount_data.columns:
            continue

        close_series = close_data[stock_code.tdx_code].sort_index().dropna()
        amount_series = amount_data[stock_code.tdx_code].sort_index().dropna()
        if len(close_series) < 2 or len(amount_series) < 1:
            continue

        day_change = calculate_percentage_change(close_series.iloc[-1], close_series.iloc[-2])
        change5 = calculate_percentage_change(close_series.iloc[-1], close_series.iloc[-6]) if len(close_series) >= 6 else None
        change20 = calculate_percentage_change(close_series.iloc[-1], close_series.iloc[-21]) if len(close_series) >= 21 else None
        amount_yi = float(amount_series.iloc[-1]) / 10000
        volume_ratio = amount_yi / (float(amount_series.iloc[-2]) / 10000) if len(amount_series) >= 2 and float(amount_series.iloc[-2]) != 0 else None
        as_of_date = str(close_series.index[-1])[:10]

        index_rows.append(
            {
                "名称": config["name"],
                "代码": stock_code.internal_code,
                "通达信代码": stock_code.tdx_code,
                "说明": config["note"],
                "收盘": round(float(close_series.iloc[-1]), 2),
                "当日%": round(day_change, 2) if day_change is not None else None,
                "5日%": round(change5, 2) if change5 is not None else None,
                "20日%": round(change20, 2) if change20 is not None else None,
                "成交额": float(amount_series.iloc[-1]),
                "成交额亿": round(amount_yi, 1),
                "量能比": round(volume_ratio, 2) if volume_ratio is not None else None,
            }
        )

    total_amount = sum(row["成交额"] for row in index_rows if row.get("成交额") is not None)
    total_amount_yi = sum(row["成交额亿"] for row in index_rows if row.get("成交额亿") is not None)
    return {
        "数据截止": as_of_date,
        "指数列表": index_rows,
        "全市场总成交额": total_amount,
        "全市场总成交额亿": round(total_amount_yi, 1),
    }

def collect_sector_heat_snapshot() -> dict[str, Any]:
    """
    采集板块列表、板块日 K，并整理成行业/概念热度榜。

    Args:
        无。数据由统一的 ``data.py`` 数据访问层提供。

    Returns:
        包含板块基础信息、热度榜和重点板块列表的结构化结果。
    """
    sectors = data_source.get_sector_list(list_type=1)
    block_type_map = load_block_type_map()
    sector_codes = [item["Code"] for item in sectors]
    open_data = None
    high_data = None
    low_data = None
    close_data = None
    amount_data = None

    for sector_code_batch in chunk_list(sector_codes, SECTOR_BATCH_SIZE):
        batch_market_data = data_source.get_market_data(
            stock_list=sector_code_batch,
            period="1d",
            count=BLOCK_LOOKBACK_BARS,
            field_list=["Open", "High", "Low", "Close", "Amount"],
        )
        if open_data is None:
            open_data = batch_market_data["Open"]
            high_data = batch_market_data["High"]
            low_data = batch_market_data["Low"]
            close_data = batch_market_data["Close"]
            amount_data = batch_market_data["Amount"]
        else:
            open_data = open_data.join(batch_market_data["Open"], how="outer")
            high_data = high_data.join(batch_market_data["High"], how="outer")
            low_data = low_data.join(batch_market_data["Low"], how="outer")
            close_data = close_data.join(batch_market_data["Close"], how="outer")
            amount_data = amount_data.join(batch_market_data["Amount"], how="outer")

    if open_data is None or high_data is None or low_data is None or close_data is None or amount_data is None:
        raise RuntimeError("板块日 K 数据拉取失败，未获取到有效返回结果。")

    sector_rows: list[dict[str, Any]] = []
    failed_count = 0
    sector_type_counter: Counter[str] = Counter()
    unknown_type_codes: list[str] = []

    for sector in sectors:
        sector_code = sector["Code"]
        if sector_code not in close_data.columns or sector_code not in amount_data.columns:
            failed_count += 1
            continue
        close_series = close_data[sector_code].sort_index().dropna()
        amount_series = amount_data[sector_code].sort_index().dropna()
        if len(close_series) < 2:
            failed_count += 1
            continue

        day_change = calculate_percentage_change(close_series.iloc[-1], close_series.iloc[-2])
        amount_yi = float(amount_series.iloc[-1]) / 10000
        trend_summary = summarize_block_trend(close_series, amount_series)

        internal_code = strip_tdx_suffix(sector_code)
        sector_type = get_block_type(sector_code, block_type_map)
        sector_type_counter[sector_type] += 1
        if sector_type == "unknown":
            unknown_type_codes.append(sector_code)

        row = {
            "代码": sector_code,
            "纯代码": internal_code,
            "名称": sector["Name"],
            "类型代码": sector_type,
            "类型": get_block_type_display(sector_code, block_type_map),
            "当日涨幅%": round(day_change, 2) if day_change is not None else None,
            "成交额": float(amount_series.iloc[-1]),
            "成交额亿": round(amount_yi, 1),
            "主力净流入": None,
            "主力净流入亿": None,
        }
        row.update(trend_summary)
        sector_rows.append(row)

    filtered_rows = [row for row in sector_rows if row["类型代码"] in RANKABLE_BLOCK_TYPES]
    industry_rows = [row for row in filtered_rows if row["类型代码"] == "industry"]
    concept_rows = [row for row in filtered_rows if row["类型代码"] == "theme"]

    industry_top = sorted(
        industry_rows,
        key=lambda row: row["当日涨幅%"] if row["当日涨幅%"] is not None else -999,
        reverse=True,
    )[:BLOCK_RANK_TOP_N]
    industry_bottom = sorted(
        industry_rows,
        key=lambda row: row["当日涨幅%"] if row["当日涨幅%"] is not None else 999,
    )[:BLOCK_RANK_TOP_N]
    concept_top = sorted(
        concept_rows,
        key=lambda row: row["当日涨幅%"] if row["当日涨幅%"] is not None else -999,
        reverse=True,
    )[:BLOCK_RANK_TOP_N]
    concept_bottom = sorted(
        concept_rows,
        key=lambda row: row["当日涨幅%"] if row["当日涨幅%"] is not None else 999,
    )[:BLOCK_RANK_TOP_N]

    ranked_rows = industry_top + industry_bottom + concept_top + concept_bottom
    ranked_codes = {row["代码"] for row in ranked_rows}
    fund_map: dict[str, float | None] = {}
    for sector_code in ranked_codes:
        try:
            more_info = data_source.get_more_info(
                stock_code=sector_code,
                field_list=["Zjl_HB"],
            )
            fund_value = safe_float(more_info.get("Zjl_HB"))
            fund_map[sector_code] = fund_value
        except Exception:
            fund_map[sector_code] = None

    for row in ranked_rows:
        fund_value = fund_map.get(row["代码"])
        row["主力净流入"] = fund_value
        row["主力净流入亿"] = round(fund_value / 10000, 2) if fund_value is not None else None

    key_blocks = pick_key_blocks(industry_top, concept_top)
    return {
        "全部板块总数": len(sectors),
        "有效板块数": len(sector_rows),
        "数据不足板块数": failed_count,
        "板块分类统计": dict(sector_type_counter),
        "未分类板块代码": unknown_type_codes,
        "过滤后板块数": len(filtered_rows),
        "全部板块摘要": sector_rows,
        "可排名板块摘要": filtered_rows,
        "行业热度榜": industry_top,
        "概念热度榜": concept_top,
        "行业跌幅榜": industry_bottom,
        "概念跌幅榜": concept_bottom,
        "重点板块": key_blocks,
        "板块K线原始数据": {
            "Open": open_data,
            "High": high_data,
            "Low": low_data,
            "Close": close_data,
            "Amount": amount_data,
        },
    }

def collect_key_sector_member_snapshot(key_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    采集重点板块的成分股，并生成第一版板块内部结构摘要。

    Args:
        key_blocks: 需要验证的重点板块列表。

    Returns:
        重点板块验证结果列表。
    """
    if not key_blocks:
        return []

    block_members: dict[str, list[str]] = {}
    member_name_cache: dict[str, str] = {}
    all_member_codes: list[str] = []
    seen_member_codes: set[str] = set()

    for block in key_blocks:
        member_rows = data_source.get_stock_list_in_sector(block_code=block["代码"], list_type=1) or []
        members: list[str] = []
        for member_row in member_rows:
            if not isinstance(member_row, dict):
                continue
            code = member_row.get("Code")
            name = member_row.get("Name")
            if not isinstance(code, str) or not code:
                continue
            members.append(code)
            if isinstance(name, str) and name:
                member_name_cache[code] = name
        block_members[block["代码"]] = members
        for code in members:
            if code not in seen_member_codes:
                seen_member_codes.add(code)
                all_member_codes.append(code)

    amount_data = None
    if all_member_codes:
        amount_market_data = data_source.get_market_data(
            stock_list=[normalize_stock_code(code).tdx_code for code in all_member_codes],
            period="1d",
            count=1,
            field_list=["Amount"],
        )
        amount_data = amount_market_data.get("Amount")

    member_cache: dict[str, dict[str, Any]] = {}
    for code in all_member_codes:
        stock_code = normalize_stock_code(code)
        more_info: dict[str, Any] = {}
        if stock_code.market_suffix != "BJ":
            more_info = data_source.get_more_info(
                stock_code=stock_code.tdx_code,
                field_list=["ZAF", "fLianB", "EverZTCount"],
            ) or {}
        amount_yi = None
        if amount_data is not None and stock_code.tdx_code in amount_data.columns:
            try:
                amount_yi = float(amount_data[stock_code.tdx_code].sort_index().iloc[-1]) / 10000
            except Exception:
                amount_yi = None
        member_cache[stock_code.tdx_code] = {
            "代码": stock_code.tdx_code,
            "涨跌幅%": safe_float(more_info.get("ZAF")),
            "量比": safe_float(more_info.get("fLianB")),
            "连板天数": safe_float(more_info.get("EverZTCount")),
            "成交额亿": round(amount_yi, 2) if amount_yi is not None else None,
        }

    analyses: list[dict[str, Any]] = []
    for block in key_blocks:
        members = [
            dict(member_cache[code])
            for code in block_members.get(block["代码"], [])
            if code in member_cache
        ]
        members_sorted = sorted(
            members,
            key=lambda row: (
                get_sort_key_desc(row.get("涨跌幅%")),
                get_sort_key_desc(row.get("成交额亿"), 0),
                get_sort_key_desc(row.get("连板天数"), 0),
                get_sort_key_desc(row.get("量比"), 0),
            ),
            reverse=True,
        )
        middle_army_sorted = sorted(
            members,
            key=lambda row: (
                get_sort_key_desc(row.get("成交额亿"), 0),
                get_sort_key_desc(row.get("涨跌幅%")),
                get_sort_key_desc(row.get("连板天数"), 0),
                get_sort_key_desc(row.get("量比"), 0),
            ),
            reverse=True,
        )
        limit_up_rows = [row for row in members_sorted if (row.get("涨跌幅%") or -999) >= LIMIT_UP_THRESHOLD]
        limit_down_rows = [row for row in members_sorted if (row.get("涨跌幅%") or 999) <= LIMIT_DOWN_THRESHOLD]
        action_label, reasons = classify_block_action(block, members)

        def format_member_name(row: dict[str, Any]) -> str:
            """
            将成分股结果格式化为“名称(纯代码)”。

            Args:
                row: 单只成分股的分析结果。

            Returns:
                适合控制台和 LLM 输入使用的名称字符串。
            """
            display_name = member_name_cache.get(row["代码"], strip_tdx_suffix(row["代码"]))
            return f"{display_name}({strip_tdx_suffix(row['代码'])})"

        total_members = len(members)
        up_count = sum(1 for row in members if (row.get("涨跌幅%") or 0) > 0)
        down_count = sum(1 for row in members if (row.get("涨跌幅%") or 0) < 0)
        analyses.append(
            {
                "代码": block["代码"],
                "纯代码": strip_tdx_suffix(block["代码"]),
                "名称": block["名称"],
                "类型代码": block["类型代码"],
                "来源榜单": block["来源榜单"],
                "当日涨幅%": block.get("当日涨幅%"),
                "20日涨幅%": block.get("20日涨幅%"),
                "主力净流入亿": block.get("主力净流入亿"),
                "成分股数": total_members,
                "上涨家数": up_count,
                "下跌家数": down_count,
                "平盘家数": total_members - up_count - down_count,
                "上涨占比%": round(up_count * 100 / total_members, 1) if total_members else None,
                "下跌占比%": round(down_count * 100 / total_members, 1) if total_members else None,
                "涨停家数": len(limit_up_rows),
                "跌停家数": len(limit_down_rows),
                "状态判断": action_label,
                "判断依据": reasons,
                "龙头候选名": [format_member_name(row) for row in members_sorted[:LEADER_CANDIDATE_COUNT]],
                "中军候选名": [format_member_name(row) for row in middle_army_sorted[:MIDDLE_ARMY_CANDIDATE_COUNT]],
                "涨停股名": [format_member_name(row) for row in limit_up_rows[:LEADER_CANDIDATE_COUNT]],
            }
        )

    return analyses


# ============================================================================
# 控制台输出区
# ============================================================================

def _fmt_num(value: Any, digits: int = 2) -> str:
    """
    将数值格式化为固定小数位字符串。

    Args:
        value: 待格式化的原始值。
        digits: 保留的小数位数。

    Returns:
        格式化后的字符串；无效值返回 ``-``。
    """
    try:
        if value is None:
            return "-"
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "-"

def _fmt_pct(value: Any, digits: int = 2) -> str:
    """
    将百分比数值格式化为带正负号的字符串。

    Args:
        value: 待格式化的百分比数值。
        digits: 保留的小数位数。

    Returns:
        格式化后的百分比字符串；无效值返回 ``-``。
    """
    try:
        if value is None:
            return "-"
        return f"{float(value):+.{digits}f}"
    except (TypeError, ValueError):
        return "-"

def print_market_index_table(index_snapshot: dict[str, Any]) -> None:
    """
    打印 6 大宽基指数表格。

    Args:
        index_snapshot: `collect_market_index_snapshot` 的返回结果。

    Returns:
        无返回值。
    """
    index_rows: list[dict[str, Any]] = index_snapshot.get("指数列表", [])
    if not index_rows:
        print("(无宽基指数数据)")
        return

    print(f"\n数据截止: {index_snapshot.get('数据截止', '')}\n")
    header = f"{'指数':<12}{'收盘':>10}{'当日%':>8}{'5日%':>8}{'20日%':>8}{'成交额亿':>12}{'量能比':>8}"
    print("-" * 72)
    print(header)
    print("-" * 72)

    for row in index_rows:
        name = row.get("名称", "")
        close = _fmt_num(row.get("收盘"), 2)
        day_pct = _fmt_pct(row.get("当日%"), 2)
        chg5 = _fmt_pct(row.get("5日%"), 2) if row.get("5日%") is not None else "-"
        chg20 = _fmt_pct(row.get("20日%"), 2) if row.get("20日%") is not None else "-"
        amount_yi = _fmt_num(row.get("成交额亿"), 1) if row.get("成交额亿") is not None else "-"
        vol_ratio = _fmt_num(row.get("量能比"), 2) if row.get("量能比") is not None else "-"
        note = row.get("说明", "")
        print(
            f"{name:<12}{close:>10}{day_pct:>8}{chg5:>8}{chg20:>8}"
            f"{amount_yi:>12}{vol_ratio:>8}  ← {note}"
        )

    total_amount_yi = index_snapshot.get("全市场总成交额亿")
    if total_amount_yi is not None:
        print(f"\n全市场总成交额: {total_amount_yi:.1f} 亿")

def print_sector_heat_tables(sector_snapshot: dict[str, Any]) -> None:
    """
    打印板块热度榜（行业/概念 Top/Bottom 共四张表）。

    Args:
        sector_snapshot: `collect_sector_heat_snapshot` 的返回结果。

    Returns:
        无返回值。
    """
    total = sector_snapshot.get("全部板块总数", 0)
    valid = sector_snapshot.get("有效板块数", 0)
    failed = sector_snapshot.get("数据不足板块数", 0)
    type_stats = sector_snapshot.get("板块分类统计", {})
    unknown_codes = sector_snapshot.get("未分类板块代码", [])
    filtered = sector_snapshot.get("过滤后板块数", 0)

    print(f"全部板块总数: {total}")
    print("日K数据拉取完成")
    print(f"计算完成: 有效 {valid} 个，数据不足 {failed} 个")
    parts = []
    for key in sorted(type_stats.keys()):
        parts.append(f"{key}={type_stats[key]}")
    print(f"板块分类统计: {', '.join(parts)}")
    if unknown_codes:
        print(f"未分类板块数: {len(unknown_codes)}")
    print(f"过滤后剩余: {filtered} 个")

    top_count = sum(
        len(sector_snapshot.get(key, []))
        for key in ("行业热度榜", "行业跌幅榜", "概念热度榜", "概念跌幅榜")
    )
    print(f"\n上榜板块共 {top_count} 个，补拉主力净流入...")

    header = (
        f"{'排名':<4}{'板块':<26}{'当日%':>8}{'20日%':>8}"
        f"{'60日%':>8}{'120日%':>8}{'主力净流入亿':>14}{'中期趋势':>12}"
    )

    def _print_block_rank(title: str, rows: list[dict[str, Any]]) -> None:
        """
        输出一组板块排名表。

        Args:
            title: 表格标题。
            rows: 待展示的板块摘要列表。

        Returns:
            无返回值。
        """
        print("\n" + "=" * 72)
        print(title)
        print("=" * 72)
        print("-" * 72)
        print(header)
        print("-" * 72)
        for i, row in enumerate(rows, 1):
            pure_code = row.get("纯代码", "")
            name_with_code = f"{row.get('名称', '')}({pure_code})"
            day_pct = _fmt_pct(row.get("当日涨幅%"), 2)
            chg20 = _fmt_pct(row.get("20日涨幅%"), 2) if row.get("20日涨幅%") is not None else "-"
            chg60 = _fmt_pct(row.get("60日涨幅%"), 2) if row.get("60日涨幅%") is not None else "-"
            chg120 = _fmt_pct(row.get("120日涨幅%"), 2) if row.get("120日涨幅%") is not None else "-"
            net_str = f"{row['主力净流入亿']:.2f}" if row.get("主力净流入亿") is not None else "-"
            trend = row.get("中期趋势") or "-"
            print(
                f"{i:<4}{name_with_code:<26}{day_pct:>8}{chg20:>8}"
                f"{chg60:>8}{chg120:>8}{net_str:>14}{trend:>12}"
            )

    top_n = BLOCK_RANK_TOP_N
    _print_block_rank(f">>> 行业板块热度榜 Top {top_n} (按当日涨幅排序)", sector_snapshot.get("行业热度榜", []))
    _print_block_rank(f">>> 概念板块热度榜 Top {top_n} (按当日涨幅排序)", sector_snapshot.get("概念热度榜", []))
    _print_block_rank(f">>> 行业板块跌幅榜 Bottom {top_n} (按当日涨幅排序)", sector_snapshot.get("行业跌幅榜", []))
    _print_block_rank(f">>> 概念板块跌幅榜 Bottom {top_n} (按当日涨幅排序)", sector_snapshot.get("概念跌幅榜", []))

def print_key_sector_analysis(key_analyses: list[dict[str, Any]]) -> None:
    """
    打印重点板块成分股验证结果。

    Args:
        key_analyses: `collect_key_sector_member_snapshot` 的返回结果。

    Returns:
        无返回值。
    """
    if not key_analyses:
        print("(无重点板块数据)")
        return

    print(f"\n重点板块成分股验证: 计划分析 {len(key_analyses)} 个板块...")
    print("\n" + "=" * 72)
    print(">>> 3. 重点板块成分股验证")
    print("=" * 72)

    for analysis in key_analyses:
        chg = analysis.get("当日涨幅%")
        chg_str = f"{chg:+.2f}%" if chg is not None else "-"
        total = analysis.get("成分股数", 0)
        up = analysis.get("上涨家数", 0)
        down = analysis.get("下跌家数", 0)
        flat_count = analysis.get("平盘家数", 0)
        limit_up = analysis.get("涨停家数", 0)
        pure_code = analysis.get("纯代码", "")
        name = analysis.get("名称", "")

        parts = [
            f"{name}({pure_code})",
            chg_str,
            f"成分股{total}只",
            f"上涨{up}",
            f"下跌{down}",
            f"平盘{flat_count}",
        ]
        if limit_up > 0:
            parts.append(f"涨停{limit_up}")
        print(f"\n  {'  '.join(parts)}")

        leaders = "、".join(analysis.get("龙头候选名", [])[:3]) or "-"
        middles = "、".join(analysis.get("中军候选名", [])[:3]) or "-"
        limit_up_names = analysis.get("涨停股名", [])
        if limit_up_names:
            lu_str = "、".join(limit_up_names[:5])
            if len(limit_up_names) > 5:
                lu_str += f"等{len(limit_up_names)}只"
        else:
            lu_str = "-"
        print(f"     龙头: {leaders}    中军: {middles}    涨停股: {lu_str}")

def print_block_strategy_tables(strategy_snapshot: dict[str, Any]) -> None:
    """
    打印板块筛选策略结果，补充热度榜之外的全市场视角。

    Args:
        strategy_snapshot: `build_block_strategy_snapshot` 的返回结果。

    Returns:
        无返回值。
    """
    strategy_results = strategy_snapshot.get("策略结果", {})
    if not isinstance(strategy_results, dict) or not strategy_results:
        print("(无板块策略结果)")
        return

    print("\n" + "=" * 72)
    print(">>> 4. 板块筛选策略")
    print("=" * 72)
    print(
        f"全部可排名板块: {strategy_snapshot.get('全部板块数', 0)} 个，"
        f"每个策略默认展示前 {BLOCK_STRATEGY_DISPLAY_LIMIT} 个"
    )

    header = (
        f"{'排名':<4}{'板块':<26}{'当日%':>8}{'20日%':>8}"
        f"{'60日%':>8}{'回撤%':>8}{'活跃天':>8}{'放量天':>8}"
    )

    for strategy_name, rows in strategy_results.items():
        display_rows = rows[:BLOCK_STRATEGY_DISPLAY_LIMIT]
        strategy_meta = next(
            (item for item in BLOCK_STRATEGY_DEFINITIONS if item["name"] == strategy_name),
            None,
        )
        print("\n" + "-" * 72)
        print(f"{strategy_name}: 命中 {len(rows)} 个")
        if strategy_meta and strategy_meta.get("summary"):
            print(f"逻辑: {strategy_meta['summary']}")
        print("-" * 72)
        if not display_rows:
            print("(无命中板块)")
            continue

        print(header)
        print("-" * 72)
        for index, row in enumerate(display_rows, 1):
            board_name = f"{row.get('名称', '')}({row.get('纯代码', '')})"
            day_pct = _fmt_pct(row.get("当日涨幅%"), 2)
            chg20 = _fmt_pct(row.get("20日涨幅%"), 2)
            chg60 = _fmt_pct(row.get("60日涨幅%"), 2)
            drawdown = _fmt_pct(row.get("距120日新高回撤%"), 2)
            active_days = str(row.get("近10日活跃天数", "-"))
            amount_days = str(row.get("近20日放量天数", "-"))
            print(
                f"{index:<4}{board_name:<26}{day_pct:>8}{chg20:>8}"
                f"{chg60:>8}{drawdown:>8}{active_days:>8}{amount_days:>8}"
            )


# ============================================================================
# LLM 市场判断区
# ============================================================================

def build_market_llm_payload(
    market_index_snapshot: dict[str, Any],
    sector_heat_snapshot: dict[str, Any],
    key_analyses: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    为大盘模块的 LLM 判断整理一份精简输入载荷。

    Args:
        market_index_snapshot: 宽基指数快照。
        sector_heat_snapshot: 板块热度快照。
        key_analyses: 重点板块成分股验证结果。

    Returns:
        适合直接序列化后送给模型的结构化输入。
    """
    return {
        "trade_date": market_index_snapshot.get("数据截止", ""),
        "market_index_snapshot": market_index_snapshot.get("指数列表", []),
        "sector_heat_snapshot": {
            "industry_top": sector_heat_snapshot.get("行业热度榜", []),
            "industry_bottom": sector_heat_snapshot.get("行业跌幅榜", []),
            "concept_top": sector_heat_snapshot.get("概念热度榜", []),
            "concept_bottom": sector_heat_snapshot.get("概念跌幅榜", []),
            "key_blocks": sector_heat_snapshot.get("重点板块", []),
        },
        "key_sector_snapshot": key_analyses,
    }

def build_market_llm_prompt(llm_payload: dict[str, Any]) -> str:
    """
    生成大盘模块合并版 LLM 判断的完整提示词。

    Args:
        llm_payload: 已整理好的输入载荷。

    Returns:
        已经拼接完成、可直接发给模型的完整 prompt。
    """
    payload_text = json.dumps(llm_payload, ensure_ascii=False, indent=2)
    return f"""
你是一个 A 股大盘与方向预案分析助手。

你的任务：
1. 先根据宽基指数判断最近市场风格与今天盘面状态。
2. 再结合行业板块、概念板块、重点板块成分股验证结果，给出次日方向预案。
3. 你必须只根据输入数据判断，不要编造外部消息、政策或新闻。

硬性规则：
1. 只允许输出合法 JSON。
2. 不允许输出 markdown。
3. 不允许输出代码块标记。
4. 不允许输出任何 JSON 之外的解释、前言、总结或备注。
5. 所有字段都必须返回。
6. 如果某项没有内容，返回空数组 [] 或字符串 "无"。
7. 如果提到具体板块，必须使用 `中文名(纯代码)` 格式，例如 `半导体(881121)`。
8. 不允许输出带 `.SH`、`.SZ`、`.BJ` 后缀的代码。

请严格输出如下 JSON：
{{
  "market_style": {{
    "recent_style": "",
    "style_strength": "",
    "short_term_continuation": "",
    "today_state": "",
    "summary": ""
  }},
  "direction_plan": {{
    "market_structure": "",
    "mid_term_leaders": [
      {{
        "name": "",
        "reason": "",
        "evidence": [""]
      }}
    ],
    "short_term_hotspots": [
      {{
        "name": "",
        "reason": "",
        "evidence": [""]
      }}
    ],
    "next_day_focus": [
      {{
        "name": "",
        "status": "",
        "bias": "",
        "reason": "",
        "confirm_signals": [""],
        "risk_signals": [""]
      }}
    ],
    "observe_directions": [
      {{
        "name": "",
        "reason": "",
        "watch_signals": [""]
      }}
    ],
    "avoid_directions": [
      {{
        "name": "",
        "reason": "",
        "risk_signals": [""]
      }}
    ],
    "conflicts": [
      {{
        "topic": "",
        "detail": ""
      }}
    ],
    "summary": ""
  }}
}}

字段取值要求：
- `market_style.recent_style`：只能从这些值中选：`科技成长`、`小盘题材`、`权重蓝筹`、`大盘普涨`、`混合轮动`、`无明显主线`
- `market_style.style_strength`：只能从这些值中选：`强`、`中`、`弱`
- `market_style.short_term_continuation`：只能从这些值中选：`强延续`、`弱延续`、`开始分歧`、`已经走弱`
- `market_style.today_state`：只能从这些值中选：`强化`、`分歧`、`回撤`、`切换`、`普跌`
- `direction_plan.market_structure`：只能从这些值中选：`老主线轮动`、`主线切换尝试`、`混合轮动`、`防守主导`
- `next_day_focus[].status`：只能从这些值中选：`主攻`、`观察`、`分歧`
- `next_day_focus[].bias`：只能从这些值中选：`进攻`、`防守`、`轮动`、`修复`

判断原则：
1. 宽基指数主要用于判断风格背景，板块数据主要用于判断方向。
2. 行业板块更偏中期资金偏好，概念板块更偏短线情绪与题材。
3. 如果板块涨幅靠前，但成分股上涨家数、涨停家数、龙头结构不配合，要谨慎。
4. 如果某个板块短线很强，但中期趋势较弱，更倾向认定为轮动或脉冲，不要轻易定义为新主线。
5. 如果多个信号冲突，必须明确写入 `conflicts`。

原始输入数据如下：
{payload_text}
""".strip()

def judge_market_with_llm(
    market_index_snapshot: dict[str, Any],
    sector_heat_snapshot: dict[str, Any],
    key_analyses: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    调用公共 LLM 接入层，完成一次合并版大盘判断。

    Args:
        market_index_snapshot: 宽基指数快照。
        sector_heat_snapshot: 板块热度快照。
        key_analyses: 重点板块成分股验证结果。

    Returns:
        包含输入载荷、完整 prompt、原始响应和解析结果的统一结构。
    """
    llm_payload = build_market_llm_payload(
        market_index_snapshot=market_index_snapshot,
        sector_heat_snapshot=sector_heat_snapshot,
        key_analyses=key_analyses,
    )
    full_prompt = build_market_llm_prompt(llm_payload)
    llm_result = call_llm_text(
        user_prompt=full_prompt,
        system_prompt="",
        temperature=0.1,
    )
    parsed_result = try_parse_json_object(llm_result["text"])
    return {
        "input_payload": llm_payload,
        "full_prompt": full_prompt,
        "raw_text": llm_result["text"],
        "raw_response": llm_result["raw_response"],
        "parsed_result": parsed_result,
        "model": llm_result["model"],
        "base_url": llm_result["base_url"],
    }

def print_market_llm_summary(llm_result: dict[str, Any]) -> None:
    """
    把 LLM 结果渲染成适合控制台查看的中文摘要。

    Args:
        llm_result: `judge_market_with_llm` 的返回结果。

    Returns:
        无返回值。
    """
    parsed_result = llm_result.get("parsed_result")
    if not isinstance(parsed_result, dict):
        print("LLM 返回未能解析成合法 JSON。")
        return

    market_style = parsed_result.get("market_style", {})
    direction_plan = parsed_result.get("direction_plan", {})

    print(f"最近主风格: {market_style.get('recent_style', '无')}")
    print(f"风格强度: {market_style.get('style_strength', '无')}")
    print(f"短线延续: {market_style.get('short_term_continuation', '无')}")
    print(f"今日状态: {market_style.get('today_state', '无')}")
    print(f"风格总结: {market_style.get('summary', '无')}")
    print(f"市场结构: {direction_plan.get('market_structure', '无')}")
    print(f"方向总结: {direction_plan.get('summary', '无')}")

    def _join_name_list(items: Any) -> str:
        """
        将 LLM 结果中的方向名称列表拼接为中文顿号分隔文本。

        Args:
            items: 可能包含名称字典的列表。

        Returns:
            拼接后的名称文本；没有有效内容时返回“无”。
        """
        if not isinstance(items, list) or not items:
            return "无"
        names = []
        for item in items:
            if isinstance(item, dict):
                names.append(str(item.get("name", "无")))
        return "、".join([name for name in names if name]) or "无"

    print(f"中期主线候选: {_join_name_list(direction_plan.get('mid_term_leaders'))}")
    print(f"短线活跃方向: {_join_name_list(direction_plan.get('short_term_hotspots'))}")
    print(f"明日优先关注: {_join_name_list(direction_plan.get('next_day_focus'))}")
    print(f"明日观察方向: {_join_name_list(direction_plan.get('observe_directions'))}")
    print(f"明日回避方向: {_join_name_list(direction_plan.get('avoid_directions'))}")

    conflicts = direction_plan.get("conflicts", [])
    if isinstance(conflicts, list) and conflicts:
        conflict_parts = []
        for item in conflicts[:3]:
            if isinstance(item, dict):
                topic = item.get("topic", "无")
                detail = item.get("detail", "无")
                conflict_parts.append(f"{topic}: {detail}")
        print(f"主要矛盾: {'；'.join(conflict_parts) if conflict_parts else '无'}")
    else:
        print("主要矛盾: 无")


# ============================================================================
# 主流程区
# ============================================================================

def run_market(args: argparse.Namespace) -> None:
    """
    执行 `market` 模块入口，跑当前第一版大盘采集主干。

    Args:
        args: 命令行参数对象。

    Returns:
        无返回值。
    """
    t0_total = time.perf_counter()

    # ── 1. 6大宽基指数 ──
    print("\n" + "=" * 72)
    print(">>> 1. 6大宽基指数")
    print("=" * 72)
    t0 = time.perf_counter()
    market_index_snapshot = collect_market_index_snapshot()
    print_market_index_table(market_index_snapshot)
    print(f"[耗时 6大宽基指数 {time.perf_counter() - t0:.1f}s]")

    # ── 2. 板块热度榜 + 3. 重点板块成分股验证 ──
    print("\n" + "=" * 72)
    print(">>> 2. 板块热度榜")
    print("=" * 72)
    t0 = time.perf_counter()
    sector_heat_snapshot = collect_sector_heat_snapshot()
    print_sector_heat_tables(sector_heat_snapshot)

    key_analyses = collect_key_sector_member_snapshot(sector_heat_snapshot["重点板块"])
    print_key_sector_analysis(key_analyses)

    strategy_snapshot = build_block_strategy_snapshot(sector_heat_snapshot.get("可排名板块摘要", []))
    print_block_strategy_tables(strategy_snapshot)
    print(f"\n[耗时 板块热度榜 {time.perf_counter() - t0:.1f}s]")

    llm_result = None
    if getattr(args, "no_llm", False):
        print("\n(已用 --no-llm 跳过 LLM 判断)")
    else:
        print("\n" + "=" * 72)
        print(">>> LLM 市场风格资金意图")
        print("=" * 72)
        t0 = time.perf_counter()
        try:
            llm_result = judge_market_with_llm(
                market_index_snapshot=market_index_snapshot,
                sector_heat_snapshot=sector_heat_snapshot,
                key_analyses=key_analyses,
            )
            print_market_llm_summary(llm_result)
            if getattr(args, "debug_llm", False):
                print("\n" + "=" * 72)
                print(">>> LLM 完整 Prompt")
                print("=" * 72)
                print(llm_result["full_prompt"])
                print("\n" + "=" * 72)
                print(">>> LLM 原始返回")
                print("=" * 72)
                print(llm_result["raw_text"])
        except Exception as exc:
            print(f"LLM 判断未执行成功: {exc}")
        print(f"[耗时 LLM判断 {time.perf_counter() - t0:.1f}s]")

    print(f"\n[总耗时 {time.perf_counter() - t0_total:.1f}s]")


# ============================================================================
# 命令行入口区
# ============================================================================

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """
    解析独立市场分析脚本的命令行参数。

    Args:
        argv: 可选参数列表；为空时读取当前进程参数。为兼容旧习惯，首个
            参数为 ``market`` 时会自动忽略。

    Returns:
        解析完成的命令行参数对象。
    """
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    if effective_argv and effective_argv[0] == "market":
        effective_argv = effective_argv[1:]

    parser = argparse.ArgumentParser(description="Cassa 独立大盘与板块分析入口。")
    parser.add_argument("--no-llm", action="store_true", help="跳过 LLM 市场判断")
    parser.add_argument(
        "--debug-llm",
        action="store_true",
        help="打印传给 LLM 的完整 Prompt 和原始返回",
    )
    return parser.parse_args(effective_argv)


def main(argv: list[str] | None = None) -> None:
    """
    初始化统一数据访问层并执行市场分析。

    Args:
        argv: 可选参数列表；主要用于测试。

    Returns:
        无返回值。
    """
    args = parse_args(argv)
    try:
        data_source.initialize(Path(__file__).resolve())
        run_market(args)
    except Exception as exc:
        print(f"market 执行失败: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
