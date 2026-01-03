"""
机器人命令扩展模块
添加群组绑定、检测等新功能命令
需要在a.py中导入并注册这些命令
"""

from telethon import events, Button
from core_functions import check_bot_is_admin, check_any_bot_in_group, get_upline_chain, get_downline_tree, check_user_conditions
import sqlite3


async def handle_bind_group(event, bot, DB):
    """处理群组绑定"""
    telegram_id = event.sender_id
    member = DB.get_member(telegram_id)

    if not member:
        await event.respond('请先发送 /start 注册')
        return

    if not member['is_vip']:
        await event.respond('⚠️ 请先开通VIP才能绑定群组')
        return

    # 提示用户发送群链接
    await event.respond(
        '📱 群组绑定步骤：\n\n'
        '1️⃣ 将本机器人拉入您的群组\n'
        '2️⃣ 将机器人设置为管理员\n'
        '3️⃣ 在您的群里输入 /link 获取群链接\n'
        '4️⃣ 将群链接发送给我\n\n'
        '💡 群链接格式：https://t.me/+xxx 或 @groupname'
    )


async def handle_group_link_message(event, bot, DB, clients=None):
    """处理用户发送的群链接"""
    telegram_id = event.sender_id
    group_link = event.message.text.strip()

    # 验证链接格式
    if not (group_link.startswith('https://t.me/') or group_link.startswith('@')):
        await event.respond('❌ 群链接格式不正确\n\n请发送完整的群链接，格式如：\nhttps://t.me/+xxx 或 @groupname')
        return

    member = DB.get_member(telegram_id)
    if not member or not member['is_vip']:
        return

    # 检测是否有机器人加入群组且为管理员（结果仅作提示，不阻断操作）
    if clients and len(clients) > 0:
        # 使用多机器人逻辑
        is_any_bot_in_group, admin_bot_id = await check_any_bot_in_group(clients, group_link)
        is_admin = admin_bot_id is not None
    else:
        # 回退到单机器人逻辑
        bot_id = (await bot.get_me()).id
        is_admin = await check_bot_is_admin(bot, bot_id, group_link)

    # 更新数据库
    conn = DB.get_conn()
    c = conn.cursor()
    c.execute('''
        UPDATE members
        SET group_link = ?, is_group_bound = 1, is_bot_admin = ?
        WHERE telegram_id = ?
    ''', (group_link, 1 if is_admin else 0, telegram_id))
    conn.commit()
    conn.close()

    if is_admin:
        await event.respond(
            '✅ 群组绑定成功！\n\n'
            f'您的群链接：{group_link}\n\n'
            '🎉 恭喜！您已完成群组绑定和管理员设置\n\n'
            '下一步：加入上层群组\n'
            '发送 /join_upline 查看需要加入的群'
        )
    else:
        await event.respond(
            '✅ 群组链接已记录\n\n'
            f'链接: {group_link}\n\n'
            'ℹ️ 未能自动检测管理员权限，请确保机器人已在群且为管理员，'
            '否则某些验证功能可能不可用。'
        )


async def handle_join_upline(event, bot, DB, get_system_config):
    """显示需要加入的上层群列表"""
    telegram_id = event.sender_id
    member = DB.get_member(telegram_id)

    if not member:
        await event.respond('请先发送 /start 注册')
        return

    if not member['is_vip']:
        await event.respond('⚠️ 请先开通VIP')
        return

    # 获取上级链
    config = get_system_config()
    max_level = int(config['level_count'])
    upline_chain = get_upline_chain(telegram_id, max_level)

    if not upline_chain:
        await event.respond('您没有上级，无需加群')
        return

    # 获取上层群列表（新格式：字典列表）
    upline_groups = []
    for item in upline_chain:
        if item.get('is_fallback'):
            # 跳过捡漏账号
            continue
        upline_id = item['id']
        level = item['level']
        up_member = DB.get_member(upline_id)
        if up_member and up_member['group_link']:
            upline_groups.append({
                'level': level,
                'username': up_member['username'],
                'group_link': up_member['group_link']
            })

    if not upline_groups:
        await event.respond('上层暂无可加入的群')
        return

    # 构建按钮
    buttons = []
    text = f'📋 需要加入的上层群组（共{len(upline_groups)}个）\n\n'

    for i, group in enumerate(upline_groups, 1):
        text += f'{i}. 第{group["level"]}层 - @{group["username"]}的群\n'
        buttons.append([Button.url(f'加入第{group["level"]}层群', group['group_link'])])

    text += '\n💡 请依次加入所有群组，完成后发送 /check_status 检查状态'

    await event.respond(text, buttons=buttons)


async def handle_check_status(event, bot, DB):
    """检查用户完成状态"""
    telegram_id = event.sender_id
    member = DB.get_member(telegram_id)

    if not member:
        await event.respond('请先发送 /start 注册')
        return

    # 检查所有条件
    conditions = await check_user_conditions(bot, telegram_id)

    if not conditions:
        await event.respond('❌ 获取状态失败')
        return

    # 生成状态报告
    status_text = '📊 您的完成状态\n\n'
    status_text += f'✅ VIP状态：{"已开通" if conditions["is_vip"] else "未开通"}\n'
    status_text += f'{"✅" if conditions["is_group_bound"] else "❌"} 群组绑定：{"已完成" if conditions["is_group_bound"] else "未完成"}\n'
    status_text += f'{"✅" if conditions["is_bot_admin"] else "❌"} 机器人管理员：{"已设置" if conditions["is_bot_admin"] else "未设置"}\n'
    status_text += f'{"✅" if conditions["is_joined_upline"] else "❌"} 加入上层群：{"已完成" if conditions["is_joined_upline"] else "未完成"}\n\n'

    if conditions['all_conditions_met']:
        status_text += '🎉 恭喜！您已完成所有条件\n现在您的下级开通VIP时，您将获得分红！'
    else:
        status_text += '⚠️ 未完成的条件：\n'
        for cond in conditions['missing_conditions']:
            status_text += f'  • {cond}\n'
        status_text += '\n💡 完成所有条件后才能获得分红'

    await event.respond(status_text)


async def handle_my_team(event, bot, DB):
    """查看团队数据"""
    telegram_id = event.sender_id
    member = DB.get_member(telegram_id)

    if not member:
        await event.respond('请先发送 /start 注册')
        return

    if not member['is_vip']:
        await event.respond('⚠️ 请先开通VIP才能查看团队数据')
        return

    # 获取下级树
    downline_tree = get_downline_tree(telegram_id, 10)

    text = '👥 我的团队数据\n\n'
    text += f'💎 VIP状态：已开通\n'
    text += f'💰 当前余额：{member["balance"]} U\n'
    text += f'💸 累计获得：{member.get("total_earned", 0)} U\n'
    text += f'⚠️ 累计错过：{member["missed_balance"]} U\n\n'

    text += '📊 团队层级分布：\n\n'

    total_members = 0
    total_vip = 0

    for level in range(1, 11):
        if level in downline_tree:
            members = downline_tree[level]
            vip_count = sum(1 for m in members if m['is_vip'])
            total_members += len(members)
            total_vip += vip_count
            text += f'第{level}层：{len(members)}人 (VIP:{vip_count}人)\n'
        else:
            text += f'第{level}层：0人\n'

    text += f'\n📈 团队总计：{total_members}人\n'
    text += f'💎 VIP总数：{total_vip}人\n'

    await event.respond(text)


# 添加命令说明
COMMAND_HELP = """
🤖 群组管理命令

/bind_group - 绑定您的群组
/join_upline - 查看需要加入的上层群
/check_status - 检查完成状态
/my_team - 查看团队数据

💡 完成所有条件后，您的下级开通VIP时
   您将获得 1U 分红！
"""
