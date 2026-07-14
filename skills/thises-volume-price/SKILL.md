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

## 业务流程

1. 读取用户给出的股票或板块 `code`。
2. 在 Cassa 项目根目录运行 `python business.py thises --codes <codes>`。
3. 读取命令输出的 JSON。
4. 从 JSON 的 `items` 中逐个取出 `daily_kline`。
5. 调用 `skills/coulling-volume-price-analysis` skill，把 `daily_kline` 以及 `code` / `name` / `target_type` 一起传给它。
6. 基于该 skill 的分析结果输出量价分析结果。
7. 如果命令返回 `errors`，需要在结果中说明哪些 code 没有成功分析。

输出结果按照 `coulling-volume-price-analysis` skill 的输出结果来输出。
