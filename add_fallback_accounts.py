#!/usr/bin/env python3
"""
添加捡漏账号脚本 - 仅添加捡漏账号，不重置数据库
"""
import os
import sys
import sqlite3

# 添加项目路径到 sys.path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

# 确保可以导入 app 模块
from app.database import get_db_conn

def add_fallback_accounts():
    """添加捡漏账号"""
    print("=" * 60)
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
    updated_count = 0
    error_count = 0
    
    for account in fallback_accounts:
        try:
            # 检查是否已存在
            c.execute('SELECT id FROM fallback_accounts WHERE telegram_id = ?', (account['telegram_id'],))
            existing = c.fetchone()
            
            if existing:
                # 更新现有账号
                c.execute('''
                    UPDATE fallback_accounts 
                    SET username = ?, group_link = ?, is_active = 1
                    WHERE telegram_id = ?
                ''', (
                    account['username'],
                    account['group_link'],
                    account['telegram_id']
                ))
                updated_count += 1
                print(f"🔄 更新捡漏账号: {account['telegram_id']} (@{account['username']})")
            else:
                # 插入新账号
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
        except Exception as e:
            error_count += 1
            print(f"❌ 处理捡漏账号失败 {account['telegram_id']}: {e}")
    
    conn.commit()
    conn.close()
    
    print("\n" + "=" * 60)
    print(f"✅ 完成！")
    print(f"   - 新增: {added_count} 个")
    print(f"   - 更新: {updated_count} 个")
    print(f"   - 失败: {error_count} 个")
    print("=" * 60)

if __name__ == '__main__':
    add_fallback_accounts()

