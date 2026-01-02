#!/usr/bin/env python3
"""
修复层级设置数据，确保level_amounts以正确的JSON字符串格式存储
"""

import sys
import os
import json
import sqlite3

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def fix_level_settings():
    """修复层级设置数据"""
    print("🔧 修复层级设置数据")
    print("=" * 50)

    db_path = os.path.join(os.path.dirname(__file__), 'data', 'bot.db')
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # 检查当前level_amounts的值
    c.execute('SELECT value FROM system_config WHERE key = ?', ('level_amounts',))
    row = c.fetchone()

    if row:
        current_value = row[0]
        print(f"当前level_amounts值: {current_value}")
        print(f"类型: {type(current_value)}")

        # 如果是列表对象，转换为JSON字符串
        if isinstance(current_value, str):
            try:
                # 尝试解析，如果成功说明是正确的JSON字符串
                parsed = json.loads(current_value)
                print("✅ 数据格式正确（JSON字符串）")
                print(f"解析后: {parsed}")
            except:
                print("❌ 数据格式错误，尝试修复...")
                # 如果不是有效的JSON，可能是存储了Python repr
                if current_value.startswith('[') and current_value.endswith(']'):
                    try:
                        # 尝试解析为Python列表
                        import ast
                        parsed_list = ast.literal_eval(current_value)
                        if isinstance(parsed_list, list):
                            json_str = json.dumps(parsed_list)
                            print(f"转换为JSON字符串: {json_str}")
                            c.execute('UPDATE system_config SET value = ? WHERE key = ?', (json_str, 'level_amounts'))
                            conn.commit()
                            print("✅ 数据已修复")
                        else:
                            print("❌ 无法解析数据")
                    except:
                        print("❌ 解析失败")
                else:
                    print("❌ 无法识别的数据格式")
        else:
            print("❌ 数据库中存储的是非字符串数据，这不应该发生")

    else:
        print("❌ 未找到level_amounts配置")

    # 验证修复结果
    print("\n🔍 验证修复结果:")
    c.execute('SELECT value FROM system_config WHERE key = ?', ('level_amounts',))
    row = c.fetchone()
    if row:
        fixed_value = row[0]
        print(f"修复后level_amounts值: {fixed_value}")
        try:
            parsed = json.loads(fixed_value)
            print(f"✅ 成功解析: {parsed}")
        except:
            print("❌ 仍然无法解析")

    conn.close()

if __name__ == '__main__':
    fix_level_settings()
