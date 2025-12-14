"""
核心功能模块
包含群组检测、层级计算、分红分配等核心逻辑
"""
import sqlite3
import os
import sys
from telethon import TelegramClient
from telethon.tl.functions.channels import GetParticipantRequest
from telethon.tl.types import ChannelParticipantAdmin, ChannelParticipantCreator

# 导入配置
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
from app.config import DB_PATH


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


def get_upline_chain(telegram_id, max_level=10):
    """
    获取用户的上级链（向上N层）
    
    Args:
        telegram_id: 用户Telegram ID
        max_level: 最大层级数
    
    Returns:
        list: 上级链列表，按层级从近到远排序 [(层级, telegram_id), ...]
    """
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app.config import DB_PATH
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    upline_chain = []
    current_id = telegram_id
    level = 1
    
    while level <= max_level:
        # 查询当前用户的推荐人
        c.execute('SELECT referrer_id FROM members WHERE telegram_id = ?', (current_id,))
        row = c.fetchone()
        
        if not row or not row[0]:
            # 没有上级了，用捡漏账号补足
            break
        
        referrer_id = row[0]
        upline_chain.append((level, referrer_id))
        current_id = referrer_id
        level += 1
    
    # 如果不足max_level层，用捡漏账号补足
    if len(upline_chain) < max_level:
        c.execute('SELECT telegram_id FROM fallback_accounts WHERE is_active = 1 ORDER BY id LIMIT ?',
                 (max_level - len(upline_chain),))
        fallback_ids = c.fetchall()
        
        for i, (fb_id,) in enumerate(fallback_ids):
            upline_chain.append((len(upline_chain) + 1, fb_id))
    
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
