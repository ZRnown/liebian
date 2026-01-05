#!/usr/bin/env python3
"""
立即检查所有机器人权限状态的脚本
用于手动触发权限检查，避免依赖可能不可靠的事件监听器
"""

import sys
import os
import asyncio
sys.path.append(os.path.dirname(__file__))

from app.database import get_db_conn
from app.config import clients

async def check_all_permissions():
    """检查所有绑定群组的机器人权限状态"""
    print("🔍 开始检查所有机器人权限状态...")

    if not clients:
        print("❌ 没有找到活跃的机器人客户端")
        return

    # 获取所有有群组绑定的用户
    conn = get_db_conn()
    c = conn.cursor()

    c.execute("""
        SELECT DISTINCT mg.telegram_id, mg.group_id, mg.group_name, m.username
        FROM member_groups mg
        JOIN members m ON mg.telegram_id = m.telegram_id
        WHERE mg.is_bot_admin = 1
    """)

    bound_groups = c.fetchall()
    conn.close()

    print(f"📋 找到 {len(bound_groups)} 个需要检查的群组绑定")

    notifications_sent = 0

    for user_id, group_id, group_name, username in bound_groups:
        try:
            print(f"🔍 检查用户 {username}({user_id}) 在群组 {group_name}({group_id}) 的权限")

            # 找到对应的机器人
            target_bot = None
            for client in clients:
                try:
                    me = await client.get_me()
                    if me.id == user_id:
                        target_bot = client
                        break
                except:
                    continue

            if not target_bot:
                print(f"⚠️ 未找到用户 {user_id} 对应的机器人，跳过")
                continue

            # 检查权限状态
            try:
                perms = await target_bot.get_permissions(group_id, user_id)
                is_admin = perms.is_admin or perms.is_creator

                if not is_admin:
                    print(f"🚨 发现机器人 {user_id} 在群组 {group_id} 失去管理员权限！")

                    # 导入通知函数
                    from app.bot_logic import notify_group_binding_invalid

                    # 发送通知 - 转换group_id格式用于匹配
                    raw_chat_id = int(str(group_id).replace('-100', '')) if str(group_id).startswith('-100') else group_id
                    await notify_group_binding_invalid(raw_chat_id, user_id, "手动检查发现管理员权限被撤销", target_bot)

                    # 更新数据库状态
                    conn = get_db_conn()
                    c = conn.cursor()
                    c.execute('UPDATE member_groups SET is_bot_admin = 0 WHERE telegram_id = ? AND group_id = ?',
                            (user_id, group_id))
                    c.execute('UPDATE members SET is_bot_admin = 0 WHERE telegram_id = ?', (user_id,))
                    conn.commit()
                    conn.close()

                    notifications_sent += 1
                    print(f"✅ 已发送通知并更新数据库状态")
                else:
                    print(f"✅ 机器人 {user_id} 在群组 {group_id} 仍具有管理员权限")

            except Exception as perm_err:
                print(f"❌ 检查机器人 {user_id} 在群组 {group_id} 权限失败: {perm_err}")
                # 如果检查失败，可能意味着机器人被踢出
                print(f"⚠️ 假设机器人已被踢出或权限被撤销，发送通知")
                from app.bot_logic import notify_group_binding_invalid
                raw_chat_id = int(str(group_id).replace('-100', '')) if str(group_id).startswith('-100') else group_id
                await notify_group_binding_invalid(raw_chat_id, user_id, "权限检查失败，可能已被踢出", target_bot)
                notifications_sent += 1

        except Exception as e:
            print(f"❌ 检查用户 {user_id} 权限失败: {e}")

    print(f"🎉 权限检查完成，共发送 {notifications_sent} 个通知")

if __name__ == "__main__":
    print("🚀 手动权限检查工具")
    print("=" * 40)

    try:
        asyncio.run(check_all_permissions())
    except Exception as e:
        print(f"❌ 执行失败: {e}")
        print("💡 请确保机器人服务正在运行")

    print("\n✅ 检查完成")

