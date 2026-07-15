# Handoff：Cassa / thises 预期功能设计与量价分析 skill

## 当前项目位置

- 工作区：`D:\股神养成plan`
- 项目目录：`D:\股神养成plan\Cassa`
- 主要 context：
  - `D:\股神养成plan\Cassa\context\2026-07-14-thises-v2.md`
  - `D:\股神养成plan\Cassa\context\2026-07-09-data-center.md`
- 主要 skill：
  - `D:\股神养成plan\Cassa\skills\thises-volume-price\SKILL.md`
  - `D:\股神养成plan\Cassa\skills\coulling-volume-price-analysis\SKILL.md`
- 主要代码：
  - `D:\股神养成plan\Cassa\business.py`
  - `D:\股神养成plan\Cassa\data.py`

## 用户偏好

- 用户在设计 thises / thesis 功能，喜欢一步一步讨论。
- 用户明确说“先讨论 / 先说思路 / 不要写代码 / 不要写 context”时，必须只讨论，不动文件。
- 用户要求写 context 时，通常要写在文件最下面，新开章节，章节名带日期。
- 用户强调：记录 context 时不要擅自发挥，只润色用户表达。
- 用户喜欢 context 里写清楚：原因、方案、完整代码。
- skill 中路径不要写绝对路径，写相对路径。
- 修改前一定先读现有文件，避免覆盖用户手动改动。

## thises 功能总体设计

用户把“预期”功能命名为 `thesis / thises`。

当前 thises V2 思路：

```text
Agent 编排
-> 调用 CLI 获取输入数据
-> 将数据传给量价分析 skill
-> skill 输出结构化 JSON 分析结果
```

当前第一版只跑通“量价关系”模块，后续再接其他模块。

### Agent 编排命令

```bash
python business.py thises --codes <code>
```

其中 `<code>` 可以是股票或板块 code，判断股票/板块的逻辑复用 report。

## context 文件状态

### `2026-07-14-thises-v2.md`

已创建，标题为：

```markdown
# Thises V2：第一版方案设计
```

顶部已有 TODO list：

```markdown
## TODO

- [ ] 15/60分钟K线交叉分析
```

文件中已记录多个阶段设计，包括：

- thises CLI 收集日 K 数据
- thises 输出只保留量价分析需要的数据
- 修复个股 name 为空
- 新增筹码分布
- `data_type` 调整为 `thises_input`
- `daily_kline[].volume_ratio`
- `market_context`
- 最新一根 K 线 `volume_ratio` 用 `more_info.fLianB` 覆盖
- stage 改为阶段区间输出

最近追加过的重要章节：

```markdown
## 2026-07-15 更新：最新一根 K 线 volume_ratio 使用通达信官方量比
```

该章节只写入 context，未必已经实现到代码。

核心方案：

```text
非最新 K：volume_ratio = 当日成交量 / 前 5 日平均成交量
最新 K：volume_ratio = more_info.fLianB
```

不管盘中还是非盘中，只要 `more_info.fLianB > 0`，就覆盖最新一根 K 的 `volume_ratio`。

原因：如果盘中，最新 K 的成交量只是盘中累计量，自己用前 5 日均量计算会失真；report 已使用 `more_info.fLianB` 作为量比口径。

### `2026-07-09-data-center.md`

底部已追加：

```markdown
## 2026-07-14 第五次更新：修复 load_daily_kline 未拼接盘中实时 K 的问题
```

记录了 bug、原因、影响、方案和完整代码。

## data.py 当前关键逻辑

`data.py` 已修复：

- `load_daily_kline()` 现在有盘中判断。
- 如果当前是 A 股盘中，并且目标日期是今天，会拼接 / 覆盖最新一根实时 K。
- `load_breakout_kline()` 不再重复做拼接，改为调用 `load_daily_kline()`。
- `is_a_share_intraday()` 当前按工作日：
  - `09:30-11:30`
  - `13:00-15:00`
- 午间不算盘中。

相关函数大致为：

```python
def should_merge_realtime_daily_kline(end_date=None):
    ...

def merge_realtime_daily_kline_map(...):
    ...

def load_daily_kline(...):
    ...

def load_breakout_kline(...):
    ...
```

## business.py 当前状态

`thises` 命令已经存在。

当前 `collect_thises_data(target)` 大致结构为：

```python
def collect_thises_data(target):
    """收集 thises 量价分析所需的日 K 数据和筹码分布。"""
    code = target["code"]
    realtime_data = collect_realtime_report_data(code)
    daily_kline = add_volume_ratio_to_daily_kline(
        collect_daily_kline_for_report(code)
    )

    item_for_chip = {
        "code": code,
        "market_snapshot": realtime_data["market_snapshot"],
        "stock_info": realtime_data["stock_info"],
        "more_info": realtime_data["more_info"],
        "daily_kline": daily_kline,
    }

    return {
        "raw_code": target.get("raw_code", ""),
        "target_type": target.get("target_type", ""),
        "code": code,
        "name": realtime_data["name"] or target.get("name", ""),
        "daily_kline": daily_kline,
        "chip": collect_chip_for_report(item_for_chip),
    }
```

已有函数：

```python
def add_volume_ratio_to_daily_kline(daily_kline):
    """给日 K 增加 volume_ratio，口径为当日成交量 / 前 5 日平均成交量。"""
    ...
```

但截至 handoff，需要注意：

- 最新一根 K 使用 `more_info.fLianB` 覆盖 `volume_ratio` 的代码，已经写入 context，但可能还没真正实现到 `business.py`。
- 下次如果用户要求“实现”，应先 inspect `business.py` 当前文件，再新增：

```python
def apply_latest_official_volume_ratio(daily_kline, more_info):
    """用通达信官方量比 fLianB 覆盖最新一根 K 线的 volume_ratio。"""
    result = [dict(row) for row in daily_kline or []]
    if not result:
        return result

    official_volume_ratio = safe_float((more_info or {}).get("fLianB"), 0.0)
    if official_volume_ratio > 0:
        result[-1]["volume_ratio"] = round(official_volume_ratio, 6)

    return result
```

并修改：

```python
daily_kline = add_volume_ratio_to_daily_kline(
    collect_daily_kline_for_report(code)
)
daily_kline = apply_latest_official_volume_ratio(
    daily_kline,
    realtime_data["more_info"],
)
```

## thises 输出数据结构

目标结构大致是：

```json
{
  "task": "thises",
  "data_type": "thises_input",
  "created_at": "",
  "market_context": {
    "as_of": "2026-07-15 10:42:00",
    "is_intraday": true
  },
  "items": [
    {
      "raw_code": "002422",
      "target_type": "stock",
      "code": "002422.SZ",
      "name": "",
      "daily_kline": [],
      "chip": {}
    }
  ],
  "errors": []
}
```

注意：

- `market_context` 的方案已写入 context。
- `coulling-volume-price-analysis` skill 目前已经要求 `market_context`。
- 但 `business.py thises` 是否已经实际输出 `market_context`，需要下次 inspect 确认。

## thises-volume-price skill 状态

文件：

```text
D:\股神养成plan\Cassa\skills\thises-volume-price\SKILL.md
```

用途：

- Agent 调用此 skill 执行 thises 量价分析编排。
- 它会运行：

```bash
python business.py thises --codes <codes>
```

- 读取完整 JSON。
- 从 JSON 中取出每个 item 的数据。
- 调用相对路径：

```text
skills/coulling-volume-price-analysis
```

重要约束：

- 前面 CLI 输出不允许截断。
- 不允许只看头尾、不允许摘要、不允许省略 `daily_kline`。
- 如果输出太长，必须通过文件或其他完整机制读取完整 JSON 后再分析。

## coulling-volume-price-analysis skill 状态

文件：

```text
D:\股神养成plan\Cassa\skills\coulling-volume-price-analysis\SKILL.md
```

这是最终做量价分析的 skill。

### 输入 JSON

当前规定输入为单个标的对象，大致：

```json
{
  "code": "881394.SH",
  "name": "证券",
  "market_context": {
    "as_of": "2026-07-15 10:42:00",
    "is_intraday": true
  },
  "daily_kline": [
    {
      "code": "881394.SH",
      "trade_date": "2026-07-14",
      "open_price": 999.64,
      "high_price": 1004.66,
      "low_price": 990.07,
      "close_price": 999.2,
      "volume": 20106216.0,
      "amount": 2332839.25,
      "volume_ratio": 1.23
    }
  ],
  "chip": {
    "profit_ratio": 0.72,
    "avg_cost": 29.8,
    "cost_90_low": 27.5,
    "cost_90_high": 32.2,
    "concentration_90": 0.16,
    "cost_70_low": 28.6,
    "cost_70_high": 31.1,
    "concentration_70": 0.1,
    "chip_status": "较集中",
    "sample_count": 120
  }
}
```

必需字段包括：

- `code`
- `name`
- `market_context`
- `market_context.as_of`
- `market_context.is_intraday`
- `daily_kline`
- `daily_kline[].code`
- `daily_kline[].trade_date`
- `daily_kline[].open_price`
- `daily_kline[].high_price`
- `daily_kline[].low_price`
- `daily_kline[].close_price`
- `daily_kline[].volume`
- `daily_kline[].amount`
- `daily_kline[].volume_ratio`
- `chip`

### 数据使用限制

skill 明确要求：

- 只能使用输入 JSON 提供的数据。
- 可以计算直接派生指标：
  - 涨跌幅
  - K 线实体
  - 上下影线
  - 成交量相对变化
  - 区间高低点
- 不得自行引入、计算或假设不存在的数据：
  - 换手率
  - MACD
  - RSI
  - MA
  - 主力净流入
  - PE/PB
  - 新闻或消息面
  - 大盘或板块情绪

### market_context 盘中盘外约束

skill 已写入：

如果 `market_context.is_intraday == true`：

- 最后一根 `daily_kline` 是盘中临时 K。
- 涉及成交量、收盘价、上下影线、实体、突破确认、反转确认、放量确认、缩量确认等判断，必须说明是“盘中暂态判断”。
- 不得把最后一根 K 当作收盘后定型 K。
- 不得输出：
  - 已经确认突破
  - 已经确认跌破
  - 已经完成反转
  - 已经确认放量止涨/止跌
- 应表达为：
  - 盘中暂时出现
  - 若收盘仍保持则可确认
  - 当前仅为盘中迹象

如果 `market_context.is_intraday == false`：

- 最后一根 K 可视为完整日 K。
- 可以基于最后一根 K 做收盘级确认。

### 输出 JSON

当前输出包含：

```json
{
  "code": "",
  "name": "",
  "direction": {},
  "truth": {},
  "stage": {},
  "smart_money": {},
  "reversal": {},
  "key_price": {},
  "chip": {}
}
```

已明确移除过：

```json
"module": "coulling_volume_price_analysis"
```

不要再加回去。

### 普通模块输出结构

普通模块包括：

- `direction`
- `truth`
- `smart_money`
- `reversal`
- `key_price`

结构：

```json
{
  "result": "",
  "data": [
    {
      "kline": {
        "code": "",
        "trade_date": "",
        "open_price": 0,
        "high_price": 0,
        "low_price": 0,
        "close_price": 0,
        "volume": 0,
        "amount": 0,
        "volume_ratio": 0
      },
      "evidence": ""
    }
  ],
  "refs": ["", "", ""]
}
```

### stage 模块最新改动

用户刚要求：

> 能否把这个 stage 的输出修改成，根据提供的历史 K 线，列出这一段 K 线中每个阶段的开始时间和结束时间？阶段包含吸筹、测试、拉升、派筹、下跌？

已经修改 `coulling-volume-price-analysis/SKILL.md`。

现在 `stage` 不再是“当前处于哪个阶段”的单点判断，而是历史区间切分：

```json
"stage": {
  "result": "",
  "data": [
    {
      "stage": "吸筹",
      "start_date": "",
      "end_date": "",
      "summary": "",
      "evidence": [
        {
          "kline": {
            "code": "",
            "trade_date": "",
            "open_price": 0,
            "high_price": 0,
            "low_price": 0,
            "close_price": 0,
            "volume": 0,
            "amount": 0,
            "volume_ratio": 0
          },
          "evidence": ""
        }
      ]
    }
  ],
  "refs": ["", "", ""]
}
```

阶段枚举限定为：

```text
吸筹、测试、拉升、派筹、下跌
```

并增加规则：

- `stage.data` 必须按时间从早到晚排列。
- `start_date` / `end_date` 必须来自输入 `daily_kline[].trade_date`。
- `summary` 说明为什么这段 K 线被归入该阶段。
- `evidence` 中每条 K 线必须原样复制输入日 K。
- 如果某一段历史 K 线阶段不清晰，不能强行切分，必须在 `summary` 中说明“不足以明确判断”，并用最接近的阶段名称归类。

### chip 模块

`chip` 模块结构特殊：

```json
"chip": {
  "result": "",
  "data": {
    "chip": {
      "profit_ratio": 0,
      "avg_cost": 0,
      "cost_90_low": 0,
      "cost_90_high": 0,
      "concentration_90": 0,
      "cost_70_low": 0,
      "cost_70_high": 0,
      "concentration_70": 0,
      "chip_status": "",
      "sample_count": 0
    },
    "kline_evidence": [
      {
        "kline": {},
        "evidence": ""
      }
    ]
  },
  "refs": ["", "", ""]
}
```

分析目标：

- 主力筹码大多在什么区间
- 是否存在套牢盘
- 套牢盘筹码大概在什么区间

注意：

- 筹码分布是估算的成本结构，不是真实账户持仓。
- 不要断言“主力真实持仓都在这里”。
- 可以说：
  - 主要成本区
  - 主力可能重点交换区
  - 可能的主力防守区

### K 线引用一致性规则

skill 现在要求：

- 所有输出模块中的 `data[].kline`
- `stage.data[].evidence[].kline`
- `chip.data.kline_evidence[].kline`

都必须从输入 `daily_kline` 中原样复制。

不允许：

- 手写
- 重算
- 四舍五入
- 拼接不同日期字段
- 把某一天的 `trade_date` 和另一根 K 的价格/成交量混用

输出前必须自检：

1. 建立 `trade_date -> 原始 K 线行` 映射。
2. 检查每个输出 `kline.trade_date` 是否存在。
3. 检查每个输出 `kline` 全字段是否与输入原始行完全一致。
4. 不一致则替换成输入原始行。

## 已运行验证

修改 `coulling-volume-price-analysis` 后运行过：

```powershell
$env:PYTHONUTF8='1'; python "D:\codex\skills\.system\skill-creator\scripts\quick_validate.py" "D:\股神养成plan\Cassa\skills\coulling-volume-price-analysis"
```

结果：

```text
Skill is valid!
```

之前 `thises-volume-price` 也用同样方式验证通过。

注意：中文 skill 文件在 Windows 默认 GBK 下可能报编码问题，验证时使用：

```powershell
$env:PYTHONUTF8='1'
```

## 下一步可能任务

可能的下一步包括：

1. 把 `stage` 最新结构也写入 `2026-07-14-thises-v2.md` context。
2. 实现 `business.py` 最新一根 K 线 `volume_ratio` 使用 `more_info.fLianB` 覆盖。
3. 确认 / 实现 `business.py thises` 输出 `market_context`。
4. 跑一次：

```bash
python business.py thises --codes 002422
```

确认输出包含：

- `data_type: "thises_input"`
- `market_context`
- `daily_kline[].volume_ratio`
- `chip`
- `name` 不为空或有 fallback
- 盘中时最新 K 已拼接
- 最新 K 的 `volume_ratio` 已使用 `more_info.fLianB`

5. 用输出 JSON 手动测试 `thises-volume-price` / `coulling-volume-price-analysis` 的协议是否顺。
