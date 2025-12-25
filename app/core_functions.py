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

async def verify_group_link(bot, link):
    """验证群链接，检查机器人是否在群内且为管理员
    
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
        
        # 1) 私有邀请链接: +hash 或 joinchat/hash -> 无法用 Bot 检测管理员，只能记录
        if tail.startswith('+') or tail.startswith('joinchat/'):
            return {
                'success': True,
                'message': '私有邀请链接已记录，Telegram 限制无法自动检测管理员，请确保机器人已在群且为管理员',
                'admin_checked': False
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
            
        # 获取机器人在群内的权限
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


async def distribute_vip_rewards(bot, telegram_id, pay_amount, config):
    """
    统一处理VIP开通后的分红逻辑
    
    :param bot: 机器人客户端
    :param telegram_id: 开通VIP的用户ID
    :param pay_amount: 支付金额（用于日志）
    :param config: 系统配置字典
    :return: dict {'real': 真实上级获得奖励数, 'fallback': 捡漏账号获得奖励数}
    """
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app.config import DB_PATH
    
    level_count = int(config.get('level_count', 10))
    reward_amount = float(config.get('level_reward', 1))
    
    # 获取完整的上级链（包含自动补位的捡漏账号）
    chain = get_upline_chain(telegram_id, level_count)
    
    # 获取开通者信息用于通知
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT username FROM members WHERE telegram_id = ?', (telegram_id,))
    user_row = c.fetchone()
    source_username = user_row[0] if user_row else str(telegram_id)
    conn.close()
    
    reward_stats = {'real': 0, 'fallback': 0}
    used_fallbacks = set()

    for item in chain:
        level = item['level']
        upline_id = item['id']
        is_fallback = item['is_fallback']
        
        # 【关键修复】如果 ID 无效，直接跳过，防止污染数据库
        if not upline_id or str(upline_id) == 'None' or upline_id == 'None':
            print(f"[分红] 跳过无效ID: Level {level}, ID={upline_id}")
            continue
        
        conn = sqlite3.connect(DB_PATH, timeout=10)
        c = conn.cursor()
        
        try:
            if is_fallback:
                # --- 捡漏账号逻辑 ---
                # 【关键修复】再次验证 ID 有效性（双重保险）
                if not upline_id or str(upline_id) == 'None' or upline_id == 'None':
                    print(f"[分红] 跳过无效的捡漏账号ID: Level {level}, ID={upline_id}")
                    conn.commit()
                    conn.close()
                    continue
                
                # 1. 确保捡漏账号在 members 表存在（为了收益能显示）
                c.execute('SELECT id FROM members WHERE telegram_id = ?', (upline_id,))
                if not c.fetchone():
                    # 获取用户名
                    c.execute('SELECT username FROM fallback_accounts WHERE telegram_id = ?', (upline_id,))
                    fb_row = c.fetchone()
                    fb_name = fb_row[0] if fb_row and fb_row[0] else f'fallback_{upline_id}'
                    # 插入members表，标记为VIP（确保 upline_id 有值）
                    c.execute('''INSERT OR IGNORE INTO members (telegram_id, username, is_vip, register_time) 
                                 VALUES (?, ?, 1, ?)''', (upline_id, fb_name, get_cn_time()))
                
                # 2. 发放奖励
                c.execute('UPDATE members SET balance = balance + ?, total_earned = total_earned + ? WHERE telegram_id = ?', 
                         (reward_amount, reward_amount, upline_id))
                
                # 3. 更新 fallback_accounts 表统计
                c.execute('UPDATE fallback_accounts SET total_earned = total_earned + ? WHERE telegram_id = ?',
                         (reward_amount, upline_id))
                
                # 4. 记录日志（记录：谁升级 -> 谁获得收益）
                c.execute('''INSERT INTO earnings_records
                           (upgraded_user, earning_user, amount, description, create_time)
                           VALUES (?, ?, ?, ?, ?)''',
                        (telegram_id, upline_id, reward_amount,
                         f'第{level}层下级开通VIP', get_cn_time()))
                
                reward_stats['fallback'] += 1
                # 标记已分配给该捡漏账号，防止同一次分配重复发放
                try:
                    used_fallbacks.add(int(upline_id))
                except:
                    pass
                
            else:
                # --- 真实上级逻辑 ---
                # 【核心修复】检查上级是否完成任务（is_joined_upline = 1）
                # 如果未完成任务，直接用捡漏账号代替，而不是烧伤
                c.execute('SELECT is_vip, is_group_bound, is_bot_admin, is_joined_upline FROM members WHERE telegram_id = ?', (upline_id,))
                row = c.fetchone()
                
                should_reward = False
                if row:
                    is_vip, is_bound, is_admin, is_joined = row
                    # 【核心修复】判断条件：VIP + 绑定群 + 机器人管理员 + 完成加群任务
                    if is_vip and is_bound and is_admin and is_joined:
                        should_reward = True
                
                if should_reward:
                    # 发放奖励给真实上级
                    c.execute('UPDATE members SET balance = balance + ?, total_earned = total_earned + ? WHERE telegram_id = ?', 
                             (reward_amount, reward_amount, upline_id))
                    
                    # 记录日志：升级用户 -> 获益用户
                    c.execute('''INSERT INTO earnings_records
                               (upgraded_user, earning_user, amount, description, create_time)
                               VALUES (?, ?, ?, ?, ?)''',
                            (telegram_id, upline_id, reward_amount,
                             f'第{level}层下级开通VIP', get_cn_time()))
                    
                    reward_stats['real'] += 1
                    
                    # 发送通知
                    try:
                        await bot.send_message(upline_id, 
                            f'🎉 获得 {reward_amount} U 奖励\n来源：第 {level} 层下级 @{source_username} 开通VIP')
                    except: 
                        pass
                else:
                    # 【核心修复】上级未完成任务或不存在 -> 直接用捡漏账号代替（不烧伤）
                    # 获取该层对应的捡漏账号
                    c.execute('SELECT telegram_id FROM fallback_accounts WHERE is_active = 1 ORDER BY id ASC')
                    fbs = c.fetchall()
                    # 过滤掉 None 值
                    valid_fbs = [r[0] for r in fbs if r[0] is not None]
                    
                    if valid_fbs:
                        # 选择一个尚未被本次分配使用的捡漏账号
                        # 如果所有都被使用了，跳过该层分配（不重复分配）
                        backup_fb_id = None
                        for offset in range(len(valid_fbs)):
                            candidate = valid_fbs[(level - 1 + offset) % len(valid_fbs)]
                            if candidate not in used_fallbacks:
                                backup_fb_id = candidate
                                break
                        # 如果没有可用的捡漏账号（都被使用了），跳过该层分配
                        if backup_fb_id is None:
                            print(f"[分红] 警告: Level {level} 所有捡漏账号都已被使用，跳过分配")
                            conn.commit()
                            conn.close()
                            continue
                        
                        # 【关键修复】再次检查 ID 有效性
                        if not backup_fb_id or str(backup_fb_id) == 'None' or backup_fb_id == 'None':
                            print(f"[分红] 跳过无效的捡漏账号ID: Level {level}, ID={backup_fb_id}")
                            conn.commit()
                            conn.close()
                            continue
                        
                        # 确保捡漏账号在members表存在
                        c.execute('SELECT id FROM members WHERE telegram_id = ?', (backup_fb_id,))
                        if not c.fetchone():
                            c.execute('SELECT username FROM fallback_accounts WHERE telegram_id = ?', (backup_fb_id,))
                            fb_row = c.fetchone()
                            fb_name = fb_row[0] if fb_row and fb_row[0] else f'fallback_{backup_fb_id}'
                            c.execute('''INSERT OR IGNORE INTO members (telegram_id, username, is_vip, register_time) 
                                         VALUES (?, ?, 1, ?)''', (backup_fb_id, fb_name, get_cn_time()))
                        
                        # 发放奖励给捡漏账号
                        c.execute('UPDATE members SET balance = balance + ?, total_earned = total_earned + ? WHERE telegram_id = ?',
                                 (reward_amount, reward_amount, backup_fb_id))
                        c.execute('UPDATE fallback_accounts SET total_earned = total_earned + ? WHERE telegram_id = ?',
                                 (reward_amount, backup_fb_id))
                        c.execute('''INSERT INTO earnings_records
                                   (upgraded_user, earning_user, amount, description, create_time)
                                   VALUES (?, ?, ?, ?, ?)''',
                                (telegram_id, backup_fb_id, reward_amount,
                                 f'第{level}层下级开通VIP', get_cn_time()))
                        reward_stats['fallback'] += 1
                        try:
                            used_fallbacks.add(int(backup_fb_id))
                        except:
                            pass
                    else:
                        print(f"[分红] 警告: Level {level} 没有可用的捡漏账号，奖励丢失")

            conn.commit()
        except Exception as e:
            print(f"[分红分配错误] Level {level}: {e}")
            import traceback
            traceback.print_exc()
        finally:
            conn.close()
            
    return reward_stats
