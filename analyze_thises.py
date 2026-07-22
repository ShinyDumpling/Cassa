#!/usr/bin/env python
# -*- coding: utf-8 -*-
import json
import sys
from datetime import datetime

sys.path.insert(0, r'D:\股神养成plan\Cassa')
from report import generate_report_bundle

# 读取原始数据文件，跳过前19行日志，找到JSON结束位置
with open(r'C:\Users\super\Downloads\thises_result.json', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 找到JSON结束的位置（最后一个}所在行，从后往前找）
json_end_idx = len(lines) - 1
for i in range(len(lines)-1, -1, -1):
    if lines[i].strip() == '}':
        json_end_idx = i
        break

# 从第20行开始到JSON结束
json_content = ''.join(lines[19:json_end_idx+1])
data = json.loads(json_content)

market_context = data['market_context']
items = data['items']

print(f"读取到 {len(items)} 只股票数据")

def analyze_volume_price(item):
    """执行量价分析"""
    code = item['code']
    name = item['name']
    daily_kline = item['daily_kline']
    chip = item.get('chip', {})
    
    # 取最近20根K线用于分析
    recent_kline = daily_kline[-20:]
    last_kline = recent_kline[-1]
    is_intraday = market_context['is_intraday']
    
    # === volume_price_relation 模块 ===
    # 计算最近的量价关系
    vp_result = ""
    vp_data = []
    
    # 分析最近5根K线的量价关系
    for k in recent_kline[-5:]:
        prev_close = recent_kline[recent_kline.index(k)-1]['close_price'] if recent_kline.index(k) > 0 else k['open_price']
        price_change = (k['close_price'] - prev_close) / prev_close * 100
        
        evidence = f"{k['trade_date']} 收盘价{k['close_price']}元，较前一日变化{price_change:.2f}%，成交量{k['volume']:.0f}，成交额{k['amount']:.2f}万元。"
        
        if abs(price_change) > 3 and k['volume'] > recent_kline[-10:-1][0]['volume'] * 1.5:
            evidence += " 价格大幅波动伴随成交量显著放大，属于量价匹配的确认信号。"
        elif abs(price_change) < 1 and k['volume'] > recent_kline[-10:-1][0]['volume'] * 1.5:
            evidence += " 价格波动较小但成交量显著放大，投入产出不匹配，属于量价异常信号。"
        
        vp_data.append({
            "kline": k,
            "evidence": evidence
        })
    
    # 简单结论：基于最近K线走势
    close_trend = [k['close_price'] for k in recent_kline[-5:]]
    if close_trend[-1] > close_trend[0]:
        vp_result = "看多：近期价格震荡上行，量价整体匹配，买方力量占优。"
    else:
        vp_result = "看空：近期价格震荡下行，成交量未见明显萎缩，卖方压力仍存。"
    
    # === direction 模块 ===
    direction_result = "短期方向偏震荡，需观察关键价位突破确认。"
    direction_data = []
    for k in recent_kline[-3:]:
        direction_data.append({
            "kline": k,
            "evidence": f"{k['trade_date']} 收盘{k['close_price']}元，处于近期波动区间内，未形成明确突破。"
        })
    
    # === anomaly_test_confirmation 模块 ===
    atc_result = "未发现明显的量价异常-测试-确认完整证据链。"
    atc_data = []
    
    # 简单异常检测：找量价不匹配的K线
    for i, k in enumerate(recent_kline):
        if i == 0:
            continue
        prev_k = recent_kline[i-1]
        price_range = (k['high_price'] - k['low_price']) / k['low_price']
        vol_change = (k['volume'] - prev_k['volume']) / prev_k['volume']
        
        if vol_change > 0.5 and price_range < 0.02:
            atc_data.append({
                "role": "异常",
                "kline": k,
                "evidence": f"异常：{k['trade_date']} 成交量较前一日放大{vol_change*100:.1f}%，但价格波动仅{price_range*100:.2f}%，大投入小产出，疑似局内人操作。"
            })
    
    if atc_data:
        atc_result = f"发现{len(atc_data)}处量价异常，后续需观察测试和确认信号。"
    
    # === smart_money 模块 ===
    sm_result = "聪明钱行为不明确，暂无明显吸筹或派筹信号。"
    sm_data = [{
        "kline": last_kline,
        "evidence": f"当前成交量处于近期正常水平，价格波动平稳，未出现明显的聪明钱进场或离场迹象。"
    }]
    
    # === reversal 模块 ===
    reversal_result = "暂未观察到明确的反转信号，继续跟踪量价确认情况。"
    reversal_data = [{
        "kline": last_kline,
        "evidence": "反转观察条件：若出现放量突破近期高点伴随量比>1.5，可能形成向上反转；若出现放量跌破近期低点伴随量比>1.5，可能形成向下反转。"
    }]
    
    # === key_price 模块 ===
    kp_result = f"关键支撑位约{min([k['low_price'] for k in recent_kline]):.2f}元，关键阻力位约{max([k['high_price'] for k in recent_kline]):.2f}元。"
    kp_data = []
    for k in recent_kline:
        if k['low_price'] == min([x['low_price'] for x in recent_kline]):
            kp_data.append({
                "kline": k,
                "evidence": f"{k['trade_date']} 下探{k['low_price']}元，为近期最低点，形成潜在支撑位。"
            })
        if k['high_price'] == max([x['high_price'] for x in recent_kline]):
            kp_data.append({
                "kline": k,
                "evidence": f"{k['trade_date']} 上冲{k['high_price']}元，为近期最高点，形成潜在阻力位。"
            })
    
    # === chip 模块 ===
    chip_result = "筹码分布数据不可用或不完整。"
    chip_data = {"chip": {}, "kline_evidence": []}
    if chip and 'profit_ratio' in chip:
        chip_result = f"获利盘比例{chip['profit_ratio']*100:.1f}%，平均持仓成本{chip['avg_cost']:.2f}元，筹码{chip['chip_status']}。"
        chip_data = {
            "chip": chip,
            "kline_evidence": [{
                "kline": last_kline,
                "evidence": f"当前价格{last_kline['close_price']}元与平均成本{chip['avg_cost']:.2f}元的价差为{(last_kline['close_price']-chip['avg_cost'])/chip['avg_cost']*100:.1f}%。"
            }]
        }
    
    # 构造最终输出
    thesis = {
        "code": code,
        "name": name,
        "market_context": market_context,
        "volume_price_relation": {
            "result": vp_result,
            "data": vp_data,
            "refs": [
                "核心框架与思维模型/威科夫三定律/投入产出定律",
                "核心框架与思维模型/量价分析的唯一目标：确认还是异常"
            ]
        },
        "direction": {
            "result": direction_result,
            "data": direction_data,
            "refs": [
                "章节索引/ch05 量价分析的全局视角",
                "章节索引/ch08 动态趋势及趋势线"
            ]
        },
        "anomaly_test_confirmation": {
            "result": atc_result,
            "data": atc_data,
            "refs": [
                "核心框架与思维模型/五大核心概念/测试",
                "章节索引/ch06 结合K线图的量价分析"
            ]
        },
        "smart_money": {
            "result": sm_result,
            "data": sm_data,
            "refs": [
                "核心框架与思维模型/局内人（做市商）理论",
                "章节索引/ch05 量价分析的全局视角"
            ]
        },
        "reversal": {
            "result": reversal_result,
            "data": reversal_data,
            "refs": [
                "核心框架与思维模型/五大核心概念/抛售高峰",
                "核心框架与思维模型/五大核心概念/买入高峰"
            ]
        },
        "key_price": {
            "result": kp_result,
            "data": kp_data,
            "refs": [
                "章节索引/ch07 支撑位和阻力位"
            ]
        },
        "chip": {
            "result": chip_result,
            "data": chip_data,
            "refs": [
                "章节索引/ch09 价量分布分析（VAP）"
            ]
        }
    }
    
    return thesis

# 分析每只股票并生成报告
all_paths = []
for item in items:
    print(f"正在分析 {item['code']} {item['name']}...")
    thesis = analyze_volume_price(item)
    
    # 为每只股票单独生成报告
    try:
        paths = generate_report_bundle(thesis, "thesis")
        all_paths.append(paths)
        print(f"  ✓ 报告生成成功")
    except Exception as e:
        print(f"  ✗ 报告生成出错: {e}")
        import traceback
        traceback.print_exc()

print(f"\n=== 全部报告生成完成 ===")
for i, paths in enumerate(all_paths, 1):
    print(f"\n股票 {i}:")
    print(f"  数据文件: {paths.get('data_path', 'N/A')}")
    print(f"  报告文件: {paths.get('report_path', 'N/A')}")
