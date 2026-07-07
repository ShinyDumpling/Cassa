# Screener 多策略与公共数据中心改造方案

## 主题概述

本文记录 2026-07-07 围绕 `screener` 多策略化所确认的完整设计。

当前 `Cassa` 的选股模块只有一套写死的“突破前入场”策略。随着后续增加其他选股方法，如果继续把所有条件直接堆进 `run_screener` 或继续让一个 `screen_single_stock` 承担所有策略，会逐渐出现以下问题：

1. 无法通过命令行选择本次运行哪套策略。
2. 数据获取、指标计算、数据规整和策略判断的边界不清晰。
3. 其他功能（历史信号验证、回测、个股报告、大盘分析、股票池监控）无法方便地复用同一套数据能力。
4. 新增策略容易复制整套主流程，形成多份重复的取数和输出代码。

本次确认的第一版方向是：

- 代码暂时继续放在唯一的 `cassa.py` 中，不拆分多个 Python 文件。
- 建立一个轻量公共数据中心，统一对外提供股票代码、日 K、指标和基础信息等数据。
- `run_screener` 作为选股主流程，负责向数据中心索取数据，并规整成策略需要的统一输入。
- 每套选股方案写成独立 Python 函数，策略函数只判断，不读取数据库、不调用通达信、不写文件。
- 通过策略注册表和 `--strategy` 参数选择策略。
- 第一轮只做结构改造，不修改现有“突破前入场”的业务条件和判断口径。

> 当前状态：本文是已确认的技术设计，尚未写入业务代码。后续实现时必须再次检查 `cassa.py` 的最新状态，并按本文的小步改造顺序执行。

## 讨论背景与关键判断

### 为什么需要公共数据中心

选股不是唯一需要行情数据的功能。以下能力都会重复使用股票代码、日 K、指标和股票信息：

- 实时选股。
- 历史日期选股和逐日回放。
- 信号效果验证和交易回测。
- 个股报告。
- 股票池监控与提醒。
- 大盘、板块和板块内选股。

因此，底层数据获取能力应该是公共能力，而不是属于某一套选股策略。

项目当前并非完全没有公共层。`cassa.py` 中已经存在：

- `TdxClient`：封装通达信接口和公式引擎调用。
- `load_stock_codes_from_db`：从 SQLite 日 K 库获取股票代码。
- `load_daily_kline_from_db`：读取单只股票日 K。
- `align_macd_with_kline`：把公式引擎 MACD 与本地 K 线对齐。
- 多个数据清洗、代码转换和股票信息读取函数。

这些已经构成公共数据能力的基础，但调用入口仍然分散。第一版数据中心不重写这些底层函数，只在其上提供统一入口。

### 为什么数据准备放在 `run_screener`

用户确认：选股主流程可以知道当前策略需要什么数据，并在调用策略前完成准备和规整。

最终职责划分如下：

```text
公共数据中心
  负责：从 SQLite、通达信等来源提供原始或通用数据
  不负责：理解某套策略、判断股票是否通过

run_screener 选股主流程
  负责：选择策略、索取所需数据、对齐和规整、调用策略、汇总输出
  不负责：亲自实现底背离或其他具体策略条件

策略函数
  负责：基于已经准备好的输入执行纯判断并返回结果
  不负责：访问数据库、调用 TDX、输出文件、控制扫描循环
```

这样既保留第一版的直白结构，也能阻止数据读取逻辑进入策略函数。

### 为什么第一版不拆文件

项目当前约定优先保持单文件，并按分区组织。策略数量还少，立即做插件系统或多模块目录会提高理解和修改成本。

第一版采用：

- 一个 `cassa.py`。
- 多个命名清晰的策略函数。
- 一个策略注册表。
- 一个统一选股主流程。

等策略达到三到四套、数据需求明显分化后，再评估拆成 `data_center.py`、`strategies/` 等模块。

## 当前代码真实状态

以下内容描述编写本文时的实际代码，不是目标代码。

### 当前 CLI

`screener` 只有以下参数：

```python
screener_parser = module_parsers.add_parser("screener", help="执行选股筛选")
screener_parser.add_argument("--pool-size", type=int, default=0, help="股票池大小，0=全市场，默认 0")
screener_parser.add_argument(
    "--min-kline",
    type=int,
    default=SCREENER_MIN_KLINE_COUNT,
    help=f"最小K线数，默认 {SCREENER_MIN_KLINE_COUNT}",
)
screener_parser.add_argument("--debug", action="store_true", help="输出每只股票的详细筛选过程")
screener_parser.set_defaults(handler=run_screener)
```

没有 `--strategy`，因此无法选择选股方案。

### 当前单股筛选入口

当前唯一策略函数叫：

```python
def screen_single_stock(
    code: str,
    kline_bars: list[KlineBar],
    macd: MacdResult,
    debug: bool = False,
) -> ScreenResult:
```

它已经满足“数据加载和 MACD 计算由调用方完成”的纯策略方向，但函数名没有表达策略名称，且没有统一策略输入结构。

内部依次调用：

1. `find_pivot_lows`
2. `check_bottom_divergence`
3. `check_trend_reversal`
4. `check_band_position`

它实际代表的是“突破前入场”策略，不是所有选股策略的通用实现。

### 当前 `run_screener`

当前流程是：

```text
load_stock_codes_from_db
  -> client.calculate_macd_batch
  -> 循环 load_daily_kline_from_db
  -> align_macd_with_kline
  -> screen_single_stock
  -> ST 过滤
  -> print_screener_summary
  -> 写 result/screener_时间.json
```

主流程直接调用底层数据库函数和 `TdxClient`，没有数据中心入口；同时直接写死调用 `screen_single_stock`。

### 当前结果结构

`ScreenResult` 仍带有当前策略专用字段：

```python
@dataclass
class ScreenResult:
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
    divergence_low_date: str
    prev_divergence_low_date: str
    detail: dict[str, Any]
```

第一轮改造可以继续保留这些字段，以免改变现有 JSON、摘要输出和人工筛选习惯。后续策略增多后，再单独设计通用结果结构。

## 已确认的目标架构

目标调用关系：

```text
CLI --strategy
    |
    v
run_screener
    |-- 从 SCREENER_STRATEGIES 找到策略函数
    |-- 通过 CassaDataCenter 获取股票池、K线、MACD等数据
    |-- 对齐并构造 ScreenerStockData
    |-- 调用 strategy_func(stock_data, debug)
    |-- 做公共后处理（例如 ST 过滤）
    |-- 打印摘要并写 JSON
    v
ScreenResult
```

策略函数之间不互相调用，也不各自复制全市场扫描流程。

## 详细代码设计

### 1. 增加策略名称常量

建议在 screener 常量区增加：

```python
SCREENER_DEFAULT_STRATEGY = "breakout_pre_entry"
```

`breakout_pre_entry` 表示当前已经存在的“突破前入场”策略。策略名称使用稳定英文标识，便于 CLI、JSON、日志和后续数据库统一引用。

不建议把中文策略名作为程序主键；中文可以用于帮助文本和展示名称。

### 2. 增加统一策略输入 `ScreenerStockData`

在 `MacdResult`、`ScreenResult` 附近增加：

```python
@dataclass
class ScreenerStockData:
    """单只股票经过主流程规整后的策略输入。

    Attributes:
        code: 纯数字股票代码。
        kline_bars: 按交易日期升序排列的日 K 数据。
        indicators: 已与 K 线对齐的指标结果，键名使用稳定英文标识。
    """

    code: str
    kline_bars: list[KlineBar]
    indicators: dict[str, Any]
```

第一版构造示例：

```python
stock_data = ScreenerStockData(
    code=code,
    kline_bars=kline_bars,
    indicators={
        "macd": macd,
    },
)
```

使用 `indicators` 字典的原因：

- 当前策略只使用 MACD。
- 后续策略可能需要 MA、成交量、量比、RSI、板块信息等。
- 不必每新增一个指标就修改所有策略函数的参数列表。

限制：

- 字典键名必须集中约定，不能同一个指标出现 `macd`、`MACD`、`macd_result` 多种名称。
- 策略函数读取必需指标时应明确检查，缺失时返回可理解的失败原因，不能静默使用空值。
- 如果后续指标种类稳定且类型检查需求增强，可以再把常用指标提升为 dataclass 字段；第一版不提前复杂化。

### 3. 增加轻量公共数据中心

建议在 `TdxClient` 和现有数据读取函数基础上增加：

```python
class CassaDataCenter:
    """统一提供 Cassa 各业务需要的公共行情与股票数据。

    第一版只包装已有数据读取能力，不在这里实现选股规则，也不缓存复杂业务状态。
    """

    def __init__(self, client: TdxClient):
        self.client = client

    def get_stock_codes(
        self,
        pool_size: int,
        min_kline: int,
    ) -> list[str]:
        """从本地日 K 数据库读取可扫描股票代码。"""
        return load_stock_codes_from_db(
            DAILY_KLINE_DB_PATH,
            pool_size,
            min_kline,
        )

    def get_daily_klines(
        self,
        code: str,
        min_kline: int,
    ) -> list[KlineBar] | None:
        """读取单只股票按日期升序排列的日 K。"""
        return load_daily_kline_from_db(
            DAILY_KLINE_DB_PATH,
            code,
            min_kline,
        )

    def calculate_macd_batch(
        self,
        codes: list[str],
    ) -> dict[str, dict[str, Any]]:
        """通过通达信公式引擎批量计算股票 MACD。"""
        tdx_codes = [to_tdx_stock_code(code) for code in codes]
        return self.client.calculate_macd_batch(
            tdx_codes=tdx_codes,
            count=SCREENER_MACD_BATCH_COUNT,
            chunk_size=SCREENER_MACD_BATCH_CHUNK_SIZE,
        )

    def get_stock_name(self, code: str) -> str:
        """读取股票名称，供公共过滤和展示使用。"""
        stock_code = normalize_stock_code(code)
        stock_info = self.client.get_stock_info(stock_code, field_list=["Name"])
        return str(stock_info.get("Name", ""))
```

命名说明：使用 `CassaDataCenter`，而不是模糊的 `DataManager` 或 `Utils`。这个类确实持有 `TdxClient` 状态，并围绕统一数据访问组织方法，符合项目中“必要类”的使用边界。

第一版数据中心明确不做：

- 不判断底背离。
- 不选择某个策略。
- 不构造 `ScreenResult`。
- 不写结果文件。
- 不直接规定某套策略需要哪些指标。
- 不做自动缓存、依赖图、插件发现等复杂机制。

### 4. 把现有策略改成具名策略函数

将：

```python
def screen_single_stock(
    code: str,
    kline_bars: list[KlineBar],
    macd: MacdResult,
    debug: bool = False,
) -> ScreenResult:
```

修改为：

```python
def screen_strategy_breakout_pre_entry(
    stock_data: ScreenerStockData,
    debug: bool = False,
) -> ScreenResult:
    """执行“突破前入场”选股策略。

    Args:
        stock_data: 主流程已经准备并对齐的单股数据。
        debug: 是否打印该股票的策略判断细节。

    Returns:
        该股票的筛选结果。
    """
    code = stock_data.code
    kline_bars = stock_data.kline_bars
    macd = stock_data.indicators.get("macd")

    if not isinstance(macd, MacdResult):
        return create_failed_screen_result(
            code=code,
            kline_bars=kline_bars,
            fail_reason="策略输入缺少已对齐的 MACD 数据",
        )

    # 下方继续使用当前已经存在的底背离、趋势反转、波段位置逻辑。
```

原函数主体中的业务逻辑原则上原样搬入，不重新调参，也不改变以下函数的口径：

- `find_pivot_lows`
- `check_bottom_divergence`
- `check_trend_reversal`
- `check_band_position`

这次重构的目标是让当前策略拥有明确身份，而不是顺便重写当前策略。

### 5. 抽取统一失败结果构造函数

当前 `run_screener` 和 `screen_single_stock` 多次手工构造 `ScreenResult`，字段较多，新增策略后容易漏字段。

建议增加小型辅助函数：

```python
def create_failed_screen_result(
    code: str,
    fail_reason: str,
    kline_bars: list[KlineBar] | None = None,
    macd: MacdResult | None = None,
) -> ScreenResult:
    """构造数据缺失或前置条件失败时的统一选股结果。"""
    latest_bar = kline_bars[-1] if kline_bars else None

    return ScreenResult(
        code=code,
        passed=False,
        fail_reason=fail_reason,
        kline_count=len(kline_bars) if kline_bars else 0,
        latest_close=latest_bar.close_price if latest_bar else 0,
        latest_date=latest_bar.trade_date if latest_bar else "",
        latest_dif=macd.dif[-1] if macd and macd.dif else 0,
        latest_dea=macd.dea[-1] if macd and macd.dea else 0,
        latest_macd=macd.macd[-1] if macd and macd.macd else 0,
        divergence_found=False,
        reversal_confirmed=False,
        band_position_ok=False,
        divergence_low_date="",
        prev_divergence_low_date="",
        detail={},
    )
```

这不是多策略架构的硬性前提，但能显著减少主流程中的重复代码，建议和结构改造一起完成。

### 6. 增加策略注册表

在所有策略函数之后增加：

```python
ScreenerStrategy = Callable[[ScreenerStockData, bool], ScreenResult]

SCREENER_STRATEGIES: dict[str, ScreenerStrategy] = {
    "breakout_pre_entry": screen_strategy_breakout_pre_entry,
}
```

需要从 `typing` 导入 `Callable`；如果项目当前已有对应导入，应复用。

注册表的职责只是把稳定策略名映射到函数。新增第二套策略时，例如：

```python
def screen_strategy_volume_breakout(
    stock_data: ScreenerStockData,
    debug: bool = False,
) -> ScreenResult:
    ...


SCREENER_STRATEGIES: dict[str, ScreenerStrategy] = {
    "breakout_pre_entry": screen_strategy_breakout_pre_entry,
    "volume_breakout": screen_strategy_volume_breakout,
}
```

第一版不做动态扫描函数名、不做插件加载、不从 YAML 执行任意逻辑。显式注册更容易阅读、调试和控制。

### 7. 增加 `--strategy` CLI 参数

原来：

```python
screener_parser.add_argument("--pool-size", ...)
screener_parser.add_argument("--min-kline", ...)
screener_parser.add_argument("--debug", ...)
```

修改为增加：

```python
screener_parser.add_argument(
    "--strategy",
    choices=sorted(SCREENER_STRATEGIES),
    default=SCREENER_DEFAULT_STRATEGY,
    help=f"选股策略，默认 {SCREENER_DEFAULT_STRATEGY}",
)
```

使用 `choices` 后，未知策略会由 `argparse` 直接给出清晰错误，不需要主流程默默回退默认策略。

兼容性：

```powershell
python cassa.py screener
```

仍然运行当前“突破前入场”策略，因此不会破坏原有使用方式。

新增明确调用方式：

```powershell
python cassa.py screener --strategy breakout_pre_entry
```

### 8. 重构 `run_screener`

`run_screener` 仍然是唯一的全市场选股主流程。改造后的关键逻辑如下：

```python
def run_screener(args: argparse.Namespace, client: TdxClient) -> None:
    """按指定策略扫描股票池并输出结果。"""
    total_started_at = time.perf_counter()
    pool_size = args.pool_size
    min_kline = args.min_kline
    debug = args.debug
    strategy_name = args.strategy

    data_center = CassaDataCenter(client)
    strategy_func = SCREENER_STRATEGIES[strategy_name]

    codes = data_center.get_stock_codes(pool_size, min_kline)
    if not codes:
        print("股票池为空，退出。")
        return

    try:
        macd_batch = data_center.calculate_macd_batch(codes)
    except RuntimeError as exc:
        print(f"批量 MACD 计算失败: {exc}")
        return

    results: list[ScreenResult] = []

    for index, code in enumerate(codes, 1):
        kline_bars = data_center.get_daily_klines(code, min_kline)
        if kline_bars is None:
            results.append(
                create_failed_screen_result(
                    code=code,
                    fail_reason="K线数据不足",
                )
            )
            continue

        tdx_code = to_tdx_stock_code(code)
        macd_raw = macd_batch.get(tdx_code, {})
        macd = align_macd_with_kline(kline_bars, macd_raw)
        if macd is None:
            results.append(
                create_failed_screen_result(
                    code=code,
                    kline_bars=kline_bars,
                    fail_reason="MACD数据缺失",
                )
            )
            continue

        stock_data = ScreenerStockData(
            code=code,
            kline_bars=kline_bars,
            indicators={"macd": macd},
        )
        result = strategy_func(stock_data, debug)
        results.append(result)

    # 后续继续执行公共 ST 过滤、摘要打印和 JSON 输出。
```

实际实现时应保留当前进度输出、耗时统计和异常提示，不能因为结构改造导致全市场扫描时失去进度反馈。

### 9. ST 过滤归属

当前 ST 过滤发生在策略执行之后，只对已通过股票查询名称并改为未通过。

第一版继续把它视为所有策略共用的后处理规则，保留在 `run_screener`，但名称读取改为通过数据中心：

```python
stock_name = data_center.get_stock_name(result.code)
```

暂不把 ST 过滤塞进某个策略函数，因为它不是“突破前入场”的专有条件。

后续如果某些策略允许 ST，需要再将其升级为可配置公共过滤项；第一版不做。

### 10. JSON 输出增加策略标识

当前顶层结果：

```python
result_data = {
    "scan_time": timestamp,
    "pool_size": len(codes),
    "total_scanned": len(results),
    "total_passed": ...,
    "results": [...],
}
```

修改为：

```python
result_data = {
    "scan_time": timestamp,
    "strategy": strategy_name,
    "pool_size": len(codes),
    "total_scanned": len(results),
    "total_passed": sum(1 for result in results if result.passed),
    "results": [...],
}
```

文件名建议改为：

```python
result_path = RESULT_DIR / f"screener_{strategy_name}_{timestamp}.json"
```

典型文件名：

```text
result/screener_breakout_pre_entry_20260707_120000.json
```

文件名包含策略是为了以后并行运行多套方案时能直接区分来源。

### 11. 控制台输出增加策略名称

运行开始时建议输出：

```text
选股策略: breakout_pre_entry
股票池: 全市场 | 最小K线数: 60
```

摘要标题也可显示策略：

```text
选股结果摘要 [breakout_pre_entry]
```

`print_screener_summary` 可以增加 `strategy_name` 参数：

```python
def print_screener_summary(
    results: list[ScreenResult],
    strategy_name: str,
) -> None:
```

如果希望本轮改动更小，也可以只在 `run_screener` 开头打印策略名，暂不修改摘要函数签名。

## 新增第二套策略时的标准步骤

后续增加策略时，按以下固定步骤进行：

1. 明确策略稳定英文名，例如 `volume_breakout`。
2. 确认策略需要的数据，例如日 K、MACD、成交量、行业。
3. 如果数据中心没有对应公共取数能力，先补充最小必要方法。
4. 在 `run_screener` 中准备并规整该策略需要的数据。
5. 新增纯策略函数 `screen_strategy_volume_breakout`。
6. 将函数加入 `SCREENER_STRATEGIES`。
7. 增加针对策略函数的最小测试或样例验证。
8. 确认 JSON 顶层正确记录策略名。

第二套策略函数示例：

```python
def screen_strategy_volume_breakout(
    stock_data: ScreenerStockData,
    debug: bool = False,
) -> ScreenResult:
    """执行放量突破策略，只基于调用方准备的数据进行判断。"""
    kline_bars = stock_data.kline_bars
    if len(kline_bars) < 20:
        return create_failed_screen_result(
            code=stock_data.code,
            kline_bars=kline_bars,
            fail_reason="放量突破策略至少需要20根K线",
        )

    # 在这里执行该策略自己的判断，不读取数据库、不调用 TDX。
    ...
```

## 不同策略需要不同数据时的处理

第一版只有一个策略，因此可以继续批量准备 MACD。增加第二套策略后，不能默认所有策略都必须计算 MACD，否则会产生不必要的通达信调用。

第一阶段可在 `run_screener` 中使用直白分支：

```python
if strategy_name == "breakout_pre_entry":
    macd_batch = data_center.calculate_macd_batch(codes)
elif strategy_name == "volume_breakout":
    macd_batch = {}
```

这是当前规模下可接受的简单实现。

当策略数量达到三到四套、分支明显增多时，再引入数据需求声明，例如：

```python
@dataclass(frozen=True)
class ScreenerStrategyDefinition:
    handler: ScreenerStrategy
    required_indicators: tuple[str, ...]


SCREENER_STRATEGIES = {
    "breakout_pre_entry": ScreenerStrategyDefinition(
        handler=screen_strategy_breakout_pre_entry,
        required_indicators=("macd",),
    ),
}
```

这属于后续演进方向，不应在只有一套策略时提前实现。

## `ScreenResult` 的兼容策略

当前 `ScreenResult` 含有底背离、趋势反转和波段位置字段，这些字段对其他策略可能没有意义。

第一版决定：暂不重构 `ScreenResult`，原因是：

- 现有 JSON 和摘要依赖这些字段。
- 当前实际只有一套策略。
- 同时改策略架构和结果协议会扩大改动面，难以确认回归来源。

新增第二套策略前，应重新评估以下通用结构：

```python
@dataclass
class ScreenResult:
    code: str
    passed: bool
    fail_reason: str
    failed_stage: str
    kline_count: int
    latest_close: float
    latest_date: str
    metrics: dict[str, Any]
    detail: dict[str, Any]
```

其中策略专用字段放到 `metrics` 或 `detail`。在正式迁移前，需要确认历史验证脚本和人工分析是否依赖当前 JSON 字段，不能直接删除。

## 数据边界与约定

### 股票代码

- 策略输入中的 `code` 保持六位纯数字字符串。
- 只有调用通达信接口前才通过 `to_tdx_stock_code` 或 `normalize_stock_code` 转换。
- 不要把带市场前缀的代码传入策略函数。

### K 线顺序

- `kline_bars` 必须按交易日期升序排列。
- `kline_bars[-1]` 表示当前运行口径下的最新一根 K 线。
- 历史日期模式实现后，主流程必须先截断到 `as_of_date`，再构造 `ScreenerStockData`，策略函数不应接触未来 K 线。

### 指标对齐

- 通达信公式引擎返回结果必须先经过 `align_macd_with_kline`。
- 策略函数收到的 MACD 长度必须和 K 线一致。
- 对齐失败应由主流程生成“MACD数据缺失”结果，不应把原始未对齐数据交给策略。

### 数据不足

- 数据中心返回 `None` 或空数据时，主流程负责生成统一失败结果。
- 策略自身额外要求的窗口长度，由策略函数检查并返回明确原因。
- 错误信息要区分“取数失败”“指标缺失”“策略条件未通过”。

## 与历史验证和回测的关系

这次多策略改造会为 `T029` 至 `T032` 的历史信号验证提供稳定入口。

未来历史模式应复用同一策略函数：

```text
历史回放主流程
  -> 数据中心读取截至 as_of_date 的数据
  -> 构造 ScreenerStockData
  -> 从 SCREENER_STRATEGIES 选择同一个策略函数
  -> 得到 ScreenResult
```

不能为回测复制一套“近似相同”的选股逻辑，否则实时选股和历史验证会逐渐产生口径差异。

未来策略标识也应进入历史信号记录：

```json
{
  "strategy": "breakout_pre_entry",
  "signal_date": "2026-07-03",
  "code": "001358",
  "passed": true
}
```

## 与大盘、板块和股票池的关系

- `market` 可以复用数据中心的公共股票、板块和行情读取能力，但其数据规整仍由 `run_market` 负责。
- “从板块出发进行板块内选股”时，板块模块先产生股票代码集合，再把代码集合交给 screener 主流程，不应把板块判断写入某个通用数据读取函数。
- 股票池监控可以复用数据中心读取 K 线和指标，但“入池理由、状态、提醒规则”仍属于股票池业务层。
- 数据中心是共享取数边界，不是把所有业务逻辑集中到一个大类中。

## 实施顺序

建议拆成小步完成，避免一次重构难以验证：

1. 增加 `SCREENER_DEFAULT_STRATEGY` 和 `--strategy`，默认行为保持不变。
2. 将 `screen_single_stock` 改名为 `screen_strategy_breakout_pre_entry`，增加注册表，先保持原参数也可以。
3. 增加 `ScreenerStockData`，把策略函数切换为统一输入。
4. 增加 `CassaDataCenter`，逐个替换 `run_screener` 中现有底层取数调用。
5. 抽取 `create_failed_screen_result`，消除重复失败对象构造。
6. JSON 和控制台增加策略名称，结果文件名加入策略标识。
7. 执行兼容性和结果一致性验证。

每一步都应保证 `python cassa.py screener` 仍能运行，不应在中间状态同时修改策略阈值。

## 验证方案

实现后至少执行以下验证。

### 1. CLI 帮助

```powershell
python cassa.py screener --help
```

预期：显示 `--strategy {breakout_pre_entry}`。

### 2. 默认策略兼容

```powershell
python cassa.py screener --pool-size 20
```

预期：等价于改造前运行当前突破前入场策略，不要求用户必须传 `--strategy`。

### 3. 显式策略选择

```powershell
python cassa.py screener --strategy breakout_pre_entry --pool-size 20
```

预期：与默认命令使用相同策略，扫描数量和逐股判断结果一致。

### 4. 非法策略

```powershell
python cassa.py screener --strategy unknown_strategy
```

预期：`argparse` 明确提示可选策略，不进入取数和扫描流程。

### 5. JSON 验证

预期生成：

```text
result/screener_breakout_pre_entry_YYYYMMDD_HHMMSS.json
```

JSON 顶层包含：

```json
{
  "scan_time": "20260707_120000",
  "strategy": "breakout_pre_entry",
  "pool_size": 20,
  "total_scanned": 20,
  "total_passed": 1,
  "results": []
}
```

### 6. 结果一致性

结构改造前后用同一数据库、同一时间和同一股票池运行。逐只比较：

- `passed`
- `fail_reason`
- `divergence_low_date`
- `prev_divergence_low_date`
- `latest_dif`
- `latest_dea`
- `latest_macd`

除新增策略元数据和文件名外，现有策略结果应保持一致。

## 已确认不在第一版实现的内容

以下内容明确暂缓：

- 不拆分 `strategies/` 目录。
- 不做动态插件加载。
- 不从 YAML 或数据库执行策略逻辑。
- 不允许 LLM 直接生成并执行策略代码。
- 不做策略依赖数据的复杂声明系统。
- 不重写现有底背离、趋势反转和波段位置条件。
- 不立即通用化 `ScreenResult`。
- 不在数据中心加入复杂缓存。
- 不在本次结构改造中同时实现历史回测。

## TODO / 后续方向

1. 按本文设计完成第一版代码改造。
2. 在增加第二套策略前，确认 `ScreenResult` 是否需要改为通用字段加 `metrics/detail`。
3. 当策略达到三到四套时，引入轻量 `ScreenerStrategyDefinition`，声明需要的指标。
4. `T029` 历史日期模式直接复用策略注册表和统一策略输入。
5. 评估把当前 screener 尚未实现的 LLM 压力位判断作为独立策略步骤还是策略后置辅助判断；在口径确认前不接入硬过滤。
6. 当公共数据中心被 `market`、`report`、`stock_pool` 等多个模块实际复用后，再考虑从 `cassa.py` 拆成独立模块。

## 关键决策与反思

1. 数据中心解决的是“数据从哪里来、如何统一取得”，不是“所有业务都塞进一个中心”。
2. 主流程准备数据是当前阶段更容易理解和调试的方案；过早让策略自动声明复杂依赖会增加框架代码。
3. 策略函数必须保持纯判断边界，这一点比是否立即拆文件更重要。
4. 第一版保留当前结果协议，优先验证结构重构没有改变选股结果。
5. 使用显式注册表比根据函数名动态发现策略更透明，也更符合当前单文件项目规模。
6. 未来实时选股、历史验证和回测必须调用同一策略函数，避免出现三套口径相似但不一致的实现。

## 来源会话

- 当前会话（2026-07-07）
- 关联上下文：`2026-07-06-screener-breakout-strategy.md`
- 关联历史验证：`2026-07-06-screener-signal-validation.md`

