"""
Cassa 数据接口模块。

第一阶段接入通达信 tqcenter 的行情类和板块类接口，并提供模块自测入口。
"""

import argparse
import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from tqcenter import tq


PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "cassa.db"
DAILY_KLINE_UPDATE_DAYS = 30
DAILY_KLINE_REALTIME_DAYS = 5
DAILY_KLINE_UPDATE_BATCH_SIZE = 500
SNAPSHOT_DIR = DATA_DIR / "snapshots"
BREAKOUT_KLINE_BATCH_SIZE = 500


_initialized = False


def initialize(script_path):
    """初始化通达信 tqcenter。"""
    global _initialized

    if _initialized:
        return

    tq.initialize(str(script_path))
    _initialized = True


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


def get_gb_info_by_date(stock_code, start_date, end_date):
    """获取指定日期区间内的历史股本信息。"""
    return tq.get_gb_info_by_date(
        stock_code=stock_code,
        start_date=start_date,
        end_date=end_date,
    )


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


def strip_tdx_suffix(stock_code):
    """去掉通达信股票代码后缀，得到纯数字代码。"""
    return str(stock_code).split(".")[0]


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


def migrate_stock_tables(conn):
    """创建股票基础信息和板块关系表，并为旧 stock_basic 表补齐缺失列。"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_basic (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        )
        """
    )
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(stock_basic)").fetchall()
    }
    if "total_shares" not in columns:
        conn.execute(
            "ALTER TABLE stock_basic ADD COLUMN total_shares REAL NOT NULL DEFAULT 0"
        )
    if "updated_at" not in columns:
        conn.execute(
            "ALTER TABLE stock_basic ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''"
        )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_sector (
            code TEXT NOT NULL,
            sector_type TEXT NOT NULL,
            sector_code TEXT NOT NULL DEFAULT '',
            sector_name TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (code, sector_type, sector_code, sector_name)
        )
        """
    )
    conn.commit()


def parse_total_shares(value):
    """将 J_zgb 转成万股；缺失或非法值按 0 处理。"""
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def collect_stock_basic_rows(stock_codes, updated_at, progress_interval=500):
    """获取全部股票名称和总股本，并按固定间隔输出进度。"""
    started_at = time.perf_counter()
    total = len(stock_codes)
    rows = []
    failed_count = 0

    print(f"[股票基础信息] 开始获取：共 {total} 只")

    for index, code in enumerate(stock_codes, 1):
        try:
            info = get_stock_info(code, field_list=[]) or {}
        except Exception as exc:
            failed_count += 1
            info = {}
            print(f"[股票基础信息] 获取失败：{code}，{exc}")

        rows.append({
            "code": code,
            "name": str(info.get("Name", "") or "").strip(),
            "total_shares": parse_total_shares(info.get("J_zgb")),
            "updated_at": updated_at,
        })

        if index % progress_interval == 0 or index == total:
            elapsed = time.perf_counter() - started_at
            print(
                f"[股票基础信息] 进度：{index}/{total}，"
                f"失败 {failed_count} 只，耗时 {elapsed:.1f}s"
            )

    elapsed = time.perf_counter() - started_at
    print(
        f"[股票基础信息] 获取完成：{total} 只，"
        f"失败 {failed_count} 只，耗时 {elapsed:.1f}s"
    )
    return rows


def collect_stock_sector_rows(stock_codes, updated_at, progress_interval=500):
    """获取行业和概念关系，并输出全量采集进度。"""
    started_at = time.perf_counter()
    total = len(stock_codes)
    failed_count = 0
    unique_rows = {}
    relation_type_map = {"行业": "industry", "概念": "concept"}

    print(f"[板块关系] 开始获取：共 {total} 只")

    for index, code in enumerate(stock_codes, 1):
        try:
            relations = get_relation(code) or []
        except Exception as exc:
            failed_count += 1
            relations = []
            print(f"[板块关系] 获取失败：{code}，{exc}")

        for relation in relations:
            sector_type = relation_type_map.get(relation.get("BlockType"))
            sector_name = str(relation.get("BlockName") or "").strip()
            if not sector_type or not sector_name:
                continue
            sector_code = str(relation.get("BlockCode") or "").strip()
            key = (code, sector_type, sector_code, sector_name)
            unique_rows.setdefault(key, {
                "code": code,
                "sector_type": sector_type,
                "sector_code": sector_code,
                "sector_name": sector_name,
                "updated_at": updated_at,
            })

        if index % progress_interval == 0 or index == total:
            elapsed = time.perf_counter() - started_at
            print(
                f"[板块关系] 进度：{index}/{total}，"
                f"已整理 {len(unique_rows)} 条，失败 {failed_count} 只，"
                f"耗时 {elapsed:.1f}s"
            )

    elapsed = time.perf_counter() - started_at
    print(
        f"[板块关系] 获取完成：{total} 只，"
        f"整理 {len(unique_rows)} 条，失败 {failed_count} 只，"
        f"耗时 {elapsed:.1f}s"
    )
    return list(unique_rows.values())


def replace_stock_metadata(stock_basic_rows, stock_sector_rows):
    """在一个事务中全量替换两张资料表，失败时回滚。"""
    conn = ensure_database()
    migrate_stock_tables(conn)
    transaction_started_at = time.perf_counter()
    try:
        print("[股票资料] 开始事务：清空并写入 stock_basic、stock_sector")
        conn.execute("BEGIN")
        conn.execute("DELETE FROM stock_sector")
        conn.execute("DELETE FROM stock_basic")
        conn.executemany(
            """INSERT INTO stock_basic
               (code, name, total_shares, updated_at)
               VALUES (?, ?, ?, ?)""",
            [
                (row["code"], row["name"], row["total_shares"], row["updated_at"])
                for row in stock_basic_rows
            ],
        )
        conn.executemany(
            """INSERT INTO stock_sector
               (code, sector_type, sector_code, sector_name, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            [
                (
                    row["code"],
                    row["sector_type"],
                    row["sector_code"],
                    row["sector_name"],
                    row["updated_at"],
                )
                for row in stock_sector_rows
            ],
        )
        conn.commit()
        elapsed = time.perf_counter() - transaction_started_at
        print(
            f"[股票资料] 事务提交完成：stock_basic={len(stock_basic_rows)}，"
            f"stock_sector={len(stock_sector_rows)}，耗时 {elapsed:.1f}s"
        )
    except Exception as exc:
        conn.rollback()
        elapsed = time.perf_counter() - transaction_started_at
        print(
            f"[股票资料] 事务失败，已回滚并保留旧数据：{exc}，"
            f"耗时 {elapsed:.1f}s"
        )
        raise


def refresh_stock_metadata(stock_codes):
    """先完整获取股票资料，再以事务全量替换本地资料表。"""
    updated_at = datetime.now().isoformat(timespec="seconds")

    print("[日K更新] 阶段 2/4：正在获取股票基础信息...")
    basic_rows = collect_stock_basic_rows(stock_codes, updated_at)

    print("[日K更新] 阶段 3/4：正在获取股票行业和概念...")
    sector_rows = collect_stock_sector_rows(stock_codes, updated_at)

    if len(basic_rows) != len(stock_codes):
        raise RuntimeError("股票基础信息未完整获取，取消本次数据库替换")

    print(
        f"[股票资料] 网络获取完成，准备开启事务："
        f"stock_basic={len(basic_rows)}，stock_sector={len(sector_rows)}"
    )
    replace_stock_metadata(basic_rows, sector_rows)
    return {"stock_basic": len(basic_rows), "stock_sector": len(sector_rows)}


def load_stock_basic_records():
    """读取本地股票基础信息。"""
    conn = ensure_database()
    migrate_stock_tables(conn)
    rows = conn.execute(
        "SELECT code, name, total_shares FROM stock_basic ORDER BY code"
    ).fetchall()
    return [
        {
            "code": row[0],
            "name": row[1] or "",
            "total_shares": float(row[2] or 0),
        }
        for row in rows
    ]


def load_stock_sectors(code):
    """从 stock_sector 查询一只股票的行业和概念，返回普通字典列表。"""
    conn = ensure_database()
    rows = conn.execute(
        """SELECT sector_type, sector_name, sector_code
           FROM stock_sector WHERE code = ?
           ORDER BY sector_type, sector_name""",
        (code,),
    ).fetchall()
    return [
        {"type": row[0], "name": row[1], "code": row[2]}
        for row in rows
    ]


def get_market_mode_label():
    """返回当前 A 股运行模式标签。"""
    return "盘中" if is_a_share_intraday() else "非盘中"


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

    stage_started_at = time.perf_counter()
    print("[日K更新] 阶段 1/4：正在获取全市场股票列表...")

    stock_rows = get_stock_list()
    stock_list = extract_stock_codes_from_stock_list(stock_rows)

    if not stock_list:
        print("[日K更新] 阶段 1/4 失败：未获取到股票列表，结束本次更新")
        return {
            "stock_count": 0,
            "updated_rows": 0,
            "count": count,
            "batch_size": batch_size,
        }

    stage_seconds = time.perf_counter() - stage_started_at
    print(
        f"[日K更新] 阶段 1/4 完成：获取 {len(stock_list)} 只股票，"
        f"耗时 {stage_seconds:.1f}s"
    )

    try:
        stats = refresh_stock_metadata(stock_list)
        print(
            f"[日K更新] 阶段 3/4 完成：股票资料更新完成 "
            f"(基础信息 {stats['stock_basic']} 只，板块关系 {stats['stock_sector']} 条)"
        )
    except Exception as exc:
        print(f"[股票资料] 全量替换失败，保留旧数据: {exc}")

    batches = chunk_list(stock_list, batch_size)
    total_batches = len(batches)
    total_updated_rows = 0

    print(
        f"[日K更新] 阶段 4/4：开始拉取日K，共 {len(stock_list)} 只，"
        f"{total_batches} 批，count={count}"
    )

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
        f"[日K更新] 阶段 4/4 完成：股票 {len(stock_list)} 只，"
        f"写入/覆盖 {total_updated_rows} 行"
    )
    print(f"[日K更新] 全部完成：总耗时 {total_seconds:.1f}s")

    return {
        "stock_count": len(stock_list),
        "updated_rows": total_updated_rows,
        "count": count,
        "batch_size": batch_size,
        "elapsed_seconds": round(total_seconds, 1),
    }


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


def should_merge_realtime_daily_kline(end_date=None):
    """判断 load_daily_kline 是否应该合并盘中实时日 K。"""
    today = datetime.now().strftime("%Y-%m-%d")
    target_date = str(end_date).strip() if end_date else today
    return target_date == today and is_a_share_intraday()


def merge_realtime_daily_kline_map(db_kline_map, realtime_kline_map, stock_list, count):
    """把实时日 K 合并到 DB 日 K map 中，并按 count 截断。"""
    result = {}
    replaced_count = 0
    appended_count = 0
    missing_realtime_count = 0

    for stock_code in stock_list:
        db_rows = [dict(row) for row in db_kline_map.get(stock_code, [])]
        realtime_rows = realtime_kline_map.get(stock_code, [])

        if not realtime_rows:
            missing_realtime_count += 1
            result[stock_code] = db_rows[-count:] if count is not None else db_rows
            continue

        before_latest_date = db_rows[-1]["trade_date"] if db_rows else ""
        merged_rows = merge_realtime_kline_rows(db_rows, realtime_rows)
        after_latest_date = merged_rows[-1]["trade_date"] if merged_rows else ""

        if before_latest_date and before_latest_date == after_latest_date:
            replaced_count += 1
        else:
            appended_count += 1

        result[stock_code] = merged_rows[-count:] if count is not None else merged_rows

    return {
        "kline_map": result,
        "replaced_count": replaced_count,
        "appended_count": appended_count,
        "missing_realtime_count": missing_realtime_count,
    }


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


def get_latest_trade_date_distribution(kline_map, stock_list):
    """统计每只股票最后一根 K 线日期分布。"""
    distribution = {}
    for stock_code in stock_list:
        rows = kline_map.get(stock_code, [])
        latest_date = rows[-1]["trade_date"] if rows else "无数据"
        distribution[latest_date] = distribution.get(latest_date, 0) + 1
    return distribution


def print_trade_date_distribution(title, distribution):
    """打印 K 线最后日期分布。"""
    print(f"[数据] {title}")
    for trade_date in sorted(distribution):
        print(f"[数据]   {trade_date}: {distribution[trade_date]}只")


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


def load_realtime_daily_kline(stock_list, batch_size=BREAKOUT_KLINE_BATCH_SIZE):
    """通过通达信读取最新日 K，用于盘中临时覆盖或追加。"""
    started_at = time.perf_counter()
    result = {}
    batches = list(chunk_list(stock_list, batch_size))
    total_batches = len(batches)

    print(
        f"[数据] 盘中实时日K开始：{len(stock_list)}只，"
        f"每批{batch_size}只，共{total_batches}批"
    )

    for batch_index, stock_batch in enumerate(batches, start=1):
        batch_started_at = time.perf_counter()
        first_code = stock_batch[0] if stock_batch else ""
        last_code = stock_batch[-1] if stock_batch else ""
        market_data = get_market_data(
            stock_list=stock_batch,
            period="1d",
            count=1,
            field_list=["Open", "High", "Low", "Close", "Volume", "Amount"],
            fill_data=True,
        )
        rows = market_data_to_daily_kline_rows(market_data, stock_batch)
        result.update(daily_kline_rows_to_map(rows))
        print(
            f"[数据] 盘中实时日K {batch_index}/{total_batches} 完成："
            f"{len(stock_batch)}只，{first_code} ~ {last_code}，"
            f"返回 {len(rows)} 行，耗时 {time.perf_counter() - batch_started_at:.1f}s"
        )

    print(
        f"[数据] 盘中实时日K完成：返回{len(result)}只，"
        f"耗时 {time.perf_counter() - started_at:.1f}s"
    )
    return result


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
    started_at = time.perf_counter()
    today = datetime.now().strftime("%Y-%m-%d")
    target_date = breakout_date or today
    intraday = should_merge_realtime_daily_kline(target_date)
    mode_text = "盘中" if intraday else "非盘中"
    count = int(box_days) + 1 + int(extra_days)

    print(f"[数据] 突破日期：{target_date}")
    print(f"[数据] 当前模式：{mode_text}")

    kline_map = load_daily_kline(
        stock_list=stock_list,
        count=count,
        end_date=target_date,
        batch_size=batch_size,
    )
    print_trade_date_distribution(
        "K线最后日期分布：",
        get_latest_trade_date_distribution(kline_map, stock_list),
    )
    print(f"[数据] K线读取总耗时：{time.perf_counter() - started_at:.1f}s")

    return kline_map


def load_daily_kline(stock_list, count=120, end_date=None, batch_size=BREAKOUT_KLINE_BATCH_SIZE):
    """按截止交易日读取日 K；盘中自动合并实时日 K。

    Args:
        stock_list: 带后缀通达信股票代码列表。
        count: 每只股票返回最近多少根 K 线，默认 120。
        end_date: 最后一根 K 线的交易日，格式 YYYY-MM-DD。历史日期不合并实时 K。
        batch_size: 盘中读取实时日 K 的批大小。

    Returns:
        按股票代码分组的日 K 字典，K 线按交易日升序排列。
    """
    db_started_at = time.perf_counter()
    db_kline_map = load_daily_kline_rows_from_db(
        code_list=stock_list,
        count=count,
        end_date=end_date,
    )
    print(
        f"[数据] 本地日K读取完成：{len(db_kline_map)}只，"
        f"耗时 {time.perf_counter() - db_started_at:.1f}s"
    )

    if not should_merge_realtime_daily_kline(end_date):
        return db_kline_map

    realtime_started_at = time.perf_counter()
    realtime_kline_map = load_realtime_daily_kline(
        stock_list=stock_list,
        batch_size=batch_size,
    )
    print(
        f"[数据] 盘中实时日K读取阶段完成：{len(realtime_kline_map)}只，"
        f"耗时 {time.perf_counter() - realtime_started_at:.1f}s"
    )

    merge_started_at = time.perf_counter()
    merge_result = merge_realtime_daily_kline_map(
        db_kline_map=db_kline_map,
        realtime_kline_map=realtime_kline_map,
        stock_list=stock_list,
        count=count,
    )
    print(
        f"[数据] 实时日K合并完成：覆盖 {merge_result['replaced_count']}只，"
        f"追加 {merge_result['appended_count']}只，"
        f"缺失实时 {merge_result['missing_realtime_count']}只，"
        f"耗时 {time.perf_counter() - merge_started_at:.1f}s"
    )
    return merge_result["kline_map"]


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


def print_json(value):
    """把接口返回结果按 JSON 打印。"""
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


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
            "  python data.py archive-snapshot\n"
            "  python data.py archive-snapshot --progress-interval 500\n"
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
        help="按截止交易日读取本地日 K",
        description=(
            "从本地 SQLite 读取某只股票截至指定交易日的最近 N 根日 K。"
            "返回结果包含截止交易日对应的 K 线（如果数据库中存在）。"
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
    load_daily_kline_parser.add_argument(
        "--end-date",
        default="",
        help="最后一根 K 线的交易日，格式 YYYY-MM-DD；默认不限制截止日期",
    )

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

    gb_info_parser = subparsers.add_parser("get_gb_info_by_date")
    gb_info_parser.add_argument("--code", required=True)
    gb_info_parser.add_argument("--start-date", required=True)
    gb_info_parser.add_argument("--end-date", required=True)

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
    elif args.command == "update-daily-kline":
        print_json(update_daily_kline_after_close(args.count, args.batch_size))
    elif args.command == "load-daily-kline":
        print_json(load_daily_kline([args.code], args.count, args.end_date or None))
    elif args.command == "archive-snapshot":
        print_json(archive_snapshot(args.progress_interval))
    elif args.command == "get_gb_info_by_date":
        print_json(
            get_gb_info_by_date(
                stock_code=args.code,
                start_date=args.start_date,
                end_date=args.end_date,
            )
        )


if __name__ == "__main__":
    main()
