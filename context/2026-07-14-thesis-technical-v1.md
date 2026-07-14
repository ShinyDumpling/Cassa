# Thesis 技术面预期：第一版骨架

## 主题概述

本文件记录 2026-07-14 围绕 `Cassa` 新版 `thesis` 功能的第一轮讨论，当前先聚焦：

```text
个股预期 -> 技术面 thesis
```

当前命名先确认使用：

```text
thesis
```

这里的 `thesis` 不是一句泛泛的“看多/看空”，而是一个可拆解、可验证、可追踪失效条件的结构化预期对象。

## 当前总体方向

用户当前设想：个股预期应从几个大方向构建：

1. 技术面
2. 情绪面
3. 消息面
4. 基本面（后续可单独补）

当前先只讨论第一块：

```text
技术面 thesis
```

## 对 `thesis` 的理解

当前建议把 `thesis` 理解为：

1. 先采集一组事实。
2. 再把事实组织成若干维度判断。
3. 最终输出一个“当前偏多 / 偏空 / 震荡 / 观望”的阶段性预期。
4. 同时给出：
   - 为什么得出这个预期
   - 哪些信号支持它
   - 哪些信号削弱它
   - 哪些条件一出现，这个预期就应失效

也就是说，`thesis` 不只是“预测结果”，还应包含“判断依据”和“失效条件”。

## 技术面第一版：当前确认的四个方向

用户当前确认技术面先从以下四个方向组织：

1. 技术状态
2. 裸 K（K 线形态）
3. 量价关系
4. MACD

这是一个可落地的第一版骨架，适合先从数据层和规则层搭起来。

## 技术面第一版骨架

### 1. 技术状态

当前用户列出的技术状态包括：

- `MA` 趋势
- 乖离率
- `RSI`
- 筹码分布
- 主力净流入
- `PE / PB`
- 成交量
- 量比
- 换手率

当前建议的理解方式：

1. `MA` 趋势、乖离率、`RSI`：更偏趋势位置与节奏判断。
2. 筹码分布：更偏成本结构与套牢/获利格局。
3. 主力净流入、成交量、量比、换手率：更偏资金活跃度与交易热度。
4. `PE / PB`：严格说更像估值/基本面，不是纯技术面；第一版可以先保留在技术状态里，但后续大概率应该从技术面拆出去，移到单独的估值/基本面维度。

当前第一版建议拆成几个更稳定的小组，避免“技术状态”这层过于宽：

- 趋势位置组：`MA`、乖离率、`RSI`
- 成本结构组：筹码分布
- 资金活跃组：成交量、量比、换手率、主力净流入
- 估值参考组：`PE / PB`（暂存，后续待定）

这里当前特别确认一层命名边界：

1. 这一组不叫“基本面”。
2. 原因是传统股票语境里，“基本面”通常更偏业绩、估值、财务、经营质量、行业地位。
3. 而这一组大多数内容本质上仍然是盘面状态、技术状态或资金行为。

因此当前文档统一使用：

```text
技术状态
```

### 2. 裸 K（K 线形态）

这一层建议只讨论“价格行为本身”，尽量少和指标混在一起。

当前可先预留的分析方向：

- 单根 K 线强弱：阳线实体、阴线实体、上下影线长度
- 关键反转形态：锤子线、吞没、早晨之星、黄昏之星
- 延续形态：连阳、连阴、平台突破后的确认 K
- 关键位置 K 线：支撑位附近、压力位附近、均线附近的反应
- 假突破 / 真突破：上影回落、放量站稳、突破后回踩

当前提醒：

1. 裸 K 这一层如果定义过多，容易变成“形态词典堆砌”。
2. 第一版更适合只保留少量、解释力强、能和交易动作相关的形态。
3. 裸 K 判断最好和“出现位置”绑定，否则同样的形态在不同位置意义完全不同。

### 3. 量价关系

这一层建议单独保留，不要并入技术状态，因为它关注的是“价格变化”和“成交行为”之间是否一致。

当前可先预留的分析方向：

- 放量上涨
- 缩量上涨
- 放量下跌
- 缩量下跌
- 缩量回调
- 放量突破
- 放量滞涨
- 高位放量分歧
- 低位放量异动

当前建议：

1. 量价关系更像“行为解释层”，不是单点指标。
2. 它和裸 K、`MA`、支撑压力的结合会很关键。
3. 第一版最好先把这些关系做成少量稳定标签，而不是上来就做很复杂的自然语言解释。

### 4. MACD

`MACD` 当前建议单独保留，因为它既是趋势指标，也是节奏指标，在现有 `business.py report` 里已经有较成熟基础。

当前可先预留的分析方向：

- 金叉 / 死叉
- 零轴上金叉 / 零轴下金叉
- 红柱放大 / 红柱缩短
- 绿柱缩短 / 绿柱放大
- `DIF` 与 `DEA` 的相对位置
- 零轴位置
- 背离（后续再谨慎讨论）

当前提醒：

1. `MACD` 很适合做趋势确认和节奏确认。
2. 背离判断通常最容易写得复杂且主观，第一版可以先不急着纳入硬规则。

## 建议的技术面 thesis 结构

当前建议不要把技术面直接做成一段文字，而是先整理成结构化对象，再决定控制台展示、Markdown 报告或后续 LLM 输入。

建议第一版可以长成：

```json
{
  "technical_thesis": {
    "bias": "bullish",
    "confidence": 0,
    "trend_assessment": {},
    "price_action_assessment": {},
    "volume_price_assessment": {},
    "macd_assessment": {},
    "supporting_signals": [],
    "weakening_signals": [],
    "invalidating_signals": [],
    "notes": []
  }
}
```

这里只是骨架，不是最终字段定稿。

## 当前建议的输出目标

技术面 thesis 第一版建议至少回答下面几个问题：

1. 当前技术面整体偏多、偏空、震荡还是中性？
2. 这个判断主要由哪几类信号支撑？
3. 当前更像趋势延续、回调中的机会，还是高位风险区？
4. 哪些现象是风险提示？
5. 什么条件出现后，这个技术面判断就应失效？

## 情绪面骨架（本轮先定命名，不展开细节）

虽然这份文件当前主讨论对象仍然是“技术面 thesis”，但本轮已先确认上层有一个独立维度：

```text
情绪面
```

当前用户的意思是：凡是和大盘、市场风险偏好、板块强弱、整体赚钱效应有关，并且需要结合大盘板块分析来理解的内容，先统一归到：

```text
情绪面
```

当前可先预留三个入口词：

1. `market`
2. 板块
3. 情绪

这里的关键不是字面上多了一个“情绪”，而是确认一件事：

1. 大盘点位本身不是目的。
2. 真正要抽取的是市场当下是否愿意给溢价、资金风格偏向哪里、板块是否有持续性、赚钱效应是否扩散。
3. 所以这一层叫“情绪面”比叫“大盘面”或“基础面”更准确。

当前先记为骨架，后续单独开一份 context 细化也可以。

## 当前讨论点

### 1. `PE / PB` 是否放在技术状态里

我的看法：

`PE / PB` 更像估值或基本面参考，不属于严格意义上的技术面，也不完全属于纯粹的技术状态。

如果我们后面会把 `thesis` 做成下面几层：

1. 技术面
2. 情绪面
3. 消息面
4. 基本面

那么我反而建议再补一个单独维度：

```text
基本面 / 估值面
```

否则 `PE / PB` 放在技术面里会让边界有点混。

当前折中方案：

第一版 context 先保留 `PE / PB`，但明确标记为“待讨论，后续可能拆出技术状态，移入基本面/估值面”。

### 2. 主力净流入到底算技术面还是资金面

我的看法：

它更像“资金行为信号”，可以先留在技术面内部，但最好作为技术面里的一个子组，而不是混在纯价格指标里。

### 3. 裸 K、量价关系、MACD 三者会有重叠

我的看法：

这不是问题，关键是职责要分清：

- 裸 K：看价格形态本身
- 量价关系：看价格与成交是否匹配
- `MACD`：看趋势动能与节奏

只要这三个层的输出口径不同，就不会乱。

### 4. 技术面第一版应优先做“解释”还是“打分”

我的看法：

第一版最好“两条都保留，但以结构化判断为主”：

1. 先做清晰标签和判断结论
2. 再决定是否汇总成分数

原因是：

单纯打分很容易好用但不可解释，单纯解释又不利于后续比较和回测。

## 当前建议的实施顺序

如果后续继续往下做，建议按下面顺序推进：

1. 先把技术面 thesis 的结构字段定下来。
2. 再明确每一块到底依赖哪些已有数据。
3. 再区分哪些可以直接复用 `business.py report` 现有结果。
4. 再决定第一版哪些判断先做硬规则，哪些先只做观察字段。
5. 最后再决定是否把技术面 thesis 接到控制台输出、JSON 输出或后续 LLM prompt。

## 当前可直接复用的现有能力

从当前 `Cassa` 已有代码看，下面这些能力已经有基础，后续很可能直接复用：

- `MA` 趋势
- 乖离率
- `RSI`
- 成交量 / 量比 / 换手率
- 支撑压力
- `MACD`
- 筹码分布
- 主力净流入
- `PE / PB`

也就是说，技术面 thesis 第一版不一定要从零开始写，更像是在现有 `business.py report` 数据采集能力和判断能力之上，再整理出一层更适合“预期”的结构。

## Thesis 第一版技术实现方案

### 当前目标

当前先不考虑 `report` 的输出形态，也不从 `report` 入口派生业务，而是单独设计 `thesis`。

第一版只跑通一个最小闭环：

```text
入口（获取股票或板块 code）
  -> 获取 data
  -> 执行量价关系模块分析
  -> 组装 thesis 结果
  -> 输出控制台摘要
  -> debug 模式输出完整 JSON
```

当前确认：流转数据和结果数据全部使用 JSON。

字段不在当前阶段一次性定死，而是在实现各模块时逐步稳定。第一版只先确定外层骨架，避免过早设计一个庞大的 schema。

### 命名确认

当前统一使用：

```text
data
```

不使用：

```text
facts
```

原因：

1. 项目里已经有 `data.py` 数据中心，`data` 这个词和现有语感一致。
2. `thesis` 的分析模块消费的是“业务数据包”，而不是直接消费零散原始接口。
3. 后续所有模块都应接收 `data`，输出标准化 `module_result`。

### 第一版数据流

建议第一版数据结构长这样：

```json
{
  "task": "thesis",
  "created_at": "2026-07-14 00:00:00",
  "items": [
    {
      "target": {
        "raw_code": "002185",
        "target_type": "stock",
        "code": "002185.SZ",
        "name": "华天科技"
      },
      "data": {
        "market_snapshot": {},
        "stock_info": {},
        "more_info": {},
        "relation": [],
        "daily_kline": [],
        "macd": [],
        "chip": {}
      },
      "module_results": [],
      "thesis": {}
    }
  ],
  "errors": []
}
```

### 第一版函数流

建议先新增这些函数：

```text
collect_thesis_data
build_thesis_data
analyze_volume_price
assemble_thesis_from_modules
build_thesis_item
build_thesis_payload
render_thesis_item
render_thesis_output
run_thesis
```

这里的关键边界：

1. `collect_thesis_data` 负责把分析所需数据一次性取齐。
2. `analyze_volume_price` 只消费 `data`，不再自己调用 `data.py`。
3. `assemble_thesis_from_modules` 只消费模块结果，不关心每个模块内部怎么算。
4. 后续新增技术状态、裸 K、`MACD` 时，都按同一类 `module_result` 外壳输出。

### 第一版 data 采集范围

当前先照着 `business.py report` 的采集逻辑取数据，暂时够用：

```text
market_snapshot
stock_info
more_info
relation
daily_kline
macd
chip
```

当前建议不要直接调用：

```python
build_report_data(codes)
```

而是复用 `business.py` 中更底层的采集函数：

```python
collect_realtime_report_data(code)
collect_daily_kline_for_report(code)
collect_macd_for_report(code)
collect_chip_for_report(item)
```

原因是：

1. `report` 是展示任务，`thesis` 是预期任务。
2. 两者第一版可以共享数据范围，但业务语义不要绑死。
3. 后续 `report` 输出格式变化，不应该影响 `thesis` 的数据流。

### 模块结果统一外壳

第一版模块结果先统一成：

```json
{
  "module": "volume_price",
  "bias": "bullish",
  "confidence": 65,
  "signals": [],
  "risks": [],
  "invalidations": [],
  "summary": ""
}
```

字段含义：

```text
module        模块名
bias          模块方向，先用 bullish / bearish / neutral / mixed
confidence    模块置信度，0-100
signals       支撑信号
risks         风险或削弱信号
invalidations 失效条件
summary       模块一句话结论
```

### 第一版量价关系逻辑

先把函数名字写了，逻辑先空着

## Thesis 第一版完整代码草案

以下代码是后续可合入 `business.py` 的完整草案。当前只记录方案，不要求本次立即落地真实代码。

### 新增常量

```python
THESIS_VOLUME_PRICE_MODULE = "volume_price"
THESIS_BIAS_BULLISH = "bullish"
THESIS_BIAS_BEARISH = "bearish"
THESIS_BIAS_NEUTRAL = "neutral"
THESIS_BIAS_MIXED = "mixed"
```

### 新增工具函数

```python
def get_latest_two_kline_rows(daily_kline):
    """返回最新两根有效 K 线，用于 thesis 分析。"""
    rows = []
    for row in daily_kline or []:
        close_price = safe_float(
            row.get("close")
            or row.get("Close")
            or row.get("close_price")
        )
        if close_price and close_price > 0:
            rows.append(row)
    if len(rows) < 2:
        return None, None
    return rows[-2], rows[-1]


def get_kline_close(row):
    """从 K 线记录中读取收盘价。"""
    if not isinstance(row, dict):
        return 0.0
    return safe_float(
        row.get("close")
        or row.get("Close")
        or row.get("close_price"),
        0.0,
    )


def get_kline_low(row):
    """从 K 线记录中读取最低价。"""
    if not isinstance(row, dict):
        return 0.0
    return safe_float(
        row.get("low")
        or row.get("Low")
        or row.get("low_price"),
        0.0,
    )


def get_kline_volume(row):
    """从 K 线记录中读取成交量。"""
    if not isinstance(row, dict):
        return 0.0
    return safe_float(
        row.get("volume")
        or row.get("Volume"),
        0.0,
    )


def calculate_average_volume(daily_kline, count=5):
    """计算最近 count 根有效 K 线的平均成交量。"""
    volumes = []
    for row in daily_kline or []:
        volume = get_kline_volume(row)
        if volume and volume > 0:
            volumes.append(volume)
    if not volumes:
        return 0.0
    recent_volumes = volumes[-count:]
    return sum(recent_volumes) / len(recent_volumes)


def create_signal(name, level, reason, value=None):
    """创建统一的信号对象。"""
    signal = {
        "name": name,
        "level": level,
        "reason": reason,
    }
    if value is not None:
        signal["value"] = value
    return signal
```

### 新增 data 采集函数

```python
def collect_thesis_data(target):
    """采集 thesis 所需 data；第一版复用 report 底层采集逻辑。"""
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

    target_payload = {
        "raw_code": item["raw_code"],
        "target_type": item["target_type"],
        "code": item["code"],
        "name": item["name"],
    }
    data_payload = {
        "market_snapshot": item["market_snapshot"],
        "stock_info": item["stock_info"],
        "more_info": item["more_info"],
        "relation": item["relation"],
        "daily_kline": item["daily_kline"],
        "macd": item["macd"],
        "chip": item["chip"],
    }
    return {
        "target": target_payload,
        "data": data_payload,
    }


def build_thesis_data(codes):
    """批量解析 code 并采集 thesis data。"""
    targets = resolve_report_codes(codes)
    items = []
    errors = []

    for target in targets:
        try:
            items.append(collect_thesis_data(target))
        except Exception as exc:
            errors.append(
                {
                    "raw_code": target.get("raw_code", ""),
                    "code": target.get("code", ""),
                    "target_type": target.get("target_type", ""),
                    "error": str(exc),
                }
            )

    return items, errors
```

### 新增量价关系分析模块

```python
def analyze_volume_price(data_payload):
    """分析量价关系，返回统一 module_result。"""
    daily_kline = data_payload.get("daily_kline") or []
    more_info = data_payload.get("more_info") or {}
    previous_row, latest_row = get_latest_two_kline_rows(daily_kline)

    if previous_row is None or latest_row is None:
        return {
            "module": THESIS_VOLUME_PRICE_MODULE,
            "bias": THESIS_BIAS_NEUTRAL,
            "confidence": 0,
            "signals": [],
            "risks": [
                create_signal(
                    "样本不足",
                    "warning",
                    "有效 K 线不足，暂时无法判断量价关系。",
                )
            ],
            "invalidations": [],
            "summary": "量价关系暂不可判断",
        }

    previous_close = get_kline_close(previous_row)
    latest_close = get_kline_close(latest_row)
    latest_low = get_kline_low(latest_row)
    latest_volume = get_kline_volume(latest_row)
    average_volume_5 = calculate_average_volume(daily_kline[:-1], count=5)
    official_volume_ratio = safe_float(more_info.get("fLianB"), 0.0)
    turnover_rate = safe_float(more_info.get("fHSL"), 0.0)

    price_change_pct = 0.0
    if previous_close > 0:
        price_change_pct = (latest_close / previous_close - 1.0) * 100.0

    volume_ratio_to_ma5 = 0.0
    if average_volume_5 > 0:
        volume_ratio_to_ma5 = latest_volume / average_volume_5

    signals = []
    risks = []
    invalidations = []
    bias = THESIS_BIAS_NEUTRAL
    confidence = 50
    summary = "量价关系中性"

    if latest_close > previous_close and volume_ratio_to_ma5 >= 1.2:
        bias = THESIS_BIAS_BULLISH
        confidence = 70
        summary = "放量上涨，量价配合偏积极"
        signals.append(
            create_signal(
                "放量上涨",
                "positive",
                "最新收盘价高于前一日，且成交量明显高于近 5 日均量。",
                round(volume_ratio_to_ma5, 4),
            )
        )
    elif latest_close > previous_close and 0 < volume_ratio_to_ma5 <= 0.8:
        bias = THESIS_BIAS_MIXED
        confidence = 55
        summary = "缩量上涨，上涨延续性需要观察"
        signals.append(
            create_signal(
                "缩量上涨",
                "mixed",
                "价格上涨但成交量低于近 5 日均量，说明追涨资金不够积极。",
                round(volume_ratio_to_ma5, 4),
            )
        )
    elif latest_close < previous_close and volume_ratio_to_ma5 >= 1.2:
        bias = THESIS_BIAS_BEARISH
        confidence = 70
        summary = "放量下跌，量价关系偏弱"
        risks.append(
            create_signal(
                "放量下跌",
                "negative",
                "最新收盘价低于前一日，且成交量明显高于近 5 日均量。",
                round(volume_ratio_to_ma5, 4),
            )
        )
    elif latest_close < previous_close and 0 < volume_ratio_to_ma5 <= 0.8:
        bias = THESIS_BIAS_NEUTRAL
        confidence = 55
        summary = "缩量回调，暂未出现明显恐慌放量"
        signals.append(
            create_signal(
                "缩量回调",
                "watch",
                "价格回调但成交量低于近 5 日均量，暂时更像正常回落。",
                round(volume_ratio_to_ma5, 4),
            )
        )
    else:
        signals.append(
            create_signal(
                "量价平衡",
                "neutral",
                "价格和成交量没有出现明显方向性组合。",
                round(volume_ratio_to_ma5, 4) if volume_ratio_to_ma5 > 0 else None,
            )
        )

    if official_volume_ratio >= 2:
        signals.append(
            create_signal(
                "量比活跃",
                "positive",
                "通达信量比较高，说明当日成交活跃度明显抬升。",
                round(official_volume_ratio, 4),
            )
        )
        confidence = min(confidence + 5, 100)

    if turnover_rate >= 8:
        risks.append(
            create_signal(
                "换手过高",
                "warning",
                "换手率较高，说明筹码分歧较大，需警惕高位震荡。",
                round(turnover_rate, 4),
            )
        )

    if latest_low > 0:
        invalidations.append(
            {
                "name": "跌破最新 K 线低点",
                "condition": f"close < {latest_low:.2f}",
                "reason": "如果后续放量跌破最新 K 线低点，当前量价判断失效。",
            }
        )

    return {
        "module": THESIS_VOLUME_PRICE_MODULE,
        "bias": bias,
        "confidence": confidence,
        "metrics": {
            "previous_close": round(previous_close, 4),
            "latest_close": round(latest_close, 4),
            "price_change_pct": round(price_change_pct, 4),
            "latest_volume": round(latest_volume, 4),
            "average_volume_5": round(average_volume_5, 4),
            "volume_ratio_to_ma5": round(volume_ratio_to_ma5, 4),
            "official_volume_ratio": round(official_volume_ratio, 4),
            "turnover_rate": round(turnover_rate, 4),
        },
        "signals": signals,
        "risks": risks,
        "invalidations": invalidations,
        "summary": summary,
    }
```

### 新增 thesis 组装函数

```python
def merge_module_signals(module_results, key):
    """从模块结果中合并 signals / risks / invalidations。"""
    merged = []
    for result in module_results or []:
        values = result.get(key) or []
        if isinstance(values, list):
            merged.extend(values)
    return merged


def assemble_thesis_from_modules(module_results):
    """根据模块结果组装最终 thesis；第一版只有量价关系模块。"""
    valid_results = [
        result
        for result in module_results or []
        if isinstance(result, dict) and result.get("module")
    ]
    if not valid_results:
        return {
            "bias": THESIS_BIAS_NEUTRAL,
            "confidence": 0,
            "summary": "暂无可用模块结果，无法生成预期。",
            "supporting_signals": [],
            "risks": [],
            "invalidations": [],
        }

    bias_scores = {
        THESIS_BIAS_BULLISH: 1,
        THESIS_BIAS_MIXED: 0,
        THESIS_BIAS_NEUTRAL: 0,
        THESIS_BIAS_BEARISH: -1,
    }
    weighted_score = 0.0
    total_weight = 0.0
    confidences = []

    for result in valid_results:
        confidence = safe_float(result.get("confidence"), 0.0)
        bias = str(result.get("bias") or THESIS_BIAS_NEUTRAL)
        weighted_score += bias_scores.get(bias, 0) * confidence
        total_weight += confidence
        confidences.append(confidence)

    normalized_score = weighted_score / total_weight if total_weight > 0 else 0.0
    average_confidence = sum(confidences) / len(confidences) if confidences else 0.0

    if normalized_score >= 0.25:
        thesis_bias = THESIS_BIAS_BULLISH
        summary = "当前预期偏多。"
    elif normalized_score <= -0.25:
        thesis_bias = THESIS_BIAS_BEARISH
        summary = "当前预期偏空。"
    elif abs(normalized_score) < 0.1:
        thesis_bias = THESIS_BIAS_NEUTRAL
        summary = "当前预期偏中性。"
    else:
        thesis_bias = THESIS_BIAS_MIXED
        summary = "当前预期多空信号混合。"

    module_summaries = [
        str(result.get("summary") or "").strip()
        for result in valid_results
        if str(result.get("summary") or "").strip()
    ]
    if module_summaries:
        summary = f"{summary} {'；'.join(module_summaries)}"

    return {
        "bias": thesis_bias,
        "confidence": round(average_confidence, 2),
        "summary": summary,
        "supporting_signals": merge_module_signals(valid_results, "signals"),
        "risks": merge_module_signals(valid_results, "risks"),
        "invalidations": merge_module_signals(valid_results, "invalidations"),
    }


def build_thesis_item(data_item):
    """对单个 target 的 data 进行模块分析并组装 thesis。"""
    data_payload = data_item.get("data") or {}
    module_results = [
        analyze_volume_price(data_payload),
    ]
    return {
        "target": data_item.get("target") or {},
        "data": data_payload,
        "module_results": module_results,
        "thesis": assemble_thesis_from_modules(module_results),
    }


def build_thesis_payload(codes):
    """构建 thesis 完整 JSON payload。"""
    codes = [code.strip() for code in codes if code.strip()]
    data_items, errors = build_thesis_data(codes)
    items = []

    for data_item in data_items:
        try:
            items.append(build_thesis_item(data_item))
        except Exception as exc:
            target = data_item.get("target") or {}
            errors.append(
                {
                    "raw_code": target.get("raw_code", ""),
                    "code": target.get("code", ""),
                    "target_type": target.get("target_type", ""),
                    "error": str(exc),
                }
            )

    return {
        "task": "thesis",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "items": items,
        "errors": errors,
    }
```

### 新增输出与 CLI 函数

```python
def format_signal_names(values):
    """把信号对象列表压缩成控制台摘要。"""
    names = []
    for value in values or []:
        if isinstance(value, dict):
            name = str(value.get("name") or "").strip()
            if name:
                names.append(name)
    return "、".join(names) if names else "无"


def render_thesis_item(item):
    """渲染单个 thesis 控制台摘要。"""
    target = item.get("target") or {}
    thesis = item.get("thesis") or {}
    module_results = item.get("module_results") or []
    volume_price_result = next(
        (
            result
            for result in module_results
            if result.get("module") == THESIS_VOLUME_PRICE_MODULE
        ),
        {},
    )

    lines = [
        f"=== {strip_code_suffix(target.get('code', ''))} {target.get('name', '')} ===".rstrip(),
        f"预期: {thesis.get('bias', '')}  置信度: {safe_float(thesis.get('confidence'), 0.0):.0f}",
    ]

    if thesis.get("summary"):
        lines.append(f"结论: {thesis.get('summary')}")

    if volume_price_result:
        lines.append(f"量价: {volume_price_result.get('summary', '')}")

    supporting_text = format_signal_names(thesis.get("supporting_signals"))
    risk_text = format_signal_names(thesis.get("risks"))
    lines.append(f"支撑信号: {supporting_text}")
    lines.append(f"风险信号: {risk_text}")

    invalidations = thesis.get("invalidations") or []
    if invalidations:
        invalidation_text = format_signal_names(invalidations)
        lines.append(f"失效条件: {invalidation_text}")

    return "\n".join(lines)


def render_thesis_output(payload):
    """渲染 thesis 控制台输出。"""
    items = payload.get("items") or []
    lines = [f"个股预期 thesis：{len(items)} 只股票", ""]
    for index, item in enumerate(items):
        lines.append(render_thesis_item(item))
        if index < len(items) - 1:
            lines.append("")

    errors = payload.get("errors") or []
    if errors:
        lines.append("")
        lines.append(f"跳过 {len(errors)} 只:")
        for error in errors:
            lines.append(f"  - {error.get('raw_code', '') or error.get('code', '')}: {error.get('error', '')}")
    return "\n".join(lines)


def run_thesis(args):
    """执行 thesis 子命令。"""
    codes = [code.strip() for code in args.codes.split(",") if code.strip()]
    payload = build_thesis_payload(codes)
    print(render_thesis_output(payload))
    if args.debug:
        print()
        print("=== DEBUG JSON ===")
        print_json(payload)
```

### CLI 接入口草案

在 `main()` 中新增：

```python
thesis_parser = subparsers.add_parser("thesis", help="生成个股预期 thesis")
thesis_parser.add_argument(
    "--codes",
    required=True,
    help="股票或板块代码，多个用逗号分隔，例如 600519,000001,880675.SH",
)
thesis_parser.add_argument("--debug", action="store_true", help="追加打印完整 JSON")
```

并在命令分发处新增：

```python
elif args.command == "thesis":
    run_thesis(args)
```

### 第一版验证命令

后续代码落地后，优先验证：

```powershell
python business.py thesis --codes 002185
python business.py thesis --codes 002185 --debug
```

预期：

1. 默认输出简短 thesis 摘要。
2. `--debug` 输出完整 JSON。
3. JSON 顶层包含 `task`、`created_at`、`items`、`errors`。
4. 每个 item 包含 `target`、`data`、`module_results`、`thesis`。
5. 第一版 `module_results` 里只有 `volume_price`。
6. 后续新增模块时，只需要往 `module_results` 继续 append 结果。

## TODO / 下一步

- 明确 `technical_thesis` 的最终字段结构
- 明确“技术状态 / 裸 K / 量价关系 / MACD”四块分别输出“原始事实 / 中间判断 / 最终结论”哪些字段
- 决定 `PE / PB` 是否继续保留在技术状态内
- 决定裸 K 第一版只保留哪些高价值形态
- 决定量价关系第一版的标签集合
- 决定 `MACD` 第一版是否纳入背离
- 决定技术面 thesis 是否需要统一评分，还是只输出标签与理由
- 讨论情绪面、消息面、基本面与技术面之间最终如何汇总成总 thesis

## 来源会话

- 当前会话（2026-07-14）
