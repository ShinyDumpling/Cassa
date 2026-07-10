---
name: cassa-screen
description: 使用 Cassa 现有 screen.py CLI 执行选股，不修改代码。Use when 用户要求选择放量突破股票、查找箱体震荡股票、运行 Cassa 选股、解释选股结果、调整选股参数如 box-days/range-max/volume-ratio-min/breakout-date，或要求通过 skill 控制 Cassa 选股策略。
---

# Cassa 选股 Skill

使用本 skill 帮用户通过现有 CLI 执行 Cassa 选股。

## 硬性边界

- 不修改任何代码。
- 不新增筛选函数。
- 不编辑 `screen.py`、`data.py`、策略文件或 context。
- 不创建临时 Python 脚本。
- 只调用项目中已经存在的 CLI 入口。
- 如果用户要求当前 CLI 不支持的筛选条件，先说明目前不能直接执行，并建议由开发任务补充入口。

## 工作目录

在 Cassa 项目根目录执行命令：

```powershell
D:\股神养成plan\Cassa
```

优先使用：

```powershell
python screen.py <command>
```

## 可用入口

查找当前仍在箱体震荡的股票：

```powershell
python screen.py scan-box
```

查找放量突破箱体的股票：

```powershell
python screen.py scan-breakout
```

查看单只股票箱体判断：

当前没有单股判断 CLI。不要调用 `box` 或 `breakout` 命令。

## 自然语言映射

当用户说“帮我选择今天目前位置放量突破的股票”“找今天放量突破的票”“当前放量突破”时，执行：

```powershell
python screen.py scan-breakout
```

当用户说“帮我找出现在还在箱体震荡的股票”“找箱体内的股票”“现在仍然箱体整理”时，执行：

```powershell
python screen.py scan-box
```

当用户指定历史日期，例如“找 2026-07-10 放量突破的股票”，执行：

```powershell
python screen.py scan-breakout --breakout-date 2026-07-10
```

当用户指定箱体天数，例如“最近 30 根 K 线箱体震荡”，执行：

```powershell
python screen.py scan-box --box-days 30
```

## 参数口径

- `--box-days`：箱体 K 线数量，默认 20。
- `--breakout-date`：观察日或突破日；不传则由数据中心按今天处理。
- `--range-max`：箱体振幅上限，默认 0.30。
- `--volume-ratio-min`：放量倍数下限，默认 1.5，仅用于 `scan-breakout`。
- `--batch-size`：每批处理股票数量，默认 500。

## 执行流程

1. 识别用户要查的是“箱体震荡”还是“放量突破”。
2. 把用户提到的日期、箱体天数、振幅上限、放量倍数转换为 CLI 参数。
3. 在项目根目录运行对应 `python screen.py ...` 命令。
4. 读取控制台输出中的分层统计、数据日期分布和最终 JSON。
5. 用简短中文汇总结果：初始数量、每层通过数量、最终入选数量、入选股票代码。

## 输出要求

- 先说明实际执行的命令。
- 再说明数据中心打印的模式：盘中或非盘中。
- 再说明每层筛选通过和淘汰数量。
- 最后给出最终入选股票代码。
- 如果没有入选股票，明确说本次没有筛出符合条件的股票。

## 异常处理

- 如果命令报错，直接复述关键错误信息，不要猜测结果。
- 如果本地 K 线日期分布明显不一致，提醒用户先检查或更新本地日 K 数据库。
- 如果用户要求“加一个新条件”“临时新增一层”，不要修改代码；说明当前 skill 只能调用已有 CLI，新增条件需要先作为开发任务落地。
