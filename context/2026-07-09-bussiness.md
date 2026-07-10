# Business Report 第一版：Skill 驱动业务入口与结构化数据包

## 主题概述

本文件记录 2026-07-09 围绕 `Cassa` 新版 `report` 功能的业务设计讨论。

当前确认：`context/` 只用于记录上下文，不参与业务运行。新版业务逻辑放在新增脚本：

```text
business.py
```

业务入口由 Agent Skill 控制。Skill 调用 `business.py`，`business.py` 调用 `data.py` 获取结构化数据并返回 JSON；Skill / Agent 再基于结构化数据和 prompt 生成最终报告。

整体链路：

```text
Skill
  -> python business.py report --codes ...
  -> business.py 调 data.py
  -> business.py 返回结构化 JSON
  -> Skill / Agent 用 prompt 生成自然语言报告
```

## 已确认结论

### 1. context 不参与业务

`context/` 只保存设计、边界、代码草案和后续 Agent 需要了解的背景。

业务运行不读取 context，不把 context 当配置文件或数据源。

### 2. 新增 `business.py` 写业务逻辑

`business.py` 是新版业务脚本，第一阶段先实现 `report` 所需的数据包构建逻辑。

当前边界：

1. `data.py` 负责数据接口、SQLite、通达信调用。
2. `business.py` 负责业务目标解析、调用数据接口、组装结构化 report 数据。
3. Skill / Agent 负责调用 `business.py`，并基于 JSON 生成报告文本。

### 3. report 入口参数统一叫 code

用户输入统一是 code，可以是股票代码，也可以是板块代码。

支持：

```text
600519
600519.SH
000001
000001.SZ
880675
880675.SH
CASSA
```

当前第一版只确认解析规则，不在本文件中扩展复杂业务采集。

### 4. 股票和板块代码转换在 `business.py` 新写函数

不从旧 `cassa.py` import。

第一版在 `business.py` 中新写两个核心方向的函数：

1. 股票代码规整函数。
2. 板块代码规整 / 判断函数。

### 5. 代码判断规则

入口全是 `code`。

判断顺序：

1. 先调用 `data.get_sector_list(list_type=1)` 拉取全部板块。
2. 用全部板块判断输入 code 是否是板块。
3. 如果是板块，返回板块目标。
4. 如果不是板块，则按个股处理。
5. 个股如果已经带 `.SH` / `.SZ` / `.BJ` 后缀，则不转换，只统一大写。
6. 个股如果不带后缀，则按股票前缀补后缀。

当前不考虑其他复杂情况。

### 6. 带后缀的 code 也先参与板块判断

例如用户传：

```text
880675.SH
```

如果它存在于通达信板块列表中，就按板块处理；如果不存在，再按个股处理。

### 7. 数据采集由数据中心补能力

用户确认：具体数据采集能力会去 `data.py` 数据中心补。

`business.py` 的 report 会调用 `data.py` 已提供或后续新增的函数，不直接调用 `tqcenter`。

### 8. 新增 `reference/` 目录保存接口字段 mapping

用户确认：字段 key 和中文名字直接记录到项目里的参考文件，不单独做复杂字典系统。

目录名采用：

```text
reference/
```

当前第一版先新增一个文件：

```text
reference/tdx_fields.json
```

职责：

`tdx_fields.json`：按接口记录字段 key 和中文名。

当前这个文件是项目内参考资料，不参与运行时逻辑。

## report 数据结构

单个 report item 结构确认如下：

```text
code            带后缀通达信代码
name            名称
market_snapshot 实时快照
stock_info      基础信息
more_info       扩展信息
relation        所属板块数组
daily_kline     120 根历史日 K + 最新 1 根实时 K
macd            MACD 数组，120 根历史 + 最新 1 根
chip            筹码分布
```

JSON 示例：

```json
{
  "code": "600519.SH",
  "name": "贵州茅台",
  "market_snapshot": {},
  "stock_info": {},
  "more_info": {},
  "relation": [],
  "daily_kline": [],
  "macd": [],
  "chip": {
    "status": "todo",
    "data": null,
    "note": "筹码分布待接入"
  }
}
```

注意：

1. `relation` 应该是数组，不是对象。
2. `macd` 应该是数组，后续写代码时需要通过真实调用测试返回结构后确定转换方式。
3. `chip` 第一版只记录 TODO，占位不实现。

## 当前最新方案：无 computed 字段

2026-07-09 后续讨论确认：不要在 report item 中增加 `computed` 字段。

当前边界调整为：

```text
business.py = 数据采集 + 必要业务计算 + 控制台输出 + debug JSON
report.py   = 暂不实现，后续再单独讨论文件报告和格式生成
```

控制台输出直接由 `business.py report` 完成，格式尽量对齐旧 `cassa.py report`。

JSON 结构保持原始数据口径：

```text
code
name
market_snapshot
stock_info
more_info
relation
daily_kline
macd
chip
```

不新增：

```text
computed
```

需要逻辑判断或计算的内容，例如均线、趋势、信号、支撑压力、理由、风险，不进入 JSON 的 `computed` 字段，而是在 `business.py` 控制台输出时即时计算并打印。

`--debug` 行为：

```text
默认：打印类旧 cassa.py report 的控制台文本。
--debug：先打印正常控制台文本，再追加完整 JSON。
```

### 控制台输出字段来源

`行业`、`概念`：从 `relation` 数组读取，按 `BlockType` 判断。

`当日开高低收`、`涨跌幅`、`振幅`：从 `market_snapshot` 的 `Open`、`Max`、`Min`、`Now`、`LastClose` 读取和计算。

`MA5`、`MA10`、`MA20`、`MA60`：从 `daily_kline` 的收盘价即时计算。

`量比`：从 `more_info.fLianB` 读取。

`换手`：从 `more_info.fHSL` 读取。

`MACD`：从 `macd` 数组最后两条即时判断。

`PE`、`PB`、`主营`：从 `more_info` 读取。

`总股本`：从 `stock_info.J_zgb` 读取。

`总市值`：由 `stock_info.J_zgb * market_snapshot.Now / 10000` 即时计算。

`资金`：从 `more_info.Zjl` 和 `more_info.Zjl_HB` 读取。

`支撑压力`：从均线和近 20 日高低点即时计算。

`趋势`、`信号`、`理由`、`风险`：由 `business.py` 控制台输出函数即时计算并打印，不进入 `computed`。

### 当前代码状态说明

本节是后续要调整到的最新方案。当前仓库中的 `business.py` 如果仍存在 `computed` 字段，后续实现时应移除。

## 按数据类型的采集范围

### 实时数据

实时数据包括：

```text
get_market_snapshot
get_stock_info
get_more_info
get_relation
```

其中 `get_relation` 需要做所属板块映射逻辑，但最终 `relation` 字段仍保持数组。

映射逻辑建议：在每条 relation item 上补充标准分类字段，例如：

```json
{
  "BlockType": "行业",
  "BlockName": "白酒",
  "BlockCode": "xxxxxx",
  "GPNume": 50,
  "mapped_type": "industry"
}
```

第一版映射规则：

```text
行业 -> industry
概念 -> concept
地域 -> region
风格 -> style
其他 -> other
```

旧 `cassa.py` 已踩过字段名坑点：通达信 relation 字段是首字母大写：

```text
BlockType
BlockName
BlockCode
GPNume
```

不要写成小写。

### 历史数据

历史数据包括：

```text
本地数据日 K，默认 120 天
```

最新确认的 report 口径：

```text
daily_kline = 120 根历史日 K + 最新 1 根实时 K
```

也就是：

1. 从本地 SQLite 取历史日 K，默认 120 根。
2. 再拼接或覆盖最新 1 根实时 K。
3. 如果本地最后一根已经是今天，则用实时数据覆盖最新一根。
4. 如果本地最后一根是昨天，则追加今天实时 K。
5. 如果实时数据不可用，则返回 120 根历史日 K。

后续数据中心可新增专门函数承载这个口径；如果先在 `business.py` 包装，也必须保持这个语义。

### 计算数据

计算数据包括：

```text
formula_process_mul_zb: MACD 默认 120 天 + 最新
筹码分布: 记录 TODO
```

MACD 调用建议：

```python
data.formula_process_mul_zb(
    formula_name="MACD",
    formula_arg="12,26,9",
    stock_list=[code],
    stock_period="1d",
    count=121,
    return_count=121,
    return_date=True,
)
```

后续需要通过真实调用确认返回结构，再转换成数组放入 `macd` 字段。

筹码分布第一版不实现：

```json
{
  "status": "todo",
  "data": null,
  "note": "筹码分布待接入"
}
```

## 建议 `business.py` 代码结构

代码最好按以下顺序组织：

```text
business.py
  文件头说明
  import
  常量
  code 解析函数
  relation 映射函数
  report 实时数据函数
  report 历史数据函数
  report 计算数据函数
  report item 组装函数
  JSON 输出函数
  CLI 入口
```

函数分组：

```text
# code 解析
has_market_suffix
strip_code_suffix
infer_stock_market_suffix
normalize_stock_code
build_sector_lookup
resolve_report_code
resolve_report_codes

# relation 映射
map_relation_type
map_relation_rows

# report 数据
collect_realtime_report_data
collect_daily_kline_for_report
collect_macd_for_report
create_chip_placeholder
collect_report_item
build_report_data

# CLI
print_json
main
```

## 早期 `business.py` 代码草案（已被当前实现取代）

以下是早期讨论阶段留下的代码草案，仅保留为历史参考。当前最新完整代码以仓库中的 `business.py` 为准。

```python
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
```

## 待验证点

后续真正实现代码时，必须验证：

1. `data.get_sector_list(list_type=1)` 的返回字段是否稳定为 `Code` / `Name`。
2. 带后缀板块代码是否能被板块列表匹配。
3. `data.load_daily_kline([code], count=120)` 是否满足 120 历史 + 最新 1 根实时 K 的口径；如不满足，需要数据中心新增专用函数。
4. `formula_process_mul_zb` 的 MACD 返回结构，确认如何转换成数组。
5. `get_relation` 的字段是否稳定为 `BlockType` / `BlockName` / `BlockCode` / `GPNume`。
6. 板块目标是否能直接调用 `get_market_snapshot` / `get_stock_info` / `get_more_info` / `get_relation`；如果板块接口行为不同，需要在 `collect_report_item` 中按 `target_type` 分支。

## 暂不做内容

第一版暂不做：

1. 不生成最终自然语言报告。
2. 不接 LLM。
3. 不实现筹码分布。
4. 不做字段解释。
5. 不做宽表数据库归档。
6. 不做复杂股票 / 板块冲突处理。
7. 不从旧 `cassa.py` import 业务函数。
8. 不让 `business.py` 直接调用 `tqcenter`。

## 后续方向

下一步建议：

1. 在 `TASKS.md` 中新增 `business.py report` 第一版任务。
2. 确认是否先补 `data.py` 的 report 专用数据函数。
3. 新增 `business.py`，先实现 code 解析和 report 数据结构。
4. 真实运行：

```powershell
python business.py report --codes 600519,000001,880675.SH
```

5. 根据真实 `macd` 和 `relation` 返回结构修正转换逻辑。
6. 再创建或更新 `cassa-business` Skill，让 Skill 调用 `business.py report` 并基于 JSON 生成报告。

## business.py 控制台输出方案

2026-07-09 后续确认：控制台输出需要保持旧 `cassa.py report` 的格式风格，但本阶段不新增 `report.py`。

命令：

```powershell
python business.py report --codes 600519,000001
python business.py report --codes 600519,000001 --debug
```

其中：

1. 默认输出旧 `cassa.py report` 风格的控制台文本。
2. `--debug` 在正常控制台文本后追加完整 JSON。
3. JSON 不包含 `computed` 字段。

### 控制台输出格式

控制台输出尽量对齐旧 `cassa.py report`：

```text
个股趋势报告：2 只股票

=== 600519.SH 贵州茅台 ===
行业: 白酒  概念: 茅指数、沪股通
当日: 开123.45 高125.00 低121.20 收124.30 +1.23% 振幅3.08%
趋势: 震荡上行 (65/100)    信号: 观察 (65分)
现价: 124.30  MA5: 123.11(+1.0%)  MA10: 121.88(+2.0%)  MA20: 119.30(+4.2%)
量能: 温和放量 (1.32)      MACD: 多头    RSI: 待接入  换手: 1.5%
基本面: PE(动)20.1  PE(TTM)18.9  PB3.20  总市值2456.7亿
资金: 主买净额1234万  主力净流入888万
支撑: 123.11, 121.88  压力: 126.20, 130.00
理由: 价格站上MA20  MACD多头  温和放量
风险: 日内振幅较大
```

注意：

1. `RSI` 当前没有数据源，第一版显示 `待接入`。
2. 如果后续要展示 RSI，应先在业务层补 RSI 数据或计算逻辑。
3. 不新增 `computed` 字段。

### business.py 完整代码草案

以下是后续调整 `business.py` 的完整草案。当前只记录在 context 中，不要求本次落地代码。

```python
"""
Cassa 业务逻辑脚本。

第一阶段实现 report 结构化数据包，并按旧 cassa.py report 风格打印控制台输出。
默认打印控制台文本；--debug 会在文本后追加完整 JSON。
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


def safe_float(value, default=0.0):
    """把接口返回值尽量转换成 float。"""
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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
```

### 后续实现注意

本方案只更新 context，不要求本次立即改真实 `business.py`。

后续真正落地时，需要移除真实 `business.py` 中已有的 `computed` 字段，并把默认 CLI 输出从 JSON 改为控制台报告文本。

## 业务判断算法对齐旧版方案

2026-07-09 对比运行结果后确认：新版 `business.py report` 和旧 `cassa.py report` 的数据基本一致，差异主要来自业务判断算法未对齐旧版。

需要对齐的旧版算法：

```text
judge_trend_status
judge_volume_status
judge_support_resistance
judge_macd_status
calculate_rsi
judge_rsi_status
calculate_signal_score
judge_buy_signal
```

### 对齐目标

后续 `business.py report --codes 600360` 应尽量得到与旧 `cassa.py report --codes 600360` 一致的业务判断：

```text
趋势: 强势多头 (90/100)
信号: 买入 (70分)
量能: 量能正常 (1.19)
MACD: 多头
RSI: 强势(66)
支撑: 13.41
理由: ✅ 强势多头，顺势做多  ⚡ 价格略高于MA5(6.4%)，可小仓介入  多头排列，持续上涨  ✅ RSI强势(66.3)，多头力量充足
```

注意：控制台标题中 code 是否显示后缀后续可单独决定。当前新版数据结构统一保留带后缀代码；如果要完全贴旧版显示，可在打印层使用 `strip_code_suffix(code)`。

### 算法差异来源

当前新版差异：

1. 趋势用简化分数，所以输出 `震荡上行 (70/100)`；旧版用 MA5/MA10/MA20 排列与发散判断，输出 `强势多头 (90/100)`。
2. 信号用简化分数区间，所以 70 分输出 `观察`；旧版 `judge_buy_signal()` 会结合趋势状态，`强势多头 + score>=60` 输出 `买入`。
3. 量能命名不一致，新版 `平量`，旧版 `量能正常`。
4. 新版没有 RSI，旧版计算 RSI6/12/24，并以 RSI12 判断状态。
5. 支撑压力口径不同，新版列出所有低于现价的均线和近 20 日低点；旧版只把 MA5/MA10 距离现价足够近时作为支撑，MA20 在现价上方时作为趋势支撑。
6. 理由和风险来自不同评分模型；后续应直接迁移旧 `calculate_signal_score()`。

### 旧版算法逻辑

以下内容来自旧 `cassa.py report` 的业务判断函数，后续新版 `business.py report` 应按这些口径对齐。

#### `judge_trend_status`

输入：

```text
ma5
ma10
ma20
```

输出：

```text
(trend_status, ma_alignment, trend_strength)
```

判断逻辑：

1. 如果 MA 数据不足，或最新 MA5 / MA20 为 0，返回：

```text
盘整 / 均线数据不足 / 50
```

2. 如果最新均线满足：

```text
MA5 > MA10 > MA20
```

则进一步比较当前 MA5-MA20 价差和 5 根 K 线前的 MA5-MA20 价差。

如果当前价差继续扩大，且当前价差超过 5%，返回：

```text
强势多头 / 强势多头排列，均线发散上行 / 90
```

否则返回：

```text
多头排列 / 多头排列 MA5>MA10>MA20 / 75
```

3. 如果：

```text
MA5 > MA10 且 MA10 <= MA20
```

返回：

```text
弱势多头 / 弱势多头，MA5>MA10 但 MA10≤MA20 / 55
```

4. 如果最新均线满足：

```text
MA5 < MA10 < MA20
```

则比较当前 MA20-MA5 价差和 5 根 K 线前的 MA20-MA5 价差。

如果当前价差继续扩大，且当前价差超过 5%，返回：

```text
强势空头 / 强势空头排列，均线发散下行 / 10
```

否则返回：

```text
空头排列 / 空头排列 MA5<MA10<MA20 / 25
```

5. 如果：

```text
MA5 < MA10 且 MA10 >= MA20
```

返回：

```text
弱势空头 / 弱势空头，MA5<MA10 但 MA10≥MA20 / 40
```

6. 其他情况返回：

```text
盘整 / 均线缠绕，趋势不明 / 50
```

#### `judge_volume_status`

输入：

```text
closes
volume_ratio
```

其中 `volume_ratio` 直接使用通达信 `more_info.fLianB`。

输出：

```text
(volume_status, volume_ratio, volume_trend)
```

判断逻辑：

1. 如果量比小于等于 0，返回：

```text
量能正常 / 0 / 数据不足
```

2. 计算最新收盘价相对前一根收盘价的涨跌幅。

3. 如果：

```text
volume_ratio >= 1.5
```

且价格上涨，返回：

```text
放量上涨 / volume_ratio / 放量上涨，多头力量强劲
```

如果价格未上涨，返回：

```text
放量下跌 / volume_ratio / 放量下跌，注意风险
```

4. 如果：

```text
volume_ratio <= 0.7
```

且价格上涨，返回：

```text
缩量上涨 / volume_ratio / 缩量上涨，上攻动能不足
```

如果价格未上涨，返回：

```text
缩量回调 / volume_ratio / 缩量回调，洗盘特征明显（好）
```

5. 其他情况返回：

```text
量能正常 / volume_ratio / 量能正常
```

#### `judge_support_resistance`

输入：

```text
kline_bars
ma5
ma10
ma20
current_price
```

输出：

```text
(support_ma5, support_ma10, support_levels, resistance_levels)
```

判断逻辑：

1. MA5 支撑：

如果现价与 MA5 的距离小于等于 2%，且现价大于等于 MA5，则：

```text
support_ma5 = True
support_levels 加入 MA5
```

2. MA10 支撑：

如果现价与 MA10 的距离小于等于 2%，且现价大于等于 MA10，则：

```text
support_ma10 = True
support_levels 加入 MA10
```

3. MA20 支撑：

如果：

```text
current_price >= MA20
```

则 `support_levels` 加入 MA20。

4. 压力位：

如果 K 线数量至少 20 根，取最近 20 根最高价中的最大值。

如果这个最近 20 日高点大于现价，则加入 `resistance_levels`。

旧版不会把所有低于现价的均线都列为支撑，只重点看 MA5 / MA10 是否贴近现价，以及 MA20 趋势支撑。

#### `judge_macd_status`

输入：

```text
dif_series
dea_series
macd_bar_series
```

输出：

```text
(macd_dif, macd_dea, macd_bar, macd_status, macd_signal)
```

判断逻辑：

1. 如果 DIF 数据不足 2 根，返回：

```text
0 / 0 / 0 / 多头 / 数据不足
```

2. 计算：

```text
prev_diff = prev_dif - prev_dea
curr_diff = cur_dif - cur_dea
```

3. 金叉 / 死叉：

```text
prev_diff <= 0 且 curr_diff > 0 = 金叉
prev_diff >= 0 且 curr_diff < 0 = 死叉
```

4. DIF 上穿 / 下穿零轴：

```text
prev_dif <= 0 且 cur_dif > 0 = 上穿零轴
prev_dif >= 0 且 cur_dif < 0 = 下穿零轴
```

5. 优先级：

如果零轴上金叉：

```text
零轴上金叉 / 零轴上金叉，强烈买入信号
```

如果 DIF 上穿零轴：

```text
上穿零轴 / DIF上穿零轴，趋势转强
```

如果普通金叉：

```text
金叉 / 金叉，趋势向上
```

如果死叉：

```text
死叉 / 死叉，趋势向下
```

如果 DIF 下穿零轴：

```text
下穿零轴 / DIF下穿零轴，趋势转弱
```

如果 DIF 和 DEA 都大于 0：

```text
多头 / 多头排列，持续上涨
```

如果 DIF 和 DEA 都小于 0：

```text
空头 / 空头排列，持续下跌
```

其他：

```text
多头 / MACD 中性区域
```

#### `calculate_rsi`

输入：

```text
closes
period
```

输出：

```text
与 closes 等长的 RSI 序列
```

计算口径：

1. 如果收盘价不足 2 根，返回与 `closes` 等长的 `50.0`。

2. 计算相邻收盘价差值：

```text
delta = close[i] - close[i-1]
gain = max(delta, 0)
loss = max(-delta, 0)
```

3. 使用 Wilder's EMA / SMMA 口径：

```text
alpha = 1 / period
avg_gain[i] = alpha * gain[i] + (1 - alpha) * avg_gain[i-1]
avg_loss[i] = alpha * loss[i] + (1 - alpha) * avg_loss[i-1]
```

4. 首个 RSI 值填 `50.0`。

5. 如果 `avg_loss == 0`，RSI 记为 `100.0`。

否则：

```text
RS = avg_gain / avg_loss
RSI = 100 - 100 / (1 + RS)
```

旧版 report 计算：

```text
RSI6
RSI12
RSI24
```

但展示和状态判断主要使用 RSI12。

#### `judge_rsi_status`

输入：

```text
rsi_6
rsi_12
rsi_24
```

输出：

```text
(rsi_status, rsi_signal)
```

判断逻辑以 RSI12 为主：

1. 如果：

```text
RSI12 > 70
```

返回：

```text
超买 / RSI超买(x>70)，短期回调风险高
```

2. 如果：

```text
RSI12 > 60
```

返回：

```text
强势 / RSI强势(x)，多头力量充足
```

3. 如果：

```text
RSI12 >= 40
```

返回：

```text
中性 / RSI中性(x)，震荡整理中
```

4. 如果：

```text
RSI12 >= 30
```

返回：

```text
弱势 / RSI弱势(x)，关注反弹
```

5. 否则返回：

```text
超卖 / RSI超卖(x<30)，反弹机会大
```

#### `calculate_signal_score`

输入：

```text
trend_status
trend_strength
bias_ma5
volume_status
support_ma5
support_ma10
macd_status
macd_signal
rsi_status
rsi_signal
```

输出：

```text
(signal_score, signal_reasons, risk_factors)
```

总分由以下部分相加：

```text
趋势 30
乖离率 20
量能 15
支撑 10
MACD 15
RSI 10
```

趋势评分：

```text
强势多头 30
多头排列 26
弱势多头 18
盘整 12
弱势空头 8
空头排列 4
强势空头 0
```

趋势理由 / 风险：

```text
强势多头、多头排列 -> ✅ {trend_status}，顺势做多
空头排列、强势空头 -> ⚠️ {trend_status}，不宜做多
```

乖离率评分：

如果是强势多头，且趋势强度大于等于 70，则 MA5 乖离率阈值放宽：

```text
effective_threshold = 5.0 * 1.5 = 7.5
```

否则阈值为：

```text
5.0
```

评分逻辑：

```text
bias_ma5 < 0 且 > -3     -> +20，价格略低于MA5，回踩买点
bias_ma5 < 0 且 > -5     -> +16，价格回踩MA5，观察支撑
bias_ma5 < 0 其他        -> +8，乖离率过大，可能破位
0 <= bias_ma5 < 2        -> +18，价格贴近MA5，介入好时机
2 <= bias_ma5 < 阈值      -> +14，价格略高于MA5，可小仓介入
bias_ma5 > 阈值           -> +4，乖离率过高，严禁追高
```

量能评分：

```text
缩量回调 15
放量上涨 12
量能正常 10
缩量上涨 6
放量下跌 0
其他 8
```

量能理由 / 风险：

```text
缩量回调 -> ✅ 缩量回调，主力洗盘
放量下跌 -> ⚠️ 放量下跌，注意风险
```

支撑评分：

```text
support_ma5  -> +5，✅ MA5支撑有效
support_ma10 -> +5，✅ MA10支撑有效
```

MACD 评分：

```text
零轴上金叉 15
金叉 12
上穿零轴 10
多头 8
空头 2
下穿零轴 0
死叉 0
其他 5
```

MACD 理由 / 风险：

```text
零轴上金叉、金叉 -> ✅ {macd_signal}
死叉、下穿零轴 -> ⚠️ {macd_signal}
其他 -> {macd_signal}
```

RSI 评分：

```text
超卖 10
强势 8
中性 5
弱势 3
超买 0
其他 5
```

RSI 理由 / 风险：

```text
超卖、强势 -> ✅ {rsi_signal}
超买 -> ⚠️ {rsi_signal}
其他 -> {rsi_signal}
```

#### `judge_buy_signal`

输入：

```text
score
trend_status
```

输出：

```text
buy_signal
```

判断逻辑：

```text
score >= 75 且 trend_status in (强势多头, 多头排列) -> 强烈买入
score >= 60 且 trend_status in (强势多头, 多头排列, 弱势多头) -> 买入
score >= 45 -> 持有
score >= 30 -> 观望
trend_status in (空头排列, 强势空头) -> 强烈卖出
其他 -> 卖出
```

### 8 个旧版函数完整代码

以下代码来自旧 `cassa.py report` 的业务判断逻辑，后续迁移到 `business.py` 时应尽量保持口径一致。

```python
def judge_trend_status(
    ma5: list[float],
    ma10: list[float],
    ma20: list[float],
) -> tuple[str, str, float]:
    """根据最新均线值判断趋势状态，对齐 DSA _analyze_trend 逻辑。

    Args:
        ma5: MA5 序列。
        ma10: MA10 序列。
        ma20: MA20 序列。

    Returns:
        (趋势状态, 均线排列描述, 趋势强度 0-100)。
    """
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
        prev_spread = (cur_ma20 - cur_ma5) / cur_ma5 * 100 if cur_ma5 > 0 else 0
        curr_spread = (cur_ma20 - cur_ma5) / cur_ma5 * 100
        if curr_spread > prev_spread and curr_spread > 5:
            return "强势空头", "强势空头排列，均线发散下行", 10.0
        return "空头排列", "空头排列 MA5<MA10<MA20", 25.0

    if cur_ma5 < cur_ma10 and cur_ma10 >= cur_ma20:
        return "弱势空头", "弱势空头，MA5<MA10 但 MA10≥MA20", 40.0

    return "盘整", "均线缠绕，趋势不明", 50.0


def judge_volume_status(
    closes: list[float],
    volume_ratio: float,
) -> tuple[str, float, str]:
    """分析量能状态，量比直接使用通达信 more_info 接口的 fLianB。

    Args:
        closes: 收盘价序列。
        volume_ratio: 通达信接口量比。

    Returns:
        (量能状态, 量比, 量能趋势描述)。
    """
    if volume_ratio <= 0:
        return "量能正常", 0.0, "数据不足"

    ratio = volume_ratio
    prev_close = closes[-2]
    price_change = (closes[-1] - prev_close) / prev_close * 100 if prev_close > 0 else 0.0

    if ratio >= TREND_VOLUME_HEAVY_RATIO:
        if price_change > 0:
            return "放量上涨", ratio, "放量上涨，多头力量强劲"
        return "放量下跌", ratio, "放量下跌，注意风险"
    if ratio <= TREND_VOLUME_SHRINK_RATIO:
        if price_change > 0:
            return "缩量上涨", ratio, "缩量上涨，上攻动能不足"
        return "缩量回调", ratio, "缩量回调，洗盘特征明显（好）"
    return "量能正常", ratio, "量能正常"


def judge_support_resistance(
    kline_bars: list[KlineBar],
    ma5: float,
    ma10: float,
    ma20: float,
    current_price: float,
) -> tuple[bool, bool, list[float], list[float]]:
    """分析支撑压力位，对齐 DSA _analyze_support_resistance 逻辑。

    Args:
        kline_bars: K 线序列。
        ma5: MA5 值。
        ma10: MA10 值。
        ma20: MA20 值。
        current_price: 当前价格。

    Returns:
        (MA5是否支撑, MA10是否支撑, 支撑位列表, 压力位列表)。
    """
    support_ma5 = False
    support_ma10 = False
    support_levels: list[float] = []
    resistance_levels: list[float] = []

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

    if len(kline_bars) >= 20:
        recent_highs = [bar.high_price for bar in kline_bars[-20:]]
        recent_high = max(recent_highs)
        if recent_high > current_price:
            resistance_levels.append(recent_high)

    return support_ma5, support_ma10, support_levels, resistance_levels


def judge_macd_status(
    dif_series: list[float],
    dea_series: list[float],
    macd_bar_series: list[float],
) -> tuple[float, float, float, str, str]:
    """判断 MACD 状态，对齐 DSA _analyze_macd 逻辑。

    Args:
        dif_series: DIF 序列。
        dea_series: DEA 序列。
        macd_bar_series: MACD 柱状图序列。

    Returns:
        (DIF, DEA, MACD柱, 状态字符串, 信号描述)。
    """
    if len(dif_series) < 2:
        return 0.0, 0.0, 0.0, "多头", "数据不足"

    cur_dif = dif_series[-1]
    cur_dea = dea_series[-1]
    cur_bar = macd_bar_series[-1]
    prev_dif = dif_series[-2]
    prev_dea = dea_series[-2]

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


def calculate_rsi(closes: list[float], period: int) -> list[float]:
    """计算 RSI 指标（Wilder's EMA / SMMA 口径）。

    Args:
        closes: 收盘价序列。
        period: RSI 周期。

    Returns:
        与 closes 等长的 RSI 序列，首位置填 50.0。
    """
    if len(closes) < 2:
        return [50.0] * len(closes)

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]

    alpha = 1.0 / period
    avg_gains = [0.0] * len(gains)
    avg_losses = [0.0] * len(losses)
    if gains:
        avg_gains[0] = sum(gains[:period]) / period if len(gains) >= period else gains[0]
        avg_losses[0] = sum(losses[:period]) / period if len(losses) >= period else losses[0]
        for i in range(1, len(gains)):
            avg_gains[i] = alpha * gains[i] + (1 - alpha) * avg_gains[i - 1]
            avg_losses[i] = alpha * losses[i] + (1 - alpha) * avg_losses[i - 1]

    rsi_values: list[float] = [50.0]
    for i in range(len(gains)):
        if avg_losses[i] == 0:
            rsi_values.append(100.0)
        else:
            rs = avg_gains[i] / avg_losses[i]
            rsi_values.append(100.0 - 100.0 / (1.0 + rs))
    return rsi_values


def judge_rsi_status(
    rsi_6: float,
    rsi_12: float,
    rsi_24: float,
) -> tuple[str, str]:
    """判断 RSI 状态，对齐 DSA _analyze_rsi 逻辑，以 RSI(12) 为主。

    Args:
        rsi_6: RSI(6) 值。
        rsi_12: RSI(12) 值。
        rsi_24: RSI(24) 值。

    Returns:
        (状态字符串, 信号描述)。
    """
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
    trend_status: str,
    trend_strength: float,
    bias_ma5: float,
    volume_status: str,
    support_ma5: bool,
    support_ma10: bool,
    macd_status: str,
    macd_signal: str,
    rsi_status: str,
    rsi_signal: str,
) -> tuple[int, list[str], list[str]]:
    """综合评分，对齐 DSA _generate_signal 逻辑。

    权重：趋势30 + 乖离20 + 量能15 + 支撑10 + MACD15 + RSI10 = 100。

    Args:
        trend_status: 趋势状态。
        trend_strength: 趋势强度。
        bias_ma5: MA5 乖离率。
        volume_status: 量能状态。
        support_ma5: MA5 是否支撑。
        support_ma10: MA10 是否支撑。
        macd_status: MACD 状态。
        macd_signal: MACD 信号描述。
        rsi_status: RSI 状态。
        rsi_signal: RSI 信号描述。

    Returns:
        (综合评分 0-100, 买入理由列表, 风险因素列表)。
    """
    score = 0
    reasons: list[str] = []
    risks: list[str] = []

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


def judge_buy_signal(score: int, trend_status: str) -> str:
    """根据评分和趋势状态生成买入信号。

    Args:
        score: 综合评分 0-100。
        trend_status: 趋势状态。

    Returns:
        买入信号字符串。
    """
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

### 后续完整 business.py 代码草案：旧版算法对齐 + RSI 接入

以下是后续调整 `business.py` 的完整草案。当前只记录在 context 中，不要求本次落地代码。

```python
"""
Cassa 业务逻辑脚本。

第一阶段实现 report 结构化数据包，并按旧 cassa.py report 风格打印控制台输出。
默认打印控制台文本；--debug 会在文本后追加完整 JSON。
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

TREND_RSI_OVERBOUGHT = 70
TREND_RSI_OVERSOLD = 30
TREND_VOLUME_SHRINK_RATIO = 0.7
TREND_VOLUME_HEAVY_RATIO = 1.5
TREND_MA_SUPPORT_TOLERANCE = 0.02
TREND_BIAS_THRESHOLD = 5.0
TREND_STRONG_BULL_BIAS_RELAX = 1.5
TREND_STRONG_BULL_STRENGTH_THRESHOLD = 70


def safe_float(value, default=0.0):
    """把接口返回值尽量转换成 float。"""
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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


def format_number(value, digits=2):
    """格式化普通数字。"""
    return f"{safe_float(value):.{digits}f}"


def format_signed_percent(value):
    """格式化带正负号的百分比。"""
    return f"{safe_float(value):+.1f}%"


def get_kline_value(row, *keys):
    """从不同命名风格的 K 线字典中读取数值。"""
    for key in keys:
        if key in row:
            return safe_float(row.get(key))
    return 0.0


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


def format_report_item(item):
    """格式化单个 report item，业务判断口径对齐旧 cassa.py report。"""
    relation = item.get("relation") or []
    industry, concepts = extract_industry_and_concepts(relation)
    today = calculate_today_quote(item)
    current_price = safe_float(today.get("current_price"))
    closes = extract_close_values(item)
    ma5_series = calculate_sma(closes, 5)
    ma10_series = calculate_sma(closes, 10)
    ma20_series = calculate_sma(closes, 20)
    ma60_series = calculate_sma(closes, 60)

    ma5 = ma5_series[-1] if ma5_series else 0.0
    ma10 = ma10_series[-1] if ma10_series else 0.0
    ma20 = ma20_series[-1] if ma20_series else 0.0
    ma60 = ma60_series[-1] if ma60_series else 0.0
    bias_ma5, bias_ma10, bias_ma20 = calculate_bias(current_price, ma5, ma10, ma20)

    trend_status, ma_alignment, trend_strength = judge_trend_status(ma5_series, ma10_series, ma20_series)

    more_info = item.get("more_info") or {}
    stock_info = item.get("stock_info") or {}
    volume_ratio = safe_float(more_info.get("fLianB"))
    turnover_rate = safe_float(more_info.get("fHSL"))
    volume_status, volume_ratio, volume_trend = judge_volume_status(closes, volume_ratio)

    support_ma5, support_ma10, support_levels, resistance_levels = judge_support_resistance(
        item, ma5, ma10, ma20, current_price
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
    market_cap = total_shares * current_price / 10000 if total_shares > 0 and current_price > 0 else 0.0

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
        f"现价: {current_price:.2f}  "
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
```

### 后续实现注意

本方案只更新 context，不要求本次立即改真实 `business.py`。

后续真正落地时：

1. 移除真实 `business.py` 中已有的 `computed` 字段。
2. 把默认 CLI 输出从 JSON 改为控制台报告文本。
3. 接入 RSI6 / RSI12 / RSI24 计算。
4. 将趋势、量能、支撑压力、MACD、信号评分、买入信号全部改为本节草案中的旧版口径。
5. 用 `python business.py report --codes 600360` 和 `python cassa.py report --codes 600360` 对比输出。

## 当前最新补充：筹码分布

### 结论

筹码分布不再使用 TODO 占位。

后续 `business.py report` 的 `chip` 字段使用 Sentinel 项目中的筹码计算方案：

```text
D:\股神养成plan\Sentinel\cyq_calculator.js
D:\股神养成plan\Sentinel\watch_dog.py
```

核心思路是：不调用外部筹码接口，而是用最近日 K + 每日换手率重建筹码分布。

JS 算法本体不内嵌在 `business.py` 中，后续先在 Cassa 项目根目录单独保存为：

```text
cyq_calculator.js
```

`business.py` 只负责读取该 JS 文件并用 `py_mini_racer` 调用 `CYQCalculator`。

注意：Sentinel 旧代码里的 `fetch_gb_history(tq, ...)` 和 `collect_chip_for_report(tq, ...)` 是直接传 `tq` 对象调用历史股本接口。这不符合 Cassa 当前分层。

Cassa 迁移时必须改成：

```text
business.py -> data.py -> tqcenter
```

`business.py` 只允许调用 `data.py` 暴露的数据函数，不直接接触 `tqcenter` 或 `tq` 对象。

历史股本接口的 `data.py` 方案和完整代码记录在：

```text
context/2026-07-09-data-center.md
```

### 输出结构

`chip` 字段只保存业务可消费的数据，不保留 `source` 字段：

```json
{
  "profit_ratio": 0.856321,
  "avg_cost": 13.42,
  "cost_90_low": 11.8,
  "cost_90_high": 15.3,
  "concentration_90": 0.128,
  "cost_70_low": 12.4,
  "cost_70_high": 14.7,
  "concentration_70": 0.085,
  "chip_status": "较集中",
  "sample_count": 120
}
```

字段含义：

```text
profit_ratio       获利比例，当前价格以下的筹码占全部筹码比例
avg_cost           平均成本/筹码中位成本，累计 50% 筹码所在价格
cost_90_low        90% 筹码区间下沿
cost_90_high       90% 筹码区间上沿
concentration_90   90% 筹码集中度，(高 - 低) / (高 + 低)，越小越集中
cost_70_low        70% 筹码区间下沿
cost_70_high       70% 筹码区间上沿
concentration_70   70% 筹码集中度，(高 - 低) / (高 + 低)，越小越集中
chip_status        按 90% 集中度粗分的筹码状态
sample_count       参与计算的有效 K 线数量
```

不可计算时也保持 `chip` 为对象，但不加 `source`：

```json
{
  "status": "todo",
  "data": null,
  "note": "筹码分布暂无法计算：有效日线/换手率样本不足 30 条。"
}
```

### 数据来源

筹码计算需要以下数据：

```text
daily_kline:
  open
  high
  low
  close
  volume
  amount

more_info:
  fHSL 当前换手率

stock_info:
  ActiveCapital 当前流通股本

新增可选接口:
  data 层历史股本接口
```

日 K 取 `report` 已经规划的 `daily_kline`，默认 120 根历史日 K + 最新实时 K。

历史股本用于还原历史每日换手率。如果历史股本接口不可用，则使用当前 `stock_info.ActiveCapital` 兜底。

### 计算流程

```text
1. 从 daily_kline 提取 open/high/low/close/volume/amount。
2. 通过 data 层历史股本接口获取历史流通股本。
3. 为每个交易日计算 daily_turnover_history：
   turnover_rate = volume / float_capital * scale
4. scale 用当前 more_info.fHSL 反推，避免通达信 Volume/ActiveCapital 单位不一致。
5. 将日 K 转换为 JS 需要的 records：
   date/open/close/high/low/volume/amount/zf/zdf/zde/hsl
6. 有效 records 少于 30 条则返回不可计算对象。
7. 从根目录 `cyq_calculator.js` 读取 JS 代码。
8. 用 py_mini_racer 执行 `CYQCalculator`。
9. 从 JS 结果提取 profit_ratio、avg_cost、70/90 区间、70/90 集中度。
10. 用 concentration_90 生成 chip_status。
```

### 筹码状态口径

沿用 Sentinel：

```python
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
```

### cyq_calculator.js 完整代码来源

根目录 `cyq_calculator.js` 直接从 Sentinel 迁移：

```text
D:\股神养成plan\Sentinel\cyq_calculator.js
```

第一版保持原 JS 算法不改名、不重写、不翻译，只把文件复制到 Cassa 根目录：

```text
D:\股神养成plan\Cassa\cyq_calculator.js
```

这样后续如果要对齐 Sentinel 或单独测试筹码算法，可以直接比较两个 JS 文件，不需要从 Python 字符串里抠代码。

### business.py 完整代码草案

以下代码后续合入 `business.py`，当前只记录方案，不要求本次落地。

```python
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from py_mini_racer import MiniRacer

import data


PROJECT_ROOT = Path(__file__).resolve().parent
CYQ_JS_PATH = PROJECT_ROOT / "cyq_calculator.js"


def load_cyq_js_code() -> str:
    """读取独立保存的筹码分布 JS 算法文件。"""
    return CYQ_JS_PATH.read_text(encoding="utf-8")


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
    return compute_chip_distribution(
        daily_kline=daily_kline,
        daily_turnover_history=daily_turnover_history,
        current_price=market_snapshot.get("Now"),
    )
```

### `collect_report_item` 接入点

后续 `collect_report_item` 先采集原始数据，再计算筹码：

```python
def collect_report_item(target):
    code = target["code"]
    item = {
        "code": code,
        "name": target.get("name") or "",
        "market_snapshot": data.get_market_snapshot(code),
        "stock_info": data.get_stock_info(code),
        "more_info": data.get_more_info(code),
        "relation": collect_relation_for_report(code),
        "daily_kline": collect_daily_kline_for_report(code),
        "macd": collect_macd_for_report(code),
        "chip": None,
    }
    item["chip"] = collect_chip_for_report(item)
    return item
```

### 控制台输出建议

控制台必须打印筹码分布摘要。

可计算时，在基本面/资金之后、支撑压力之前增加一行：

```text
筹码: 获利盘85.6%  平均成本13.42  90集中度0.128  状态: 较集中
```

不可计算时也打印：

```text
筹码: 不可计算（有效日线/换手率样本不足 30 条）
```

如果没有具体原因，则打印：

```text
筹码: 不可计算
```

## 当前最新补充：report 计算价格与筹码控制台输出

### 背景

`market_snapshot.Now` 在盘前可能是 0。

如果用 `Now=0` 计算乖离率、支撑压力、总市值或筹码获利比例，会出现类似：

```text
MA5: 22.65(-100.0%)
风险: 乖离率过大(-100.0%)
```

用户确认：当日行情展示暂时不改，仍然来自 `market_snapshot`；但业务计算中的乖离率等指标要使用最新 K 线收盘价。

### 最新规则

`data.load_daily_kline()` 已在数据层按交易时段决定是否拼接实时K：

```text
盘中/午间：拼接实时K，最新K线 close_price 等于实时价
盘前/盘后/休市：不拼接实时K，最新K线 close_price 是最近有效收盘价
```

因此 `business.py report` 的计算价格统一取：

```text
calc_price = 最新有效 daily_kline.close_price
```

用于：

```text
乖离率
支撑压力
总市值估算
筹码获利比例
```

继续使用 `market_snapshot` 的地方：

```text
当日: Open / Max / Min / Now / LastClose
现价: Now
```

也就是说：展示价格和计算价格可以不同。第一版先保障计算结果正确，不改当日行情展示。

### 完整修改代码

以下代码后续替换/补充到 `business.py` 中。

#### 新增：最新有效K线收盘价

```python
def get_latest_kline_close(item, default=0.0):
    """取最新有效日K收盘价，作为 report 计算用价格。"""
    closes = extract_close_values(item)
    if closes:
        return closes[-1]
    return safe_float(default)
```

#### 新增：筹码控制台格式化

```python
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

    profit_ratio = safe_float(chip.get("profit_ratio"))
    avg_cost = safe_float(chip.get("avg_cost"))
    concentration_90 = safe_float(chip.get("concentration_90"))
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
```

#### 替换：collect_chip_for_report 中的 current_price

旧逻辑：

```python
return compute_chip_distribution(
    daily_kline=daily_kline,
    daily_turnover_history=daily_turnover_history,
    current_price=market_snapshot.get("Now"),
)
```

新逻辑：

```python
calc_price = get_latest_kline_close(item, default=market_snapshot.get("Now"))
return compute_chip_distribution(
    daily_kline=daily_kline,
    daily_turnover_history=daily_turnover_history,
    current_price=calc_price,
)
```

完整函数：

```python
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
```

#### 修改：format_report_item 中的价格口径

`format_report_item()` 开头价格部分调整为：

```python
today = calculate_today_quote(item)
display_price = safe_float(today.get("current_price"))
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
```

支撑压力改为：

```python
support_ma5, support_ma10, support_levels, resistance_levels = judge_support_resistance(
    item, ma5, ma10, ma20, calc_price
)
```

总市值估算改为：

```python
market_cap = total_shares * calc_price / 10000 if total_shares > 0 and calc_price > 0 else 0.0
```

控制台展示仍用 `display_price`：

```python
lines.append(
    f"现价: {display_price:.2f}  "
    f"MA5: {ma5:.2f}({bias_ma5:+.1f}%)  "
    f"MA10: {ma10:.2f}({bias_ma10:+.1f}%)  "
    f"MA20: {ma20:.2f}({bias_ma20:+.1f}%)"
)
```

资金后增加筹码行：

```python
lines.append(format_chip_line(item.get("chip")))
```

推荐放置位置：

```python
net_buy_amount = safe_float(more_info.get("Zjl"))
main_net_inflow = safe_float(more_info.get("Zjl_HB"))
if net_buy_amount != 0 or main_net_inflow != 0:
    lines.append(f"资金: 主买净额{net_buy_amount:.0f}万  主力净流入{main_net_inflow:.0f}万")

lines.append(format_chip_line(item.get("chip")))

support_text = ", ".join(f"{value:.2f}" for value in support_levels) if support_levels else "无"
resistance_text = ", ".join(f"{value:.2f}" for value in resistance_levels) if resistance_levels else "无"
lines.append(f"支撑: {support_text}  压力: {resistance_text}")
```

### 验证建议

盘前运行：

```powershell
python business.py report --codes 002185
```

预期：

1. `当日` 和 `现价` 仍按 `market_snapshot` 打印。
2. `MA5/MA10/MA20` 后面的乖离率不再出现 `-100.0%`。
3. `支撑/压力` 不再因为 `Now=0` 被污染。
4. 控制台出现 `筹码:` 行。
5. 筹码不可计算时打印 `筹码: 不可计算（...）`。

## 字段 mapping 文件

### `reference/tdx_fields.json`

按接口记录字段 key 和中文名，当前覆盖：

```text
get_market_snapshot
get_stock_info
get_more_info
get_relation
```

用途：

1. 后续看到接口原始字段时，能快速查中文含义。
2. 后续新增业务展示项时，先从这里查候选字段。

## 来源会话

来源：2026-07-09 当前会话。
