# 2026-07-15 screen.py v2 重构 Handoff

## 背景

当前 `screen.py` 已经能运行多个选股入口，包括：

- `scan-box`
- `scan-breakout`
- `scan-breakout-pullback-ma5`
- `heat`

但现有结构基本是“一个选股策略一个大函数”。例如 `screen_heat()`、`screen_volume_breakout()`、`screen_box_consolidation()`、`screen_breakout_pullback_ma()` 都各自完成：

- 获取全部 A 股股票池。
- 读取 K 线。
- 准备策略指标。
- 逐层筛选。
- 记录 layers。
- 组装结果 JSON。
- 打印结果。

这种方式前期开发快，但后续扩展性不够。新增策略时会继续复制整套流程，JSON 输出也容易继续分裂成不同格式。

本次已经确认：后续准备在新会话整体重构 screen 层。

## 当前已确认口径

### 1. 需要统一 JSON 输出

目标 JSON 外壳：

```json
{
  "strategy": "heat",
  "run_date": "2026-07-15",
  "mode": "盘中",
  "conditions": [],
  "selected": [
    {
      "code": "000554.SZ",
      "name": "泰山石油",
      "sectors": [
        {
          "type": "industry",
          "name": "XXX",
          "code": ""
        }
      ],
      "latest_kline": {}
    }
  ],
  "layers": []
}
```

说明：

- `strategy`：策略名，例如 `heat`、`volume_breakout`。
- `run_date`：本次选股对应日期。
- `mode`：盘中 / 非盘中。
- `conditions`：策略条件定义，需要和 `layers` 对应。
- `selected`：最终入选股票列表。
- `layers`：每层筛选统计。

### 2. `conditions` 和 `layers` 的关系

`conditions` 是规则定义，`layers` 是执行结果。

例如资金热度：

```json
[
  {
    "layer": "ST/退市过滤",
    "field": "name",
    "operator": "not_contains",
    "value": ["ST", "退市"]
  },
  {
    "layer": "价格区间过滤",
    "field": "latest_kline.close_price",
    "operator": "between",
    "value": [3, 220],
    "unit": "元"
  },
  {
    "layer": "成交额过滤",
    "field": "latest_kline.amount",
    "operator": ">=",
    "value": 30000,
    "unit": "万元"
  },
  {
    "layer": "换手率过滤",
    "field": "turnover_rate",
    "operator": ">=",
    "value": 2.0,
    "unit": "%"
  },
  {
    "layer": "量比过滤",
    "field": "volume_ratio",
    "operator": ">=",
    "value": 1.5
  },
  {
    "layer": "涨幅过滤",
    "field": "change_pct",
    "operator": ">=",
    "value": 1.0,
    "unit": "%"
  }
]
```

### 3. `selected` 的字段口径

统一结构先严格按以下字段：

```json
{
  "code": "000554.SZ",
  "name": "泰山石油",
  "sectors": [],
  "latest_kline": {}
}
```

其中：

- `latest_kline` 字段对应 SQLite `daily_kline` 表字段口径。
- `amount` 继续保持数据库里的万元口径，不为了输出改数据。
- `sectors` 只放行业和概念板块，不放地域、风格或其他类型。

### 4. 板块映射口径

已确认：`sectors` 按 `business.py` 里的逻辑来，不使用 `tdx_block_type_map.json` 做本次筛选结果输出映射。

现有函数：

```python
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
```

`data.get_relation(stock_code)` 返回字段口径：

```json
{
  "BlockType": "行业",
  "BlockName": "半导体",
  "BlockCode": "881319.SH"
}
```

输出 `sectors` 时：

- `BlockType == 行业` -> `type = industry`
- `BlockType == 概念` -> `type = concept`
- `BlockType == 地域` -> 过滤
- `BlockType == 风格` -> 过滤
- 其他 / 空名称 -> 过滤

### 5. 数据补齐阶段

已经确认采用“先筛选，后补齐输出数据”的流程。

筛选阶段只准备过滤必须使用的数据。

选出最终股票后，再只对 `final_codes` 补齐：

- `sectors`
- `latest_kline`
- 输出展示字段

这样可以避免对全部 A 股逐只调用 `data.get_relation()` 导致流程变慢。

资金热度 `heat` 中以下字段仍然必须在过滤前准备：

- `name`：用于 ST / 退市过滤。
- `turnover_rate`：用于换手率过滤。
- `price`：用于价格区间过滤。
- `amount`：用于成交额过滤，单位万元。
- `volume_ratio`：用于量比过滤。
- `change_pct`：用于涨幅过滤。

## 为什么需要重构

现在的 `screen.py` 里，不同策略的差异本质只有：

- 要读多少 K 线。
- 要准备哪些指标。
- 有哪些筛选层。
- 每层筛选函数是什么。
- `conditions` 怎么描述。
- 入选股票是否有策略独有字段。

但现有每个 `screen_*()` 函数都重复实现完整流程。

继续按这种模式扩展，会导致：

- 每个新策略都复制获取股票池、读取 K 线、run_layer、结果组装。
- JSON 输出容易继续不一致。
- `--debug` 输出难以稳定消费。
- 控制台打印和结果 JSON 之间关系越来越乱。
- 后续 Agent / Skill 调用时需要为每个策略单独适配。

所以需要抽出通用执行器和统一结果组装器。

## 建议重构目标

### 1. `screen.py` 的核心角色

`screen.py` 应该变成通用执行层：

- 获取股票池。
- 读取 K 线。
- 调用策略的 prepare。
- 顺序执行策略 layers。
- 记录每层统计。
- 统一构建 JSON。
- 统一打印结果。

具体策略只提供规则，不自己复制整个执行流程。

### 2. 策略定义保持轻量

建议不要上复杂插件系统，也不要做过度抽象。

可以先采用普通 dict + 函数：

```python
strategy_spec = {
    "name": "heat",
    "get_kline_config": get_heat_kline_config,
    "prepare": prepare_heat_context,
    "build_layers": build_heat_layers,
    "build_conditions": build_heat_conditions,
    "build_detail_map": build_heat_detail_map,
}
```

统一 runner：

```python
def run_screen_strategy(strategy_spec, run_date="", batch_size=DEFAULT_BATCH_SIZE):
    ...
```

未来如果策略数量更多，再考虑 dataclass 或 class。

### 3. 通用执行流程

推荐流程：

```text
1. 获取全部 A 股股票池
2. 根据策略配置读取 K 线
3. 策略 prepare_context，准备指标和中间数据
4. 策略 build_layers，返回筛选层定义
5. runner 顺序执行 run_layer
6. 得到 final_codes
7. 只对 final_codes 补齐 selected 输出数据
8. build_screen_result 统一组装 JSON
9. print_screen_result 统一打印
```

### 4. 层定义建议

每层可以定义为简单 dict：

```python
{
    "name": "成交额过滤",
    "filter": lambda codes, context: filter_heat_amount(
        codes,
        context["metric_map"],
        amount_min=context["params"]["amount_min"],
    ),
}
```

runner 调用时：

```python
for layer in layers:
    current_codes = run_layer(
        layer_name=layer["name"],
        input_codes=current_codes,
        filter_func=lambda codes: layer["filter"](codes, context),
        layer_records=layer_records,
    )
```

### 5. 统一结果构建

建议通用函数只关心统一外壳，不关心具体策略。

```python
def build_screen_result(
    strategy,
    run_date,
    mode,
    conditions,
    layers,
    selected_codes,
    kline_map=None,
    name_map=None,
    metric_map=None,
    detail_map=None,
    include_sectors=True,
    extra=None,
):
    selected = build_selected_items(
        selected_codes=selected_codes,
        kline_map=kline_map or {},
        name_map=name_map or {},
        metric_map=metric_map or {},
        detail_map=detail_map or {},
        include_sectors=include_sectors,
    )

    result = {
        "strategy": strategy,
        "run_date": run_date or "",
        "mode": mode or "",
        "conditions": conditions,
        "selected": selected,
        "layers": layers,
    }
    result.update(extra or {})
    return result
```

`selected` 固定外壳：

```json
{
  "code": "000554.SZ",
  "name": "泰山石油",
  "sectors": [],
  "latest_kline": {}
}
```

如果后续需要策略独有字段，不要平铺到 selected 顶层，建议加扩展字段：

```json
{
  "metrics": {},
  "strategy_data": {}
}
```

但本次用户目前确认的严格格式里，先只要求：

- `code`
- `name`
- `sectors`
- `latest_kline`

### 6. 统一板块补齐函数

建议：

```python
from business import map_relation_type


def build_stock_sectors(stock_code):
    """把通达信板块关系转换为统一 sectors 结构，只保留行业和概念。"""
    relation_rows = data.get_relation(stock_code)
    sectors = []
    seen = set()

    for row in relation_rows or []:
        if not isinstance(row, dict):
            continue

        sector_type = map_relation_type(row.get("BlockType"))
        if sector_type not in {"industry", "concept"}:
            continue

        sector_name = str(row.get("BlockName", "") or "").strip()
        sector_code = str(row.get("BlockCode", "") or "").strip()
        dedupe_key = (sector_type, sector_name, sector_code)
        if not sector_name or dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        sectors.append(
            {
                "type": sector_type,
                "name": sector_name,
                "code": sector_code,
            }
        )

    return sectors
```

### 7. 统一最新 K 线函数

```python
def normalize_latest_kline(kline_row):
    """按 SQLite daily_kline 字段口径输出最新 K 线。"""
    if not kline_row:
        return {}

    return {
        "code": kline_row.get("code", ""),
        "trade_date": kline_row.get("trade_date", ""),
        "open_price": safe_float(kline_row.get("open_price")),
        "high_price": safe_float(kline_row.get("high_price")),
        "low_price": safe_float(kline_row.get("low_price")),
        "close_price": safe_float(kline_row.get("close_price")),
        "volume": safe_float(kline_row.get("volume")),
        "amount": safe_float(kline_row.get("amount")),
    }
```

## 建议迁移顺序

### 第一步：只抽统一 JSON 组装

先不改变各策略筛选逻辑，只把结果统一：

- 新增 `build_screen_result()`
- 新增 `build_selected_items()`
- 新增 `build_stock_sectors()`
- 新增 `normalize_latest_kline()`
- 每个现有 `screen_*()` 最后调用统一 builder

这样风险最低。

### 第二步：抽通用 runner

把以下重复流程抽到 `run_screen_strategy()`：

- 获取股票池。
- 读取 K 线。
- 初始化 `layer_records`。
- 顺序执行 layers。
- 结果组装。
- 全流程耗时打印。

### 第三步：迁移 heat

优先迁移 `heat`，因为它是当前新增策略，而且层级最清晰：

- ST / 退市过滤
- 价格区间过滤
- 成交额过滤
- 换手率过滤
- 量比过滤
- 涨幅过滤

`heat` 迁移成功后，再迁移放量突破。

### 第四步：迁移放量突破 / 箱体 / 回踩 MA

迁移顺序建议：

1. `screen_volume_breakout`
2. `screen_box_consolidation`
3. `screen_breakout_pullback_ma`

原因：

- 放量突破和箱体共享大量箱体判断逻辑。
- 回踩 MA 依赖突破、均线、回踩三段，更适合最后迁移。

## 当前需要注意的坑

### 1. 不要全量补齐 sectors

`data.get_relation(stock_code)` 只应该对最终入选股票调用。

不要对 5000 多只全部 A 股调用，否则速度会很慢。

### 2. heat 的部分字段必须过滤前准备

虽然输出数据可以选后补齐，但 `heat` 过滤本身需要：

- `name`
- `turnover_rate`
- `price`
- `amount`
- `volume_ratio`
- `change_pct`

这些不能只在最终入选后才获取。

### 3. amount 单位

用户确认过：

- 条件 `amount_min` 用万元口径计算。
- 不修改 SQLite 原始数据。
- 输出 `latest_kline.amount` 继续按 SQLite 字段原口径。

### 4. 盘中 / 非盘中逻辑

`data.load_breakout_kline()` 已经有盘中/非盘中逻辑。

之前讨论过：

- 盘中时，如果最新一根本地 K 线不是今天，应拼接通达信最新 K 线。
- 如果最新一根本地 K 线已经是今天，则替换/覆盖为通达信最新 K 线。
- 非盘中不应该拉实时日 K。

后续重构时不要破坏这层逻辑。

### 5. 当前日志

当前 `screen.py` 已经开始加入耗时日志：

- `timed_step()`
- `elapsed_seconds()`
- `run_layer()` 记录每层耗时

重构时应保留全流程和每层耗时输出。

### 6. 控制台输出与 JSON 输出

当前 `print_screen_result(result, debug=False)` 还读取旧字段：

- `selected_count`
- `selected_codes`
- `selected_items`

重构后建议：

- 控制台普通输出从 `selected` 读取代码和数量。
- `--debug` 输出完整统一 JSON。
- 兼容期可以保留旧字段，但不要让旧字段继续成为主结构。

## 当前相关文件

- `screen.py`：当前选股入口和策略函数。
- `data.py`：数据中心，包含 `load_breakout_kline()`、`get_relation()`、`get_stock_info()`、`get_more_info()`。
- `business.py`：已有 `map_relation_type()`、`map_relation_rows()`、`extract_industry_and_concepts()`。
- `tdx_block_type_map.json`：板块代码分类表，但本次 screen 输出先不按它做 sectors 映射。
- `context/2026-07-09-screen.md`：screen 第一版设计。
- `context/2026-07-15-screen-v2.md`：资金热度、耗时日志、统一 JSON 输出方案记录。

## 推荐下一会话开场任务

下一会话可以直接让 Codex：

```text
阅读 context/2026-07-15-screen-v2-handoff.md、context/2026-07-15-screen-v2.md、screen.py、data.py、business.py。
按 handoff 方案重构 screen.py：
第一阶段先抽统一 JSON 输出和 selected 补齐函数，不改策略过滤结果。
```

第一阶段完成标准：

- `python screen.py heat --debug` 输出新统一 JSON。
- `scan-breakout`、`scan-box`、`scan-breakout-pullback-ma5` 也能输出同一外壳。
- `layers` 保留每层统计。
- `sectors` 只对最终入选股票补齐。
- `sectors` 只包含 `industry` 和 `concept`。
- `latest_kline` 对应 SQLite `daily_kline` 字段口径。
