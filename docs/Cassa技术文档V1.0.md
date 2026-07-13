# Cassa 技术文档 V1.0

> 生成日期：2026-07-13  
> 覆盖脚本：`data.py`、`screen.py`、`business.py`

---

## 目录

- [一、数据中心](#一数据中心)
  - [1.1 更新本地日线数据库](#11-更新本地日线数据库)
  - [1.2 按截止交易日读取本地日K](#12-按截止交易日读取本地日k)
  - [1.3 归档全部A股和全部板块的当前快照](#13-归档全部a股和全部板块的当前快照)
- [二、选股](#二选股)
  - [2.1 放量突破选股策略](#21-放量突破选股策略)
- [三、业务](#三业务)
  - [3.1 数据报告](#31-数据报告)

---

## 一、数据中心

> 源文件：`data.py`  
> 依赖：通达信 `tqcenter`（`from tqcenter import tq`）  
> 本地存储：SQLite（`data/cassa.db`）

### 1.1 更新本地日线数据库

#### 功能描述

收盘后将全部 A 股最近 N 天的前复权日 K 线数据批量拉取，写入本地 SQLite 数据库 `data/cassa.db`。已存在的 `(code, trade_date)` 组合会被覆盖更新。支持分批拉取，避免单次请求过大。

**命令行**：`python data.py update-daily-kline --count 30 --batch-size 500`

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--count` | 30 | 每只股票拉取最近多少天日K |
| `--batch-size` | 500 | 每批处理多少只股票 |

#### 业务流程

```
python data.py update-daily-kline
  │
  └─ update_daily_kline_after_close(count, batch_size)
       │
       ├─ get_stock_list()                           # 获取全市场股票列表
       ├─ extract_stock_codes_from_stock_list()      # 提取纯代码
       ├─ chunk_list(stock_list, batch_size)          # 分批
       │
       └─ 对每一批:
            ├─ get_market_data()                     # 通通达信拉日K
            ├─ market_data_to_daily_kline_rows()     # 转换为数据库行格式
            └─ upsert_daily_kline_rows()             # upsert 到 SQLite
```

#### 代码实现

##### 新增函数: `ensure_database()`

初始化 `data/cassa.db` 和 `daily_kline` 表。

```python
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
```

##### 新增函数: `upsert_daily_kline_rows(rows)`

把日 K 行列表写入数据库，`(code, trade_date)` 冲突时覆盖更新。

```python
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
```

##### 新增函数: `update_daily_kline_after_close(count, batch_size)`

收盘后全量更新入口。获取全市场股票列表 → 分批拉取日K → upsert 到数据库。

```python
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

##### 新增函数: `market_data_to_daily_kline_rows(market_data, stock_list)`

把通达信 `get_market_data` 返回的 DataFrame 结构转换为 `daily_kline` 表的行格式。

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

##### 新增函数: `chunk_list(items, chunk_size)`

通用分批工具。

```python
def chunk_list(items, chunk_size):
    """把列表按固定大小切成多批。"""
    chunks = []
    for start in range(0, len(items), chunk_size):
        chunks.append(items[start:start + chunk_size])
    return chunks
```

##### 新增函数: `extract_stock_codes_from_stock_list(stock_rows)`

从通达信 `get_stock_list` 返回结果中提取股票代码列表。

```python
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
```

##### 新增函数: `get_market_data(stock_list, period, count, ...)`

底层通达信 K 线数据获取。

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
```

##### 新增函数: `get_stock_list()`

获取全市场股票列表。

```python
```

---

### 1.2 按截止交易日读取本地日K

#### 功能描述

从本地 SQLite 数据库中按截止交易日读取指定股票的日 K 线数据。支持截止日期过滤和数量限制。盘中有特殊处理：自动从通达信拉取最新一根 K 线合并到数据库结果中（不写库）。

**命令行**：`python data.py load-daily-kline --code 000001.SZ --count 120 --end-date 2026-07-11`

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--code` | 必填 | 通达信格式股票代码 |
| `--count` | 120 | 返回最近多少根日K |
| `--end-date` | 无限制 | 截止交易日 YYYY-MM-DD |

#### 业务流程

```
python data.py load-daily-kline --code 000001.SZ
  │
  └─ load_daily_kline(stock_list, count, end_date)     # 对外接口
       │
       └─ load_daily_kline_rows_from_db(code_list, count, end_date)
            │
            ├─ ensure_database()                        # 确保表存在
            ├─ chunk_list(code_list, 900)               # SQLite IN 子句分批（≤900参数）
            ├─ SELECT ... FROM daily_kline WHERE ...    # 按截止日+数量查询
            └─ 按代码分组，K线升序，截取最近 count 根

盘中使用 load_breakout_kline() 时会额外:
  ├─ load_realtime_daily_kline()      # 通通达信拉最新1根日K
  └─ 数据库中最后一天与实时K合并       # 替换同日或追加新日
```

#### 代码实现

##### 新增函数: `load_daily_kline(stock_list, count, end_date)`

对外接口，封装底层数据库读取。

```python
def load_daily_kline(stock_list, count=120, end_date=None):
    """按截止交易日从本地数据库读取日 K。

    Args:
        stock_list: 带后缀通达信股票代码列表。
        count: 每只股票返回最近多少根 K 线，默认 120。
        end_date: 最后一根 K 线的交易日，格式 YYYY-MM-DD。返回结果包含
            该日期对应的 K 线（如果数据库中存在）。

    Returns:
        按股票代码分组的日 K 字典，K 线按交易日升序排列。
    """
    return load_daily_kline_rows_from_db(
        code_list=stock_list,
        count=count,
        end_date=end_date,
    )
```

##### 新增函数: `load_daily_kline_rows_from_db(code_list, count, end_date)`

核心查询函数。只从本地 SQLite 读取，不调用通达信。SQLite 的 IN 子句参数上限为 999，故每批最多 900 个代码。

```python
def load_daily_kline_rows_from_db(code_list, count=None, end_date=None):
    """只从本地数据库读取日 K，不调用通达信。

    Args:
        code_list: 带后缀通达信股票代码列表。
        count: 每只股票最多返回多少根 K 线；None 表示返回全部。
        end_date: 截止交易日，格式 YYYY-MM-DD；返回 `trade_date <= end_date`
            的 K 线，并在每只股票内保留最近 `count` 根。

    Returns:
        按股票代码分组的日 K 字典，K 线按交易日升序排列。
    """
    if not code_list:
        return {}

    conn = ensure_database()
    rows = []
    try:
        for code_batch in chunk_list(code_list, 900):
            placeholders = ",".join(["?"] * len(code_batch))
            sql = (
                f"""
                SELECT code, trade_date, open_price, high_price, low_price,
                       close_price, volume, amount
                FROM daily_kline
                WHERE code IN ({placeholders})
                """
            )
            params = list(code_batch)
            if end_date:
                sql += " AND trade_date <= ?"
                params.append(str(end_date).strip())
            sql += " ORDER BY code, trade_date ASC"
            rows.extend(conn.execute(sql, params).fetchall())
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

##### 新增函数: `daily_kline_rows_to_map(rows)`

把日 K 行列表整理成按股票代码分组的字典，每组内按交易日升序排列。

```python
def daily_kline_rows_to_map(rows):
    """把日 K 行列表整理成按股票代码分组的字典。"""
    kline_map = {}
    for row in rows:
        stock_code = row["code"]
        if stock_code not in kline_map:
            kline_map[stock_code] = []
        kline_map[stock_code].append(row)

    for stock_code in kline_map:
        kline_map[stock_code].sort(key=lambda item: item["trade_date"])

    return kline_map
```

##### 新增函数: `load_realtime_daily_kline(stock_list, batch_size)`

通过通达信读取每只股票最新 1 根日 K，用于盘中临时覆盖或追加。

```python
def load_realtime_daily_kline(stock_list, batch_size=BREAKOUT_KLINE_BATCH_SIZE):
    """通过通达信读取最新日 K，用于盘中临时覆盖或追加。"""
    result = {}

    for stock_batch in chunk_list(stock_list, batch_size):
        market_data = get_market_data(
            stock_list=stock_batch,
            period="1d",
            count=1,
            field_list=["Open", "High", "Low", "Close", "Volume", "Amount"],
            fill_data=True,
        )
        rows = market_data_to_daily_kline_rows(market_data, stock_batch)
        result.update(daily_kline_rows_to_map(rows))

    return result
```

##### 新增函数: `merge_realtime_kline_rows(db_rows, realtime_rows)`

把通达信最新日 K 合并到数据库日 K 的返回副本中（不写数据库）。同日替换，新日追加。

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
```

##### 新增函数: `load_breakout_kline(stock_list, box_days, breakout_date, extra_days, batch_size)`

选股专用 K 线加载器。默认返回 `box_days + 1` 根 K 线。盘中自动拉取实时 K 线合并。

```python
def load_breakout_kline(
    stock_list,
    box_days=20,
    breakout_date="",
    extra_days=0,
    batch_size=BREAKOUT_KLINE_BATCH_SIZE,
):
    """读取放量突破选股所需 K 线。

    默认返回每只股票 box_days + 1 根 K 线；extra_days 用于需要
    突破后继续观察的策略，例如突破后回踩 MA5。
    """
    today = datetime.now().strftime("%Y-%m-%d")
    target_date = breakout_date or today
    intraday = target_date == today and is_a_share_intraday()
    mode_text = "盘中" if intraday else "非盘中"
    count = int(box_days) + 1 + int(extra_days)

    print(f"[数据] 突破日期：{target_date}")
    print(f"[数据] 当前模式：{mode_text}")

    db_kline_map = load_daily_kline(
        stock_list=stock_list,
        count=count,
        end_date=target_date,
    )
    print_trade_date_distribution(
        "本地K线最后日期分布：",
        get_latest_trade_date_distribution(db_kline_map, stock_list),
    )

    if not intraday:
        return db_kline_map

    realtime_kline_map = load_realtime_daily_kline(
        stock_list=stock_list,
        batch_size=batch_size,
    )
    print_trade_date_distribution(
        "实时K线日期分布：",
        get_latest_trade_date_distribution(realtime_kline_map, stock_list),
    )

    result = {}
    replaced_count = 0
    appended_count = 0
    missing_realtime_count = 0

    for stock_code in stock_list:
        db_rows = [dict(row) for row in db_kline_map.get(stock_code, [])]
        realtime_rows = realtime_kline_map.get(stock_code, [])

        if not realtime_rows:
            missing_realtime_count += 1
            result[stock_code] = db_rows[-count:]
            continue

        realtime_row = dict(realtime_rows[-1])
        if db_rows and db_rows[-1]["trade_date"] == realtime_row["trade_date"]:
            db_rows[-1] = realtime_row
            replaced_count += 1
        else:
            db_rows.append(realtime_row)
            appended_count += 1

        result[stock_code] = db_rows[-count:]

    print(
        f"[数据] 盘中合并完成：替换 {replaced_count}只，"
        f"追加 {appended_count}只，无实时K {missing_realtime_count}只"
    )
    print_trade_date_distribution(
        "合并后K线最后日期分布：",
        get_latest_trade_date_distribution(result, stock_list),
    )

    return result
```

##### 新增函数: `is_a_share_intraday(now)`

判断当前是否为 A 股盘中交易时段（午间 11:30-13:00 不算盘中）。

```python
def is_a_share_intraday(now=None):
    """判断当前是否为 A 股盘中；午间不算盘中。"""
    current = now or datetime.now()
    if current.weekday() >= 5:
        return False

    minutes = current.hour * 60 + current.minute
    morning_open = 9 * 60 + 30
    morning_close = 11 * 60 + 30
    afternoon_open = 13 * 60
    afternoon_close = 15 * 60

    return (
        morning_open <= minutes <= morning_close
        or afternoon_open <= minutes <= afternoon_close
    )
```

##### 新增函数: `get_latest_trade_date_distribution(kline_map, stock_list)`

统计每只股票最后一根 K 线的日期分布。

```python
def get_latest_trade_date_distribution(kline_map, stock_list):
    """统计每只股票最后一根 K 线日期分布。"""
    distribution = {}
    for stock_code in stock_list:
        rows = kline_map.get(stock_code, [])
        latest_date = rows[-1]["trade_date"] if rows else "无数据"
        distribution[latest_date] = distribution.get(latest_date, 0) + 1
    return distribution
```

##### 新增函数: `print_trade_date_distribution(title, distribution)`

打印 K 线最后日期分布。

```python
def print_trade_date_distribution(title, distribution):
    """打印 K 线最后日期分布。"""
    print(f"[数据] {title}")
    for trade_date in sorted(distribution):
        print(f"[数据]   {trade_date}: {distribution[trade_date]}只")
```

---

### 1.3 归档全部A股和全部板块的当前快照

#### 功能描述

一次性将全部 A 股个股和全部板块的当前快照数据归档到本地 JSONL 文件。每个对象会依次调用三个通达信接口：`get_market_snapshot`（实时行情）、`get_stock_info`（基础信息）、`get_more_info`（扩展信息），结果按日期分目录存储。使用临时文件 + 原子替换保证数据一致性。

**命令行**：`python data.py archive-snapshot --progress-interval 500`

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--progress-interval` | 500 | 每处理多少个对象打印一次进度 |

**输出结构**：
```
data/snapshots/{YYYY-MM-DD}/
  ├── stocks/
  │   ├── market_snapshot.jsonl
  │   ├── stock_info.jsonl
  │   ├── more_info.jsonl
  │   └── error.jsonl
  └── sectors/
      ├── market_snapshot.jsonl
      ├── stock_info.jsonl
      ├── more_info.jsonl
      └── error.jsonl
```

#### 业务流程

```
python data.py archive-snapshot
  │
  └─ archive_snapshot(progress_interval)
       │
       ├─ get_stock_archive_items()               # 获取全A股代码+名称
       ├─ archive_snapshot_group(stock_items, ...) # 归档个股
       │    └─ 对每只股票:
       │         ├─ get_market_snapshot(code)      # 实时行情快照
       │         ├─ get_stock_info(code)            # 基础信息
       │         ├─ get_more_info(code)             # 扩展信息
       │         └─ write_jsonl_line() 写入临时文件
       │         → replace_tmp_file() 原子替换正式文件
       │
       ├─ get_sector_archive_items()               # 获取全板块代码+名称
       └─ archive_snapshot_group(sector_items, ...) # 归档板块
            └─ 同上
```

#### 代码实现

##### 新增函数: `archive_snapshot(progress_interval)`

总入口。先归档全部 A 股个股，再归档全部板块。

```python
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

##### 新增函数: `archive_snapshot_group(items, item_type, output_dir, archive_date, progress_interval)`

对一组对象（股票或板块）依次调用三个快照接口，每个接口输出一个 JSONL 文件。使用临时文件 + 原子替换保证数据一致性。

```python
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
```

##### 新增函数: `get_stock_archive_items()`

从通达信获取全部 A 股列表，提取代码和名称。

```python
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
```

##### 新增函数: `get_sector_archive_items()`

从通达信获取全部板块列表，提取代码和名称。

```python
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
```

##### 新增函数: `write_jsonl_line(file_obj, value)`

写入一行 JSONL。

```python
def write_jsonl_line(file_obj, value):
    """写入一行 JSONL。"""
    file_obj.write(json.dumps(value, ensure_ascii=False, default=str))
    file_obj.write("\n")
```

##### 新增函数: `replace_tmp_file(tmp_path, final_path)`

用临时文件原子覆盖正式文件。

```python
def replace_tmp_file(tmp_path, final_path):
    """用临时文件覆盖正式文件。"""
    if final_path.exists():
        final_path.unlink()
    tmp_path.rename(final_path)
```

---

## 二、选股

> 源文件：`screen.py`  
> 依赖：`data` 模块（`import data`，用于 K 线加载和股票列表获取）

### 2.1 放量突破选股策略

#### 功能描述

从全部 A 股中筛选出"放量突破箱体"的股票。核心逻辑分两层：先用增强版箱体规则判断前 N 根 K 线是否构成横盘箱体，再判断最后一根 K 线是否以放量（≥ 箱体均量 × 倍数）突破箱体上沿。

**命令行**：`python screen.py scan-breakout --box-days 20 --range-max 0.30 --volume-ratio-min 1.5`

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--box-days` | 20 | 箱体区间的K线根数 |
| `--breakout-date` | 最新K线 | 突破K的交易日 YYYY-MM-DD |
| `--range-max` | 0.30 | 箱体振幅上限（如0.30=30%） |
| `--volume-ratio-min` | 1.5 | 放量倍数下限（突破量 ≥ 箱体均量 × 1.5） |
| `--batch-size` | 500 | 每批拉取股票K线数 |
| `--debug` | false | 输出完整JSON调试信息 |

**增强版箱体判断（V2）五条件**：
1. 分位数振幅 ≤ `range_max`（90分位高 - 10分位低，减少极端影线干扰）
2. 顶部触边次数 ≥ 2（高点触及上沿附近）
3. 底部触边次数 ≥ 2（低点触及下沿附近）
4. 收盘价内部比例 ≥ 80%（收盘价在箱体内的比例）
5. 中轴漂移 ≤ 8%（前半段与后半段均价的偏离度）

#### 业务流程

```
python screen.py scan-breakout
  │
  └─ screen_volume_breakout(box_days, breakout_date, range_max, volume_ratio_min)
       │
       ├─ get_all_a_share_codes()                        # 获取全A股代码
       ├─ data.load_breakout_kline(stock_list, ...)      # 加载 K 线（box_days + 1 根）
       │
       ├─ [层1] filter_box_consolidation(...)             # 箱体区间筛选
       │    └─ 对每只股票: is_box_consolidation_v2()      # 增强版五条件判断
       │         └─ calculate_box_metrics_v2()            # 计算分位数上下沿/触边/内部比例/中轴漂移
       │              ├─ calculate_percentile()            # 分位数计算
       │              └─ calculate_average_close()         # 平均收盘价
       │
       └─ [层2] filter_volume_breakout(...)               # 放量突破筛选
            └─ 对每只股票: is_volume_breakout_from_box()   # 价穿箱体上沿 + 量 ≥ 均量 × 倍数
                 └─ analyze_volume_breakout_from_box()     # 输出详细判断结果

→ print_screen_result() 打印结果摘要
```

#### 代码实现

##### 新增函数: `screen_volume_breakout(box_days, breakout_date, range_max, volume_ratio_min, batch_size)`

选股主入口。从全 A 股出发，两层筛选：箱体区间筛选 → 放量突破筛选。

```python
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
```

##### 新增函数: `calculate_box_metrics(kline_bars)`

基础版箱体指标计算。取最高价和最低价作为上下沿。

```python
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
```

##### 新增函数: `calculate_percentile(values, percentile)`

分位数计算。用于增强版箱体指标，减少极端影线对上下沿的影响。

```python
def calculate_percentile(values, percentile):
    """计算分位数，percentile 取值 0 到 1。"""
    if not values:
        return 0.0

    sorted_values = sorted(float(value) for value in values)
    if len(sorted_values) == 1:
        return sorted_values[0]

    rank = float(percentile) * (len(sorted_values) - 1)
    lower_index = int(rank)
    upper_index = min(lower_index + 1, len(sorted_values) - 1)
    weight = rank - lower_index
    return (
        sorted_values[lower_index] * (1 - weight)
        + sorted_values[upper_index] * weight
    )
```

##### 新增函数: `calculate_average_close(kline_bars)`

计算一段 K 线的平均收盘价。

```python
def calculate_average_close(kline_bars):
    """计算一段 K 线的平均收盘价。"""
    if not kline_bars:
        return 0.0

    return (
        sum(float(bar["close_price"]) for bar in kline_bars)
        / len(kline_bars)
    )
```

##### 新增函数: `calculate_box_metrics_v2(kline_bars, top_quantile, bottom_quantile, edge_touch_ratio)`

增强版箱体指标。用分位数确定上下沿，同时计算触边次数、收盘价内部比例和中轴漂移。

```python
def calculate_box_metrics_v2(
    kline_bars,
    top_quantile=DEFAULT_BOX_V2_TOP_QUANTILE,
    bottom_quantile=DEFAULT_BOX_V2_BOTTOM_QUANTILE,
    edge_touch_ratio=DEFAULT_BOX_V2_EDGE_TOUCH_RATIO,
):
    """计算增强版箱体指标，减少极端影线对上下沿的影响。"""
    if not kline_bars:
        return {
            "bar_count": 0,
            "top_price": 0.0,
            "bottom_price": 0.0,
            "range_pct": 0.0,
            "average_volume": 0.0,
            "top_touch_count": 0,
            "bottom_touch_count": 0,
            "inside_close_count": 0,
            "inside_close_ratio": 0.0,
            "mid_drift_pct": 0.0,
        }

    high_prices = [float(bar["high_price"]) for bar in kline_bars]
    low_prices = [float(bar["low_price"]) for bar in kline_bars]
    close_prices = [float(bar["close_price"]) for bar in kline_bars]
    average_volume = sum(float(bar["volume"]) for bar in kline_bars) / len(kline_bars)

    top_price = calculate_percentile(high_prices, top_quantile)
    bottom_price = calculate_percentile(low_prices, bottom_quantile)
    range_pct = ((top_price - bottom_price) / bottom_price) if bottom_price > 0 else 0.0

    top_touch_line = top_price * (1 - float(edge_touch_ratio))
    bottom_touch_line = bottom_price * (1 + float(edge_touch_ratio))
    top_touch_count = sum(1 for price in high_prices if price >= top_touch_line)
    bottom_touch_count = sum(1 for price in low_prices if price <= bottom_touch_line)
    inside_close_count = sum(
        1
        for price in close_prices
        if bottom_price <= price <= top_price
    )
    inside_close_ratio = inside_close_count / len(kline_bars)

    middle_index = len(kline_bars) // 2
    first_half = kline_bars[:middle_index]
    second_half = kline_bars[middle_index:]
    first_average_close = calculate_average_close(first_half)
    second_average_close = calculate_average_close(second_half)
    mid_drift_pct = (
        abs(second_average_close - first_average_close) / first_average_close
        if first_average_close > 0
        else 0.0
    )

    return {
        "bar_count": len(kline_bars),
        "top_price": round(top_price, 4),
        "bottom_price": round(bottom_price, 4),
        "range_pct": round(range_pct, 6),
        "average_volume": round(average_volume, 4),
        "top_touch_count": top_touch_count,
        "bottom_touch_count": bottom_touch_count,
        "inside_close_count": inside_close_count,
        "inside_close_ratio": round(inside_close_ratio, 6),
        "mid_drift_pct": round(mid_drift_pct, 6),
    }
```

##### 新增函数: `is_box_consolidation(kline_bars, range_max)`

基础版箱体判断。仅用振幅一个条件。

```python
def is_box_consolidation(kline_bars, range_max=DEFAULT_BOX_RANGE_MAX):
    """判断一段 K 线是否是箱体。"""
    if len(kline_bars) < 2:
        return False

    metrics = calculate_box_metrics(kline_bars)
    return metrics["range_pct"] <= float(range_max)
```

##### 新增函数: `is_box_consolidation_v2(...)`

增强版箱体判断。五个条件综合判断：振幅、顶部触边、底部触边、收盘内部比例、中轴漂移。

```python
def is_box_consolidation_v2(
    kline_bars,
    range_max=DEFAULT_BOX_RANGE_MAX,
    top_quantile=DEFAULT_BOX_V2_TOP_QUANTILE,
    bottom_quantile=DEFAULT_BOX_V2_BOTTOM_QUANTILE,
    edge_touch_ratio=DEFAULT_BOX_V2_EDGE_TOUCH_RATIO,
    min_top_touches=DEFAULT_BOX_V2_MIN_TOP_TOUCHES,
    min_bottom_touches=DEFAULT_BOX_V2_MIN_BOTTOM_TOUCHES,
    inside_ratio_min=DEFAULT_BOX_V2_INSIDE_RATIO_MIN,
    mid_drift_max=DEFAULT_BOX_V2_MID_DRIFT_MAX,
):
    """增强版箱体判断：振幅、触边、内部比例和中轴漂移共同判断。"""
    if len(kline_bars) < 2:
        return False

    metrics = calculate_box_metrics_v2(
        kline_bars=kline_bars,
        top_quantile=top_quantile,
        bottom_quantile=bottom_quantile,
        edge_touch_ratio=edge_touch_ratio,
    )

    return (
        metrics["range_pct"] <= float(range_max)
        and metrics["top_touch_count"] >= int(min_top_touches)
        and metrics["bottom_touch_count"] >= int(min_bottom_touches)
        and metrics["inside_close_ratio"] >= float(inside_ratio_min)
        and metrics["mid_drift_pct"] <= float(mid_drift_max)
    )
```

##### 新增函数: `is_volume_breakout_from_box(box_kline_bars, breakout_kline, range_max, volume_ratio_min)`

判断最后一根 K 线是否放量突破前面箱体。两个条件：收盘价突破箱体上沿 + 成交量 ≥ 箱体均量 × 倍数。

```python
def is_volume_breakout_from_box(
    box_kline_bars,
    breakout_kline,
    range_max=DEFAULT_BOX_RANGE_MAX,
    volume_ratio_min=DEFAULT_VOLUME_RATIO_MIN,
):
    """判断第二个参数 K 线是否放量突破前面箱体。"""
    if not is_box_consolidation_v2(box_kline_bars, range_max=range_max):
        return False

    if not breakout_kline:
        return False

    metrics = calculate_box_metrics_v2(box_kline_bars)
    breakout_close = float(breakout_kline["close_price"])
    breakout_volume = float(breakout_kline["volume"])
    average_volume = float(metrics["average_volume"])

    if average_volume <= 0:
        return False

    is_price_breakout = breakout_close > float(metrics["top_price"])
    is_volume_breakout = breakout_volume >= average_volume * float(volume_ratio_min)
    return is_price_breakout and is_volume_breakout
```

##### 新增函数: `filter_box_consolidation(stock_codes, kline_map, box_days, range_max)`

从股票列表中筛出前 box_days 根 K 线处于箱体的股票。

```python
def filter_box_consolidation(stock_codes, kline_map, box_days, range_max=DEFAULT_BOX_RANGE_MAX):
    """从股票列表中筛出前 box_days 根 K 线处于箱体的股票。"""
    passed_codes = []
    for stock_code in stock_codes:
        kline_bars = kline_map.get(stock_code, [])
        if len(kline_bars) < box_days + 1:
            continue
        if is_box_consolidation_v2(kline_bars[:-1], range_max=range_max):
            passed_codes.append(stock_code)

    return passed_codes
```

##### 新增函数: `filter_volume_breakout(stock_codes, kline_map, box_days, range_max, volume_ratio_min)`

从箱体股票中筛出最后一根 K 线放量突破的股票。

```python
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
```

##### 新增函数: `get_all_a_share_codes()`

获取全部 A 股股票代码。

```python
def get_all_a_share_codes():
    """获取全部 A 股股票代码。"""
    stock_rows = data.get_stock_list()
    return data.extract_stock_codes_from_stock_list(stock_rows)
```

##### 新增函数: `run_layer(layer_name, input_codes, filter_func, layer_records)`

执行一层筛选并记录通过数量。用于多层级联筛选时的日志和统计。

```python
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
```

##### 新增函数: `print_screen_result(result, debug, code_limit)`

打印选股结果摘要。列表展示前 100 只入选代码，debug 模式追加完整 JSON。

```python
def print_screen_result(result, debug=False, code_limit=DEFAULT_CONSOLE_CODE_LIMIT):
    """打印选股结果摘要，debug 模式下追加完整 JSON。"""
    print("[结果] 策略：", result.get("strategy", ""))
    print(f"[结果] 初始股票数：{result.get('initial_count', 0)}")
    print(f"[结果] 入选股票数：{result.get('selected_count', 0)}")

    selected_codes = result.get("selected_codes", [])
    if selected_codes:
        print("[结果] 入选代码：")
        display_codes = selected_codes[:code_limit]
        for index, stock_code in enumerate(display_codes, start=1):
            print(f"[结果]   {index}. {stock_code}")
        if len(selected_codes) > code_limit:
            print(
                f"[结果]   ... 还有 {len(selected_codes) - code_limit} 只，"
                "使用 --debug 查看完整 JSON"
            )
    else:
        print("[结果] 本次没有筛出符合条件的股票")

    if debug:
        print("[DEBUG] 完整 JSON：")
        print_json(result)
```

---

## 三、业务

> 源文件：`business.py`  
> 依赖：`data` 模块、`py_mini_racer`（JS 引擎，用于筹码分布计算）、`pandas`

### 3.1 数据报告

#### 功能描述

对输入的股票或板块代码生成综合技术分析报告。自动识别输入是股票还是板块代码，采集实时行情、日K、MACD、筹码分布等数据，输出包括趋势状态、量能分析、支撑压力位、MACD/RSI 信号、综合评分和买入信号。

**命令行**：`python business.py report --codes 600519,000001,880675.SH`

| 参数 | 说明 |
|---|---|
| `--codes` | 股票/板块代码，逗号分隔 |
| `--debug` | 追加完整 JSON 调试数据 |

#### 业务流程

```
python business.py report --codes 600519,000001
  │
  └─ build_report_data(codes)
       │
       ├─ resolve_report_codes(codes)                   # 解析输入代码（个股/板块）
       │    ├─ get_sector_list()                         # 拉取板块列表建索引
       │    ├─ build_sector_lookup()                     # 按代码/名称建查找表
       │    └─ resolve_report_code()                     # 逐个判断股票 vs 板块
       │         ├─ normalize_stock_code()               # 个股补通达信后缀
       │         └─ infer_stock_market_suffix()          # 推断市场后缀
       │
       └─ 对每个目标 collect_report_item(target):
            │
            ├─ collect_realtime_report_data(code)        # 实时数据采集
            │    ├─ get_market_snapshot()                # 行情快照
            │    ├─ get_stock_info()                      # 基础信息
            │    ├─ get_more_info()                       # 扩展信息(换手率/量比/PE/PB/资金)
            │    └─ get_relation()                        # 行业+概念板块关系
            │
            ├─ collect_daily_kline_for_report(code)       # 120根历史日K
            │    └─ data.load_daily_kline()
            │
            ├─ collect_macd_for_report(code)              # MACD 数组
            │    └─ data.formula_process_mul_zb()
            │
            └─ collect_chip_for_report(item)              # 筹码分布
                 ├─ fetch_gb_history()                    # 历史股本
                 ├─ compute_daily_turnover_history()     # 历史换手率
                 └─ compute_chip_distribution()           # 筹码分布核心(JS引擎)
                      └─ build_cyq_kline_records()       # K线+换手率记录

→ render_console_report() → 格式化控制台输出
```

#### 代码实现

##### A. 入口与代码解析

##### 新增函数: `build_report_data(codes)`

顶层入口。解析输入代码 → 逐个采集数据 → 返回结构化数据包。

```python
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
```

##### 新增函数: `resolve_report_codes(codes)`

批量解析 report 输入 code。先拉取板块列表建索引，再逐个判断。

```python
def resolve_report_codes(codes):
    """批量解析 report 输入 code。"""
    sector_rows = data.get_sector_list(list_type=1)
    sector_lookup = build_sector_lookup(sector_rows)
    return [resolve_report_code(code, sector_lookup) for code in codes]
```

##### 新增函数: `resolve_report_code(code, sector_lookup)`

判断单个 code 是板块还是个股，返回统一目标结构。

```python
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
```

##### 新增函数: `build_sector_lookup(sector_rows)`

把通达信板块列表转换成便于按原始输入匹配的索引（支持按代码、纯代码、名称查找）。

```python
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
```

##### 新增函数: `normalize_stock_code(code)`

把用户输入的个股代码规整为带后缀的通达信代码（如 `600519` → `600519.SH`）。

```python
def normalize_stock_code(code):
    """把用户输入的个股代码规整为带后缀的通达信代码。"""
    normalized_code = str(code).strip().upper()
    if has_market_suffix(normalized_code):
        return normalized_code

    internal_code = strip_code_suffix(normalized_code)
    suffix = infer_stock_market_suffix(internal_code)
    return f"{internal_code}.{suffix}"
```

##### 新增函数: `infer_stock_market_suffix(internal_code)`

根据纯数字股票代码推断通达信市场后缀（SH/SZ/BJ）。

```python
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
```

##### 新增函数: `collect_report_item(target)`

采集单个 report 目标的结构化数据（实时数据 + 日K + MACD + 筹码）。

```python
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
```

##### B. 数据采集

##### 新增函数: `collect_realtime_report_data(code)`

采集 report 所需的实时数据：行情快照、基础信息、扩展信息、板块关系。

```python
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
```

##### 新增函数: `collect_daily_kline_for_report(code, history_count)`

采集 120 根历史日 K。

```python
def collect_daily_kline_for_report(code, history_count=REPORT_HISTORY_COUNT):
    """采集 120 根历史日 K。"""
    kline_by_code = data.load_daily_kline([code], count=history_count)
    return kline_by_code.get(code, [])
```

##### 新增函数: `collect_macd_for_report(code, count)`

采集 report 所需 MACD 数组，默认 121 根（120 历史 + 最新 1 根）。

```python
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
```

##### 新增函数: `convert_macd_result_to_array(raw_macd, code)`

把 formula_process_mul_zb 的 MACD 返回结果转换成数组。

```python
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
```

##### C. 趋势分析

##### 新增函数: `calculate_sma(values, period)`

计算简单移动平均线，长度与输入一致。不足 period 的位置填 0.0。

```python
def calculate_sma(values, period):
    """计算简单移动平均线，长度与输入一致。"""
    result = []
    for index in range(len(values)):
        if index + 1 < period:
            result.append(0.0)
        else:
            result.append(sum(values[index + 1 - period : index + 1]) / period)
    return result
```

##### 新增函数: `calculate_rsi(closes, period)`

计算 RSI 指标，使用 Wilder's EMA / SMMA 口径。

```python
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
```

##### 新增函数: `judge_trend_status(ma5, ma10, ma20)`

根据最新均线值判断趋势状态。七种状态：强势多头、多头排列、弱势多头、盘整、弱势空头、空头排列、强势空头。

```python
def judge_trend_status(ma5, ma10, ma20):
    """根据最新均线值判断趋势状态。"""
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
```

##### 新增函数: `calculate_bias(price, ma5, ma10, ma20)`

计算 MA5 / MA10 / MA20 乖离率。

```python
def calculate_bias(price, ma5, ma10, ma20):
    """计算 MA5 / MA10 / MA20 乖离率。"""
    bias_ma5 = (price - ma5) / ma5 * 100 if ma5 > 0 else 0.0
    bias_ma10 = (price - ma10) / ma10 * 100 if ma10 > 0 else 0.0
    bias_ma20 = (price - ma20) / ma20 * 100 if ma20 > 0 else 0.0
    return bias_ma5, bias_ma10, bias_ma20
```

##### D. 量能与支撑压力

##### 新增函数: `judge_volume_status(closes, volume_ratio)`

分析量能状态。五种状态：放量上涨、放量下跌、缩量上涨、缩量回调、量能正常。

```python
def judge_volume_status(closes, volume_ratio):
    """分析量能状态。"""
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
```

##### 新增函数: `judge_support_resistance(item, ma5, ma10, ma20, current_price)`

分析支撑压力位。MA5/MA10 接近时作为支撑，20日内最高价作为压力。

```python
def judge_support_resistance(item, ma5, ma10, ma20, current_price):
    """分析支撑压力位。"""
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
```

##### 新增函数: `judge_macd_status(item)`

判断 MACD 状态。七种状态：零轴上金叉、金叉、上穿零轴、多头、空头、下穿零轴、死叉。

```python
def judge_macd_status(item):
    """判断 MACD 状态。"""
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
```

##### 新增函数: `judge_rsi_status(rsi_6, rsi_12, rsi_24)`

判断 RSI 状态。以 RSI(12) 为主，五种状态：超买(>70)、强势(>60)、中性(40-60)、弱势(30-40)、超卖(<30)。

```python
def judge_rsi_status(rsi_6, rsi_12, rsi_24):
    """判断 RSI 状态，以 RSI(12) 为主。"""
    if rsi_12 > TREND_RSI_OVERBOUGHT:
        return "超买", f"RSI超买({rsi_12:.1f}>70)，短期回调风险高"
    if rsi_12 > 60:
        return "强势", f"RSI强势({rsi_12:.1f})，多头力量充足"
    if rsi_12 >= 40:
        return "中性", f"RSI中性({rsi_12:.1f})，震荡整理中"
    if rsi_12 >= TREND_RSI_OVERSOLD:
        return "弱势", f"RSI弱势({rsi_12:.1f})，关注反弹"
    return "超卖", f"RSI超卖({rsi_12:.1f}<30)，反弹机会大"
```

##### E. 综合评分与信号

##### 新增函数: `calculate_signal_score(...)`

综合评分。六个维度：趋势(0-30分) + 乖离(0-20分) + 量能(0-15分) + 支撑(0-10分) + MACD(0-15分) + RSI(0-10分)。

```python
def calculate_signal_score(
    trend_status, trend_strength, bias_ma5,
    volume_status, support_ma5, support_ma10,
    macd_status, macd_signal, rsi_status, rsi_signal,
):
    """综合评分，六个维度满分 100 分。"""
    score = 0
    reasons = []
    risks = []

    # 趋势维度 (0-30)
    trend_scores = {"强势多头": 30, "多头排列": 26, "弱势多头": 18, "盘整": 12, "弱势空头": 8, "空头排列": 4, "强势空头": 0}
    score += trend_scores.get(trend_status, 12)
    if trend_status in ("强势多头", "多头排列"):
        reasons.append(f"✅ {trend_status}，顺势做多")
    elif trend_status in ("空头排列", "强势空头"):
        risks.append(f"⚠️ {trend_status}，不宜做多")

    # 强势多头时放宽乖离容忍度
    is_strong_bull = trend_status == "强势多头" and trend_strength >= TREND_STRONG_BULL_STRENGTH_THRESHOLD
    effective_threshold = TREND_BIAS_THRESHOLD * TREND_STRONG_BULL_BIAS_RELAX if is_strong_bull else TREND_BIAS_THRESHOLD

    # 乖离维度 (0-20)
    if bias_ma5 < 0:
        if bias_ma5 > -3:
            score += 20; reasons.append(f"✅ 价格略低于MA5({bias_ma5:.1f}%)，回踩买点")
        elif bias_ma5 > -5:
            score += 16; reasons.append(f"✅ 价格回踩MA5({bias_ma5:.1f}%)，观察支撑")
        else:
            score += 8; risks.append(f"⚠️ 乖离率过大({bias_ma5:.1f}%)，可能破位")
    elif bias_ma5 < 2:
        score += 18; reasons.append(f"✅ 价格贴近MA5({bias_ma5:.1f}%)，介入好时机")
    elif bias_ma5 < effective_threshold:
        score += 14; reasons.append(f"⚡ 价格略高于MA5({bias_ma5:.1f}%)，可小仓介入")
    elif bias_ma5 > effective_threshold:
        score += 4; risks.append(f"❌ 乖离率过高({bias_ma5:.1f}%>{effective_threshold:.1f}%)，严禁追高")

    # 量能维度 (0-15)
    volume_scores = {"缩量回调": 15, "放量上涨": 12, "量能正常": 10, "缩量上涨": 6, "放量下跌": 0}
    score += volume_scores.get(volume_status, 8)
    if volume_status == "缩量回调":
        reasons.append("✅ 缩量回调，主力洗盘")
    elif volume_status == "放量下跌":
        risks.append("⚠️ 放量下跌，注意风险")

    # 支撑维度 (0-10)
    if support_ma5: score += 5; reasons.append("✅ MA5支撑有效")
    if support_ma10: score += 5; reasons.append("✅ MA10支撑有效")

    # MACD维度 (0-15)
    macd_scores = {"零轴上金叉": 15, "金叉": 12, "上穿零轴": 10, "多头": 8, "空头": 2, "下穿零轴": 0, "死叉": 0}
    score += macd_scores.get(macd_status, 5)
    if macd_status in ("零轴上金叉", "金叉"): reasons.append(f"✅ {macd_signal}")
    elif macd_status in ("死叉", "下穿零轴"): risks.append(f"⚠️ {macd_signal}")
    else: reasons.append(macd_signal)

    # RSI维度 (0-10)
    rsi_scores = {"超卖": 10, "强势": 8, "中性": 5, "弱势": 3, "超买": 0}
    score += rsi_scores.get(rsi_status, 5)
    if rsi_status in ("超卖", "强势"): reasons.append(f"✅ {rsi_signal}")
    elif rsi_status == "超买": risks.append(f"⚠️ {rsi_signal}")
    else: reasons.append(rsi_signal)

    return score, reasons, risks
```

##### 新增函数: `judge_buy_signal(score, trend_status)`

根据评分和趋势状态生成买入信号。

```python
def judge_buy_signal(score, trend_status):
    """根据评分和趋势状态生成买入信号。"""
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
```

##### 新增函数: `calculate_today_quote(item)`

从 market_snapshot 中计算当日行情。

```python
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
```

##### F. 筹码分布

##### 新增函数: `collect_chip_for_report(item)`

筹码分布计算入口。通过 data.py 补历史股本，计算换手率，调用 JS 引擎计算筹码分布。

```python
def collect_chip_for_report(item):
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
```

##### 新增函数: `compute_chip_distribution(daily_kline, daily_turnover_history, current_price)`

筹码分布核心计算。构建 K 线记录 → 调用 JS 引擎 `CYQCalculator` → 提取获利比例、平均成本、集中度。

```python
def compute_chip_distribution(daily_kline, daily_turnover_history, current_price):
    records = build_cyq_kline_records(daily_kline, daily_turnover_history)
    if len(records) < 30:
        return create_chip_unavailable("筹码分布暂无法计算：有效日线/换手率样本不足 30 条。")

    js_engine = MiniRacer()
    js_engine.eval(load_cyq_js_code())
    result = js_engine.call("CYQCalculator", len(records) - 1, records)

    price_now = safe_float(current_price, safe_float(records[-1].get("close")))
    profit_ratio = compute_profit_ratio_from_distribution(price_now, result.get("x", []), result.get("y", []))
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
        "concentration_90": round(float(concentration_90), 6) if concentration_90 is not None else None,
        "cost_70_low": safe_float(price_range_70[0]),
        "cost_70_high": safe_float(price_range_70[1]),
        "concentration_70": round(float(concentration_70), 6) if concentration_70 is not None else None,
        "chip_status": chip_status_from_concentration(concentration_90),
        "sample_count": len(records),
    }
```

##### 新增函数: `compute_daily_turnover_history(daily_kline, gb_history, current_float_capital, current_turnover_rate, snapshot_volume)`

计算历史日换手率。用历史股本变动记录 + 缩放系数推算每根日 K 的换手率。

```python
def compute_daily_turnover_history(daily_kline, gb_history, current_float_capital, current_turnover_rate, snapshot_volume):
    records = []
    for item in gb_history:
        effective_date = pick_effective_date(item)
        float_capital = pick_effective_float_capital(item)
        if effective_date and float_capital:
            records.append({"date": effective_date, "float_capital": float_capital})
    records.sort(key=lambda item: item["date"])

    fallback_float_capital = safe_float(current_float_capital)
    reference_float_capital = records[-1]["float_capital"] if records else fallback_float_capital
    scale = infer_turnover_scale(daily_kline, current_turnover_rate, reference_float_capital, snapshot_volume)

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

        history.append({
            "date": trade_date,
            "volume": round(float(volume), 4) if volume is not None else None,
            "float_capital": round(float(active_float_capital), 4) if active_float_capital is not None else None,
            "turnover_rate": turnover_rate,
        })

    return {"daily_turnover_history": history, "daily_turnover_meta": {"formula": "turnover_rate = volume / float_capital * scale", "scale": round(scale, 6), "gb_record_count": len(records), "fallback_float_capital": fallback_float_capital}}
```

##### G. 工具函数

##### 新增函数: `safe_float(value, default)`

安全转浮点数，处理 None / 空字符串 / NaN。

```python
def safe_float(value, default=None):
    try:
        if value is None or value == "": return default
        result = float(value)
        if pd.isna(result): return default
        return result
    except (TypeError, ValueError): return default
```

##### 新增函数: `get_kline_value(row, *keys)`

从不同命名风格的 K 线字典中读取数值。

```python
def get_kline_value(row, *keys):
    for key in keys:
        if key in row: return safe_float(row.get(key))
    return 0.0
```

##### 新增函数: `extract_close_values(item)` / `extract_high_low_values(item)`

从 daily_kline 中提取收盘价序列和高低点序列。

```python
def extract_close_values(item):
    values = [get_kline_value(row, "close_price", "Close", "close") for row in item.get("daily_kline") or []]
    return [value for value in values if value > 0]

def extract_high_low_values(item):
    rows = item.get("daily_kline") or []
    highs = [get_kline_value(row, "high_price", "High", "high") for row in rows]
    lows = [get_kline_value(row, "low_price", "Low", "low") for row in rows]
    return [value for value in highs if value > 0], [value for value in lows if value > 0]
```

##### 新增函数: `has_market_suffix(code)` / `strip_code_suffix(code)`

判断 code 是否已带通达信市场后缀 / 去掉后缀。

```python
def has_market_suffix(code):
    normalized_code = str(code).strip().upper()
    if "." not in normalized_code: return False
    _, suffix = normalized_code.rsplit(".", maxsplit=1)
    return suffix in MARKET_SUFFIXES

def strip_code_suffix(code):
    normalized_code = str(code).strip().upper()
    if "." in normalized_code: return normalized_code.split(".", maxsplit=1)[0]
    return normalized_code
```

##### 新增函数: `format_report_item(item)` / `render_console_report(payload)`

格式化单个 report item 为控制台文本 / 渲染完整报告。

```python
def format_report_item(item):
    """格式化单个 report item 控制台输出。"""
    relation = item.get("relation") or []
    industry, concepts = extract_industry_and_concepts(relation)
    today = calculate_today_quote(item)
    display_price = safe_float(today.get("current_price"), 0.0)
    calc_price = get_latest_kline_close(item, default=display_price)
    closes = extract_close_values(item)
    ma5_series = calculate_sma(closes, 5)
    ma10_series = calculate_sma(closes, 10)
    ma20_series = calculate_sma(closes, 20)

    ma5 = ma5_series[-1] if ma5_series else 0.0
    ma10 = ma10_series[-1] if ma10_series else 0.0
    ma20 = ma20_series[-1] if ma20_series else 0.0
    bias_ma5, bias_ma10, bias_ma20 = calculate_bias(calc_price, ma5, ma10, ma20)
    trend_status, ma_alignment, trend_strength = judge_trend_status(ma5_series, ma10_series, ma20_series)

    more_info = item.get("more_info") or {}
    volume_ratio = safe_float(more_info.get("fLianB"))
    turnover_rate = safe_float(more_info.get("fHSL"))
    volume_status, volume_ratio, volume_trend = judge_volume_status(closes, volume_ratio)

    support_ma5, support_ma10, support_levels, resistance_levels = judge_support_resistance(item, ma5, ma10, ma20, calc_price)
    macd_dif, macd_dea, macd_bar, macd_status, macd_signal = judge_macd_status(item)

    rsi_6_series = calculate_rsi(closes, 6)
    rsi_12_series = calculate_rsi(closes, 12)
    rsi_24_series = calculate_rsi(closes, 24)
    rsi_6 = rsi_6_series[-1] if rsi_6_series else 50.0
    rsi_12 = rsi_12_series[-1] if rsi_12_series else 50.0
    rsi_24 = rsi_24_series[-1] if rsi_24_series else 50.0
    rsi_status, rsi_signal = judge_rsi_status(rsi_6, rsi_12, rsi_24)

    signal_score, signal_reasons, risk_factors = calculate_signal_score(
        trend_status, trend_strength, bias_ma5, volume_status, support_ma5, support_ma10,
        macd_status, macd_signal, rsi_status, rsi_signal,
    )
    buy_signal = judge_buy_signal(signal_score, trend_status)

    total_shares = safe_float(item.get("stock_info", {}).get("J_zgb"))
    market_cap = total_shares * calc_price / 10000 if total_shares > 0 and calc_price > 0 else 0.0

    lines = [f"=== {strip_code_suffix(item.get('code', ''))} {item.get('name', '')} ===".rstrip()]
    if industry: lines.append(f"行业: {industry}    概念: {'、'.join(concepts)}" if concepts else f"行业: {industry}")
    lines.append(f"当日: 开{today['today_open']:.2f} 高{today['today_high']:.2f} 低{today['today_low']:.2f} 收{today['current_price']:.2f} {today['price_change_pct']:+.2f}% 振幅{today['amplitude']:.2f}%")
    lines.append(f"趋势: {trend_status} ({trend_strength:.0f}/100)    信号: {buy_signal} ({signal_score}分)")
    lines.append(f"现价: {display_price:.2f}  MA5: {ma5:.2f}({bias_ma5:+.1f}%)  MA10: {ma10:.2f}({bias_ma10:+.1f}%)  MA20: {ma20:.2f}({bias_ma20:+.1f}%)")
    turnover_text = f"  换手: {turnover_rate:.1f}%" if turnover_rate > 0 else ""
    lines.append(f"量能: {volume_status} ({volume_ratio:.2f})      MACD: {macd_status}    RSI: {rsi_status}({rsi_12:.0f}){turnover_text}")
    if market_cap > 0: lines.append(f"基本面: 总市值{market_cap:.1f}亿")
    net_buy = safe_float(more_info.get("Zjl")); main_net = safe_float(more_info.get("Zjl_HB"))
    if net_buy != 0 or main_net != 0: lines.append(f"资金: 主买净额{net_buy:.0f}万  主力净流入{main_net:.0f}万")
    lines.append(format_chip_line(item.get("chip")))
    support_text = ", ".join(f"{value:.2f}" for value in support_levels) if support_levels else "无"
    resistance_text = ", ".join(f"{value:.2f}" for value in resistance_levels) if resistance_levels else "无"
    lines.append(f"支撑: {support_text}  压力: {resistance_text}")
    if signal_reasons: lines.append(f"理由: {'  '.join(signal_reasons)}")
    if risk_factors: lines.append(f"风险: {'  '.join(risk_factors)}")
    return "\n".join(lines)

def render_console_report(payload):
    items = payload.get("items") or []
    lines = [f"个股趋势报告：{len(items)} 只股票", ""]
    for index, item in enumerate(items):
        lines.append(format_report_item(item))
        if index < len(items) - 1: lines.append("")
    errors = payload.get("errors") or []
    if errors:
        lines.append(""); lines.append(f"跳过 {len(errors)} 只:")
        for error in errors: lines.append(f"  - {error.get('raw_code', '') or error.get('code', '')}: {error.get('error', '')}")
    return "\n".join(lines)
```