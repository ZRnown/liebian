#!/usr/bin/env python3
"""
数据库清理脚本 - 清理幽灵用户和无效数据
执行前请先备份数据库！
"""
import sqlite3
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.config import DB_PATH

def cleanup_database():
    """清理数据库中的脏数据"""
    print("=" * 60)
    print("开始清理数据库脏数据...")
    print("=" * 60)
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    try:
        # 1. 删除无效的幽灵用户
        print("\n1. 删除无效的幽灵用户...")
        # 先查询一下有多少无效用户
        c.execute("""
            SELECT COUNT(*) FROM members 
            WHERE telegram_id IS NULL 
               OR telegram_id = 'None' 
               OR CAST(telegram_id AS TEXT) = 'None'
               OR username = 'fallback_None'
               OR username LIKE 'fallback_%None%'
        """)
        count_before = c.fetchone()[0]
        print(f"   发现 {count_before} 个可疑的无效用户")
        
        c.execute("""
            DELETE FROM members 
            WHERE telegram_id IS NULL 
               OR telegram_id = 'None' 
               OR CAST(telegram_id AS TEXT) = 'None'
               OR username = 'fallback_None'
               OR username LIKE 'fallback_%None%'
        """)
        deleted_members = c.rowcount
        print(f"   已删除 {deleted_members} 个无效用户")
        
        # 2. 删除关联的错误收益记录
        print("\n2. 删除关联的错误收益记录...")
        c.execute("""
            DELETE FROM earnings_records 
            WHERE member_id IS NULL 
               OR member_id = 'None'
               OR CAST(member_id AS TEXT) = 'None'
        """)
        deleted_earnings = c.rowcount
        print(f"   已删除 {deleted_earnings} 条无效收益记录")
        
        # 3. 检查并清理无效的充值记录
        print("\n3. 检查无效的充值记录...")
        c.execute("""
            DELETE FROM recharge_records 
            WHERE member_id IS NULL 
               OR member_id = 'None'
               OR CAST(member_id AS TEXT) = 'None'
        """)
        deleted_recharges = c.rowcount
        print(f"   已删除 {deleted_recharges} 条无效充值记录")
        
        # 4. 检查并清理无效的提现记录
        print("\n4. 检查无效的提现记录...")
        # 检查表是否存在
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='withdrawals'")
        table_exists = c.fetchone()
        if table_exists:
            c.execute("""
                DELETE FROM withdrawals 
                WHERE member_id IS NULL 
                   OR member_id = 'None'
                   OR CAST(member_id AS TEXT) = 'None'
            """)
            deleted_withdrawals = c.rowcount
            print(f"   已删除 {deleted_withdrawals} 条无效提现记录")
        else:
            print("   表 'withdrawals' 不存在，跳过")
            deleted_withdrawals = 0
        
        # 提交更改
        conn.commit()
        
        print("\n" + "=" * 60)
        print("数据库清理完成！")
        print("=" * 60)
        print(f"总计删除:")
        print(f"  - 无效用户: {deleted_members} 个")
        print(f"  - 无效收益记录: {deleted_earnings} 条")
        print(f"  - 无效充值记录: {deleted_recharges} 条")
        print(f"  - 无效提现记录: {deleted_withdrawals} 条")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ 清理过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
    finally:
        conn.close()

if __name__ == '__main__':
    print("⚠️  警告：此脚本将删除数据库中的无效数据！")
    print("⚠️  请确保已备份数据库！")
    response = input("\n是否继续？(yes/no): ")
    
    if response.lower() == 'yes':
        cleanup_database()
    else:
        print("已取消操作。")

