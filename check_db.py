#!/usr/bin/env python3
"""
直接检查数据库中的值
"""

import sys
import os
import sqlite3
import json

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def check_database():
    """直接检查数据库"""
    print("🔍 检查数据库内容")
    print("=" * 50)

    db_path = os.path.join(os.path.dirname(__file__), 'data', 'bot.db')
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # 查询所有配置
    c.execute('SELECT key, value FROM system_config ORDER BY key')
    rows = c.fetchall()

    print("数据库中的所有配置:")
    for key, value in rows:
        print(f"  {key}: {value}")

    print("\n重点检查层级设置:")
    configs_to_check = ['level_count', 'level_reward', 'level_amounts']
    for key in configs_to_check:
        c.execute('SELECT value FROM system_config WHERE key = ?', (key,))
        row = c.fetchone()
        if row:
            value = row[0]
            print(f"  {key}: {value}")
            if key == 'level_amounts':
                try:
                    parsed = json.loads(value)
                    print(f"    解析后: {parsed}")
                except Exception as e:
                    print(f"    解析失败: {e}")
        else:
            print(f"  {key}: 未设置")

    conn.close()

if __name__ == '__main__':
    check_database()
