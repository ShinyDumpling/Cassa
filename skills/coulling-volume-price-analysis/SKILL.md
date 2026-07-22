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

必需字段：

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

### K 线引用一致性规则

所有输出模块中的 `data[].kline`、`anomaly_test_confirmation.data[].kline` 和 `chip.data.kline_evidence[].kline` 必须从输入 `daily_kline` 中按原始对象整行复制，不允许手写、重算、四舍五入、拼接不同日期字段，或把某一天的 `trade_date` 与另一根 K 线的价格/成交量字段混用。

如果 `evidence` 或 `result` 中提到某个交易日，则同一条证据里的 `kline.trade_date` 必须等于该交易日，并且 `open_price`、`high_price`、`low_price`、`close_price`、`volume`、`amount`、`volume_ratio` 必须与输入中该 `trade_date` 的原始行完全一致。

输出 JSON 前必须做一次自检：

1. 为输入 `daily_kline` 建立 `trade_date -> 原始 K 线行` 的映射。
2. 检查输出中每一个 `kline.trade_date` 都存在于输入映射。
3. 检查输出中每一个 `kline` 的全部字段与输入映射中的原始行完全一致。
4. 若发现不一致，必须用输入原始行替换该 `kline` 后再输出。

输出 JSON 前还必须检查所有自然语言字段中的价格来源：

1. 单根 K 线价格必须带有 `trade_date` 和价格字段名称。
2. 区间高点/低点必须带有形成日期、价格字段和统计区间。
3. 筹码价格必须说明对应的筹码估算字段。
4. 派生价格必须说明原始价格和推导规则。
5. 无法回溯到输入 K 线、输入筹码字段或明确派生过程的价格必须删除，不得猜测。

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
6. 必须读取输入 JSON 中的 `market_context.is_intraday`，并根据盘中 / 盘外状态进行判断。
7. 必须严格按照同目录下的 `量价关系归因法.md` 执行 `volume_price_relation` 模块，不得自行简化、替换或引入另一套量价关系归因规则。
8. `volume_price_relation` 的成交量字段使用规则：
   - 当 `market_context.is_intraday == false` 时，使用完整日 K 的 `daily_kline[].volume` 做成交量比较，不使用 `volume_ratio` 重复归因。
   - 当 `market_context.is_intraday == true` 时，最新 K 线的 `volume` 只能作为盘中累计量原样说明，不得与历史全天 `volume` 直接比较；必须比较最新实时 `volume_ratio` 与前 3～5 根有效 K 线的 `volume_ratio`，判断截至当前的相对成交活跃程度。
   - 不得重新计算或修改输入中的 `volume_ratio`。
   - `volume_ratio` 只能说明成交活跃度，不能单独证明买方或卖方变化，也不能单独形成突破、反转、放量或缩量确认。
9. `volume_price_relation.result` 必须明确输出“看多”或“看空”；证据不足时只能降低结论强度，不能只输出“无法判断”。
10. 所有自然语言字段中出现的价格必须标注来源。单根 K 线价格写明交易日和开盘价/最高价/最低价/收盘价；区间高低点写明形成日期、价格字段和统计区间；筹码价格写明对应筹码字段；派生价格写明原始价格和推导规则。
11. 必须输出 `anomaly_test_confirmation` 模块，按时间顺序识别最近异常、后续测试和后续确认或否定。
12. `anomaly_test_confirmation` 只回顾已经发生的证据链；`reversal` 只输出当前之后的反转观察条件，两个模块不得重复。
13. `volume_price_relation.result` 必须严格按照"价格变化、成交量变化、买卖方结果、量价结论"的顺序输出。
14. `volume_price_relation.result` 和 `volume_price_relation.data[].evidence` 使用"买方力量、买方主动性、卖方压力"等直观表达，不得使用"供给、需求"，也不得把成交量直接解释成买家或卖家人数变化。

如果 `market_context.is_intraday == true`：

1. 最后一根 `daily_kline` 是盘中临时 K，不是完整日 K。
2. 涉及成交量、收盘价、上下影线、实体、突破确认、反转确认、放量确认、缩量确认等判断，必须结合盘中状态说明为“盘中暂态判断”。
3. 不得把最后一根 K 当作收盘后定型 K。
4. 不得输出“已经确认突破”“已经确认跌破”“已经完成反转”“已经确认放量止涨/止跌”等收盘级确认结论。
5. 正确表达应为“盘中暂时出现”“若收盘仍保持则可确认”“当前仅为盘中迹象”。
6. 分析最新 K 线成交量时，先原样说明盘中累计 `volume` 及其不可与历史全天量直接比较的限制，再比较最新实时 `volume_ratio` 与前 3～5 根有效 K 线的 `volume_ratio`。
7. 量比比较必须列出最新值、历史比较值及对应交易日，并说明最新值处于近期全部值之上、近期多数值之上、近期主要区间内、近期多数值之下或近期全部值之下。
8. 如果有效历史量比少于 2 根，必须说明样本不足，不得据此判断成交活跃度变化。

如果 `market_context.is_intraday == false`：

1. 可以把最后一根 `daily_kline` 视为完整日 K。
2. 可以基于最后一根 K 做收盘级别的确认判断。

### 输出 JSON 格式

输出必须是 JSON 对象，不要输出 JSON 以外的解释文字。

```json
{
  "code": "",
  "name": "",
  "market_context": {
    "as_of": "",
    "is_intraday": false
  },
  "volume_price_relation": {
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
    "refs": ["", ""]
  },
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
  "anomaly_test_confirmation": {
    "result": "",
    "data": [
      {
        "role": "异常",
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
        "evidence": "异常："
      },
      {
        "role": "测试",
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
        "evidence": "测试："
      },
      {
        "role": "确认",
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
        "evidence": "确认："
      }
    ],
    "refs": []
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

- `market_context`：原样反映输入中的市场状态。
- `market_context.as_of`：分析数据对应的时间。
- `market_context.is_intraday`：`true` 表示盘中，`false` 表示非盘中。
- `volume_price_relation`：必须严格按照同目录 `量价关系归因法.md` 执行的量价关系归因模块。
- `direction`：判断下一步更偏看多还是看空。
- `anomaly_test_confirmation`：定位最近一根或连续多根量价异常 K 线，判断异常之后是否出现测试，以及测试之后是否得到确认或被否定。
- `smart_money`：判断聪明钱更像在买还是在卖。
- `reversal`：判断趋势什么时候可能反转，以及接下来什么情况算异常、什么情况算确认。
- `key_price`：根据日 K 数据分析关键支撑位和阻力位，说明哪些价位是关键战场以及强度如何。
- `chip`：结合 120 日 K 数据和筹码分布数据，分析主力筹码大多在什么区间、是否存在套牢盘、套牢盘筹码大概在什么区间。

普通模块（`direction` / `smart_money` / `reversal` / `key_price`）都必须包含：

- `result`：分析结论。
- `data`：支撑结论的数据，必须是数组。
- `refs`：书中理论索引。

`volume_price_relation` 也必须使用普通模块结构，包含 `result`、`data` 和 `refs`。其中 `result` 必须输出看多或看空；`data[].kline` 必须从输入 `daily_kline` 原样复制；其分析依据只能使用价格字段和 `volume`，不能使用 `volume_ratio`（盘中例外，见归因法）。

普通模块 `data` 中的每一项都必须包含：

- `kline`：完整单根日 K 数据（从输入 `daily_kline` 中原样取出，字段和值必须完全一致）。
- `evidence`：基于该 K 线得到的证据说明。

`anomaly_test_confirmation.data[]` 比普通模块多一个 `role` 字段，其余 `kline` 与 `evidence` 规则完全一致。

`anomaly_test_confirmation` 必须包含：

- `result`：按时间总结最近异常、测试以及确认或否定状态；未发现异常时明确说明未发现。
- `data`：异常、测试、确认 K 线组成的单一证据数组，必须按 `kline.trade_date` 升序排列；允许为空。
- `refs`：书中理论索引。

`data[].role` 只能是 `异常`、`测试`、`确认`。

`data[].evidence` 必须分别以 `异常：`、`测试：`、`确认：`开头，并解释该 K 线承担对应角色的原因。

异常 K 线必须早于测试 K 线，测试 K 线必须早于确认 K 线。同一交易日原则上只输出一次；如果同一根 K 线先完成测试并形成确认，使用 `role = "确认"` 并在证据中说明。

如果未发现异常，`data` 必须为空数组，不能强行选择普通 K 线填充。

`chip` 模块结构与其他模块不同，`data` 是对象，包含：

- `data.chip`：直接透传输入中的筹码分布字段。
- `data.kline_evidence`：数组，用来放筹码判断所引用的 K 线证据，每一项使用统一的 `{kline, evidence}` 结构。

`chip` 模块注意事项：

1. 筹码分布是模型估算的成本结构，不等同于真实账户持仓。
2. 不要直接断言"主力真实持仓都在这里"。
3. 可以表述为"主要成本区""主力可能重点交换区""可能的主力防守区"。
4. 如果 `chip.status == "todo"`，必须在 `result` 中说明筹码分布不可用，不能猜测筹码结构。
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
