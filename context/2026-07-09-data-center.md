# 数据中心拆分第一阶段：通达信接口模块

## 主题概述

本文件记录 2026-07-09 围绕 `Cassa` 从单文件结构开始拆分的第一阶段方案。

当前用户明确提出：原来所有逻辑都直接写在 `cassa.py` 中，后续继续新增策略和业务能力会越来越不适合维护，因此准备开始拆分。但本阶段不直接重构旧文件，不围绕 `screener` 单一业务场景设计，而是先从更底层的数据来源开始，按 Python 项目常见方式新增独立入口和独立数据模块。

本阶段已从 `main` 切出新分支：

```text
feat/data-center-split
```

切分支前检查到 `main` 工作区干净，没有未提交文件；`main` 相对 `origin/main` ahead 22 个提交。

## 已确认结论

### 1. 保留旧 `cassa.py` 完全不动

本阶段不迁移、不删改、不替换原来的 `cassa.py`。

原因：

1. `cassa.py` 当前仍承载已有业务入口，直接重构风险较大。
2. 当前目标是先验证新模块边界，而不是一次性完成全项目拆分。
3. 旧文件暂时作为可运行基线，新文件并行生长。

### 2. 新数据中心脚本命名为 `data.py`

用户明确指定：数据中心脚本名字使用：

```text
data.py
```

这里的 `data.py` 第一阶段并不是复杂的数据中心框架，而是先作为通达信数据接口模块存在。

### 3. 第一阶段先在 `data.py` 中暴露模块自测入口

讨论中确认：一般 Python 项目不把 `data.py` 作为正式业务入口。

常见边界应是：

```text
main.py = 项目入口 / 业务入口 / CLI 分发
data.py = 数据读取 / 数据接口 / 数据处理函数
```

但本阶段为了保持最小文件数量和最小验证成本，先不新增 `main.py`，而是在 `data.py` 文件末尾保留：

```python
if __name__ == "__main__":
    main()
```

这个 `main()` 只用于自测 `data.py` 中的通达信接口是否可用，不定义为长期正式业务入口。

后续当业务入口变复杂，或开始组织多模块业务流程时，再新增 `main.py`，并把正式 CLI 分发迁过去。

### 4. 第一阶段只写普通函数

本阶段明确不使用 `TdxClient` 类。

不用类的原因：

1. 当前只是在拆第一层通达信接口，状态很少。
2. 不需要多个通达信连接实例。
3. 暂时不做复杂依赖注入、mock、缓存、限流或统一日志。
4. 用户要求“最普通的代码写法”，因此第一版以直白函数为主。

后续只有当需要保存复杂状态、统一错误策略、统一测试替换或支持多个数据源实例时，再考虑类。

### 5. 不做静默调用和异常吞掉

旧 `cassa.py` 的 `TdxClient` 中有 `_invoke_quietly`，会用 `redirect_stdout` 和 `redirect_stderr` 静默调用第三方接口。

新 `data.py` 第一版不沿用这个做法。

原因：

1. 第一阶段是验证接口，应该直接看到通达信接口原始输出和错误。
2. 普通写法更容易确认接口参数和返回结构。
3. 不提前引入额外包装层。

因此 `data.py` 中直接调用 `tqcenter.tq`。

### 6. 暂时不写复杂类型标注

之前讨论过 `-> dict[str, Any]` 的含义：这是 Python 类型标注，表示函数预计返回 key 为字符串、value 为任意类型的字典。

用户倾向第一版保持普通写法，因此新模块可以少写或不写复杂返回类型标注，只保留清晰函数名和中文 docstring。

## 本阶段接口范围

第一阶段只接入用户指定的通达信接口，分为行情类和板块类。

### 行情类接口

```text
get_market_data
get_market_snapshot
get_stock_info
get_more_info
get_relation
```

用途概括：

1. `get_market_data`：获取 K 线行情数据。
2. `get_market_snapshot`：获取单只股票实时快照。
3. `get_stock_info`：获取股票基础信息。
4. `get_more_info`：获取股票扩展信息。
5. `get_relation`：获取股票所属板块关系。

### 板块类接口

```text
get_stock_list
get_sector_list
get_stock_list_in_sector
```

用途概括：

1. `get_stock_list`：获取全市场股票列表。旧 `cassa.py` 当前尚未接入，`TASKS.md` 中原有 T018 记录过暂缓接入该能力。
2. `get_sector_list`：获取 A 股板块列表。
3. `get_stock_list_in_sector`：获取板块成分股列表。

### 公式类接口

后续讨论 report 移植时确认：当前 `report` 需要 MACD，但数据层不能只想着 MACD，而应接入通用公式接口。

第一阶段新增：

```text
formula_process_mul_zb
```

它是通达信批量调用技术指标公式的接口，不是 MACD 专用接口。MACD 只是业务层传入的一种参数组合：

```python
formula_name="MACD"
formula_arg="12,26,9"
```

旧 `cassa.py` 中还封装了：

```text
formula_set_data
formula_zb
```

但查询后确认这两个封装目前没有任何实际调用点，只是预留能力。因此第一阶段不接入它们。

结论：

1. `data.py` 只新增通用 `formula_process_mul_zb`。
2. 不新增 `calculate_macd_batch` 这种 MACD 专用函数。
3. MACD、KDJ、RSI、BOLL 等具体公式由 report / screener 等业务层决定。
4. 第一版按最普通写法直接调用通达信接口，不先加 `chunk_list` 分批逻辑。
5. 后续如果真实遇到股票数量大、接口超时或返回过大，再给 `formula_process_mul_zb` 增加 `chunk_size` 分批能力。

## 复权类型约定

本阶段确认：所有涉及复权类型的接口，默认全部写死为前复权。

原因：

1. `TASKS.md` 中已有项目原则：本项目所有复权类型统一使用前复权。
2. 后续选股、回测、趋势分析都应使用同一价格口径，避免不同模块之间出现不可比数据。
3. 第一阶段先不把复权类型暴露成可选业务参数，减少口径分叉。

当前计划接入的接口中，只有 K 线类接口需要关注复权类型：

```text
get_market_data
```

因此 `data.py` 中 `get_market_data` 第一版应直接传：

```python
dividend_type="front"
```

不需要复权类型的接口包括：

```text
get_market_snapshot
get_stock_info
get_more_info
get_relation
get_stock_list
get_sector_list
get_stock_list_in_sector
```

旧 `cassa.py` 中公式引擎相关接口还存在数字型复权参数：

```text
formula_set_data           dividend_type=1
formula_process_mul_zb     dividend_type=1
```

本阶段会接入 `formula_process_mul_zb`，其中复权参数先沿用旧代码口径：

```python
dividend_type=1
```

后续应确认通达信公式接口中 `1` 是否对应前复权；在确认前，context 中保留这个风险点。

## 股票代码口径

本阶段新增统一口径：新版数据中心内部所有股票代码都使用带市场后缀的通达信格式。

示例：

```text
000001.SZ
600519.SH
688318.SH
```

### 数据中心边界

`data.py` 作为数据中心，不负责猜测用户输入的纯数字代码属于哪个市场。

数据中心函数要求调用方传入带后缀代码：

```python
get_market_snapshot("000001.SZ")
get_stock_info("600519.SH")
load_daily_kline(["000001.SZ", "600519.SH"])
```

本地 SQLite 中也直接存带后缀代码，不再存纯数字代码。

原因：

1. 数据中心需要稳定、无歧义的代码主键。
2. 北交所、科创板、指数、板块等代码规则容易让纯数字推断变复杂。
3. 数据层不应该混入业务入口的输入容错逻辑。

### 业务层边界

用户在业务入口使用时，经常输入纯数字代码，例如：

```text
000001
600519
```

因此“纯数字代码补后缀”的逻辑应放在业务层或入口层，例如未来 `main.py`、`report.py`、`screener.py`。

业务层负责：

1. 接收用户输入。
2. 判断是否已经带后缀。
3. 对纯数字代码补成通达信格式。
4. 再调用 `data.py`。

### 对数据库设计的影响

原先草案中写过：

```text
code          纯数字股票代码
```

现在改为：

```text
code          带后缀通达信股票代码，例如 000001.SZ
```

唯一约束保持：

```text
UNIQUE(code, trade_date)
```

但这里的 `code` 是带后缀代码。

### 对代码草案的影响

原先草案中有：

```python
def strip_tdx_suffix(stock_code):
    """去掉通达信股票代码后缀，得到纯数字代码。"""
    return str(stock_code).split(".")[0]
```

这个函数不应再用于 `data.py` 的数据库主键。

后续实现时：

1. `market_data_to_daily_kline_rows` 中 `row["code"]` 应直接使用 `stock_code`，保留后缀。
2. `load_daily_kline_rows_from_db` 查询时也按带后缀代码查询。
3. `merge_realtime_kline_rows` / `load_daily_kline` 中的 code 对齐也按带后缀代码。
4. 如果某个自测命令用户输入纯数字，第一阶段可以直接要求用户改成带后缀；不要在 `data.py` 内猜后缀。

## 本地 SQLite 数据库方案

### 数据库路径与命名

本阶段确认：数据库文件放在 `data.py` 同级目录下的 `data/` 目录中。

这里的根目录以 `data.py` 所在目录为准，因为当前阶段 `data.py` 是确定会存在的文件。后续即使新增 `main.py`，也应放在 `data.py` 同级目录中。

```text
Cassa/
  data.py        # 数据接口模块
  main.py        # 后续可能新增的正式业务入口
  data/
    cassa.db     # Cassa 自己的 SQLite 数据库
```

代码中应使用相对 `data.py` 的路径，不再写死旧的绝对路径：

```python
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "cassa.db"
```

这里 `PROJECT_ROOT` 不是用户主目录，也不是 Git 仓库外部目录，而是 `data.py` 所在目录。

### 数据库名称

SQLite 数据库文件名固定为：

```text
cassa.db
```

所有 Cassa 自己管理的表都建在这个数据库里。

### 日 K 表

第一阶段先设计统一日 K 表：

```text
daily_kline
```

建议字段：

```text
code          带后缀通达信股票代码，例如 000001.SZ
trade_date    交易日，YYYY-MM-DD
open_price
high_price
low_price
close_price
volume
amount
created_at
updated_at
```

唯一约束：

```text
UNIQUE(code, trade_date)
```

由于项目复权口径已经统一为前复权，第一版可以不单独放 `adjust_type` 字段，避免每条记录都重复存同一常量。后续如果真的需要多复权口径共存，再重新评估是否增加 `adjust_type`。

### 收盘后增量更新

日 K 数据库只允许在收盘后写入当天 K 线。

第一阶段不做复杂状态表，不维护每只股票自己的缺口区间。

统一采用滚动窗口更新：

```text
对目标股票列表统一调用通达信 get_market_data，拉最近 30 天日 K。
```

写入逻辑：

```text
如果 daily_kline 中已存在 (code, trade_date)，则覆盖更新该行。
如果不存在，则插入新行。
```

也就是 SQLite 的 upsert 语义：

```sql
INSERT INTO daily_kline (...)
VALUES (...)
ON CONFLICT(code, trade_date) DO UPDATE SET ...
```

这样可以处理：

1. 上一次更新时某只股票某天漏数据，后续 30 天滚动窗口还有机会补上。
2. 同一天重复执行收盘更新时，不会产生重复记录。
3. 个别股票缺失天数不统一时，不必为每只股票单独计算拉取区间。

暂不考虑：

1. `daily_kline_update_state` 状态表。
2. 每只股票独立缺口扫描。
3. 对停牌日强行补空 K 线。

### 业务查询日 K 的统一函数

用户确认：不希望同时存在 `load_daily_kline_from_db()` 和 `load_daily_kline_with_realtime()` 两套逻辑。

因此第一阶段只设计一个统一读取函数，例如：

```python
def load_daily_kline(code, count=120):
    """读取日 K，并用通达信最新日 K 对返回数据做临时拼接或覆盖。"""
```

逻辑：

1. 先从本地 `daily_kline` 表读取该股票历史 K 线，按日期升序排列。
2. 再调用通达信 `get_market_data` 拉该股票最新日 K，至少取最近 1 根，必要时可以取最近 2 到 5 根提高容错。
3. 比较数据库最新 K 线日期和通达信最新 K 线日期。
4. 如果日期一致：用通达信最新 K 线覆盖返回列表中的最后一根。
5. 如果数据库日期小于通达信日期：把通达信最新 K 线追加到返回列表末尾。
6. 如果数据库日期大于通达信日期：报错。

这里的“覆盖”只发生在函数返回的数据中，不写回数据库。

原因：

1. 盘中业务需要实时 K 线参与判断。
2. 当天 K 线只允许收盘后由更新脚本写库。
3. 查询函数不能因为盘中运行而偷偷污染历史数据库。

### 单函数查询逻辑的边界检查

这个单函数方案整体可行，但实现时要注意以下边界：

1. 通达信最新 K 线可能是盘中临时 K，不能写入数据库。
2. 如果数据库为空，且通达信能返回最新 K 线，可以直接返回通达信 K 线；但业务层要知道历史长度可能不足。
3. 如果数据库最新日期大于通达信最新日期，说明本地数据或通达信返回存在时间口径异常，应直接报错，不应静默回退。
4. 如果通达信最新 K 线日期和数据库最后日期一致，使用通达信数据覆盖返回值可以让盘中价格、最高、最低及时更新。
5. 如果通达信返回多根 K 线，而数据库落后不止一天，第一版可以只追加最新一根；但更稳的做法是把通达信返回的最近几根逐日和数据库结果做同样的覆盖 / 追加合并。这样能自然补上少量缺口。

建议第一版实现时，让查询函数调用 `get_market_data(count=5)`，然后对返回的最近几根日 K 按日期逐根合并到数据库结果的拷贝中：

```text
同日期：覆盖返回数据
新日期：追加到返回数据
远早于数据库最后日期：忽略
如果出现通达信日期小于数据库最新日期且没有任何可合并新数据：报错或提示异常
```

这样仍然是一个统一函数，但比“只看最新一根”更能处理数据库短期缺口。

## 后续代码修改记录方式

后续真正写代码时，context 中应按以下方式记录：

1. 修改已有代码：写明原代码位置、原来是什么、现在改成什么。
2. 新增代码：写明新增到哪个文件、哪个位置，并贴完整代码。
3. 不在 context 中只写“新增某函数”，必须能让后续 Agent 从 context 看出函数签名、核心逻辑和调用边界。

## `data.py` 数据库代码草案

### 新增位置

后续新建 `data.py` 时，数据库相关代码建议放在通达信接口函数之后、自测入口之前。

文件结构建议：

```text
data.py
  import
  路径与常量
  通达信初始化
  通达信行情类接口
  通达信板块类接口
  通达信公式类接口
  SQLite 建表与日 K 更新 / 查询
  自测入口 main()
```

### 原代码

当前没有独立 `data.py` 文件，因此没有原代码。

旧 `cassa.py` 中相关旧逻辑分散在：

```text
DAILY_KLINE_DB_PATH = Path(r"D:\股神养成plan\Sentinel\all_daily_k.db")
load_stock_codes_from_db(...)
load_daily_kline_from_db(...)
```

新 `data.py` 不复用旧的绝对路径，也不再设计成只读外部 `Sentinel/all_daily_k.db`。

### 新增代码

以下是后续写入 `data.py` 的数据库部分完整草案。

```python
from datetime import datetime
from pathlib import Path
import sqlite3
import time


PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "cassa.db"
DAILY_KLINE_UPDATE_DAYS = 30
DAILY_KLINE_REALTIME_DAYS = 5
DAILY_KLINE_UPDATE_BATCH_SIZE = 500


def ensure_database():
    """初始化 Cassa SQLite 数据库和日 K 表。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_kline (
            code        TEXT NOT NULL,
            trade_date  TEXT NOT NULL,
            open_price  REAL NOT NULL,
            high_price  REAL NOT NULL,
            low_price   REAL NOT NULL,
            close_price REAL NOT NULL,
            volume      REAL NOT NULL DEFAULT 0,
            amount      REAL NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            PRIMARY KEY (code, trade_date)
        )
        """
    )
    conn.commit()
    return conn


def upsert_daily_kline_rows(rows):
    """把日 K 行写入数据库，已存在的 code + trade_date 直接覆盖。"""
    if not rows:
        return 0

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = ensure_database()
    try:
        for row in rows:
            conn.execute(
                """
                INSERT INTO daily_kline (
                    code, trade_date, open_price, high_price, low_price,
                    close_price, volume, amount, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(code, trade_date) DO UPDATE SET
                    open_price = excluded.open_price,
                    high_price = excluded.high_price,
                    low_price = excluded.low_price,
                    close_price = excluded.close_price,
                    volume = excluded.volume,
                    amount = excluded.amount,
                    updated_at = excluded.updated_at
                """,
                (
                    row["code"],
                    row["trade_date"],
                    row["open_price"],
                    row["high_price"],
                    row["low_price"],
                    row["close_price"],
                    row.get("volume", 0),
                    row.get("amount", 0),
                    now,
                    now,
                ),
            )
        conn.commit()
    finally:
        conn.close()

    return len(rows)


def load_daily_kline_rows_from_db(code_list, count=None):
    """只从本地数据库读取日 K，不调用通达信。"""
    if not code_list:
        return {}

    conn = ensure_database()
    placeholders = ",".join(["?"] * len(code_list))
    try:
        rows = conn.execute(
            f"""
            SELECT code, trade_date, open_price, high_price, low_price,
                   close_price, volume, amount
            FROM daily_kline
            WHERE code IN ({placeholders})
            ORDER BY code, trade_date ASC
            """,
            code_list,
        ).fetchall()
    finally:
        conn.close()

    result = {}
    for row in rows:
        code = row[0]
        if code not in result:
            result[code] = []
        result[code].append(
            {
                "code": code,
                "trade_date": row[1],
                "open_price": float(row[2]),
                "high_price": float(row[3]),
                "low_price": float(row[4]),
                "close_price": float(row[5]),
                "volume": float(row[6]),
                "amount": float(row[7]),
            }
        )

    if count is not None:
        for code in result:
            if len(result[code]) > count:
                result[code] = result[code][-count:]

    return result
```

### 通达信 K 线返回转换代码

`get_market_data` 返回结构通常按字段分组，旧 `cassa.py` 中按 `market_data["Close"]`、`market_data["Amount"]` 这种方式读取，因此新增一个转换函数，把单只或多只股票的字段表转成数据库行。

```python
def market_data_to_daily_kline_rows(market_data, stock_list):
    """把通达信 get_market_data 返回结果转换为 daily_kline 行。"""
    rows = []
    open_data = market_data.get("Open")
    high_data = market_data.get("High")
    low_data = market_data.get("Low")
    close_data = market_data.get("Close")
    volume_data = market_data.get("Volume")
    amount_data = market_data.get("Amount")

    if open_data is None or high_data is None or low_data is None or close_data is None:
        return rows

    for stock_code in stock_list:
        if stock_code not in close_data.columns:
            continue

        close_series = close_data[stock_code].dropna()
        for trade_date in close_series.index:
            rows.append(
                {
                    "code": stock_code,
                    "trade_date": str(trade_date)[:10],
                    "open_price": float(open_data[stock_code].loc[trade_date]),
                    "high_price": float(high_data[stock_code].loc[trade_date]),
                    "low_price": float(low_data[stock_code].loc[trade_date]),
                    "close_price": float(close_data[stock_code].loc[trade_date]),
                    "volume": float(volume_data[stock_code].loc[trade_date]) if volume_data is not None else 0.0,
                    "amount": float(amount_data[stock_code].loc[trade_date]) if amount_data is not None else 0.0,
                }
            )

    return rows
```

### 收盘后更新代码

新增位置：放在 `market_data_to_daily_kline_rows` 后面。

更新命令不再要求用户传 `--codes`。日 K 数据库的常规更新目标是全部 A 股，因此函数内部调用 `get_stock_list()` 获取股票列表。

`--count` 作为更新窗口参数：

```text
count=30     日常增量更新
count=500    首次加载较长历史
count=3000   数据错乱时近似全量重刷
```

由于全 A 股数量较大，第一版就保留简单分批更新能力，避免一次性把全部股票传给 `get_market_data` 导致接口超时或返回过大。

该命令可能运行较久，例如：

```powershell
python data.py update-daily-kline --count 500 --batch-size 500
```

因此更新函数必须打印进度日志：

1. 开始时打印本次 `count` 和 `batch_size`。
2. 获取股票列表前后打印状态和股票数量。
3. 每批开始时打印当前批次、总批数、股票数量、首尾代码。
4. 每批完成时打印本批写入行数、累计写入行数、本批耗时和总耗时。
5. 如果某批失败，打印批次号、首尾代码和错误，然后继续抛出异常，不静默吞掉。
6. 全部完成后打印总股票数、总写入行数和总耗时。

```python
def chunk_list(items, chunk_size):
    """把列表按固定大小切成多批。"""
    chunks = []
    for start in range(0, len(items), chunk_size):
        chunks.append(items[start:start + chunk_size])
    return chunks


def extract_stock_codes_from_stock_list(stock_rows):
    """从通达信 get_stock_list 返回结果中提取股票代码。"""
    stock_codes = []
    for row in stock_rows:
        if isinstance(row, dict):
            code = row.get("Code", "")
        else:
            code = str(row)

        if code:
            stock_codes.append(code)

    return stock_codes


def update_daily_kline_after_close(
    count=DAILY_KLINE_UPDATE_DAYS,
    batch_size=DAILY_KLINE_UPDATE_BATCH_SIZE,
):
    """收盘后更新全部 A 股最近 N 天日 K，并 upsert 到本地数据库。"""
    started_at = time.perf_counter()

    print(f"[日K更新] 开始更新全部A股日K：count={count}, batch_size={batch_size}")
    print("[日K更新] 正在获取全市场股票列表...")

    stock_rows = get_stock_list()
    stock_list = extract_stock_codes_from_stock_list(stock_rows)

    if not stock_list:
        print("[日K更新] 未获取到股票列表，结束。")
        return {
            "stock_count": 0,
            "updated_rows": 0,
            "count": count,
            "batch_size": batch_size,
        }

    batches = chunk_list(stock_list, batch_size)
    total_batches = len(batches)
    total_updated_rows = 0

    print(f"[日K更新] 获取到 {len(stock_list)} 只股票，共 {total_batches} 批。")

    for batch_index, stock_batch in enumerate(batches, 1):
        batch_started_at = time.perf_counter()
        first_code = stock_batch[0]
        last_code = stock_batch[-1]

        print(
            f"[日K更新] 第 {batch_index}/{total_batches} 批开始："
            f"{len(stock_batch)} 只，{first_code} ~ {last_code}"
        )

        try:
            market_data = get_market_data(
                stock_list=stock_batch,
                period="1d",
                count=count,
                field_list=["Open", "High", "Low", "Close", "Volume", "Amount"],
                fill_data=True,
            )
            rows = market_data_to_daily_kline_rows(market_data, stock_batch)
            updated_rows = upsert_daily_kline_rows(rows)
        except Exception as exc:
            print(
                f"[日K更新] 第 {batch_index}/{total_batches} 批失败："
                f"{first_code} ~ {last_code}，错误：{exc}"
            )
            raise

        total_updated_rows += updated_rows
        batch_seconds = time.perf_counter() - batch_started_at
        total_seconds = time.perf_counter() - started_at

        print(
            f"[日K更新] 第 {batch_index}/{total_batches} 批完成："
            f"本批写入 {updated_rows} 行，累计 {total_updated_rows} 行，"
            f"本批耗时 {batch_seconds:.1f}s，总耗时 {total_seconds:.1f}s"
        )

    total_seconds = time.perf_counter() - started_at
    print(
        f"[日K更新] 全部完成：股票 {len(stock_list)} 只，"
        f"写入/覆盖 {total_updated_rows} 行，总耗时 {total_seconds:.1f}s"
    )

    return {
        "stock_count": len(stock_list),
        "updated_rows": total_updated_rows,
        "count": count,
        "batch_size": batch_size,
        "elapsed_seconds": round(total_seconds, 1),
    }
```

### 业务查询统一函数代码

新增位置：放在收盘后更新函数之后。

第一版要求调用方传通达信格式股票代码，例如 `000001.SZ`、`600519.SH`。数据库内部也统一存带后缀代码。

```python
def merge_realtime_kline_rows(db_rows, realtime_rows):
    """把通达信最新日 K 合并到数据库日 K 的返回副本中，不写数据库。"""
    merged_rows = [dict(row) for row in db_rows]

    if not realtime_rows:
        return merged_rows

    if not merged_rows:
        return [dict(row) for row in realtime_rows]

    row_by_date = {row["trade_date"]: index for index, row in enumerate(merged_rows)}
    latest_db_date = merged_rows[-1]["trade_date"]
    latest_realtime_date = realtime_rows[-1]["trade_date"]

    if latest_db_date > latest_realtime_date:
        raise RuntimeError(
            f"本地日K日期晚于通达信最新日期：db={latest_db_date}, tdx={latest_realtime_date}"
        )

    for realtime_row in realtime_rows:
        trade_date = realtime_row["trade_date"]
        if trade_date in row_by_date:
            merged_rows[row_by_date[trade_date]] = dict(realtime_row)
        elif trade_date > latest_db_date:
            merged_rows.append(dict(realtime_row))

    merged_rows.sort(key=lambda row: row["trade_date"])
    return merged_rows


def load_daily_kline(stock_list, count=120):
    """读取日 K，并用通达信最新日 K 对返回数据做临时拼接或覆盖。

    这个函数是业务层统一读取入口：
    1. 先读本地数据库历史 K 线。
    2. 再调用通达信拉最近几根日 K。
    3. 同日期则用通达信数据覆盖返回结果。
    4. 新日期则追加到返回结果末尾。
    5. 覆盖和追加只发生在返回值中，不写数据库。
    """
    result = {}
    realtime_data = get_market_data(
        stock_list=stock_list,
        period="1d",
        count=DAILY_KLINE_REALTIME_DAYS,
        field_list=["Open", "High", "Low", "Close", "Volume", "Amount"],
        fill_data=True,
    )
    realtime_rows = market_data_to_daily_kline_rows(realtime_data, stock_list)
    db_rows_by_code = load_daily_kline_rows_from_db(stock_list, count=count)
    for stock_code in stock_list:
        db_rows = db_rows_by_code.get(stock_code, [])
        stock_realtime_rows = [r for r in realtime_rows if r["code"] == stock_code]
        merged_rows = merge_realtime_kline_rows(db_rows, stock_realtime_rows)

        if count is not None and len(merged_rows) > count:
            merged_rows = merged_rows[-count:]
        result[stock_code] = merged_rows
    return result
```

### 自测入口新增命令草案

后续更新 `data.py` 的 `main()` 时，新增以下命令：

```text
update-daily-kline
load-daily-kline
```

新增位置：放在现有自测入口的 parser 分支中。

```python
update_daily_kline_parser = subparsers.add_parser("update-daily-kline")
update_daily_kline_parser.add_argument("--count", type=int, default=DAILY_KLINE_UPDATE_DAYS)
update_daily_kline_parser.add_argument("--batch-size", type=int, default=DAILY_KLINE_UPDATE_BATCH_SIZE)

load_daily_kline_parser = subparsers.add_parser("load-daily-kline")
load_daily_kline_parser.add_argument("--code", required=True)
load_daily_kline_parser.add_argument("--count", type=int, default=120)
```

对应分发代码：

```python
elif args.command == "update-daily-kline":
    print_json(update_daily_kline_after_close(args.count, args.batch_size))
elif args.command == "load-daily-kline":
    print_json(load_daily_kline([args.code], args.count))
```

验证命令：

```powershell
python data.py update-daily-kline --count 30
python data.py update-daily-kline --count 500 --batch-size 500
python data.py load-daily-kline --code 000001.SZ --count 120
```

## `data.py` 自测入口帮助信息改造

### 背景

当前运行：

```powershell
python data.py -h
```

输出只显示子命令名称：

```text
usage: data.py [-h]
               {get_market_snapshot,get_stock_info,get_more_info,get_relation,get_sector_list,get_stock_list,get_stock_list_in_sector,update-daily-kline,load-daily-kline}
               ...

positional arguments:
  {get_market_snapshot,get_stock_info,get_more_info,get_relation,get_sector_list,get_stock_list,get_stock_list_in_sector,update-daily-kline,load-daily-kline}

options:
  -h, --help            show this help message and exit
```

问题：

1. 主帮助中看不出每个命令是干什么的。
2. 参数没有中文解释。
3. 没有常用示例。

### 修改位置

修改 `data.py` 文件中的 `main()` 函数。

不要改通达信接口函数和数据库函数，只改 argparse 自测入口。

### 原代码

当前 `main()` 中 argparse 部分是：

```python
def main():
    """自测 data.py 中的通达信接口。"""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    get_market_snapshot_parser = subparsers.add_parser("get_market_snapshot")
    get_market_snapshot_parser.add_argument("--code", required=True)

    get_stock_info_parser = subparsers.add_parser("get_stock_info")
    get_stock_info_parser.add_argument("--code", required=True)

    get_more_info_parser = subparsers.add_parser("get_more_info")
    get_more_info_parser.add_argument("--code", required=True)

    get_relation_parser = subparsers.add_parser("get_relation")
    get_relation_parser.add_argument("--code", required=True)

    get_sector_list_parser = subparsers.add_parser("get_sector_list")
    get_sector_list_parser.add_argument("--list-type", type=int, default=1)

    get_stock_list_parser = subparsers.add_parser("get_stock_list")

    get_stock_list_in_sector_parser = subparsers.add_parser("get_stock_list_in_sector")
    get_stock_list_in_sector_parser.add_argument("--block-code", required=True)
    get_stock_list_in_sector_parser.add_argument("--block-type", type=int, default=0)
    get_stock_list_in_sector_parser.add_argument("--list-type", type=int, default=1)

    update_daily_kline_parser = subparsers.add_parser("update-daily-kline")
    update_daily_kline_parser.add_argument("--codes", required=True)
    update_daily_kline_parser.add_argument("--count", type=int, default=DAILY_KLINE_UPDATE_DAYS)

    load_daily_kline_parser = subparsers.add_parser("load-daily-kline")
    load_daily_kline_parser.add_argument("--code", required=True)
    load_daily_kline_parser.add_argument("--count", type=int, default=120)
```

### 现代码草案

将上面 argparse 部分改为：

```python
def main():
    """自测 data.py 中的通达信接口。"""
    parser = argparse.ArgumentParser(
        description="Cassa 数据接口自测工具：用于验证通达信接口和本地 SQLite 日 K 数据功能。",
        epilog=(
            "示例：\n"
            "  python data.py get_market_snapshot --code 000001.SZ\n"
            "  python data.py get_stock_info --code 600519.SH\n"
            "  python data.py get_more_info --code 000001.SZ\n"
            "  python data.py get_relation --code 000001.SZ\n"
            "  python data.py get_sector_list\n"
            "  python data.py get_stock_list_in_sector --block-code CASSA --block-type 1\n"
            "  python data.py update-daily-kline --count 30\n"
            "  python data.py update-daily-kline --count 500 --batch-size 500\n"
            "  python data.py load-daily-kline --code 000001.SZ --count 120"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        title="可用命令",
        metavar="命令",
    )

    get_market_snapshot_parser = subparsers.add_parser(
        "get_market_snapshot",
        help="获取单只股票实时行情快照",
        description="获取单只股票实时行情快照，例如现价、今开、最高、最低、成交量等。",
    )
    get_market_snapshot_parser.add_argument(
        "--code",
        required=True,
        help="通达信格式股票代码，例如 000001.SZ、600519.SH",
    )

    get_stock_info_parser = subparsers.add_parser(
        "get_stock_info",
        help="获取股票基础信息",
        description="获取股票基础信息，例如名称、总股本等字段。",
    )
    get_stock_info_parser.add_argument(
        "--code",
        required=True,
        help="通达信格式股票代码，例如 000001.SZ、600519.SH",
    )

    get_more_info_parser = subparsers.add_parser(
        "get_more_info",
        help="获取股票扩展信息",
        description="获取股票扩展信息，例如换手率、量比、PE、PB、资金等字段。",
    )
    get_more_info_parser.add_argument(
        "--code",
        required=True,
        help="通达信格式股票代码，例如 000001.SZ、600519.SH",
    )

    get_relation_parser = subparsers.add_parser(
        "get_relation",
        help="获取股票所属行业和概念板块关系",
        description="获取股票所属板块关系，常用于识别行业板块和概念板块。",
    )
    get_relation_parser.add_argument(
        "--code",
        required=True,
        help="通达信格式股票代码，例如 000001.SZ、600519.SH",
    )

    get_sector_list_parser = subparsers.add_parser(
        "get_sector_list",
        help="获取通达信板块列表",
        description="获取通达信板块列表。list-type=0 只返回代码，list-type=1 返回代码和名称。",
    )
    get_sector_list_parser.add_argument(
        "--list-type",
        type=int,
        default=1,
        choices=[0, 1],
        help="返回类型：0=只返回代码，1=返回代码和名称，默认 1",
    )

    get_stock_list_parser = subparsers.add_parser(
        "get_stock_list",
        help="获取全市场股票列表",
        description="获取全市场股票列表。注意：该命令可能输出大量数据。",
    )

    get_stock_list_in_sector_parser = subparsers.add_parser(
        "get_stock_list_in_sector",
        help="获取指定板块成分股",
        description="获取指定板块的成分股列表，支持系统板块和自定义板块。",
    )
    get_stock_list_in_sector_parser.add_argument(
        "--block-code",
        required=True,
        help="板块代码或板块名称，例如 CASSA、880675.SH、减速器",
    )
    get_stock_list_in_sector_parser.add_argument(
        "--block-type",
        type=int,
        default=0,
        choices=[0, 1],
        help="板块类型：0=系统板块或板块名称，1=自定义板块，默认 0",
    )
    get_stock_list_in_sector_parser.add_argument(
        "--list-type",
        type=int,
        default=1,
        choices=[0, 1],
        help="返回类型：0=只返回代码，1=返回代码和名称，默认 1",
    )

    update_daily_kline_parser = subparsers.add_parser(
        "update-daily-kline",
        help="收盘后更新本地日 K 数据库",
        description=(
            "收盘后更新全部 A 股最近 N 天前复权日 K，并写入 data/cassa.db。"
            "已存在的日期会覆盖更新。"
        ),
    )
    update_daily_kline_parser.add_argument(
        "--count",
        type=int,
        default=DAILY_KLINE_UPDATE_DAYS,
        help=(
            f"拉取最近多少天日 K，默认 {DAILY_KLINE_UPDATE_DAYS}。"
            "日常增量可设小，首次加载或重刷可设大。"
        ),
    )
    update_daily_kline_parser.add_argument(
        "--batch-size",
        type=int,
        default=DAILY_KLINE_UPDATE_BATCH_SIZE,
        help=f"每批更新多少只股票，默认 {DAILY_KLINE_UPDATE_BATCH_SIZE}",
    )

    load_daily_kline_parser = subparsers.add_parser(
        "load-daily-kline",
        help="读取日 K 并临时拼接最新通达信 K 线",
        description=(
            "先读取本地 SQLite 日 K，再调用通达信获取最近 K 线，"
            "同日期覆盖返回结果，新日期追加到返回结果，不写回数据库。"
        ),
    )
    load_daily_kline_parser.add_argument(
        "--code",
        required=True,
        help="通达信格式股票代码，例如 000001.SZ、600519.SH",
    )
    load_daily_kline_parser.add_argument(
        "--count",
        type=int,
        default=120,
        help="返回最近多少根日 K，默认 120",
    )
```

`args = parser.parse_args()` 以及后面的命令分发逻辑保持不变。

### 预期效果

主帮助：

```powershell
python data.py -h
```

应显示每个子命令的中文说明和示例。

单命令帮助：

```powershell
python data.py update-daily-kline -h
python data.py load-daily-kline -h
```

应显示该命令的中文参数解释。

## `archive-snapshot` 当前快照归档方案

### 背景

以下三个通达信接口只能查询当前数据，不能传日期查询历史：

```text
get_market_snapshot
get_stock_info
get_more_info
```

因此如果后续需要回看历史，只能由 Cassa 在每天收盘后主动执行一次，把当天结果归档下来。

### 命令

新增自测命令：

```powershell
python data.py archive-snapshot
```

不提供 `--date` 参数。

原因：

1. 这些接口不能传日期。
2. 归档日期就是执行脚本当天日期。
3. 如果当天重跑，则覆盖当天归档文件。

可选参数：

```powershell
python data.py archive-snapshot --progress-interval 500
```

`--progress-interval` 用于控制每处理多少个对象打印一次进度。

### 归档范围

归档范围包括两类：

1. 全部 A 股个股。
2. 全部板块。

个股列表来源：

```python
get_stock_list()
```

板块列表来源：

```python
get_sector_list(list_type=1)
```

对每个个股 / 板块分别调用：

```text
get_market_snapshot
get_stock_info
get_more_info
```

### 保存目录

归档文件放在 `data.py` 同级目录下的 `data/snapshots/` 中。

个股和板块分开两个目录保存：

```text
data/
  snapshots/
    2026-07-09/
      stocks/
        market_snapshot.jsonl
        stock_info.jsonl
        more_info.jsonl
        error.jsonl
      sectors/
        market_snapshot.jsonl
        stock_info.jsonl
        more_info.jsonl
        error.jsonl
```

当天重跑覆盖当天文件，包括正常数据文件和 `error.jsonl`。

### JSONL 正常行格式

个股：

```json
{"type":"stock","code":"000001.SZ","name":"平安银行","archive_date":"2026-07-09","api":"get_market_snapshot","data":{}}
```

板块：

```json
{"type":"sector","code":"880001.SH","name":"证券","archive_date":"2026-07-09","api":"get_more_info","data":{}}
```

字段说明：

```text
type          stock / sector
code          带后缀通达信代码
name          名称
archive_date  归档日期，即脚本执行当天
api           接口名
data          原始接口返回
```

### JSONL 错误行格式

单个接口失败时，写入对应目录下的 `error.jsonl`：

```json
{"type":"stock","code":"000001.SZ","name":"平安银行","archive_date":"2026-07-09","api":"get_more_info","error":"接口调用失败信息"}
```

```json
{"type":"sector","code":"880001.SH","name":"证券","archive_date":"2026-07-09","api":"get_stock_info","error":"接口调用失败信息"}
```

失败处理规则：

1. 单个接口失败只记录 `error.jsonl`。
2. 控制台打印失败日志。
3. 不终止整体任务。
4. 同一个对象的其他接口如果成功，仍正常写入对应文件。

### 新增代码

新增位置：`data.py` 中，建议放在日 K 更新 / 查询函数之后，自测入口 `main()` 之前。

```python
SNAPSHOT_DIR = DATA_DIR / "snapshots"


def write_jsonl_line(file_obj, value):
    """写入一行 JSONL。"""
    file_obj.write(json.dumps(value, ensure_ascii=False, default=str))
    file_obj.write("\n")


def replace_tmp_file(tmp_path, final_path):
    """用临时文件覆盖正式文件。"""
    if final_path.exists():
        final_path.unlink()
    tmp_path.rename(final_path)


def get_stock_archive_items():
    """获取全部 A 股归档对象。"""
    stock_rows = get_stock_list()
    items = []
    for row in stock_rows:
        if isinstance(row, dict):
            code = row.get("Code", "")
            name = row.get("Name", "")
        else:
            code = str(row)
            name = ""

        if code:
            items.append(
                {
                    "code": code,
                    "name": name,
                }
            )

    return items


def get_sector_archive_items():
    """获取全部板块归档对象。"""
    sector_rows = get_sector_list(list_type=1)
    items = []
    for row in sector_rows:
        if isinstance(row, dict):
            code = row.get("Code", "")
            name = row.get("Name", "")
        else:
            code = str(row)
            name = ""

        if code:
            items.append(
                {
                    "code": code,
                    "name": name,
                }
            )

    return items


def archive_snapshot_group(items, item_type, output_dir, archive_date, progress_interval=500):
    """归档一组对象的当前快照类接口数据。"""
    output_dir.mkdir(parents=True, exist_ok=True)

    api_definitions = [
        ("get_market_snapshot", "market_snapshot.jsonl", get_market_snapshot),
        ("get_stock_info", "stock_info.jsonl", get_stock_info),
        ("get_more_info", "more_info.jsonl", get_more_info),
    ]

    tmp_files = {
        filename: output_dir / f"{filename}.tmp"
        for _, filename, _ in api_definitions
    }
    tmp_files["error.jsonl"] = output_dir / "error.jsonl.tmp"

    final_files = {
        filename: output_dir / filename
        for _, filename, _ in api_definitions
    }
    final_files["error.jsonl"] = output_dir / "error.jsonl"

    handles = {}
    success_counts = {
        "get_market_snapshot": 0,
        "get_stock_info": 0,
        "get_more_info": 0,
    }
    error_count = 0
    started_at = time.perf_counter()

    try:
        for filename, tmp_path in tmp_files.items():
            handles[filename] = open(tmp_path, "w", encoding="utf-8")

        total = len(items)
        print(f"[快照归档] {item_type} 开始：{total} 个对象，输出目录 {output_dir}")

        for index, item in enumerate(items, 1):
            code = item.get("code", "")
            name = item.get("name", "")

            for api_name, filename, api_func in api_definitions:
                try:
                    data = api_func(code)
                    write_jsonl_line(
                        handles[filename],
                        {
                            "type": item_type,
                            "code": code,
                            "name": name,
                            "archive_date": archive_date,
                            "api": api_name,
                            "data": data,
                        },
                    )
                    success_counts[api_name] += 1
                except Exception as exc:
                    error_count += 1
                    print(f"[快照归档] {item_type} {code} {name} {api_name} 失败：{exc}")
                    write_jsonl_line(
                        handles["error.jsonl"],
                        {
                            "type": item_type,
                            "code": code,
                            "name": name,
                            "archive_date": archive_date,
                            "api": api_name,
                            "error": str(exc),
                        },
                    )

            if progress_interval > 0 and index % progress_interval == 0:
                elapsed_seconds = time.perf_counter() - started_at
                print(
                    f"[快照归档] {item_type} 进度 {index}/{total}，"
                    f"snapshot={success_counts['get_market_snapshot']}，"
                    f"stock_info={success_counts['get_stock_info']}，"
                    f"more_info={success_counts['get_more_info']}，"
                    f"error={error_count}，耗时 {elapsed_seconds:.1f}s"
                )

        for handle in handles.values():
            handle.close()
        handles = {}

        for filename, tmp_path in tmp_files.items():
            replace_tmp_file(tmp_path, final_files[filename])

    finally:
        for handle in handles.values():
            handle.close()

    elapsed_seconds = time.perf_counter() - started_at
    print(
        f"[快照归档] {item_type} 完成：{len(items)} 个对象，"
        f"snapshot={success_counts['get_market_snapshot']}，"
        f"stock_info={success_counts['get_stock_info']}，"
        f"more_info={success_counts['get_more_info']}，"
        f"error={error_count}，耗时 {elapsed_seconds:.1f}s"
    )

    return {
        "type": item_type,
        "total": len(items),
        "success": success_counts,
        "error": error_count,
        "elapsed_seconds": round(elapsed_seconds, 1),
    }


def archive_snapshot(progress_interval=500):
    """归档全部 A 股个股和全部板块的当前快照类接口数据。"""
    archive_date = datetime.now().strftime("%Y-%m-%d")
    date_dir = SNAPSHOT_DIR / archive_date
    started_at = time.perf_counter()

    print(f"[快照归档] 开始归档当前快照：archive_date={archive_date}")
    print("[快照归档] 正在获取全部 A 股列表...")
    stock_items = get_stock_archive_items()
    print(f"[快照归档] 获取到 {len(stock_items)} 只 A 股")

    stock_result = archive_snapshot_group(
        items=stock_items,
        item_type="stock",
        output_dir=date_dir / "stocks",
        archive_date=archive_date,
        progress_interval=progress_interval,
    )

    print("[快照归档] 正在获取全部板块列表...")
    sector_items = get_sector_archive_items()
    print(f"[快照归档] 获取到 {len(sector_items)} 个板块")

    sector_result = archive_snapshot_group(
        items=sector_items,
        item_type="sector",
        output_dir=date_dir / "sectors",
        archive_date=archive_date,
        progress_interval=progress_interval,
    )

    elapsed_seconds = time.perf_counter() - started_at
    print(f"[快照归档] 全部完成，总耗时 {elapsed_seconds:.1f}s")

    return {
        "archive_date": archive_date,
        "stocks": stock_result,
        "sectors": sector_result,
        "elapsed_seconds": round(elapsed_seconds, 1),
    }
```

### 自测入口新增代码

修改 `data.py` 的 `main()` 中 argparse 部分，新增：

```python
archive_snapshot_parser = subparsers.add_parser(
    "archive-snapshot",
    help="归档全部 A 股和全部板块的当前快照接口数据",
    description=(
        "归档 get_market_snapshot / get_stock_info / get_more_info 当前返回。"
        "这些接口不能传日期，因此归档日期使用脚本执行当天。"
    ),
)
archive_snapshot_parser.add_argument(
    "--progress-interval",
    type=int,
    default=500,
    help="每处理多少个对象打印一次进度，默认 500",
)
```

命令分发新增：

```python
elif args.command == "archive-snapshot":
    print_json(archive_snapshot(args.progress_interval))
```

主帮助示例中新增：

```python
"  python data.py archive-snapshot\n"
"  python data.py archive-snapshot --progress-interval 500\n"
```

## 建议文件结构

第一阶段先新增一个平铺文件：

```text
Cassa/
  cassa.py       # 旧入口，保持完全不动
  data.py        # 新通达信数据接口模块，文件内带一个自测入口
```

本阶段暂不创建 `cassa_core/` 包，也暂不拆成多层目录。

原因：

1. 当前需要先确认接口边界。
2. 平铺脚本更容易快速验证。
3. 过早建包会把问题变成目录设计，而不是接口验证。

## `data.py` 代码写法草案

`data.py` 第一版只负责初始化和原始接口调用。

```python
"""
Cassa 数据接口模块。

第一阶段只接入通达信 tqcenter 的行情类和板块类接口。
"""

from tqcenter import tq


_initialized = False


def initialize(script_path):
    """初始化通达信 tqcenter。"""
    global _initialized

    if _initialized:
        return

    tq.initialize(str(script_path))
    _initialized = True
```

行情类接口：

```python
def get_market_data(
    stock_list,
    period="1d",
    count=60,
    start_time="",
    end_time="",
    field_list=None,
    fill_data=True,
):
    """获取 K 线行情数据。"""
    return tq.get_market_data(
        field_list=field_list or [],
        stock_list=stock_list,
        period=period,
        start_time=start_time,
        end_time=end_time,
        count=count,
        dividend_type="front",
        fill_data=fill_data,
    )


def get_market_snapshot(stock_code, field_list=None):
    """获取单只股票实时快照。"""
    return tq.get_market_snapshot(
        stock_code=stock_code,
        field_list=field_list or [],
    )


def get_stock_info(stock_code, field_list=None):
    """获取股票基础信息。"""
    return tq.get_stock_info(
        stock_code=stock_code,
        field_list=field_list or [],
    )


def get_more_info(stock_code, field_list=None):
    """获取股票扩展信息。"""
    return tq.get_more_info(
        stock_code=stock_code,
        field_list=field_list or [],
    )


def get_relation(stock_code):
    """获取股票所属板块关系。"""
    return tq.get_relation(stock_code=stock_code)
```

板块类接口：

```python
def get_stock_list():
    """获取全市场股票列表。"""
    return tq.get_stock_list()


def get_sector_list(list_type=1):
    """获取板块列表。"""
    return tq.get_sector_list(list_type=list_type)


def get_stock_list_in_sector(block_code, block_type=0, list_type=1):
    """获取板块成分股列表。"""
    return tq.get_stock_list_in_sector(
        block_code=block_code,
        block_type=block_type,
        list_type=list_type,
    )
```

公式类接口：

```python
def formula_process_mul_zb(
    formula_name,
    stock_list,
    formula_arg="",
    stock_period="1d",
    count=150,
    xsflag=-1,
    return_count=None,
    return_date=True,
):
    """批量调用通达信技术指标公式。

    Args:
        formula_name: 公式名称，例如 MACD、KDJ、RSI。
        stock_list: 通达信格式股票代码列表，例如 ["000001.SZ", "600519.SH"]。
        formula_arg: 公式参数，例如 MACD 的 "12,26,9"。
        stock_period: K 线周期，默认日线 "1d"。
        count: 每只股票参与计算的 K 线数量。
        xsflag: 通达信公式接口参数，默认沿用旧逻辑 -1。
        return_count: 返回的结果数量；默认与 count 一致。
        return_date: 是否返回日期。

    Returns:
        通达信公式接口原始返回结果。
    """
    if return_count is None:
        return_count = count

    return tq.formula_process_mul_zb(
        formula_name=formula_name,
        formula_arg=formula_arg,
        xsflag=xsflag,
        return_count=return_count,
        return_date=return_date,
        stock_list=stock_list,
        stock_period=stock_period,
        count=count,
        dividend_type=1,
    )
```

第一版不在 `data.py` 中做分批、不合并批次结果、不解释某个公式的输出线含义。

## `data.py` 自测入口代码写法草案

`data.py` 文件末尾可以带一个自测入口，只用于验证本模块接口，不承载正式业务判断。

```python
"""
Cassa 数据接口模块。

第一阶段接入通达信 tqcenter 的行情类和板块类接口，并提供模块自测入口。
"""

import argparse
import json
from pathlib import Path

from tqcenter import tq


def print_json(value):
    """把接口返回结果按 JSON 打印。"""
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def main():
    """自测 data.py 中的通达信接口。"""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    get_market_snapshot_parser = subparsers.add_parser("get_market_snapshot")
    get_market_snapshot_parser.add_argument("--code", required=True)

    stock_info_parser = subparsers.add_parser("get_stock_info")
    stock_info_parser.add_argument("--code", required=True)

    more_info_parser = subparsers.add_parser("get_more_info")
    more_info_parser.add_argument("--code", required=True)

    relation_parser = subparsers.add_parser("get_relation")
    relation_parser.add_argument("--code", required=True)

    sector_list_parser = subparsers.add_parser("get_sector_list")
    sector_list_parser.add_argument("--list-type", type=int, default=1)

    stock_list_parser = subparsers.add_parser("get_stock_list")

    stock_list_in_sector_parser = subparsers.add_parser("get_stock_list_in_sector")
    stock_list_in_sector_parser.add_argument("--block-code", required=True)
    stock_list_in_sector_parser.add_argument("--block-type", type=int, default=0)
    stock_list_in_sector_parser.add_argument("--list-type", type=int, default=1)

    args = parser.parse_args()

    initialize(Path(__file__))

    if args.command == "get_market_snapshot":
        print_json(get_market_snapshot(args.code))
    elif args.command == "get_stock_info":
        print_json(get_stock_info(args.code))
    elif args.command == "get_more_info":
        print_json(get_more_info(args.code))
    elif args.command == "get_relation":
        print_json(get_relation(args.code))
    elif args.command == "get_sector_list":
        print_json(get_sector_list(args.list_type))
    elif args.command == "get_stock_list":
        print_json(get_stock_list())
    elif args.command == "get_stock_list_in_sector":
        print_json(
            get_stock_list_in_sector(
                block_code=args.block_code,
                block_type=args.block_type,
                list_type=args.list_type,
            )
        )


if __name__ == "__main__":
    main()
```

后续可以再补 `market-data` 命令，但第一版也可以先从快照、基础信息、板块列表等低成本接口验证开始。

## 验证命令草案

```powershell
python data.py get_market_snapshot --code 000001.SZ
python data.py get_stock_info --code 000001.SZ
python data.py get_more_info --code 000001.SZ
python data.py get_relation --code 000001.SZ
python data.py get_sector_list
python data.py get_stock_list
python data.py get_stock_list_in_sector --block-code CASSA --block-type 1
```

注意：

1. 这些命令需要本机通达信客户端和 `tqcenter` 正常可用。
2. 第一版不自动把纯数字代码转成带市场后缀代码，因此验证时优先输入 `000001.SZ`、`600519.SH` 这种通达信格式。
3. `get_stock_list` 可能返回全市场大量数据，验证时如果输出过大，后续应在 `main.py` 增加 `--limit` 或摘要打印；但 `data.py` 仍应保留原始返回。

## 与旧 `cassa.py` 的关系

旧 `cassa.py` 当前已经封装了 `TdxClient`，其中包含更多接口和旧业务调用逻辑。

本阶段新 `data.py` 不直接复用旧 `TdxClient`。

原因：

1. 这次目标是重新确立数据接口模块的最小形态。
2. 旧 `TdxClient` 混合了静默调用、代码对象、公式引擎和业务调用习惯。
3. 新模块先保持透明、普通、可验证。

等 `data.py` 验证稳定后，再决定是否让旧业务逐步迁移到新入口，或者进一步拆出代码规范化、SQLite、本地股票池等模块。

## 暂不做内容

本阶段暂不做：

1. 不改 `cassa.py`。
2. 不接 screener 策略逻辑。
3. 不实现 SQLite 读取。
4. 不实现公式引擎接口。
5. 不实现股票代码自动规范化。
6. 不实现业务数据中心类。
7. 不做缓存、重试、静默输出、统一错误包装。
8. 不提交代码，除非用户明确要求。

## 后续方向

下一步如果用户确认，可以在 `feat/data-center-split` 分支上新增：

```text
data.py
```

然后按最小验证命令逐个确认行情类与板块类接口可用。

接口可用后，再考虑第二阶段：

1. 是否补 `get_market_data` 的 CLI 验证入口。
2. 是否引入股票代码规范化函数。
3. 是否接入本地 SQLite 数据源。
4. 是否把 `data.py` 从“通达信接口模块”扩展成真正的数据中心。
5. 是否逐步迁移旧 `cassa.py` 的调用方。
6. 是否新增 `main.py` 作为正式业务入口，并让 `data.py` 回归纯数据接口模块。

## 来源会话

来源：2026-07-09 当前会话。
