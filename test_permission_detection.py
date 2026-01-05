#!/usr/bin/env python3
"""
权限撤销检测测试脚本
用于验证权限检测功能是否正常工作
"""

import sys
import os
sys.path.append(os.path.dirname(__file__))

from app.database import get_db_conn

def check_database_setup():
    """检查数据库设置"""
    print("🔍 检查数据库设置...")

    try:
        conn = get_db_conn()
        c = conn.cursor()

        # 检查member_groups表
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='member_groups'")
        if c.fetchone():
            print("✅ member_groups 表存在")

            # 检查表结构
            c.execute("PRAGMA table_info(member_groups)")
            columns = c.fetchall()
            required_cols = ['telegram_id', 'group_id', 'group_name', 'group_link', 'is_bot_admin']
            existing_cols = [col[1] for col in columns]

            for col in required_cols:
                if col in existing_cols:
                    print(f"✅ 列 {col} 存在")
                else:
                    print(f"❌ 列 {col} 缺失")

        else:
            print("❌ member_groups 表不存在")

        # 检查members表中的权限字段
        c.execute("PRAGMA table_info(members)")
        columns = c.fetchall()
        permission_cols = ['is_group_bound', 'is_bot_admin', 'is_joined_upline']
        existing_cols = [col[1] for col in columns]

        for col in permission_cols:
            if col in existing_cols:
                print(f"✅ members表列 {col} 存在")
            else:
                print(f"❌ members表列 {col} 缺失")

        conn.close()

    except Exception as e:
        print(f"❌ 数据库检查失败: {e}")

def check_code_syntax():
    """检查代码语法"""
    print("\n🔍 检查代码语法...")

    try:
        import ast

        # 检查bot_logic.py
        with open('app/bot_logic.py', 'r', encoding='utf-8') as f:
            content = f.read()

        ast.parse(content)
        print("✅ bot_logic.py 语法正确")

        # 检查是否包含权限检测相关函数
        if 'notify_group_binding_invalid' in content:
            print("✅ notify_group_binding_invalid 函数存在")
        else:
            print("❌ notify_group_binding_invalid 函数缺失")

        if 'raw_update_handler' in content:
            print("✅ raw_update_handler 函数存在")
        else:
            print("❌ raw_update_handler 函数缺失")

        if '/check_permission' in content:
            print("✅ /check_permission 命令存在")
        else:
            print("❌ /check_permission 命令缺失")

    except SyntaxError as e:
        print(f"❌ 语法错误: {e}")
    except Exception as e:
        print(f"❌ 代码检查失败: {e}")

def show_test_instructions():
    """显示测试说明"""
    print("\n📋 测试说明:")
    print("1. 重启机器人服务")
    print("2. 发送 /check_permission 命令测试手动检测")
    print("3. 在群组中撤销机器人的管理员权限")
    print("4. 观察是否收到权限撤销通知")
    print("5. 检查日志中的Raw事件输出")

    print("\n🔍 关键日志关键词:")
    print("- '[Raw事件] 📡 收到更新:' - Raw事件监听器工作")
    print("- '[Raw权限检测]' - 权限检测过程")
    print("- '[通知] ✅ 找到 X 个绑定用户' - 通知发送成功")
    print("- '[状态检测] 🔄 检测到权限变化' - 定时检测触发")

if __name__ == "__main__":
    print("🚀 权限撤销检测功能测试")
    print("=" * 50)

    check_database_setup()
    check_code_syntax()
    show_test_instructions()

    print("\n✅ 测试脚本执行完成")
    print("如果所有检查都通过，请重启机器人并测试权限撤销通知功能")
