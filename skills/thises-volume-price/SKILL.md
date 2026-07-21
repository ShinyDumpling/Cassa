---
name: thises-volume-price
description: 使用 Cassa thises 数据收集入口，对股票或板块做量价关系分析。Use when 用户要求分析股票或板块的量价关系，或要求基于 thises 数据做量价模块分析。
---

# Thises 量价关系分析 Skill

## 适用场景

使用本 skill 帮用户完成 `thises` 第一版中的量价关系分析。

本 skill 不直接调用底层数据接口，不手写数据采集逻辑，只通过 `business.py thises` CLI 获取数据。

## 必须调用的命令

在 Cassa 项目根目录执行：

```powershell
python business.py thises --codes <codes>
```

其中 `<codes>` 来自用户输入，不能写死。

示例：

```powershell
python business.py thises --codes 881394
python business.py thises --codes 002185
python business.py thises --codes 600519,000001
```

## 输入协议

本 skill 的输入不是用户手写 JSON，而是上面 CLI 命令执行后的 JSON 输出。

Agent 必须先运行命令，再基于命令返回的数据进行量价分析。

命令输出的 JSON 必须完整保留，不允许截断、摘要、只取前几行、只取后几行，或只保留部分 `daily_kline`。如果输出过长，需要通过文件或其他方式读取完整 JSON 后再分析。

## 业务流程

1. 读取用户给出的股票或板块 `code`。
2. 在 Cassa 项目根目录运行 `python business.py thises --codes <codes>`。
3. 读取命令输出的 JSON。
4. 读取命令输出 JSON 顶层的 `market_context`。
5. 从 JSON 的 `items` 中逐个取出 `code` / `name` / `daily_kline` / `chip`。
6. 调用 `skills/coulling-volume-price-analysis` skill，把 `code` / `name` / `daily_kline` / `chip` 以及顶层 `market_context` 一起传给它。
7. 按 `coulling-volume-price-analysis` skill 的最终输出协议，构造 thesis 分析 JSON（每个 `item` 一份）。
8. 在 Cassa 项目根目录调用 `report.py` 保存报告：

   ```python
   from report import generate_report_bundle
   paths = generate_report_bundle(data, "thesis")
   ```

   返回结果必须同时包含 `data_path` 和 `report_path`。
9. 确认返回的 data_path 和 report_path 都存在。
   确认两个文件位于 Cassa/result/thesis/YYYY-MM-DD/ 下。
   确认两个文件的文件名主体完全一致，仅后缀分别为 -data.json 和 -report.md。
   向用户返回两个实际生成文件的绝对路径。
10. 如果命令返回 `errors`，需要在结果中说明哪些 code 没有成功分析。

最终交付不再只返回分析 JSON，也不直接把大段 Markdown 打印到控制台，而是返回：

- 原始 JSON 文件路径（`-data.json`）
- Markdown 报告文件路径（`-report.md`）
