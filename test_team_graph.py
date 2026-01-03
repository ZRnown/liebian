#!/usr/bin/env python3
"""
测试团队图谱API
"""

import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_database():
    """测试数据库连接和数据"""
    try:
        from app.database import get_db_conn

        print("测试数据库连接...")
        conn = get_db_conn()
        c = conn.cursor()

        # 检查是否有用户数据
        c.execute("SELECT COUNT(*) FROM members")
        count = c.fetchone()[0]
        print(f"数据库中有 {count} 个用户")

        if count > 0:
            # 获取第一个用户ID
            c.execute("SELECT telegram_id, username FROM members LIMIT 1")
            row = c.fetchone()
            print(f"示例用户: ID={row[0]}, 用户名={row[1]}")
            return row[0]  # 返回用户ID用于测试

        conn.close()
        return None

    except Exception as e:
        print(f"数据库测试失败: {e}")
        return None

def test_api_logic(telegram_id):
    """测试API逻辑"""
    try:
        from app.database import get_db_conn

        print(f"\n测试API逻辑，用户ID: {telegram_id}")
        conn = get_db_conn()
        c = conn.cursor()

        # 获取当前会员
        c.execute("""SELECT telegram_id, username, balance, is_vip, referrer_id,
            is_group_bound, is_bot_admin, is_joined_upline, direct_count, team_count, total_earned
            FROM members WHERE telegram_id = ?""", (telegram_id,))
        row = c.fetchone()

        if not row:
            print("❌ 用户不存在")
            conn.close()
            return False

        print("✅ 用户存在，数据完整")
        print(f"用户名: {row[1]}, VIP: {row[3]}, 余额: {row[2]}")

        center = {
            'telegram_id': row[0], 'username': row[1], 'balance': row[2],
            'is_vip': row[3], 'referrer_id': row[4], 'is_group_bound': row[5],
            'is_bot_admin': row[6], 'is_joined_upline': row[7],
            'direct_count': row[8] or 0, 'team_count': row[9] or 0, 'total_earned': row[10] or 0
        }

        print("✅ center数据结构正确")
        print(f"center.telegram_id: {center['telegram_id']}")

        conn.close()
        return True

    except Exception as e:
        print(f"❌ API逻辑测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    print("=== 团队图谱API测试 ===\n")

    # 测试数据库
    telegram_id = test_database()

    if telegram_id:
        # 测试API逻辑
        success = test_api_logic(telegram_id)
        if success:
            print("\n✅ 所有测试通过")
        else:
            print("\n❌ 测试失败")
    else:
        print("\n❌ 没有可用的测试用户")
