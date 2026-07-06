"""
Cassa

主入口脚本。

当前第一版先完成通达信 `tqcenter` 的最小接入，只封装以下 5 个接口：

- `get_market_data`
- `get_market_snapshot`
- `get_stock_info`
- `get_more_info`
- `get_relation`

脚本内目录约定：

- 中间产物放在同级 `tmp/`
- 最终结果放在同级 `result/`
- 数据源放在同级 `data/`

详细协作规则见同级 `AGENTS.md`。
"""

from __future__ import annotations

# ============================================================================
# 第一层：依赖导入层
# 这一层只负责导入标准库、第三方库和通达信接口，不承载业务逻辑。
# ============================================================================

import argparse
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
import io
import json
import os
from pathlib import Path
import time
from typing import Any

import requests
from tqcenter import tq


# ============================================================================
# 第二层：常量与配置层
# 这一层集中定义路径、默认字段、代码规则和命令层会复用的静态配置。
# 后续如果要迁移大盘模块，这里会继续承接“默认参数”和“字段白名单”。
# ============================================================================

PROJECT_ROOT = Path(__file__).resolve().parent
TMP_DIR = PROJECT_ROOT / "tmp"
RESULT_DIR = PROJECT_ROOT / "result"
DATA_DIR = PROJECT_ROOT / "data"
CONTEXT_DIR = PROJECT_ROOT / "context"
BLOCK_TYPE_MAP_PATH = PROJECT_ROOT / "tdx_block_type_map.json"

SUMMARY_MARKET_DATA_FIELDS = [
    "Open",
    "High",
    "Low",
    "Close",
    "Volume",
    "Amount",
]
SUMMARY_STOCK_INFO_FIELDS = [
    "Name",
    "BelongHS300",
    "BelongRZRQ",
    "BelongHSGT",
    "IsSTGP",
    "HSStockKind",
    "ActiveCapital",
    "J_zgb",
    "J_start",
    "rs_hyname",
    "blockzscode",
]
SUMMARY_MORE_INFO_FIELDS = [
    "MainBusiness",
    "DynaPE",
    "MorePE",
    "StaticPE_TTM",
    "PB_MRQ",
    "FreeLtgb",
    "ReportDate",
    "ZTDate_Recent",
    "RecentHGDate",
    "RecentIncentDate",
]
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

# ── 选股模块常量 ──
DAILY_KLINE_DB_PATH = Path(r"D:\股神养成plan\Sentinel\all_daily_k.db")
MACD_FORMULA_NAME = "MACD"
MACD_FORMULA_ARG = "12,26,9"
SCREENER_MIN_KLINE_COUNT = 60
SCREENER_DEFAULT_POOL_SIZE = 20
SCREENER_PIVOT_LEFT_WINDOW = 5
SCREENER_PIVOT_RIGHT_WINDOW = 5
SCREENER_DIVERGENCE_MAX_INTERVAL = 40
SCREENER_DIVERGENCE_RECENCY = 30
SCREENER_CONSOLIDATION_AMPLITUDE_THRESHOLD = 0.08
SCREENER_KISS_RATIO = 0.3
SCREENER_HIGH_PULLBACK_THRESHOLD = 0.5
SCREENER_LOOKBACK_BARS_FOR_BREAK = 20
SCREENER_DIF_RECENT_WINDOW = 40
SCREENER_MACD_BATCH_COUNT = 150
SCREENER_MACD_BATCH_CHUNK_SIZE = 500


# ============================================================================
# 第三层：数据结构层
# 这一层只定义项目内部稳定传递的数据结构。
# 当前先保留最基础的股票代码对象，后续大盘模块可继续新增结构化对象。
# ============================================================================

@dataclass(frozen=True)
class StockCode:
    """统一描述项目内部股票代码与通达信股票代码的双重口径。"""

    raw_code: str
    internal_code: str
    market_suffix: str
    tdx_code: str


@dataclass(frozen=True)
class SectorCode:
    """统一描述项目内部板块代码与通达信板块代码的双重口径。"""

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


@dataclass
class KlineBar:
    """单根日 K 线的规整结构。"""

    trade_date: str
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    amount: float


@dataclass
class PivotLow:
    """枢轴低点：某一根 K 线在其左右窗口内是最低点。"""

    bar_index: int
    trade_date: str
    value: float


@dataclass
class MacdResult:
    """通达信公式引擎返回的 MACD 三条线。"""

    dif: list[float]
    dea: list[float]
    macd: list[float]


@dataclass
class ScreenResult:
    """单只股票的选股筛选结果。"""

    code: str
    passed: bool
    fail_reason: str
    kline_count: int
    latest_close: float
    latest_date: str
    latest_dif: float
    latest_dea: float
    latest_macd: float
    divergence_found: bool
    reversal_confirmed: bool
    band_position_ok: bool
    detail: dict[str, Any]


# ============================================================================
# 第四层：通达信采集层
# 这一层只负责和 `tqcenter` 交互，屏蔽初始化、参数拼装和接口调用细节。
# 后续大盘模块迁移时，指数、板块、成分股等采集逻辑都优先放在这一层。
# ============================================================================

class TdxClient:
    """封装 `tqcenter` 初始化，以及 Cassa 当前会用到的少量通达信接口。"""

    def __init__(self, script_path: Path) -> None:
        """
        创建一个可复用的通达信客户端包装器。

        Args:
            script_path: 传给 `tq.initialize` 的当前脚本路径。
        """
        self.script_path = script_path
        self.is_initialized = False

    def initialize(self) -> None:
        """
        只初始化一次 `tqcenter`。

        Raises:
            RuntimeError: 当通达信客户端未启动或初始化失败时抛出。
        """
        if self.is_initialized:
            return

        try:
            self._invoke_quietly(tq.initialize, str(self.script_path))
        except Exception as exc:
            raise RuntimeError(
                "tqcenter 初始化失败，请先打开支持 TQ 的通达信客户端。"
            ) from exc

        self.is_initialized = True

    def _invoke_quietly(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """
        静默执行第三方接口，避免把底层调试输出直接打到控制台。

        Args:
            func: 需要调用的第三方函数。
            *args: 位置参数。
            **kwargs: 命名参数。

        Returns:
            第三方函数的原始返回值。
        """
        output_buffer = io.StringIO()
        with redirect_stdout(output_buffer), redirect_stderr(output_buffer):
            return func(*args, **kwargs)

    def get_market_data(
        self,
        stock_codes: list[StockCode],
        period: str,
        count: int,
        dividend_type: str,
        start_time: str = "",
        end_time: str = "",
        field_list: list[str] | None = None,
        fill_data: bool = True,
    ) -> dict[str, Any]:
        """
        获取单只股票的 K 线行情。

        Args:
            stock_codes: 已规整的股票代码对象列表。
            period: K 线周期，例如 `1d`。
            count: 需要返回的 K 线数量。
            dividend_type: 复权方式，可选 `none`、`front`、`back`。
            start_time: 可选的起始日期，含当天。
            end_time: 可选的结束日期，含当天。
            field_list: 可选的字段列表。
            fill_data: 是否对缺失行情进行向后填充。

        Returns:
            通达信原始 K 线返回结果。
        """
        self.initialize()
        effective_fields = field_list or []
        return self._invoke_quietly(
            tq.get_market_data,
            field_list=effective_fields,
            stock_list=[stock_code.tdx_code for stock_code in stock_codes],
            period=period,
            start_time=start_time,
            end_time=end_time,
            count=count,
            dividend_type=dividend_type,
            fill_data=fill_data,
        )

    def get_market_snapshot(
        self,
        stock_code: StockCode,
        field_list: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        获取单只股票的最新快照。

        Args:
            stock_code: 已规整的股票代码对象。
            field_list: 可选的字段列表。

        Returns:
            通达信原始快照结果。
        """
        self.initialize()
        return self._invoke_quietly(
            tq.get_market_snapshot,
            stock_code=stock_code.tdx_code,
            field_list=field_list or [],
        )

    def get_stock_info(
        self,
        stock_code: StockCode,
        field_list: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        获取单只股票的基础信息。

        Args:
            stock_code: 已规整的股票代码对象。
            field_list: 可选的字段列表。

        Returns:
            通达信原始基础信息结果。
        """
        self.initialize()
        return self._invoke_quietly(
            tq.get_stock_info,
            stock_code=stock_code.tdx_code,
            field_list=field_list or [],
        )

    def get_more_info(
        self,
        stock_code: StockCode,
        field_list: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        获取单只股票的扩展信息。

        Args:
            stock_code: 已规整的股票代码对象。
            field_list: 可选的字段列表。

        Returns:
            通达信原始扩展信息结果。
        """
        self.initialize()
        return self._invoke_quietly(
            tq.get_more_info,
            stock_code=stock_code.tdx_code,
            field_list=field_list or [],
        )

    def get_relation(self, stock_code: StockCode) -> list[dict[str, Any]]:
        """
        获取单只股票所属的板块关系。

        Args:
            stock_code: 已规整的股票代码对象。

        Returns:
            通达信原始板块关系列表。
        """
        self.initialize()
        return self._invoke_quietly(tq.get_relation, stock_code=stock_code.tdx_code)

    def get_sector_list(self, list_type: int = 1) -> list[Any]:
        """
        获取 A 股板块列表。

        Args:
            list_type: 返回数据类型。`0` 只返回代码，`1` 返回代码和名称。

        Returns:
            通达信原始板块列表结果。
        """
        self.initialize()
        return self._invoke_quietly(tq.get_sector_list, list_type=list_type)

    def get_stock_list_in_sector(
        self,
        block_code: str,
        block_type: int = 0,
        list_type: int = 1,
    ) -> list[Any]:
        """
        获取板块成分股列表。

        Args:
            block_code: 板块代码或板块名称。
            block_type: 板块类型。`0` 表示系统板块指数或板块名称，`1` 表示自定义板块。
            list_type: 返回数据类型。`0` 只返回代码，`1` 返回代码和名称。

        Returns:
            通达信原始板块成分股列表。
        """
        self.initialize()
        return self._invoke_quietly(
            tq.get_stock_list_in_sector,
            block_code=block_code,
            block_type=block_type,
            list_type=list_type,
        )

    def set_formula_data(
        self,
        tdx_code: str,
        kline_bars: list[KlineBar],
    ) -> None:
        """
        把外部 K 线数据喂给通达信公式引擎，供后续 formula_zb 计算使用。

        Args:
            tdx_code: 通达信格式的股票代码，例如 `000001.SZ`。
            kline_bars: 已规整的日 K 线列表，按时间从早到晚排列。

        Raises:
            RuntimeError: 当通达信公式引擎设置数据失败时抛出。
        """
        self.initialize()
        formatted_data = [
            {
                "Date": f"{bar.trade_date} 00:00:00",
                "Open": bar.open_price,
                "High": bar.high_price,
                "Low": bar.low_price,
                "Close": bar.close_price,
                "Volume": bar.volume,
                "Amount": bar.amount,
            }
            for bar in kline_bars
        ]
        result = self._invoke_quietly(
            tq.formula_set_data,
            stock_code=tdx_code,
            stock_period="1d",
            stock_data=formatted_data,
            count=len(formatted_data),
            dividend_type=1,
        )
        if not isinstance(result, dict) or result.get("ErrorId") != "0":
            raise RuntimeError(f"通达信公式引擎设置数据失败：{result}")

    def calculate_formula_zb(
        self,
        formula_name: str,
        formula_arg: str,
    ) -> dict[str, list[float | None]]:
        """
        调用通达信技术指标公式，返回各输出线。

        需要先调用 `set_formula_data` 设置 K 线数据。

        Args:
            formula_name: 公式名称，例如 `MACD`。
            formula_arg: 公式参数，例如 `12,26,9`。

        Returns:
            以输出线名称为键的字典，值为与 K 线等长的列表。

        Raises:
            RuntimeError: 当公式计算失败时抛出。
        """
        self.initialize()
        result = self._invoke_quietly(
            tq.formula_zb,
            formula_name=formula_name,
            formula_arg=formula_arg,
        )
        if not isinstance(result, dict) or result.get("ErrorId") != "0":
            raise RuntimeError(f"通达信公式计算失败：{result}")
        return result.get("Value", {})

    def calculate_macd_batch(
        self,
        tdx_codes: list[str],
        count: int,
        chunk_size: int,
    ) -> dict[str, dict[str, list[dict[str, str]]]]:
        """
        批量调用通达信指标公式计算 MACD，内部自动分批。

        使用 `formula_process_mul_zb` 接口，无需提前 set_data，
        通达信引擎直接从本地盘后数据拉取 K 线并计算。

        Args:
            tdx_codes: 通达信格式股票代码列表。
            count: 每只股票截取的 K 线数量（从最新往前算）。
            chunk_size: 每批调用的股票数量上限。

        Returns:
            以 tdx_code 为键的字典，值为各输出线列表，例如：
            `{'000001.SZ': {'DIF': [{'Date': 'YYYYMMDD', 'Value': '0.05'}, ...], ...}}`

        Raises:
            RuntimeError: 当批量计算失败时抛出。
        """
        self.initialize()
        all_results: dict[str, dict[str, list[dict[str, str]]]] = {}

        for chunk in chunk_list(tdx_codes, chunk_size):
            result = self._invoke_quietly(
                tq.formula_process_mul_zb,
                formula_name=MACD_FORMULA_NAME,
                formula_arg=MACD_FORMULA_ARG,
                xsflag=-1,
                return_count=count,
                return_date=True,
                stock_list=chunk,
                stock_period="1d",
                count=count,
                dividend_type=1,
            )
            if not isinstance(result, dict) or result.get("ErrorId") != "0":
                raise RuntimeError(f"批量 MACD 计算失败：{result}")
            for code, values in result.items():
                if code == "ErrorId":
                    continue
                all_results[code] = values

        return all_results


class OpenAiCompatibleLlmClient:
    """封装 OpenAI 兼容格式的文本生成调用。"""

    def __init__(self, config: LlmConfig) -> None:
        """
        创建一个可复用的 LLM 客户端。

        Args:
            config: 已校验完成的 LLM 配置对象。
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
# 第五层：基础工具层
# 这一层放无状态的小工具函数，主要做目录准备、代码标准化、类型规整。
# 这些函数不直接做业务判断，只给更上层的采集、计算、输出服务。
# ============================================================================

def ensure_project_dirs() -> None:
    """
    创建项目约定的标准目录。

        Returns:
        无返回值。
    """
    for path in (TMP_DIR, RESULT_DIR, DATA_DIR, CONTEXT_DIR):
        path.mkdir(parents=True, exist_ok=True)


def mask_secret(secret_value: str) -> str:
    """
    对敏感字符串做脱敏展示。

    Args:
        secret_value: 原始敏感字符串。

    Returns:
        只保留前后少量字符的脱敏结果。
    """
    if not secret_value:
        return ""
    if len(secret_value) <= 8:
        return "*" * len(secret_value)
    return f"{secret_value[:4]}***{secret_value[-4:]}"


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

    Returns:
        可复用的 OpenAI 兼容格式客户端。
    """
    return OpenAiCompatibleLlmClient(load_llm_config_from_env())


def load_block_type_map() -> dict[str, dict[str, Any]]:
    """
    读取板块分类映射表。

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


def to_tdx_stock_code(internal_code: str) -> str:
    """
    把项目内部纯数字代码转换成通达信代码。

    Args:
        internal_code: 项目内部使用的纯数字股票代码。

    Returns:
        带市场后缀的通达信股票代码。
    """
    market_suffix = infer_market_suffix(internal_code)
    return f"{internal_code}.{market_suffix}"


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


def normalize_stock_code_list(raw_codes: list[str]) -> list[StockCode]:
    """
    批量规整股票代码列表。

    Args:
        raw_codes: 原始股票代码列表。

    Returns:
        规整后的股票代码对象列表。
    """
    return [normalize_stock_code(raw_code) for raw_code in raw_codes]


def normalize_sector_code(raw_code: str) -> SectorCode:
    """
    统一构建板块代码对象，供项目内部和通达信接口同时使用。

    Args:
        raw_code: 板块代码，允许纯数字或带后缀。

    Returns:
        同时包含纯数字代码与通达信代码的板块代码对象。
    """
    internal_code = to_internal_stock_code(raw_code)
    market_suffix = extract_market_suffix(raw_code) or infer_market_suffix(internal_code)
    return SectorCode(
        raw_code=raw_code,
        internal_code=internal_code,
        market_suffix=market_suffix,
        tdx_code=f"{internal_code}.{market_suffix}",
    )


def normalize_scalar(value: Any) -> Any:
    """
    把第三方库返回的标量尽量转换成普通 Python 值。

    Args:
        value: 通达信返回结果中的单个值。

    Returns:
        如果可以转换，就返回普通 Python 标量；否则原样返回。
    """
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return value
    return value


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
# 第六层：数据整理层
# 这一层把通达信原始返回规整成更适合项目内部消费的结构。
# 这里仍然不承载大盘结论，只做字段抽取、扁平化和格式转换。
# ============================================================================

def extract_latest_market_bar(market_data: dict[str, Any], stock_code: StockCode) -> dict[str, Any]:
    """
    从通达信 K 线结果中提取最新一根 K 线。

    Args:
        market_data: `get_market_data` 的原始返回结果。
        stock_code: 已规整的股票代码对象。

    Returns:
        一份扁平化的最新 K 线字典。
    """
    latest_bar: dict[str, Any] = {}
    for field_name, field_table in market_data.items():
        if field_name == "ErrorId":
            continue
        if not hasattr(field_table, "loc"):
            continue
        if stock_code.tdx_code not in field_table.columns:
            continue

        stock_series = field_table[stock_code.tdx_code]
        if hasattr(stock_series, "iloc") and len(stock_series) > 0:
            latest_bar[field_name] = normalize_scalar(stock_series.iloc[-1])
            latest_bar["Date"] = str(stock_series.index[-1].date())

    return latest_bar


def select_fields(source_data: dict[str, Any], field_names: list[str]) -> dict[str, Any]:
    """
    从通达信返回字典里筛出指定字段。

    Args:
        source_data: 通达信原始返回字典。
        field_names: 需要按顺序保留的字段名列表。

    Returns:
        只包含目标字段、且值已做基础规整的新字典。
    """
    selected_data: dict[str, Any] = {}
    for field_name in field_names:
        if field_name in source_data:
            selected_data[field_name] = normalize_scalar(source_data[field_name])
    if "ErrorId" in source_data:
        selected_data["ErrorId"] = normalize_scalar(source_data["ErrorId"])
    return selected_data


def build_stock_bundle(
    client: TdxClient,
    stock_code: StockCode,
    period: str,
    count: int,
    dividend_type: str,
) -> dict[str, Any]:
    """
    组装 Cassa 当前版本所需的单只股票基础数据包。

    Args:
        client: 已准备好的通达信客户端包装器。
        stock_code: 已规整的股票代码对象。
        period: K 线周期。
        count: K 线数量。
        dividend_type: 复权方式。

    Returns:
        一份适合后续摘要输出和分析使用的组合数据字典。
    """
    market_data = client.get_market_data(
        stock_codes=[stock_code],
        period=period,
        count=count,
        dividend_type=dividend_type,
        field_list=[],
    )
    market_snapshot = client.get_market_snapshot(stock_code=stock_code)
    stock_info = client.get_stock_info(
        stock_code=stock_code,
        field_list=[],
    )
    more_info = client.get_more_info(
        stock_code=stock_code,
        field_list=[],
    )
    relation_list = client.get_relation(stock_code=stock_code)

    return {
        "stock_code": stock_code.internal_code,
        "tdx_code": stock_code.tdx_code,
        "period": period,
        "count": count,
        "dividend_type": dividend_type,
        "latest_market_bar": extract_latest_market_bar(market_data, stock_code),
        "market_snapshot": market_snapshot,
        "market_data": market_data,
        "stock_info": select_fields(stock_info, SUMMARY_STOCK_INFO_FIELDS),
        "more_info": select_fields(more_info, SUMMARY_MORE_INFO_FIELDS),
        "raw_market_snapshot": market_snapshot,
        "raw_stock_info": stock_info,
        "raw_more_info": more_info,
        "raw_relation_list": relation_list,
        "relation_list": relation_list,
    }


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


def _safe_non_negative(value: Any) -> float:
    """把缺失值转成 0，便于做排序比较。"""
    try:
        if value is None:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_negative_floor(value: Any, fallback: float = -999.0) -> float:
    """把缺失值转成很小的负值，便于做倒序排序。"""
    try:
        if value is None:
            return fallback
        return float(value)
    except (TypeError, ValueError):
        return fallback


def match_continuous_strength_block(row: dict[str, Any]) -> tuple[bool, list[str]]:
    """识别持续走强、并非单日脉冲的板块。"""
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
    """识别中期跌深后开始修复的板块。"""
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
    """识别带量启动或带量突破的板块。"""
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
    """识别趋势未坏、回踩不重的板块。"""
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
    """识别仍处于强势区、接近近120日高点的板块。"""
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
    """识别已经从高位回撤很深的板块。"""
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
    """识别最近反复活跃、持续有资金参与的板块。"""
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
    """识别此前不显眼、最近开始低波转强的板块。"""
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


def collect_market_index_snapshot(client: TdxClient) -> dict[str, Any]:
    """
    采集宽基指数摘要，作为大盘模块的第一层基础输入。

    Args:
        client: 已准备好的通达信客户端包装器。

    Returns:
        包含 6 大宽基指数摘要与总成交额的结构化结果。
    """
    index_codes = [normalize_stock_code(item["code"]) for item in MARKET_INDEX_CONFIGS]
    market_data = client.get_market_data(
        stock_codes=index_codes,
        period="1d",
        count=21,
        dividend_type="none",
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


def collect_sector_heat_snapshot(client: TdxClient) -> dict[str, Any]:
    """
    采集板块列表、板块日 K，并整理成行业/概念热度榜。

    Args:
        client: 已准备好的通达信客户端包装器。

    Returns:
        包含板块基础信息、热度榜和重点板块列表的结构化结果。
    """
    sectors = client.get_sector_list(list_type=1)
    block_type_map = load_block_type_map()
    sector_codes = [item["Code"] for item in sectors]
    open_data = None
    high_data = None
    low_data = None
    close_data = None
    amount_data = None

    for sector_code_batch in chunk_list(sector_codes, SECTOR_BATCH_SIZE):
        batch_market_data = client.get_market_data(
            stock_codes=[
                StockCode(
                    raw_code=sector_code,
                    internal_code=strip_tdx_suffix(sector_code),
                    market_suffix=sector_code.split(".")[-1],
                    tdx_code=sector_code,
                )
                for sector_code in sector_code_batch
            ],
            period="1d",
            count=BLOCK_LOOKBACK_BARS,
            dividend_type="none",
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
            more_info = client.get_more_info(
                stock_code=StockCode(
                    raw_code=sector_code,
                    internal_code=strip_tdx_suffix(sector_code),
                    market_suffix=sector_code.split(".")[-1],
                    tdx_code=sector_code,
                ),
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


def collect_key_sector_member_snapshot(client: TdxClient, key_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    采集重点板块的成分股，并生成第一版板块内部结构摘要。

    Args:
        client: 已准备好的通达信客户端包装器。
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
        member_rows = client.get_stock_list_in_sector(block_code=block["代码"], list_type=1) or []
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
        amount_market_data = client.get_market_data(
            stock_codes=[normalize_stock_code(code) for code in all_member_codes],
            period="1d",
            count=1,
            dividend_type="none",
            field_list=["Amount"],
        )
        amount_data = amount_market_data.get("Amount")

    member_cache: dict[str, dict[str, Any]] = {}
    for code in all_member_codes:
        stock_code = normalize_stock_code(code)
        more_info: dict[str, Any] = {}
        if stock_code.market_suffix != "BJ":
            more_info = client.get_more_info(
                stock_code=stock_code,
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
# 第六层补充：选股模块 —— SQLite 数据读取 + MACD 计算 + 筛选逻辑
# 这一块负责从本地 SQLite 读取 K 线、喂给通达信公式引擎算 MACD、执行三步筛选。
# ============================================================================

def load_stock_codes_from_db(
    db_path: Path,
    pool_size: int,
    min_kline_count: int,
) -> list[str]:
    """
    从 SQLite 数据库中选取 K 线数量最多的前 N 只股票代码。

    Args:
        db_path: SQLite 数据库路径。
        pool_size: 需要返回的股票数量上限。
        min_kline_count: K 线数量的最低门槛。

    Returns:
        纯数字股票代码列表，按 K 线数量从多到少排列。
    """
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        if pool_size == 0:
            cursor.execute(
                "SELECT code, COUNT(*) as cnt FROM daily_kline "
                "GROUP BY code HAVING cnt >= ? ORDER BY cnt DESC",
                (min_kline_count,),
            )
        else:
            cursor.execute(
                "SELECT code, COUNT(*) as cnt FROM daily_kline "
                "GROUP BY code HAVING cnt >= ? ORDER BY cnt DESC LIMIT ?",
                (min_kline_count, pool_size),
            )
        rows = cursor.fetchall()
    finally:
        conn.close()

    return [row[0] for row in rows]


def load_daily_kline_from_db(
    db_path: Path,
    code: str,
    min_kline_count: int,
) -> list[KlineBar] | None:
    """
    从 SQLite 数据库读取单只股票的全部日 K 线。

    Args:
        db_path: SQLite 数据库路径。
        code: 纯数字股票代码。
        min_kline_count: K 线数量的最低门槛，不足则返回 None。

    Returns:
        按时间从早到晚排列的 K 线列表；如果数据不足则返回 None。
    """
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT trade_date, open_price, high_price, low_price, close_price, volume, amount "
            "FROM daily_kline WHERE code = ? ORDER BY trade_date ASC",
            (code,),
        )
        rows = cursor.fetchall()
    finally:
        conn.close()

    if len(rows) < min_kline_count:
        return None

    bars: list[KlineBar] = []
    for row in rows:
        bars.append(KlineBar(
            trade_date=row[0],
            open_price=float(row[1]),
            high_price=float(row[2]),
            low_price=float(row[3]),
            close_price=float(row[4]),
            volume=float(row[5]),
            amount=float(row[6]),
        ))
    return bars


def align_macd_with_kline(
    kline_bars: list[KlineBar],
    macd_raw: dict[str, list[dict[str, str]]],
) -> MacdResult | None:
    """
    把批量 MACD 结果按日期和 SQLite K 线对齐。

    通达信批量接口返回的 MACD 数据按日期从早到晚排列，
    通过日期匹配把 MACD 值对齐到 K 线序列上。
    如果尾部 MACD 数据缺失（停牌等），用 0.0 填充。

    Args:
        kline_bars: SQLite 读取的 K 线列表，按时间从早到晚。
        macd_raw: 批量接口返回的单只股票 MACD 字典，例如
            `{'DIF': [{'Date': 'YYYYMMDD', 'Value': '0.05'}, ...], ...}`。

    Returns:
        对齐后的 MacdResult；如果数据为空则返回 None。
    """
    if not macd_raw:
        return None

    def build_date_value_map(items: list[dict[str, str]]) -> dict[str, float]:
        result: dict[str, float] = {}
        for item in items:
            date_str = item.get("Date", "")
            value_str = item.get("Value", "")
            try:
                result[date_str] = float(value_str)
            except (TypeError, ValueError):
                result[date_str] = 0.0
        return result

    dif_map = build_date_value_map(macd_raw.get("DIF", []))
    dea_map = build_date_value_map(macd_raw.get("DEA", []))
    macd_map = build_date_value_map(macd_raw.get("MACD", []))

    dif: list[float] = []
    dea: list[float] = []
    macd: list[float] = []

    for bar in kline_bars:
        # SQLite 日期格式为 YYYY-MM-DD，通达信返回格式为 YYYYMMDD
        date_compact = bar.trade_date.replace("-", "")
        dif.append(dif_map.get(date_compact, 0.0))
        dea.append(dea_map.get(date_compact, 0.0))
        macd.append(macd_map.get(date_compact, 0.0))

    return MacdResult(dif=dif, dea=dea, macd=macd)


def find_pivot_lows(
    values: list[float],
    left_window: int,
    right_window: int,
    dates: list[str],
) -> list[PivotLow]:
    """
    检测序列中的枢轴低点。

    某个位置 i 是枢轴低点，当且仅当 values[i] 是 [i-left, i+right] 范围内的最小值。

    Args:
        values: 数值序列。
        left_window: 左侧窗口大小。
        right_window: 右侧窗口大小。
        dates: 与 values 等长的日期序列。

    Returns:
        枢轴低点列表，按位置从早到晚排列。
    """
    pivot_lows: list[PivotLow] = []
    total = len(values)

    for i in range(left_window, total - right_window):
        window_start = i - left_window
        window_end = i + right_window + 1
        window = values[window_start:window_end]
        if values[i] == min(window) and values[i] < max(window):
            pivot_lows.append(PivotLow(
                bar_index=i,
                trade_date=dates[i],
                value=values[i],
            ))

    return pivot_lows


def check_bottom_divergence(
    price_lows: list[PivotLow],
    macd_values: list[float],
    max_interval: int,
    recency: int,
    total_bars: int,
) -> dict[str, Any]:
    """
    检测底背离：最近的价格低点低于前一个价格低点，但对应位置的 MACD 值高于前一个。

    直接取价格低点对应位置的 MACD 柱状图值进行比较，不再要求 MACD 也形成 pivot low。
    同时要求最近的价格低点距离最新 K 线不超过 recency 根，确保背离有时效性。

    Args:
        price_lows: 价格枢轴低点列表。
        macd_values: MACD 柱状图序列（与 K 线等长）。
        max_interval: 两个低点之间的最大 K 线距离。
        recency: 最近低点距最新 K 线的最大允许距离。
        total_bars: K 线总数量。

    Returns:
        包含是否发现背离、背离位置等信息的字典。
    """
    if len(price_lows) < 2:
        return {"found": False, "reason": "低点数量不足"}

    latest_price_low = price_lows[-1]
    prev_price_low = price_lows[-2]

    # 时效性约束：最近的价格低点距最新 K 线不超过 recency 根
    bars_since_latest = total_bars - 1 - latest_price_low.bar_index
    if bars_since_latest > recency:
        return {"found": False, "reason": f"最近低点距今{bars_since_latest}根，超过{recency}根时效限制"}

    # 两个低点间隔不超过 max_interval
    if latest_price_low.bar_index - prev_price_low.bar_index > max_interval:
        return {"found": False, "reason": "两个价格低点间隔超过阈值"}

    # 价格必须创新低
    if latest_price_low.value >= prev_price_low.value:
        return {"found": False, "reason": "价格未创新低"}

    # 直接取价格低点对应位置的 MACD 值比较
    latest_macd_value = macd_values[latest_price_low.bar_index]
    prev_macd_value = macd_values[prev_price_low.bar_index]

    if latest_macd_value <= prev_macd_value:
        return {"found": False, "reason": "MACD 值未抬高"}

    return {
        "found": True,
        "prev_price_low": prev_price_low,
        "latest_price_low": latest_price_low,
        "prev_macd_value": prev_macd_value,
        "latest_macd_value": latest_macd_value,
    }


def check_trend_reversal(
    dif: list[float],
    dea: list[float],
    divergence_result: dict[str, Any],
    kline_bars: list[KlineBar],
) -> dict[str, Any]:
    """
    确认趋势反转：DIF 上零轴 + 零轴下方金叉 + 下跌节奏被打破。

    Args:
        dif: DIF 序列。
        dea: DEA 序列。
        divergence_result: 底背离检测结果。
        kline_bars: K 线列表。

    Returns:
        包含是否确认反转、各项子条件状态的字典。
    """
    total = len(dif)
    if total < 2:
        return {"confirmed": False, "reason": "数据不足"}

    latest_dif = dif[-1]

    # 条件1：DIF 当前在零轴上方
    dif_above_zero = latest_dif > 0

    # 条件2：在背离低点之后出现过零轴下方金叉（DIF 从下穿上 DEA，且两者都在零轴下方）
    golden_cross_below_zero = False
    if divergence_result.get("found"):
        divergence_bar = divergence_result["latest_price_low"].bar_index
        for i in range(divergence_bar + 1, total):
            if i < 1:
                continue
            prev_dif = dif[i - 1]
            prev_dea = dea[i - 1]
            curr_dif = dif[i]
            curr_dea = dea[i]
            if prev_dif <= prev_dea and curr_dif > curr_dea and curr_dif < 0 and curr_dea < 0:
                golden_cross_below_zero = True
                break

    # 条件3：下跌节奏被打破 —— 最近 N 根 K 线的最低价 > 最近的 pivot low
    rhythm_broken = False
    if divergence_result.get("found"):
        divergence_low_value = divergence_result["latest_price_low"].value
        lookback_start = max(0, total - SCREENER_LOOKBACK_BARS_FOR_BREAK)
        recent_lowest = min(bar.low_price for bar in kline_bars[lookback_start:])
        rhythm_broken = recent_lowest > divergence_low_value

    confirmed = dif_above_zero and golden_cross_below_zero and rhythm_broken

    return {
        "confirmed": confirmed,
        "dif_above_zero": dif_above_zero,
        "golden_cross_below_zero": golden_cross_below_zero,
        "rhythm_broken": rhythm_broken,
    }


def check_band_position(
    dif: list[float],
    dea: list[float],
    kline_bars: list[KlineBar],
) -> dict[str, Any]:
    """
    判断波段位置：盘整 + 飞吻 + 排除高位回调。

    Args:
        dif: DIF 序列。
        dea: DEA 序列。
        kline_bars: K 线列表。

    Returns:
        包含是否处于合适波段位置、各项子条件状态的字典。
    """
    total = len(dif)
    if total < SCREENER_LOOKBACK_BARS_FOR_BREAK:
        return {"ok": False, "reason": "数据不足"}

    latest_dif = dif[-1]

    # 条件1：盘整 —— 最近 N 根 K 线振幅小于阈值
    lookback_start = total - SCREENER_LOOKBACK_BARS_FOR_BREAK
    recent_bars = kline_bars[lookback_start:]
    recent_high = max(bar.high_price for bar in recent_bars)
    recent_low = min(bar.low_price for bar in recent_bars)
    recent_avg = sum(bar.close_price for bar in recent_bars) / len(recent_bars)
    amplitude = (recent_high - recent_low) / recent_avg if recent_avg > 0 else 999
    is_consolidating = amplitude < SCREENER_CONSOLIDATION_AMPLITUDE_THRESHOLD

    # 条件2：飞吻 —— DIF 在零轴上方但贴近零轴
    recent_dif_max = max(abs(d) for d in dif[-SCREENER_DIF_RECENT_WINDOW:])
    kiss_upper = recent_dif_max * SCREENER_KISS_RATIO
    is_kiss = 0 < latest_dif < kiss_upper if kiss_upper > 0 else False

    # 条件3：排除高位回调 —— DIF 从近期高点的回落幅度不超过阈值
    dif_recent_window = dif[-SCREENER_DIF_RECENT_WINDOW:]
    dif_high = max(dif_recent_window)
    pullback_ratio = (dif_high - latest_dif) / dif_high if dif_high > 0 else 0
    not_high_pullback = pullback_ratio < SCREENER_HIGH_PULLBACK_THRESHOLD

    # 条件4：没有出现高位死叉（DIF 从上方下穿 DEA 且 DIF 仍在较高位置）
    no_high_death_cross = True
    if total >= 2:
        prev_dif = dif[-2]
        prev_dea = dea[-2]
        curr_dif = dif[-1]
        curr_dea = dea[-1]
        if prev_dif > prev_dea and curr_dif <= curr_dea and curr_dif > kiss_upper:
            no_high_death_cross = False

    ok = is_consolidating and is_kiss and not_high_pullback and no_high_death_cross

    return {
        "ok": ok,
        "is_consolidating": is_consolidating,
        "amplitude": amplitude,
        "is_kiss": is_kiss,
        "kiss_upper": kiss_upper,
        "not_high_pullback": not_high_pullback,
        "pullback_ratio": pullback_ratio,
        "no_high_death_cross": no_high_death_cross,
    }


def screen_single_stock(
    code: str,
    kline_bars: list[KlineBar],
    macd: MacdResult,
    debug: bool = False,
) -> ScreenResult:
    """
    对单只股票执行纯筛选逻辑（底背离 + 趋势反转 + 波段位置）。

    数据加载和 MACD 计算由调用方完成，本函数只做筛选判断。

    Args:
        code: 纯数字股票代码。
        kline_bars: 已从 SQLite 加载的 K 线列表。
        macd: 已对齐的 MACD 结果。
        debug: 是否在控制台打印详细筛选过程。

    Returns:
        选股筛选结果对象。
    """
    dates = [bar.trade_date for bar in kline_bars]

    # 第3步：底背离检测
    price_lows = find_pivot_lows(
        [bar.low_price for bar in kline_bars],
        SCREENER_PIVOT_LEFT_WINDOW,
        SCREENER_PIVOT_RIGHT_WINDOW,
        dates,
    )
    divergence_result = check_bottom_divergence(
        price_lows, macd.macd, SCREENER_DIVERGENCE_MAX_INTERVAL,
        SCREENER_DIVERGENCE_RECENCY, len(kline_bars),
    )
    divergence_found = divergence_result.get("found", False)

    if debug:
        print(f"  [{code}] 底背离: {divergence_result}")

    if not divergence_found:
        return ScreenResult(
            code=code, passed=False, fail_reason=f"底背离未通过: {divergence_result.get('reason', '')}",
            kline_count=len(kline_bars), latest_close=kline_bars[-1].close_price,
            latest_date=kline_bars[-1].trade_date, latest_dif=macd.dif[-1],
            latest_dea=macd.dea[-1], latest_macd=macd.macd[-1],
            divergence_found=False, reversal_confirmed=False,
            band_position_ok=False, detail={"divergence": divergence_result},
        )

    # 第4步：趋势反转确认
    reversal_result = check_trend_reversal(macd.dif, macd.dea, divergence_result, kline_bars)
    reversal_confirmed = reversal_result.get("confirmed", False)

    if debug:
        print(f"  [{code}] 趋势反转: {reversal_result}")

    if not reversal_confirmed:
        return ScreenResult(
            code=code, passed=False, fail_reason=f"趋势反转未通过: {reversal_result}",
            kline_count=len(kline_bars), latest_close=kline_bars[-1].close_price,
            latest_date=kline_bars[-1].trade_date, latest_dif=macd.dif[-1],
            latest_dea=macd.dea[-1], latest_macd=macd.macd[-1],
            divergence_found=True, reversal_confirmed=False,
            band_position_ok=False, detail={"divergence": divergence_result, "reversal": reversal_result},
        )

    # 第5步：波段位置判断
    band_result = check_band_position(macd.dif, macd.dea, kline_bars)
    band_position_ok = band_result.get("ok", False)

    if debug:
        print(f"  [{code}] 波段位置: {band_result}")

    return ScreenResult(
        code=code, passed=band_position_ok,
        fail_reason="" if band_position_ok else f"波段位置未通过: {band_result}",
        kline_count=len(kline_bars), latest_close=kline_bars[-1].close_price,
        latest_date=kline_bars[-1].trade_date, latest_dif=macd.dif[-1],
        latest_dea=macd.dea[-1], latest_macd=macd.macd[-1],
        divergence_found=True, reversal_confirmed=True,
        band_position_ok=band_position_ok,
        detail={"divergence": divergence_result, "reversal": reversal_result, "band": band_result},
    )


# ============================================================================
# 第七层：输出渲染层
# 这一层负责把内部结构渲染成控制台摘要或 JSON 文本。
# 后续大盘模块的控制台输出、debug JSON、Markdown 报告也会按这个思路分层。
# ============================================================================

def print_stock_bundle_summary(stock_bundle: dict[str, Any]) -> None:
    """
    打印单只股票数据包的摘要信息。

    Args:
        stock_bundle: `build_stock_bundle` 返回的整理后结果。

    Returns:
        无返回值。
    """
    stock_code = stock_bundle["stock_code"]
    stock_info = stock_bundle["stock_info"]
    market_snapshot = stock_bundle["market_snapshot"]
    latest_market_bar = stock_bundle["latest_market_bar"]
    relation_list = stock_bundle["relation_list"]
    tdx_code = stock_bundle["tdx_code"]

    print(f"股票: {stock_code} ({tdx_code}) {stock_info.get('Name', '')}".strip())
    print(
        f"快照: 现价={market_snapshot.get('Now')} 开盘={market_snapshot.get('Open')} "
        f"最高={market_snapshot.get('Max')} 最低={market_snapshot.get('Min')} "
        f"总手={market_snapshot.get('Volume')}"
    )
    print(
        f"最新 {stock_bundle['period']} K线: 日期={latest_market_bar.get('Date')} "
        f"收盘={latest_market_bar.get('Close')} 成交量={latest_market_bar.get('Volume')} "
        f"成交额={latest_market_bar.get('Amount')}"
    )
    print(
        f"基础信息: 行业={stock_info.get('rs_hyname')} 上市日期={stock_info.get('J_start')} "
        f"流通股本={stock_info.get('ActiveCapital')} 总股本={stock_info.get('J_zgb')}"
    )
    print(
        f"扩展信息: 动态市盈率={stock_bundle['more_info'].get('DynaPE')} "
        f"TTM市盈率={stock_bundle['more_info'].get('StaticPE_TTM')} "
        f"市净率={stock_bundle['more_info'].get('PB_MRQ')} "
        f"最近涨停={stock_bundle['more_info'].get('ZTDate_Recent')}"
    )
    print(f"所属板块: 共 {len(relation_list)} 个")
    for relation in relation_list[:10]:
        print(
            f"  - {relation.get('BlockType')} | {relation.get('BlockName')} | "
            f"{relation.get('BlockCode')} | 成分股数={relation.get('GPNume')}"
        )


def convert_to_json_ready(value: Any) -> Any:
    """
    把返回结果转换成适合 JSON 输出的普通 Python 结构。

    Args:
        value: 任意返回对象。

    Returns:
        可直接传给 `json.dumps` 的普通结构。
    """
    if hasattr(value, "to_dict"):
        try:
            return convert_to_json_ready(value.to_dict())
        except Exception:
            pass
    if isinstance(value, dict):
        return {str(key): convert_to_json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [convert_to_json_ready(item) for item in value]
    return normalize_scalar(value)


def print_json_output(value: Any) -> None:
    """
    以格式化 JSON 形式打印接口返回结果。

    Args:
        value: 需要打印的对象。

    Returns:
        无返回值。
    """
    print(json.dumps(convert_to_json_ready(value), ensure_ascii=False, indent=2, default=str))


def _fmt_num(value: Any, digits: int = 2) -> str:
    """把数值格式化成指定位数的字符串，无效时返回 `-`。"""
    try:
        if value is None:
            return "-"
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "-"


def _fmt_pct(value: Any, digits: int = 2) -> str:
    """把百分比数值格式化成带符号的字符串，无效时返回 `-`。"""
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
# 第八层：命令执行层
# 这一层负责把命令行子命令映射到具体能力，属于“输入分发层”。
# 它只负责组织参数和调用下层能力，不负责底层采集实现。
# ============================================================================

def run_market(args: argparse.Namespace, client: TdxClient) -> None:
    """
    执行 `market` 模块入口，跑当前第一版大盘采集主干。

    Args:
        args: 命令行参数对象。
        client: 通达信客户端包装器。

    Returns:
        无返回值。
    """
    t0_total = time.perf_counter()

    # ── 1. 6大宽基指数 ──
    print("\n" + "=" * 72)
    print(">>> 1. 6大宽基指数")
    print("=" * 72)
    t0 = time.perf_counter()
    market_index_snapshot = collect_market_index_snapshot(client)
    print_market_index_table(market_index_snapshot)
    print(f"[耗时 6大宽基指数 {time.perf_counter() - t0:.1f}s]")

    # ── 2. 板块热度榜 + 3. 重点板块成分股验证 ──
    print("\n" + "=" * 72)
    print(">>> 2. 板块热度榜")
    print("=" * 72)
    t0 = time.perf_counter()
    sector_heat_snapshot = collect_sector_heat_snapshot(client)
    print_sector_heat_tables(sector_heat_snapshot)

    key_analyses = collect_key_sector_member_snapshot(client, sector_heat_snapshot["重点板块"])
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

def run_tdx_api_snapshot(args: argparse.Namespace, client: TdxClient) -> None:
    """
    执行 `tdx_api snapshot` 子命令。

    Args:
        args: 命令行参数对象。
        client: 通达信客户端包装器。

    Returns:
        无返回值。
    """
    stock_code = normalize_stock_code(args.code)
    print_json_output(client.get_market_snapshot(stock_code))


def run_tdx_api_stock_info(args: argparse.Namespace, client: TdxClient) -> None:
    """
    执行 `tdx_api stock_info` 子命令。

    Args:
        args: 命令行参数对象。
        client: 通达信客户端包装器。

    Returns:
        无返回值。
    """
    stock_code = normalize_stock_code(args.code)
    print_json_output(client.get_stock_info(stock_code, field_list=[]))


def run_tdx_api_more_info(args: argparse.Namespace, client: TdxClient) -> None:
    """
    执行 `tdx_api more_info` 子命令。

    Args:
        args: 命令行参数对象。
        client: 通达信客户端包装器。

    Returns:
        无返回值。
    """
    stock_code = normalize_stock_code(args.code)
    print_json_output(client.get_more_info(stock_code, field_list=[]))


def run_tdx_api_relation(args: argparse.Namespace, client: TdxClient) -> None:
    """
    执行 `tdx_api relation` 子命令。

    Args:
        args: 命令行参数对象。
        client: 通达信客户端包装器。

    Returns:
        无返回值。
    """
    stock_code = normalize_stock_code(args.code)
    print_json_output(client.get_relation(stock_code))


def run_tdx_api_sector_list(args: argparse.Namespace, client: TdxClient) -> None:
    """
    执行 `tdx_api sector_list` 子命令。

    Args:
        args: 命令行参数对象。
        client: 通达信客户端包装器。

    Returns:
        无返回值。
    """
    print_json_output(client.get_sector_list(list_type=args.list_type))


def run_tdx_api_stock_list_in_sector(args: argparse.Namespace, client: TdxClient) -> None:
    """
    执行 `tdx_api stock_list_in_sector` 子命令。

    Args:
        args: 命令行参数对象。
        client: 通达信客户端包装器。

    Returns:
        无返回值。
    """
    print_json_output(
        client.get_stock_list_in_sector(
            block_code=args.block_code,
            block_type=args.block_type,
            list_type=args.list_type,
        )
    )


def run_tdx_api_summary(args: argparse.Namespace, client: TdxClient) -> None:
    """
    执行 `tdx_api summary` 子命令。

    Args:
        args: 命令行参数对象。
        client: 通达信客户端包装器。

    Returns:
        无返回值。
    """
    stock_code = normalize_stock_code(args.code)
    stock_bundle = build_stock_bundle(
        client=client,
        stock_code=stock_code,
        period=args.period,
        count=args.count,
        dividend_type=args.dividend_type,
    )
    print_stock_bundle_summary(stock_bundle)
    print("")
    print("完整接口返回:")
    print_json_output(
        {
            "market_snapshot": stock_bundle["raw_market_snapshot"],
            "stock_info": stock_bundle["raw_stock_info"],
            "more_info": stock_bundle["raw_more_info"],
            "relation": stock_bundle["raw_relation_list"],
        }
    )


def run_llm_config(args: argparse.Namespace, client: TdxClient) -> None:
    """
    执行 `llm config` 子命令，检查当前环境变量配置。

    Args:
        args: 命令行参数对象。
        client: 通达信客户端包装器。此命令不会使用该对象。

    Returns:
        无返回值。
    """
    _ = args
    _ = client
    config = load_llm_config_from_env()
    print_json_output(
        {
            "api_key_env": LLM_API_KEY_ENV_NAME,
            "api_key_masked": mask_secret(config.api_key),
            "base_url": config.base_url,
            "model": config.model,
            "timeout_seconds": config.timeout_seconds,
        }
    )


def run_llm_text(args: argparse.Namespace, client: TdxClient) -> None:
    """
    执行 `llm text` 子命令，测试公共文本生成能力。

    Args:
        args: 命令行参数对象。
        client: 通达信客户端包装器。此命令不会使用该对象。

    Returns:
        无返回值。
    """
    _ = client
    result = call_llm_text(
        user_prompt=args.prompt,
        system_prompt=args.system,
        temperature=args.temperature,
    )
    print(result["text"])


def print_screener_summary(results: list[ScreenResult]) -> None:
    """
    打印选股结果摘要表格。

    Args:
        results: 全部股票的筛选结果列表。

    Returns:
        无返回值。
    """
    print("\n" + "=" * 72)
    print("选股结果摘要")
    print("=" * 72)

    # 统计
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    divergence_count = sum(1 for r in results if r.divergence_found)
    reversal_count = sum(1 for r in results if r.reversal_confirmed)

    print(f"扫描: {total} 只 | 底背离: {divergence_count} | 趋势反转: {reversal_count} | 通过: {passed}")
    print("-" * 72)

    # 通过的股票
    if passed > 0:
        print("\n>>> 通过筛选")
        print(f"{'代码':<8} {'K线':>4} {'最新价':>8} {'日期':<12} {'DIF':>8} {'DEA':>8} {'MACD':>8}")
        print("-" * 72)
        for r in results:
            if r.passed:
                print(f"{r.code:<8} {r.kline_count:>4} {r.latest_close:>8.2f} {r.latest_date:<12} {r.latest_dif:>8.3f} {r.latest_dea:>8.3f} {r.latest_macd:>8.3f}")

    # 未通过的摘要
    failed = [r for r in results if not r.passed]
    if failed:
        print(f"\n>>> 未通过 ({len(failed)} 只)")
        print(f"{'代码':<8} {'K线':>4} {'阶段':<8} {'原因'}")
        print("-" * 72)
        for r in failed:
            if not r.divergence_found:
                stage = "底背离"
            elif not r.reversal_confirmed:
                stage = "趋势反转"
            elif not r.band_position_ok:
                stage = "波段位置"
            else:
                stage = "未知"
            reason = r.fail_reason[:50] if r.fail_reason else ""
            print(f"{r.code:<8} {r.kline_count:>4} {stage:<8} {reason}")


def run_screener(args: argparse.Namespace, client: TdxClient) -> None:
    """
    执行 `screener` 子命令，对股票池执行选股筛选。

    使用通达信批量公式接口一次性计算全部股票的 MACD，
    再逐只对齐 K 线并执行三步筛选。

    Args:
        args: 命令行参数对象。
        client: 通达信客户端包装器。

    Returns:
        无返回值。
    """
    t0_total = time.perf_counter()

    pool_size = args.pool_size
    min_kline = args.min_kline
    debug = args.debug

    if pool_size == 0:
        print(f"股票池: 全市场 | 最小K线数: {min_kline}")
    else:
        print(f"股票池大小: {pool_size} | 最小K线数: {min_kline}")

    # 第1步：从 SQLite 读取股票池
    print("\n>>> 1. 从数据库加载股票池...")
    codes = load_stock_codes_from_db(DAILY_KLINE_DB_PATH, pool_size, min_kline)
    print(f"加载到 {len(codes)} 只股票")

    if not codes:
        print("股票池为空，退出。")
        return

    # 第2步：批量计算 MACD
    print(f"\n>>> 2. 批量计算 MACD（每批 {SCREENER_MACD_BATCH_CHUNK_SIZE} 只）...")
    t0_macd = time.perf_counter()
    tdx_codes = [to_tdx_stock_code(code) for code in codes]
    try:
        macd_batch = client.calculate_macd_batch(
            tdx_codes=tdx_codes,
            count=SCREENER_MACD_BATCH_COUNT,
            chunk_size=SCREENER_MACD_BATCH_CHUNK_SIZE,
        )
    except RuntimeError as exc:
        print(f"批量 MACD 计算失败: {exc}")
        return
    print(f"MACD 计算完成，耗时 {time.perf_counter() - t0_macd:.1f}s，覆盖 {len(macd_batch)} 只")

    # 第3步：逐只加载 K 线 + 对齐 MACD + 筛选
    print(f"\n>>> 3. 逐只筛选...")
    results: list[ScreenResult] = []
    for i, code in enumerate(codes, 1):
        kline_bars = load_daily_kline_from_db(DAILY_KLINE_DB_PATH, code, min_kline)
        if kline_bars is None:
            result = ScreenResult(
                code=code, passed=False, fail_reason="K线数据不足",
                kline_count=0, latest_close=0, latest_date="", latest_dif=0,
                latest_dea=0, latest_macd=0, divergence_found=False,
                reversal_confirmed=False, band_position_ok=False, detail={},
            )
            results.append(result)
            if i % 500 == 0:
                print(f"  [{i}/{len(codes)}] 进度...")
            continue

        tdx_code = to_tdx_stock_code(code)
        macd_raw = macd_batch.get(tdx_code, {})
        macd = align_macd_with_kline(kline_bars, macd_raw)
        if macd is None:
            result = ScreenResult(
                code=code, passed=False, fail_reason="MACD数据缺失",
                kline_count=len(kline_bars), latest_close=kline_bars[-1].close_price,
                latest_date=kline_bars[-1].trade_date, latest_dif=0,
                latest_dea=0, latest_macd=0, divergence_found=False,
                reversal_confirmed=False, band_position_ok=False, detail={},
            )
            results.append(result)
            continue

        result = screen_single_stock(code, kline_bars, macd, debug)
        status = "通过" if result.passed else "未通过"
        if result.passed or debug:
            print(f"  [{i}/{len(codes)}] {code} - {status} - {result.fail_reason}")
        elif i % 500 == 0:
            print(f"  [{i}/{len(codes)}] 进度...")
        results.append(result)

    # 打印摘要
    print_screener_summary(results)

    # 输出结果到 result/ 目录
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    result_path = RESULT_DIR / f"screener_{timestamp}.json"
    result_data = {
        "scan_time": timestamp,
        "pool_size": len(codes),
        "total_scanned": len(results),
        "total_passed": sum(1 for r in results if r.passed),
        "results": [
            {
                "code": r.code,
                "passed": r.passed,
                "fail_reason": r.fail_reason,
                "kline_count": r.kline_count,
                "latest_close": r.latest_close,
                "latest_date": r.latest_date,
                "latest_dif": r.latest_dif,
                "latest_dea": r.latest_dea,
                "latest_macd": r.latest_macd,
                "divergence_found": r.divergence_found,
                "reversal_confirmed": r.reversal_confirmed,
                "band_position_ok": r.band_position_ok,
            }
            for r in results
        ],
    }
    with result_path.open("w", encoding="utf-8") as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存到: {result_path}")

    print(f"\n[总耗时 {time.perf_counter() - t0_total:.1f}s]")


def parse_args() -> argparse.Namespace:
    """
        解析命令行参数。

    Returns:
        解析完成的参数对象。
    """
    parser = argparse.ArgumentParser(description="Cassa 命令行入口。")
    module_parsers = parser.add_subparsers(dest="module", required=True)

    market_parser = module_parsers.add_parser("market", help="执行大盘模块当前第一版采集主干")
    market_parser.add_argument("--no-llm", action="store_true", help="跳过 market 中的 LLM 判断")
    market_parser.add_argument("--debug-llm", action="store_true", help="打印传给 LLM 的完整 prompt 和原始返回")
    market_parser.set_defaults(handler=run_market)

    screener_parser = module_parsers.add_parser("screener", help="执行选股筛选")
    screener_parser.add_argument("--pool-size", type=int, default=0, help="股票池大小，0=全市场，默认 0")
    screener_parser.add_argument("--min-kline", type=int, default=SCREENER_MIN_KLINE_COUNT, help=f"最小K线数，默认 {SCREENER_MIN_KLINE_COUNT}")
    screener_parser.add_argument("--debug", action="store_true", help="输出每只股票的详细筛选过程")
    screener_parser.set_defaults(handler=run_screener)

    tdx_api_parser = module_parsers.add_parser("tdx_api", help="调用通达信 `tqcenter` 接口")
    tdx_api_subparsers = tdx_api_parser.add_subparsers(dest="tdx_action", required=True)

    llm_parser = module_parsers.add_parser("llm", help="调用公共 LLM 接入层")
    llm_subparsers = llm_parser.add_subparsers(dest="llm_action", required=True)

    llm_config_parser = llm_subparsers.add_parser("config", help="查看当前 LLM 环境变量配置")
    llm_config_parser.set_defaults(handler=run_llm_config)

    llm_text_parser = llm_subparsers.add_parser("text", help="调用公共文本生成接口")
    llm_text_parser.add_argument("--prompt", required=True, help="用户提示词")
    llm_text_parser.add_argument("--system", default="", help="可选系统提示词")
    llm_text_parser.add_argument("--temperature", type=float, default=0.2, help="生成温度")
    llm_text_parser.set_defaults(handler=run_llm_text)

    summary_parser = tdx_api_subparsers.add_parser("summary", help="组合调用内部所需接口并打印摘要")
    summary_parser.add_argument("--code", required=True, help="单个股票代码，推荐输入纯数字")
    summary_parser.add_argument("--period", default="1d", help="K线周期，默认为 1d")
    summary_parser.add_argument("--count", type=int, default=60, help="需要获取的 K 线数量")
    summary_parser.add_argument(
        "--dividend-type",
        default="none",
        choices=["none", "front", "back"],
        help="K线复权方式",
    )
    summary_parser.set_defaults(handler=run_tdx_api_summary)

    snapshot_parser = tdx_api_subparsers.add_parser(
        "snapshot",
        help="获取最新快照，只支持单个股票代码",
    )
    snapshot_parser.add_argument("--code", required=True, help="单个股票代码，推荐输入纯数字")
    snapshot_parser.set_defaults(handler=run_tdx_api_snapshot)

    stock_info_parser = tdx_api_subparsers.add_parser(
        "stock_info",
        help="获取证券基础信息，只支持单个股票代码",
    )
    stock_info_parser.add_argument("--code", required=True, help="单个股票代码，推荐输入纯数字")
    stock_info_parser.set_defaults(handler=run_tdx_api_stock_info)

    more_info_parser = tdx_api_subparsers.add_parser(
        "more_info",
        help="获取证券扩展信息，只支持单个股票代码",
    )
    more_info_parser.add_argument("--code", required=True, help="单个股票代码，推荐输入纯数字")
    more_info_parser.set_defaults(handler=run_tdx_api_more_info)

    relation_parser = tdx_api_subparsers.add_parser(
        "relation",
        help="获取所属板块，只支持单个股票代码",
    )
    relation_parser.add_argument("--code", required=True, help="单个股票代码，推荐输入纯数字")
    relation_parser.set_defaults(handler=run_tdx_api_relation)

    sector_list_parser = tdx_api_subparsers.add_parser(
        "sector_list",
        help="获取 A 股板块列表",
    )
    sector_list_parser.add_argument(
        "--list-type",
        type=int,
        default=1,
        choices=[0, 1],
        help="返回数据类型：0 只返回代码，1 返回代码和名称",
    )
    sector_list_parser.set_defaults(handler=run_tdx_api_sector_list)

    stock_list_in_sector_parser = tdx_api_subparsers.add_parser(
        "stock_list_in_sector",
        help="获取某个板块的成分股列表",
    )
    stock_list_in_sector_parser.add_argument(
        "--block-code",
        required=True,
        help="板块代码或板块名称，例如 880675.SH 或 减速器",
    )
    stock_list_in_sector_parser.add_argument(
        "--block-type",
        type=int,
        default=0,
        choices=[0, 1],
        help="板块类型：0 系统板块或板块名称，1 自定义板块",
    )
    stock_list_in_sector_parser.add_argument(
        "--list-type",
        type=int,
        default=1,
        choices=[0, 1],
        help="返回数据类型：0 只返回代码，1 返回代码和名称",
    )
    stock_list_in_sector_parser.set_defaults(handler=run_tdx_api_stock_list_in_sector)

    return parser.parse_args()


# ============================================================================
# 第九层：主入口层
# 这一层只负责初始化项目目录、解析命令行、创建客户端并分发到命令执行层。
# 它不直接承载采集细节、业务判断或渲染逻辑。
# ============================================================================

def main() -> None:
    """
    运行当前最小可用版本的 Cassa 演示入口。

    Returns:
        无返回值。
    """
    ensure_project_dirs()
    args = parse_args()
    client = TdxClient(script_path=Path(__file__).resolve())
    args.handler(args, client)


if __name__ == "__main__":
    main()
