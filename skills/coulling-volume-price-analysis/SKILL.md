---
name: coulling-volume-price-analysis
description: "知识库来自《量价分析：量价分析创始人威科夫的盘口解读方法》(A Complete Guide to Volume Price Analysis) 作者安娜·库林(Anna Coulling)。用于在交易决策时应用量价分析框架、理解威科夫三定律、识别吸筹/派筹/测试信号、或快速查阅量价关系模式。"
---

# 量价分析：量价分析创始人威科夫的盘口解读方法
**作者**: 安娜·库林（Anna Coulling）| **译者**: 肖凤娟 | **原书**: A Complete Guide to Volume Price Analysis | **241页** | **12章** | **生成**: 2026-07-13


---

## 如何使用本 Skill

用户提供日 K 数据并要求做量价分析时，必须按本节协议执行。

### 输入参数格式

输入必须是 JSON 对象，格式如下：

```json
{
  "code": "881394.SH",
  "name": "证券",
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

必需字段：

- `code`
- `name`
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

`chip` 字段说明：

- `profit_ratio`：获利盘比例，表示当前价格下估算有多少比例的筹码处于盈利状态。
- `avg_cost`：平均成本，表示估算的市场平均持仓成本。
- `cost_90_low`：90% 成本区间下沿。
- `cost_90_high`：90% 成本区间上沿。
- `concentration_90`：90% 成本集中度，数值越小表示筹码越集中，数值越大表示筹码越分散。
- `cost_70_low`：70% 核心成本区间下沿。
- `cost_70_high`：70% 核心成本区间上沿。
- `concentration_70`：70% 核心成本集中度，数值越小表示核心筹码越集中。
- `chip_status`：筹码状态，例如“高度集中”“较集中”“中等”“较分散”。
- `sample_count`：参与筹码计算的有效 K 线数量。

如果 `chip.status == "todo"`，说明筹码分布不可用，分析时不能强行使用筹码分布做判断，只能退回日 K 量价分析。

### 数据使用限制

分析时只能使用“输入参数格式”中明确提供的数据。

允许基于已提供的日 K 数据计算直接派生指标，例如：

- 涨跌幅
- K 线实体大小
- 上下影线
- 成交量相对变化
- 区间高低点

这些派生指标必须能从输入的 `daily_kline` 明确计算出来，并且需要在 `data.evidence` 中说明使用了哪些日期和原始字段。

不得自行引入、计算或假设输入中不存在的数据，包括但不限于：

- 换手率
- `MACD`
- `RSI`
- `MA`
- 主力净流入
- `PE / PB`
- 新闻或消息面
- 大盘或板块情绪

如果某个判断需要这些未提供字段，必须在 `result` 或 `data.evidence` 中说明“输入数据未提供，不能判断”，不能补算、猜测或引用。

### 业务逻辑

1. 严格按照下方“核心框架与思维模型”执行分析。
2. 根据接收的日 K 数据进行量价分析。
3. 输出结构化 JSON 分析结果。
4. 分析结果必须遵循“有结论、有数据、有理论”的原则。
5. 每个结论都必须有足够的数据支撑，并给出对应的书中理论索引。

### 输出 JSON 格式

输出必须是 JSON 对象，不要输出 JSON 以外的解释文字。

```json
{
  "code": "",
  "name": "",
  "direction": {
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
  },
  "truth": {
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
  },
  "stage": {
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
  },
  "smart_money": {
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
  },
  "reversal": {
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
  },
  "key_price": {
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
  },
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
    },
    "refs": ["", "", ""]
  }
}
```

字段要求：

- `direction`：判断下一步更偏看多还是看空。
- `truth`：判断目前价格运动是真实运动还是陷阱。
- `stage`：判断当前处于吸筹、拉升、派筹、下跌中的哪个阶段。
- `smart_money`：判断聪明钱更像在买还是在卖。
- `reversal`：判断趋势什么时候可能反转，以及接下来什么情况算异常、什么情况算确认。
- `key_price`：根据日 K 数据分析关键支撑位和阻力位，说明哪些价位是关键战场以及强度如何。
- `chip`：结合 120 日 K 数据和筹码分布数据，分析主力筹码大多在什么区间、是否存在套牢盘、套牢盘筹码大概在什么区间。

普通模块（`direction` / `truth` / `stage` / `smart_money` / `reversal` / `key_price`）都必须包含：

- `result`：分析结论。
- `data`：支撑结论的数据，必须是数组。
- `refs`：书中理论索引。

普通模块 `data` 中的每一项都必须包含：

- `kline`：完整单根日 K 数据（从输入 `daily_kline` 中原样取出）。
- `evidence`：基于该 K 线得到的证据说明。

`data` 示例：

```json
[
  {
    "kline": {
      "code": "881394.SH",
      "trade_date": "2026-07-14",
      "open_price": 999.64,
      "high_price": 1004.66,
      "low_price": 990.07,
      "close_price": 999.20,
      "volume": 20106216.0,
      "amount": 2332839.25,
      "volume_ratio": 1.23
    },
    "evidence": "收盘价 999.20，成交量 20106216.0，价格回落但成交量仍处于高位。"
  }
]
```

`chip` 模块结构与其他模块不同，`data` 是对象，包含：

- `data.chip`：直接透传输入中的筹码分布字段。
- `data.kline_evidence`：数组，用来放筹码判断所引用的 K 线证据，每一项使用统一的 `{kline, evidence}` 结构。

`chip` 模块注意事项：

1. 筹码分布是模型估算的成本结构，不等同于真实账户持仓。
2. 不要直接断言“主力真实持仓都在这里”。
3. 可以表述为“主要成本区”“主力可能重点交换区”“可能的主力防守区”。
4. 如果 `chip.status == "todo"`，必须在 `result` 中说明筹码分布不可用，不能猜测筹码结构。

理论索引建议使用章节或框架名称，例如：

```json
[
  "核心框架与思维模型/威科夫三定律/投入产出定律",
  "核心框架与思维模型/量价分析的唯一目标：确认还是异常",
  "章节索引/ch05 量价分析的全局视角",
  "章节索引/ch07 支撑位和阻力位"
]
```

---

## 核心框架与思维模型

### 威科夫三定律 (Wyckoff's Three Laws)

量价分析的理论基石，由理查德·威科夫（Richard Wyckoff）在20世纪初建立：

1. **供求定律 (Supply & Demand)**：当需求大于供给时价格上涨，反之则下跌。这是所有价格运动的根本驱动力。

2. **因果定律 (Cause & Effect)**：趋势的规模与前期准备成正比。吸筹/派筹阶段越久（因），后续趋势越大（果）。小规模的成交量变化引起小范围波动，重大起因产生重大结果。

3. **投入产出定律 (Effort vs Result)**：成交量（投入）必须与价格变动（产出）相匹配。这是量价分析最核心的操作原则——用于判断价格运动是真实的还是虚假的。

### 量价分析的唯一目标：确认还是异常

使用量价分析时，你只寻找两件事：
- **确认**：成交量印证价格行为 → 趋势有效，继续持有
- **异常**：成交量与价格不匹配 → 趋势可能反转的早期信号

异常的两类典型情况：
- **高成交量 + 小价格波动**（低实体K线）：市场弱势，投入大但产出小。做市商在出货/吸筹，趋势即将反转
- **低成交量 + 大价格波动**（高实体K线）：潜在陷阱，价格变动缺乏真实支撑

### 五大核心概念

1. **吸筹 (Accumulation)**：局内人以批发价填满仓库的阶段。通过利空消息制造恐慌，迫使散户卖出，局内人低价买入。表现为价格反复震荡下跌，最终形成价格盘整区间。

2. **派筹 (Distribution)**：局内人将存货以零售价卖出的阶段。通过利好消息制造贪婪，吸引散户追高买入。表现为价格在顶部区间反复震荡，最终以买入高峰结束。

3. **测试 (Testing)**：局内人在行动前确认市场余量的关键步骤。
   - **供给测试**：吸筹后，价格回落至先前卖压区，若成交量低→卖盘已被吸收，可推高市场
   - **需求测试**：派筹后，价格回升至先前买压区，若成交量低→买盘已被满足，可推低市场

4. **抛售高峰 (Selling Climax)**：吸筹阶段的终点。恐慌性抛售达到顶峰，成交量急剧放大，随后市场止跌企稳，新趋势开始。

5. **买入高峰 (Buying Climax)**：派筹阶段的终点。贪婪性买入达到顶峰，成交量急剧放大，随后市场见顶，新下跌趋势开始。

### 六大交易指导原则

1. **艺术而非科学**：量价分析是主观判断，无法用软件自动化。需要人脑综合判断。
2. **耐心**：市场不会瞬间反转。信号出现后，等待确认，不要立即行动。
3. **相对性**：成交量是相对的。比较当前成交量与历史成交量，关注一致性而非绝对精确度。
4. **熟能生巧**：任何时间跨度、任何市场均适用，但需要持续练习。
5. **技术分析补充**：结合支撑位/阻力位、趋势线、K线形态确认量价信号。
6. **确认还是异常**：始终回到这个核心问题——价格被成交量确认，还是存在异常？

### 量价分析三步法

1. **微观**：分析单根K线图与对应成交量的关系
2. **中观**：分析最近几根K线图共同的量价关系，确认趋势
3. **宏观**：拉远至整幅图，识别吸筹/派筹阶段和测试信号

### 局内人（做市商）理论

局内人（做市商、专业投资者、大型操盘手）通过操纵两种情绪获利：
- **恐惧** → 制造利空、暴跌震仓 → 散户卖出 → 局内人低价吸筹
- **贪婪** → 制造利好、推高价格 → 散户追涨 → 局内人高价派筹

核心工具是**媒体**——任何消息都为操纵市场提供了借口。局内人的每一步都经过精心计划，他们的行为必然反映在成交量上，因为成交量无法隐藏。

---

## 章节索引

| # | 标题 | 核心框架 |
|---|------|---------|
| [ch01](chapters/ch01-trading-nothing-new.md) | 交易之中无新事 | 道氏理论三阶段、威科夫三定律、盘口解读 |
| [ch02](chapters/ch02-why-volume-matters.md) | 为何成交量如此重要 | 成交量验证价格、成交量不可隐藏 |
| [ch03](chapters/ch03-price.md) | 合理的价格 | 供求关系、价格的真实性与虚假性 |
| [ch04](chapters/ch04-core-principles.md) | 量价分析的首要原则 | 六大原则、确认vs异常、单根/多根K线分析 |
| [ch05](chapters/ch05-global-perspective.md) | 量价分析的全局视角 | 吸筹、派筹、供给测试、需求测试、抛售高峰、买入高峰 |
| [ch06](chapters/ch06-candlestick-vpa.md) | 结合K线图的量价分析 | 五原则、射击十字星、锤头线、放量止跌/止涨 |
| [ch07](chapters/ch07-support-resistance.md) | 支撑位和阻力位 | 横盘整理、突破确认、量价结合判断 |
| [ch08](chapters/ch08-dynamic-trends.md) | 动态趋势及趋势线 | 动态趋势线、传统趋势线弊端、趋势早期进场 |
| [ch09](chapters/ch09-vap.md) | 价量分布分析（VAP） | VAP vs VPA、成交量聚集区域、突破 |
| [ch10](chapters/ch10-examples.md) | 量价分析实例 | 多市场实盘案例、股票/外汇/期货/商品 |
| [ch11](chapters/ch11-putting-together.md) | 综合运用 | 横盘整理形态、多重时间跨度、完整交易流程 |
| [ch12](chapters/ch12-latest-developments.md) | 量价分析的最新发展 | 理论扩展、未来趋势 |

## 主题索引

- **VPA（量价分析）** → ch01, ch04, ch05
- **VAP（价量分布）** → ch09
- **威科夫三定律** → ch01, ch04
- **供求定律** → ch01, ch03
- **因果定律** → ch01, ch04, ch05
- **投入产出定律** → ch01, ch04
- **吸筹** → ch05, ch11
- **派筹** → ch05, ch11
- **供给测试** → ch05
- **需求测试** → ch05, ch06
- **抛售高峰** → ch05, ch06
- **买入高峰** → ch05, ch06
- **射击十字星** → ch06
- **锤头线** → ch06
- **放量止跌** → ch06
- **放量止涨** → ch06
- **局内人/做市商** → ch05, ch06, ch11
- **支撑位和阻力位** → ch07
- **动态趋势线** → ch08
- **多重时间跨度** → ch06, ch11
- **确认 vs 异常** → ch04
- **道氏理论** → ch01
- **杰西·利弗莫尔** → ch01
- **理查德·威科夫** → ch01
- **K线图五原则** → ch06

## 辅助文件

- [glossary.md](glossary.md) — 所有关键术语及定义
- [patterns.md](patterns.md) — 量价分析模式汇总
- [cheatsheet.md](cheatsheet.md) — 交易决策速查表

---

## 范围与限制

本 Skill 仅覆盖书中内容。实际交易决策需结合当前市场环境和个人风险偏好。量价分析适用于所有市场（股票、外汇、期货、商品）和所有时间框架（跳动点图到月线图），但不同市场的吸筹/派筹时间跨度差异显著。
