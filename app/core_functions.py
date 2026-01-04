"""
核心功能模块
包含群组检测、层级计算、分红分配等核心逻辑
"""
import sqlite3
import os
import sys
from datetime import datetime, timedelta, timezone
from telethon import TelegramClient
from telethon.tl.functions.channels import GetParticipantRequest
from telethon.tl.types import ChannelParticipantAdmin, ChannelParticipantCreator

# 导入配置
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
from app.config import DB_PATH

# 定义中国时区
CN_TIMEZONE = timezone(timedelta(hours=8))

def get_cn_time():
    """获取中国时间字符串"""
    return datetime.now(CN_TIMEZONE).isoformat()

async def verify_group_link(bot, link, clients=None):
    """验证群链接，检查机器人是否在群内且为管理员

    Args:
        bot: Telegram机器人客户端（用于向后兼容）
        link: 群组链接
        clients: 可选的机器人客户端列表，如果提供则检查是否有任何机器人加入群组

    支持：
    - http://t.me/群用户名 / https://t.me/群用户名 （公开群，支持自动检测管理员）
    - http://t.me/+xxxx / https://t.me/+xxxx / https://t.me/joinchat/xxxx （私有邀请链接，只能记录，无法自动检测管理员）

    返回示例：
    - {'success': True, 'message': 'xxx', 'admin_checked': True/False}
    """
    try:
        # 必须是 http(s)://t.me/ 开头
        if link.startswith('http://t.me/'):
            tail = link.replace('http://t.me/', '').split('?')[0]
        elif link.startswith('https://t.me/'):
            tail = link.replace('https://t.me/', '').split('?')[0]
        else:
            return {'success': False, 'message': '链接格式不正确，请使用 http://t.me/ 开头的链接', 'admin_checked': False}
        
        # 1) 私有邀请链接: +hash 或 joinchat/hash
        if tail.startswith('+') or tail.startswith('joinchat/'):
            try:
                from telethon.tl.functions.messages import CheckChatInviteRequest
                from telethon.tl.types import ChatInviteAlready, ChatInvite

                hash_val = tail.replace('+', '').replace('joinchat/', '')
                # 使用 CheckChatInviteRequest 检查链接
                invite = await bot(CheckChatInviteRequest(hash_val))

                if isinstance(invite, ChatInviteAlready):
                    # 机器人已经在群里：可以直接获取 Chat 对象和 ID
                    chat = invite.chat
                    # 尝试检查管理员权限 (如果能获取 participants)
                    # 这里简单返回成功，后续逻辑会利用 group_id 进一步检查
                    return {
                        'success': True,
                        'message': '验证成功，机器人已在群内',
                        'admin_checked': True, # 既然在群里，且能解析，暂且认为通过，后续会有异步任务检查Admin
                        'group_id': chat.id,
                        'group_name': getattr(chat, 'title', None)
                    }
                elif isinstance(invite, ChatInvite):
                    # 机器人不在群里
                    return {
                        'success': False,
                        'message': '机器人尚未加入该群组，请先将机器人拉入群组并设为管理员',
                        'admin_checked': False
                    }
            except Exception as e:
                print(f'[私有链接验证失败] {e}')
                # 降级处理：无法解析ID，但记录链接
                return {
                    'success': True,
                    'message': '私有链接已记录 (无法自动获取ID，建议在群内发送 /bind 绑定)',
                    'admin_checked': False,
                    'group_id': None
                }
        
        # 2) 普通公开群用户名：可以检测是否为管理员
        username = tail
        try:
            # 尝试获取实体
            entity = await bot.get_entity(username)
        except Exception as e:
            print(f'获取实体失败: {e}')
            return {'success': False, 'message': '无法访问该群，可能是私有群 or 链接无效', 'admin_checked': False}
        
        # 检查是否是群组或超级群
        if not hasattr(entity, 'broadcast') or entity.broadcast:
            return {'success': False, 'message': '这不是一个群组链接', 'admin_checked': False}
            
        # 检查是否有机器人加入群组
        if clients and len(clients) > 0:
            # 使用新的逻辑：检查是否有任何机器人加入群组
            try:
                is_any_bot_in_group, admin_bot_id = await check_any_bot_in_group(clients, username)

                if not is_any_bot_in_group:
                    return {'success': False, 'message': '没有机器人加入该群组，请先将至少一个机器人拉入群组', 'admin_checked': False}

                # 如果有机器人是管理员，返回成功
                if admin_bot_id is not None:
                    return {'success': True, 'message': '验证成功，至少一个机器人是群管理员', 'admin_checked': True}
                else:
                    return {'success': True, 'message': '群链接已记录，至少一个机器人已加入群组，但可能不是管理员', 'admin_checked': False}

            except Exception as e:
                print(f'多机器人权限检查失败: {e}')
                # 如果新逻辑失败，回退到原逻辑
                return {'success': False, 'message': '权限检查失败，请确保至少一个机器人已在群且为管理员', 'admin_checked': False}
        else:
            # 使用原有逻辑：检查当前机器人
            try:
                me = await bot.get_me()
                participant = await bot(GetParticipantRequest(
                    channel=entity,
                    participant=me.id
                ))

                # 检查是否为管理员
                from telethon.tl.types import (
                    ChatParticipantAdmin,
                    ChatParticipantCreator,
                    ChannelParticipantAdmin,
                    ChannelParticipantCreator
                )

                is_admin = isinstance(participant.participant, (
                    ChatParticipantAdmin,
                    ChatParticipantCreator,
                    ChannelParticipantAdmin,
                    ChannelParticipantCreator
                ))

                if not is_admin:
                    return {'success': False, 'message': '机器人不是群管理员', 'admin_checked': True}

                return {'success': True, 'message': '验证成功', 'admin_checked': True}

            except Exception as e:
                print(f'获取权限失败: {e}')
                return {'success': False, 'message': '机器人不在该群内或无法获取权限', 'admin_checked': True}
            
    except Exception as e:
        print(f'验证群链接失败: {e}')
        return {'success': False, 'message': f'验证失败: {str(e)}', 'admin_checked': False}


async def check_user_in_group(bot, user_id, group_link):
    """
    检测用户是否在指定群组中
    
    Args:
        bot: Telegram机器人客户端
        user_id: 用户Telegram ID
        group_link: 群组链接
    
    Returns:
        bool: True表示用户在群组中
    """
    try:
        # 从群链接提取群组
        if 'joinchat/' in group_link or 't.me/' in group_link:
            group_entity = await bot.get_entity(group_link)
        else:
            return False
        
        # 检查用户是否在群组中
        try:
            participant = await bot(GetParticipantRequest(group_entity, user_id))
            return True
        except:
            return False
    except Exception as e:
        print(f"检测用户是否在群失败: {e}")
        return False


async def check_bot_is_admin(bot, bot_id, group_link):
    """
    检测机器人是否为群组管理员

    Args:
        bot: Telegram机器人客户端
        bot_id: 机器人的Telegram ID
        group_link: 群组链接

    Returns:
        bool: True表示机器人是管理员
    """
    try:
        group_entity = await bot.get_entity(group_link)

        # 获取机器人在群组中的身份
        participant = await bot(GetParticipantRequest(group_entity, bot_id))

        # 检查是否为管理员或创建者
        if isinstance(participant.participant, (ChannelParticipantAdmin, ChannelParticipantCreator)):
            return True
        return False
    except Exception as e:
        print(f"检测机器人管理员权限失败: {e}")
        return False


async def check_any_bot_in_group(clients, group_link):
    """
    检查是否有任何活跃的机器人加入了指定的群组

    Args:
        clients: 活跃的机器人客户端列表
        group_link: 群组链接

    Returns:
        tuple: (is_any_bot_in_group, is_admin_bot_id)
               is_any_bot_in_group: 是否有机器人加入群组
               is_admin_bot_id: 如果有机器人是管理员，返回其bot_id，否则为None
    """
    from telethon.tl.types import (
        ChannelParticipantAdmin, ChannelParticipantCreator,
        ChannelParticipant, ChatParticipant, ChatParticipantAdmin, ChatParticipantCreator
    )

    for client in clients:
        try:
            bot_id = (await client.get_me()).id
            group_entity = await client.get_entity(group_link)

            # 获取机器人在群组中的身份
            participant = await client(GetParticipantRequest(group_entity, bot_id))

            # 检查是否在群组中（包括所有类型的参与者）
            if isinstance(participant.participant, (ChannelParticipantAdmin, ChannelParticipantCreator,
                                                  ChannelParticipant, ChatParticipant,
                                                  ChatParticipantAdmin, ChatParticipantCreator)):
                # 检查是否为管理员或创建者
                if isinstance(participant.participant, (ChannelParticipantAdmin, ChannelParticipantCreator,
                                                      ChatParticipantAdmin, ChatParticipantCreator)):
                    return True, bot_id  # 返回True和管理员bot_id
                else:
                    return True, None  # 在群组中但不是管理员

        except Exception as e:
            # 这个机器人不在群组中，继续检查下一个
            continue

    return False, None  # 没有机器人加入群组


def get_upline_chain(telegram_id, max_level=10):
    """
    获取用户的上级链（向上N层），如果上级不足，自动用捡漏账号补齐
    
    Args:
        telegram_id: 用户Telegram ID
        max_level: 最大层级数
    
    Returns:
        list: 上级链列表，格式: [{'level': 层级, 'id': telegram_id, 'is_fallback': bool}, ...]
    """
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app.config import DB_PATH
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    upline_chain = []  # 格式: [{'level': 层级, 'id': telegram_id, 'is_fallback': bool}]
    current_id = telegram_id
    
    # 1. 先找真实的推荐人链条
    for level in range(1, max_level + 1):
        c.execute('SELECT referrer_id FROM members WHERE telegram_id = ?', (current_id,))
        row = c.fetchone()
        
        if row and row[0]:
            # 找到真实上级
            upline_chain.append({'level': level, 'id': row[0], 'is_fallback': False})
            current_id = row[0]
        else:
            # 没有上级了，停止查找真实上级
            break
    
    # 2. 如果层数不足，用捡漏账号补齐
    current_chain_len = len(upline_chain)
    needed_count = max_level - current_chain_len
    
    if needed_count > 0:
        # 获取所有激活的捡漏账号，按ID排序
        c.execute('SELECT telegram_id FROM fallback_accounts WHERE is_active = 1 ORDER BY id ASC')
        fallback_rows = c.fetchall()
        # 过滤掉 None 值，确保全是有效的 ID
        fallback_ids = [r[0] for r in fallback_rows if r[0] is not None]
        
        if fallback_ids:
            # 从下一层开始补
            start_level = current_chain_len + 1
            for i in range(needed_count):
                current_level = start_level + i
                # 循环使用捡漏账号: 第1个补位用第1个账号，第2个用第2个...
                # 使用取余算法实现循环分配
                fb_id = fallback_ids[i % len(fallback_ids)]
                
                upline_chain.append({
                    'level': current_level, 
                    'id': fb_id, 
                    'is_fallback': True
                })
        else:
            print(f'[get_upline_chain] 警告: 数据库中没有激活的捡漏账号，无法补足 {needed_count} 层')
    
    conn.close()
    return upline_chain


def get_downline_tree(telegram_id, max_level=10):
    """
    获取用户的下级树（向下N层）
    
    Args:
        telegram_id: 用户Telegram ID
        max_level: 最大层级数
    
    Returns:
        dict: 下级树结构 {层级: [用户列表]}
    """
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app.config import DB_PATH
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    downline_tree = {}
    current_level_ids = [telegram_id]
    
    for level in range(1, max_level + 1):
        if not current_level_ids:
            break
        
        # 查询当前层级所有用户的直推下级
        placeholders = ','.join(['?'] * len(current_level_ids))
        c.execute(f'''
            SELECT telegram_id, username, is_vip, register_time
            FROM members
            WHERE referrer_id IN ({placeholders})
        ''', current_level_ids)
        
        downlines = c.fetchall()
        if downlines:
            downline_tree[level] = [
                {
                    'telegram_id': row[0],
                    'username': row[1],
                    'is_vip': row[2],
                    'register_time': row[3]
                }
                for row in downlines
            ]
            # 准备下一层的查询
            current_level_ids = [row[0] for row in downlines]
        else:
            break
    
    conn.close()
    return downline_tree


def calculate_team_stats(telegram_id, max_level=10):
    """
    计算团队统计数据
    
    Args:
        telegram_id: 用户Telegram ID
        max_level: 最大层级数
    
    Returns:
        dict: {'direct_count': 直推人数, 'team_count': 团队总人数, 'vip_count': VIP人数}
    """
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app.config import DB_PATH
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # 直推人数
    c.execute('SELECT COUNT(*) FROM members WHERE referrer_id = ?', (telegram_id,))
    direct_count = c.fetchone()[0]
    
    # 团队总人数（递归查询所有下级）
    team_count = 0
    vip_count = 0
    
    downline_tree = get_downline_tree(telegram_id, max_level)
    for level_users in downline_tree.values():
        team_count += len(level_users)
        vip_count += sum(1 for u in level_users if u['is_vip'])
    
    conn.close()
    return {
        'direct_count': direct_count,
        'team_count': team_count,
        'vip_count': vip_count
    }


async def check_user_conditions(bot, telegram_id):
    """
    检查用户是否满足所有条件
    
    Returns:
        dict: {
            'is_vip': bool,
            'is_group_bound': bool,
            'is_bot_admin': bool,
            'is_joined_upline': bool,
            'missing_conditions': []  # 未满足的条件列表
        }
    """
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app.config import DB_PATH
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''
        SELECT is_vip, is_group_bound, is_bot_admin, is_joined_upline, group_link
        FROM members WHERE telegram_id = ?
    ''', (telegram_id,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        return None
    
    is_vip, is_group_bound, is_bot_admin, is_joined_upline, group_link = row
    
    missing_conditions = []
    if not is_vip:
        missing_conditions.append('未开通VIP')
    if not is_group_bound:
        missing_conditions.append('未绑定群组')
    if not is_bot_admin:
        missing_conditions.append('未设置机器人为管理员')
    if not is_joined_upline:
        missing_conditions.append('未加入上层所有群组')
    
    return {
        'is_vip': bool(is_vip),
        'is_group_bound': bool(is_group_bound),
        'is_bot_admin': bool(is_bot_admin),
        'is_joined_upline': bool(is_joined_upline),
        'group_link': group_link or '',
        'missing_conditions': missing_conditions,
        'all_conditions_met': len(missing_conditions) == 0
    }


def update_level_path(telegram_id):
    """
    更新用户的层级路径
    
    Args:
        telegram_id: 用户Telegram ID
    """
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app.config import DB_PATH
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # 获取上级链
    path = []
    current_id = telegram_id
    
    for _ in range(20):  # 最多20层
        c.execute('SELECT referrer_id FROM members WHERE telegram_id = ?', (current_id,))
        row = c.fetchone()
        if not row or not row[0]:
            break
        path.insert(0, str(row[0]))
        current_id = row[0]
    
    level_path = ','.join(path) if path else ''
    
    # 更新level_path字段
    c.execute('UPDATE members SET level_path = ? WHERE telegram_id = ?', (level_path, telegram_id))
    conn.commit()
    conn.close()


def get_fallback_account(level):
    """
    获取指定层级的捡漏账号

    Args:
        level: 层级数 (1-10)

    Returns:
        int: 捡漏账号的telegram_id
    """
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app.config import DB_PATH
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 按顺序获取捡漏账号
    c.execute('SELECT telegram_id FROM fallback_accounts WHERE is_active = 1 ORDER BY id LIMIT 1 OFFSET ?',
             (level - 1,))
    row = c.fetchone()
    conn.close()

    return row[0] if row else None


# 【新增】生成VIP开通成功后的详细文案
def generate_vip_success_message(telegram_id, amount, vip_price, current_balance):
    """生成符合要求的VIP开通文案"""
    try:
        from app.config import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # 获取系统配置的层数
        c.execute("SELECT value FROM system_config WHERE key = 'level_count'")
        row = c.fetchone()
        level_count = int(row[0]) if row else 10
        conn.close()

        # 获取上级群列表
        upline_chain = get_upline_chain(telegram_id, level_count)
        upline_groups_text = ""
        group_count = 0

        # 再次连接获取上级详细信息
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        for item in upline_chain:
            if item.get('is_fallback'): continue # 跳过捡漏账号的群

            uid = item['id']
            lvl = item['level']
            c.execute("SELECT username, group_link FROM members WHERE telegram_id = ?", (uid,))
            u_row = c.fetchone()

            if u_row and u_row[1]: # 有群链接
                # 简单处理群名
                g_link = u_row[1]
                u_name = u_row[0] or f"用户{uid}"
                upline_groups_text += f"{lvl}. @{u_name}的群\n"
                group_count += 1

        conn.close()

        msg = (
            f"🎉 充值成功！VIP已开通！\n\n"
            f"💰 充值金额: {amount} U\n"
            f"💎 VIP费用: {vip_price} U\n"
            f"💵 当前余额: {current_balance} U\n\n"
            f"⚠️ 重要：请立即完成以下操作\n\n"
            f"1️⃣ 绑定您的群组\n"
            f"2️⃣ 加入上层群组（共{group_count}个）\n"
            f"{upline_groups_text}\n"
            f"完成以上操作后，您的下级开通VIP时\n"
            f"您才能获得分红！"
        )
        return msg
    except Exception as e:
        print(f"[生成文案错误] {e}")
        return f"🎉 VIP开通成功！\n花费: {vip_price}U\n余额: {current_balance}U"


async def distribute_vip_rewards(bot, telegram_id, pay_amount, config):
    """
    统一处理VIP开通后的分红逻辑（终极修复版：全链路去重 + 详细说明记录）
    """
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app.config import DB_PATH

    level_count = int(config.get('level_count', 10))
    reward_amount = float(config.get('level_reward', 1))

    chain = get_upline_chain(telegram_id, level_count)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT username FROM members WHERE telegram_id = ?', (telegram_id,))
    user_row = c.fetchone()
    source_username = user_row[0] if user_row else str(telegram_id)
    conn.close()

    reward_stats = {'real': 0, 'fallback': 0}

    # 记录本轮已获得奖励的账号ID（包括真实用户和捡漏账号）
    used_ids_in_this_round = set()

    # 预先加载所有活跃捡漏账号（按ID排序）
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT telegram_id FROM fallback_accounts WHERE is_active = 1 ORDER BY id ASC')
    all_fb_rows = c.fetchall()
    all_valid_fbs = [r[0] for r in all_fb_rows if r[0] is not None]
    conn.close()

    for item in chain:
        level = item['level']
        upline_id = item['id']
        is_fallback_in_chain = item['is_fallback']

        if not upline_id or str(upline_id) == 'None': continue

        conn = sqlite3.connect(DB_PATH, timeout=10)
        c = conn.cursor()

        try:
            target_id_to_reward = None
            is_rewarding_fallback = False

            # 【关键修改】用于存储具体的失败原因描述
            record_description = ""
            # --- 步骤A：确定这一层的原始接收者 ---
            if is_fallback_in_chain:
                # 链条本身就是捡漏账号（说明这一层没有真实上级）
                candidate_id = upline_id
                is_rewarding_fallback = True
                record_description = f"第{level}层无上级（自动捡漏）"
            else:
                # 真实用户，检查条件
                c.execute('SELECT username, is_vip, is_group_bound, is_bot_admin, is_joined_upline FROM members WHERE telegram_id = ?', (upline_id,))
                row = c.fetchone()

                # 获取上级显示名称
                upline_name = str(upline_id)
                if row and row[0]:
                    upline_name = f"@{row[0]}"

                if row and row[1] and row[2] and row[3] and row[4]:
                    # 真实用户达标
                    candidate_id = upline_id
                    is_rewarding_fallback = False
                    record_description = f"第{level}层下级开通VIP"
                else:
                    # 真实用户不达标
                    candidate_id = None
                    is_rewarding_fallback = True

                    # 【关键修改】构建详细的失败原因
                    fail_reasons = []
                    if not row:
                        fail_reasons.append("用户不存在")
                    else:
                        if not row[1]: fail_reasons.append("未VIP")
                        if not row[2]: fail_reasons.append("未绑群")
                        if not row[3]: fail_reasons.append("未设置群管")
                        if not row[4]: fail_reasons.append("未加群")

                    reason_str = ",".join(fail_reasons)
                    # 这里的格式就是您想要的：显示具体哪个上级没完成
                    record_description = f"上级 {upline_name} {reason_str}（转入捡漏）"
                    # 记录错过收益通知
                    if row:
                        c.execute('UPDATE members SET missed_balance = missed_balance + ? WHERE telegram_id = ?',
                                 (reward_amount, upline_id))
                        # 发送通知给那个不争气的上级
                        try:
                            await bot.send_message(
                                upline_id,
                                f"💸 **错失收益通知**\n\n"
                                f"您错过了 {reward_amount} U 的收益！\n"
                                f"原因: {reason_str}\n"
                                f"来源: 下级 @{source_username} (第{level}层) 开通VIP\n\n"
                                f"请尽快完成任务，以免再次错过！"
                            )
                        except: pass

            # --- 步骤B：如果需要捡漏，寻找替补 ---
            if is_rewarding_fallback:
                start_index = (level - 1) % len(all_valid_fbs) if all_valid_fbs else 0
                found_fb = None

                # 优先检查 chain 自带的那个捡漏号
                if candidate_id and candidate_id in all_valid_fbs and candidate_id not in used_ids_in_this_round:
                    found_fb = candidate_id
                else:
                    # 轮询查找
                    if all_valid_fbs:
                        for i in range(len(all_valid_fbs)):
                            idx = (start_index + i) % len(all_valid_fbs)
                            fb_candidate = all_valid_fbs[idx]
                            if fb_candidate not in used_ids_in_this_round:
                                found_fb = fb_candidate
                                break
                        if found_fb is None: found_fb = all_valid_fbs[start_index]

                target_id_to_reward = found_fb
            else:
                target_id_to_reward = candidate_id

            # --- 步骤C：执行发放 ---
            if target_id_to_reward:
                # 确保账号存在
                if is_rewarding_fallback:
                    c.execute('SELECT id FROM members WHERE telegram_id = ?', (target_id_to_reward,))
                    if not c.fetchone():
                        c.execute('SELECT username FROM fallback_accounts WHERE telegram_id = ?', (target_id_to_reward,))
                        fb_name = c.fetchone()
                        name = fb_name[0] if fb_name else f'fallback_{target_id_to_reward}'
                        c.execute('INSERT OR IGNORE INTO members (telegram_id, username, is_vip, register_time) VALUES (?, ?, 1, ?)',
                                 (target_id_to_reward, name, get_cn_time()))

                    c.execute('UPDATE fallback_accounts SET total_earned = total_earned + ? WHERE telegram_id = ?',
                             (reward_amount, target_id_to_reward))
                    reward_stats['fallback'] += 1
                else:
                    reward_stats['real'] += 1

                used_ids_in_this_round.add(int(target_id_to_reward))

                # 更新余额
                c.execute('UPDATE members SET balance = balance + ?, total_earned = total_earned + ? WHERE telegram_id = ?',
                         (reward_amount, reward_amount, target_id_to_reward))

                # 【关键修改】写入数据库时使用上面构建好的详细说明
                c.execute('''INSERT INTO earnings_records (upgraded_user, earning_user, amount, description, create_time)
                           VALUES (?, ?, ?, ?, ?)''',
                           (telegram_id, target_id_to_reward, reward_amount, record_description, get_cn_time()))

                # 通知
                if not is_rewarding_fallback:
                    try:
                        await bot.send_message(target_id_to_reward,
                            f'🎉 获得 {reward_amount} U 奖励\n来源：第 {level} 层下级 @{source_username} 开通VIP')
                    except: pass

            conn.commit()
        except Exception as e:
            print(f"[分红分配错误] Level {level}: {e}")
        finally:
            conn.close()

    return reward_stats
