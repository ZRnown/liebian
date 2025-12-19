#!/usr/bin/env python3
"""
数据库重置脚本 - 重置数据库并添加捡漏账号
⚠️ 警告：此脚本会删除所有数据！
"""
import os
import sys
import sqlite3
import shutil
from datetime import datetime

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.config import DB_PATH, DATA_DIR
from app.database import init_db, get_db_conn, get_cn_time

def backup_database():
    """备份现有数据库"""
    if os.path.exists(DB_PATH):
        backup_path = os.path.join(DATA_DIR, f'bot_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db')
        shutil.copy2(DB_PATH, backup_path)
        print(f"✅ 数据库已备份到: {backup_path}")
        return backup_path
    return None

def reset_database():
    """重置数据库"""
    print("=" * 60)
    print("🗑️  开始重置数据库...")
    print("=" * 60)
    
    # 1. 备份现有数据库
    backup_path = backup_database()
    
    # 2. 删除现有数据库文件
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"✅ 已删除现有数据库文件: {DB_PATH}")
    
    # 3. 重新初始化数据库
    print("\n📊 重新初始化数据库...")
    init_db()
    print("✅ 数据库初始化完成")
    
    return backup_path

def add_fallback_accounts():
    """添加捡漏账号"""
    print("\n" + "=" * 60)
    print("➕ 添加捡漏账号...")
    print("=" * 60)
    
    # 捡漏账号数据
    fallback_accounts = [
        {'telegram_id': 8889990001, 'username': 'cslb0006', 'group_link': 'https://t.me/cslb0006'},
        {'telegram_id': 8889990002, 'username': 'cslb0007', 'group_link': 'https://t.me/cslb0007'},
        {'telegram_id': 8889990003, 'username': 'cslb0008', 'group_link': 'https://t.me/cslb0008'},
        {'telegram_id': 8889990004, 'username': 'cslb0009', 'group_link': 'https://t.me/cslb0009'},
        {'telegram_id': 8889990005, 'username': 'cslb00010', 'group_link': 'https://t.me/cslb00010'},
        {'telegram_id': 8889990006, 'username': 'cslb00011', 'group_link': 'https://t.me/cslb00011'},
        {'telegram_id': 8889990007, 'username': 'cslb00012', 'group_link': 'https://t.me/cslb00012'},
        {'telegram_id': 8889990008, 'username': 'cslb00013', 'group_link': 'https://t.me/cslb00013'},
        {'telegram_id': 8889990009, 'username': 'cslb00014', 'group_link': 'https://t.me/cslb00014'},
        {'telegram_id': 88899900010, 'username': 'cslb00015', 'group_link': 'https://t.me/cslb00015'},
    ]
    
    conn = get_db_conn()
    c = conn.cursor()
    
    added_count = 0
    for account in fallback_accounts:
        try:
            # 插入捡漏账号
            c.execute('''
                INSERT INTO fallback_accounts 
                (telegram_id, username, group_link, total_earned, is_active)
                VALUES (?, ?, ?, 0, 1)
            ''', (
                account['telegram_id'],
                account['username'],
                account['group_link']
            ))
            added_count += 1
            print(f"✅ 添加捡漏账号: {account['telegram_id']} (@{account['username']})")
        except sqlite3.IntegrityError:
            # 如果已存在，更新信息
            c.execute('''
                UPDATE fallback_accounts 
                SET username = ?, group_link = ?, is_active = 1
                WHERE telegram_id = ?
            ''', (
                account['username'],
                account['group_link'],
                account['telegram_id']
            ))
            print(f"🔄 更新捡漏账号: {account['telegram_id']} (@{account['username']})")
        except Exception as e:
            print(f"❌ 添加捡漏账号失败 {account['telegram_id']}: {e}")
    
    conn.commit()
    conn.close()
    
    print(f"\n✅ 成功处理 {added_count} 个捡漏账号")
    return added_count

def main():
    """主函数"""
    print("⚠️" * 30)
    print("⚠️  警告：此操作将删除所有数据库数据！")
    print("⚠️" * 30)
    print("\n操作步骤：")
    print("1. 备份现有数据库")
    print("2. 删除现有数据库")
    print("3. 重新初始化数据库")
    print("4. 添加10个捡漏账号")
    print()
    
    response = input("是否继续？(yes/no): ").strip().lower()
    
    if response != 'yes':
        print("❌ 操作已取消")
        return
    
    try:
        # 重置数据库
        backup_path = reset_database()
        
        # 添加捡漏账号
        add_fallback_accounts()
        
        print("\n" + "=" * 60)
        print("✅ 数据库重置完成！")
        print("=" * 60)
        if backup_path:
            print(f"📦 备份文件: {backup_path}")
        print("\n💡 提示：")
        print("   - 数据库已重置并初始化")
        print("   - 已添加10个捡漏账号")
        print("   - 默认管理员账号: admin / admin")
        print("   - 请重启应用以生效")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ 操作失败: {e}")
        import traceback
        traceback.print_exc()
        if backup_path and os.path.exists(backup_path):
            print(f"\n💡 可以从备份恢复: {backup_path}")

if __name__ == '__main__':
    main()

