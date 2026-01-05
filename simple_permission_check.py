#!/usr/bin/env python3
"""
简化版权限检查脚本 - 不依赖可能有语法错误的bot_logic.py
"""

import sqlite3
import os
import sys

def get_db_conn():
    """获取数据库连接"""
    db_path = os.path.join(os.path.dirname(__file__), 'data', 'bot.db')
    return sqlite3.connect(db_path)

async def check_permissions_simple():
    """简化版权限检查"""
    print("🔍 简化权限检查开始...")

    try:
        conn = get_db_conn()
        c = conn.cursor()

        # 获取所有绑定群组的用户
        c.execute("""
            SELECT DISTINCT mg.telegram_id, mg.group_id, mg.group_name, m.username
            FROM member_groups mg
            JOIN members m ON mg.telegram_id = m.telegram_id
            WHERE mg.is_bot_admin = 1
        """)

        bound_groups = c.fetchall()
        conn.close()

        print(f"📋 找到 {len(bound_groups)} 个需要检查的群组绑定")

        print("📋 绑定详情:")
        for user_id, group_id, group_name, username in bound_groups:
            print(f"  - 用户: {username}({user_id}) -> 群组: {group_name}({group_id})")

        print("\n⚠️ 注意：由于主程序有语法错误，无法进行实际的Telegram API权限检查")
        print("💡 请先修复 app/bot_logic.py 的语法错误，然后运行完整的权限检查")

        return len(bound_groups)

    except Exception as e:
        print(f"❌ 检查失败: {e}")
        return 0

if __name__ == "__main__":
    print("🚀 简化权限检查工具")
    print("=" * 40)

    try:
        import asyncio
        count = asyncio.run(check_permissions_simple())
        print(f"\n✅ 检查完成，发现 {count} 个绑定")
    except Exception as e:
        print(f"❌ 执行失败: {e}")

    print("\n🔧 修复建议:")
    print("1. 修复 app/bot_logic.py 中的语法错误")
    print("2. 重启机器人服务")
    print("3. 再次运行完整权限检查")
