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
from pathlib import Path
import time
from typing import Any

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
SECTOR_BATCH_SIZE = 120
RANKABLE_BLOCK_TYPES = {"industry", "theme"}
KEY_BLOCKS_PER_BUCKET = 2
LEADER_CANDIDATE_COUNT = 3
MIDDLE_ARMY_CANDIDATE_COUNT = 3
LIMIT_UP_THRESHOLD = 9.5
LIMIT_DOWN_THRESHOLD = -9.5
SH_CODE_PREFIXES = ("5", "6", "9")
SZ_CODE_PREFIXES = ("0", "1", "2", "3")
BJ_CODE_PREFIXES = ("920", "4", "8")


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
    type_map = {
        "88": "theme",
        "881": "industry",
    }

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
        if internal_code.startswith("881"):
            sector_type = "industry"
        elif internal_code.startswith("880"):
            sector_type = "theme"
        else:
            sector_type = "unknown"
        sector_type_counter[sector_type] += 1

        row = {
            "代码": sector_code,
            "纯代码": internal_code,
            "名称": sector["Name"],
            "类型代码": sector_type,
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
        row["主力净流入亿"] = round(fund_value / 100000000, 2) if fund_value is not None else None

    key_blocks = pick_key_blocks(industry_top, concept_top)
    return {
        "全部板块总数": len(sectors),
        "有效板块数": len(sector_rows),
        "数据不足板块数": failed_count,
        "板块分类统计": dict(sector_type_counter),
        "过滤后板块数": len(filtered_rows),
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
    filtered = sector_snapshot.get("过滤后板块数", 0)

    print(f"全部板块总数: {total}")
    print("日K数据拉取完成")
    print(f"计算完成: 有效 {valid} 个，数据不足 {failed} 个")
    parts = []
    for key in sorted(type_stats.keys()):
        parts.append(f"{key}={type_stats[key]}")
    print(f"板块分类统计: {', '.join(parts)}")
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
    _print_block_rank(f">>> 🔥 行业板块热度榜 Top {top_n} (按当日涨幅排序)", sector_snapshot.get("行业热度榜", []))
    _print_block_rank(f">>> 🚀 概念板块热度榜 Top {top_n} (按当日涨幅排序)", sector_snapshot.get("概念热度榜", []))
    _print_block_rank(f">>> 📉 行业板块跌幅榜 Bottom {top_n} (按当日涨幅排序)", sector_snapshot.get("行业跌幅榜", []))
    _print_block_rank(f">>> 📉 概念板块跌幅榜 Bottom {top_n} (按当日涨幅排序)", sector_snapshot.get("概念跌幅榜", []))


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
            f"🔥 {name}({pure_code})",
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
    print(f"[⏱ 6大宽基指数耗时 {time.perf_counter() - t0:.1f}s]")

    # ── 2. 板块热度榜 + 3. 重点板块成分股验证 ──
    print("\n" + "=" * 72)
    print(">>> 2. 板块热度榜")
    print("=" * 72)
    t0 = time.perf_counter()
    sector_heat_snapshot = collect_sector_heat_snapshot(client)
    print_sector_heat_tables(sector_heat_snapshot)

    key_analyses = collect_key_sector_member_snapshot(client, sector_heat_snapshot["重点板块"])
    print_key_sector_analysis(key_analyses)
    print(f"\n[⏱ 板块热度榜耗时 {time.perf_counter() - t0:.1f}s]")

    # ── 4. LLM 判断 (TODO) ──
    print("\n" + "=" * 72)
    print(">>> 🤖 LLM 最近市场风格判断")
    print("=" * 72)
    print("TODO")
    print(f"[⏱ LLM风格判断耗时 {time.perf_counter() - t0:.1f}s]")  # placeholder

    print("\n" + "=" * 72)
    print(">>> 🤖 LLM 市场资金意图判断")
    print("=" * 72)
    print("TODO")

    print(f"\n[⏱ 总耗时 {time.perf_counter() - t0_total:.1f}s]")

    # ── JSON 模式：额外输出原始数据 ──
    if getattr(args, "json", False):
        print("")
        print_json_output(
            {
                "market_index_snapshot": market_index_snapshot,
                "sector_heat_snapshot": {
                    key: value
                    for key, value in sector_heat_snapshot.items()
                    if key != "板块K线原始数据"
                },
                "key_sector_snapshot": key_analyses,
            }
        )


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


def parse_args() -> argparse.Namespace:
    """
        解析命令行参数。

    Returns:
        解析完成的参数对象。
    """
    parser = argparse.ArgumentParser(description="Cassa 命令行入口。")
    module_parsers = parser.add_subparsers(dest="module", required=True)

    market_parser = module_parsers.add_parser("market", help="执行大盘模块当前第一版采集主干")
    market_parser.add_argument("--json", action="store_true", help="以 JSON 格式输出原始数据（默认输出格式化表格）")
    market_parser.set_defaults(handler=run_market)

    tdx_api_parser = module_parsers.add_parser("tdx_api", help="调用通达信 `tqcenter` 接口")
    tdx_api_subparsers = tdx_api_parser.add_subparsers(dest="tdx_action", required=True)

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
