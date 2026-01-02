#!/usr/bin/env python3
"""
测试前端API调用的调试脚本 - 直接测试后端逻辑
"""

import sys
import os
import json

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_backend_logic():
    """直接测试后端逻辑"""
    print("🔍 后端逻辑测试")
    print("=" * 50)

    try:
        # 手动导入所需模块
        import sqlite3

        def get_db_conn():
            db_path = os.path.join(os.path.dirname(__file__), 'data', 'bot.db')
            return sqlite3.connect(db_path)

        def get_system_config():
            conn = get_db_conn()
            c = conn.cursor()
            c.execute('SELECT key, value FROM system_config')
            rows = c.fetchall()
            conn.close()

            config = {}
            for key, value in rows:
                config[key] = value
            return config

        def update_system_config(key, value):
            conn = get_db_conn()
            c = conn.cursor()
            c.execute('INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)', (key, value))
            conn.commit()
            conn.close()

        # 获取当前配置
        print("📊 当前数据库配置:")
        config = get_system_config()
        for k, v in config.items():
            print(f"  {k}: {v}")

        # 模拟前端发送的数据
        print("\n📤 模拟前端发送数据:")
        frontend_data = {
            "level_count": 10,
            "level_amounts": {  # 对象格式
                "1": 3210.0,
                "2": 3210.0,
                "3": 3210.0,
                "4": 3210.0,
                "5": 3210.0,
                "6": 3210.0,
                "7": 3210.0,
                "8": 3210.0,
                "9": 3210.0,
                "10": 3210.0
            }
        }
        print(json.dumps(frontend_data, indent=2, ensure_ascii=False))

        # 模拟后端保存逻辑
        print("\n💾 模拟后端保存逻辑:")

        data = frontend_data
        target_count = int(data.get('level_count', 10))
        raw_amounts = data.get('level_amounts')

        print(f"目标层数: {target_count}")
        print(f"原始金额数据: {raw_amounts}")

        final_amounts = []
        for i in range(target_count):
            val_float = 0.0
            if raw_amounts:
                val = None
                if isinstance(raw_amounts, list):
                    if i < len(raw_amounts):
                        val = raw_amounts[i]
                elif isinstance(raw_amounts, dict):
                    # 尝试多种 Key 格式
                    val = raw_amounts.get(str(i + 1))
                    if val is None: val = raw_amounts.get(i + 1)
                    if val is None: val = raw_amounts.get(str(i))
                    if val is None: val = raw_amounts.get(i)

                try:
                    if val is not None and str(val).strip() != "":
                        val_float = float(val)
                except:
                    val_float = 0.0

            # 只处理真正的0值
            if val_float <= 0.0001:
                val_float = 1.0  # 默认值

            final_amounts.append(val_float)

        print(f"最终保存的数组: {final_amounts}")

        # 保存到数据库
        update_system_config('level_count', target_count)
        update_system_config('level_amounts', json.dumps(final_amounts))
        update_system_config('level_reward', 1.0)

        print("✅ 数据已保存到数据库")

        # 验证保存结果
        print("\n🔍 验证保存结果:")
        new_config = get_system_config()
        print(f"level_count: {new_config.get('level_count')}")
        print(f"level_amounts: {new_config.get('level_amounts')}")

        # 测试获取API的逻辑
        print("\n📖 模拟获取API逻辑:")

        level_count = int(new_config.get('level_count', 10))
        level_reward = float(new_config.get('level_reward', 1.0))
        level_amounts_str = new_config.get('level_amounts')
        level_amounts = []

        if level_amounts_str:
            try:
                parsed = json.loads(level_amounts_str)
                if isinstance(parsed, list):
                    for x in parsed:
                        try:
                            v = float(x)
                            if v <= 0.001: v = level_reward
                            level_amounts.append(v)
                        except:
                            level_amounts.append(level_reward)
            except:
                level_amounts = []

        # 补齐
        if len(level_amounts) < level_count:
            missing = level_count - len(level_amounts)
            level_amounts += [level_reward] * missing

        level_amounts = level_amounts[:level_count]

        print(f"返回给前端的level_amounts: {level_amounts}")

        return {
            'success': True,
            'level_count': level_count,
            'level_reward': level_reward,
            'level_amounts': level_amounts
        }

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == '__main__':
    result = test_backend_logic()
    if result:
        print(f"\n✅ 测试完成，结果: {json.dumps(result, indent=2, ensure_ascii=False)}")
