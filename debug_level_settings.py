#!/usr/bin/env python3
"""
调试层级设置脚本 - 检查VIP价格计算问题
"""

import sys
import os
import json
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 手动导入必要的模块
import sqlite3

def get_db_conn():
    """获取数据库连接"""
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'bot.db')
    return sqlite3.connect(db_path)

def get_system_config():
    """获取系统配置"""
    conn = get_db_conn()
    c = conn.cursor()
    c.execute('SELECT key, value FROM system_config')
    rows = c.fetchall()
    conn.close()

    config = {}
    for key, value in rows:
        config[key] = value
    return config

def compute_vip_price_from_config(config):
    """计算VIP价格 (逻辑同步Web端)"""
    try:
        level_count = int(config.get('level_count', 10))
        # 默认值防止为0
        default_reward = float(config.get('level_reward', 1.0))
        if default_reward <= 0: default_reward = 1.0

        level_amounts = config.get('level_amounts')
        if level_amounts:
            try:
                if isinstance(level_amounts, str):
                    parsed = json.loads(level_amounts)
                else:
                    parsed = level_amounts
            except: parsed = None

            if isinstance(parsed, list):
                vals = []
                last_val = default_reward
                for x in parsed[:level_count]:
                    try:
                        v = float(x)
                        if v > 0: last_val = v
                    except: v = last_val
                    vals.append(v)
                # 补齐
                if len(vals) < level_count:
                    vals += [last_val] * (level_count - len(vals))
                return sum(vals)
            elif isinstance(parsed, dict):
                total = 0.0
                for i in range(1, level_count + 1):
                    v = parsed.get(str(i)) or parsed.get(i) or default_reward
                    total += float(v)
                return total
    except: pass

    try: return float(config.get('vip_price', 10))
    except: return 10.0

def debug_level_settings():
    """调试层级设置"""
    print("🔍 调试层级设置")
    print("=" * 50)

    # 获取配置
    config = get_system_config()
    print(f"当前配置: {config}")

    # 解析层级数据
    level_count = int(config.get('level_count', 10))
    level_reward = float(config.get('level_reward', 1.0))
    level_amounts_str = config.get('level_amounts')

    print(f"层数: {level_count}")
    print(f"默认奖励: {level_reward}")
    print(f"层级金额字符串: {level_amounts_str}")

    # 解析层级金额
    if level_amounts_str:
        import json
        try:
            parsed = json.loads(level_amounts_str)
            print(f"解析后的数据: {parsed}")
            if isinstance(parsed, list):
                print("按列表处理:")
                for i, v in enumerate(parsed, 1):
                    print(f"  第{i}层: {v}")
        except Exception as e:
            print(f"解析失败: {e}")

    # 计算VIP价格
    vip_price = compute_vip_price_from_config(config)
    print(f"\n计算得到的VIP价格: {vip_price}")

    # 手动计算
    print("\n手动计算过程:")
    if level_amounts_str:
        try:
            parsed = json.loads(level_amounts_str)
            if isinstance(parsed, list):
                total = sum(float(x) for x in parsed[:level_count])
                print(f"列表求和: {total}")
        except Exception as e:
            print(f"手动计算失败: {e}")

if __name__ == '__main__':
    debug_level_settings()
