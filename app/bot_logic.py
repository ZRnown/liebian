"""
机器人逻辑层 - 统一管理所有Telegram机器人交互
【核心修复】所有VIP开通路径都调用 distribute_vip_rewards，删除冗余的手写分红逻辑
"""
import asyncio
import sqlite3
import time
import os
from urllib.parse import quote  # 【新增】用于URL编码推广文案
from datetime import datetime, timedelta, timezone
from telethon import TelegramClient, events, Button
from telethon.sessions import MemorySession
from telethon.tl.types import ChannelParticipantsAdmins
from telethon.tl.functions.channels import GetParticipantRequest
import socks

from config import (
    API_ID, API_HASH, ADMIN_IDS, USE_PROXY,
    PROXY_TYPE, PROXY_HOST, PROXY_PORT, DATA_DIR
)
from database import DB, get_cn_time, get_system_config, get_db_conn
from core_functions import (
    get_upline_chain, check_user_conditions, update_level_path,
    distribute_vip_rewards, check_user_in_group, check_bot_is_admin,
    verify_group_link, check_any_bot_in_group
)
from bot_commands_addon import (
    handle_bind_group, handle_join_upline, handle_group_link_message,
    handle_check_status, handle_my_team
)

def compute_vip_price_from_config(config):
    """计算VIP价格 (逻辑同步Web端)"""
    try:
        level_count = int(config.get('level_count', 10))
        # 默认值防止为0
        default_reward = float(config.get('level_reward', 1.0))
        if default_reward <= 0: default_reward = 1.0

        level_amounts = config.get('level_amounts')
        if level_amounts:
            import json
            try:
                if isinstance(level_amounts, str):
                    parsed = json.loads(level_amounts)
                else:
                    parsed = level_amounts
            except:
                parsed = None

            if isinstance(parsed, list):
                vals = []
                last_val = default_reward
                for x in parsed[:level_count]:
                    try:
                        v = float(x)
                        if v > 0: last_val = v
                    except: v = last_val
                    vals.append(v)
                # 补齐
                if len(vals) < level_count:
                    vals += [last_val] * (level_count - len(vals))
                return sum(vals)
            elif isinstance(parsed, dict):
                total = 0.0
                for i in range(1, level_count + 1):
                    v = parsed.get(str(i)) or parsed.get(i) or default_reward
                    total += float(v)
                return total

        # 默认返回固定价格
        return default_reward * level_count
    except Exception as e:
        print(f'[VIP价格计算] 错误: {e}')
        return 10.0  # 默认价格



# 按钮文字常量
BTN_PROFILE = '👤 个人中心'
BTN_FISSION = '🔗 群裂变加入'
BTN_VIEW_FISSION = '📊 我的裂变'
BTN_RESOURCES = '📁 行业资源'
BTN_PROMOTE = '💰 赚钱推广'
BTN_SUPPORT = '👩‍💼 在线客服'
BTN_BACK = '🔙 返回主菜单'
BTN_ADMIN = '⚙️ 管理后台'
BTN_VIP = '💎 开通会员'
BTN_MY_PROMOTE = '💫 我的推广'
BTN_EARNINGS = '📊 收益记录'


async def send_vip_required_prompt(event_or_id, reply_method='respond'):
    """给未开通VIP的用户发送统一提示文案，支持 event 或 telegram_id"""
    try:
        if isinstance(event_or_id, int):
            telegram_id = event_or_id
            member = DB.get_member(telegram_id)
            client = bot # 默认使用主bot发送主动消息
        else:
            original = event_or_id
            client = original.client # 使用触发事件的那个机器人实例
            try:
                original_sender_id = original.sender_id
                original.sender_id = get_main_account_id(original_sender_id, getattr(original.sender, 'username', None))
            except Exception:
                pass
            member = DB.get_member(original.sender_id)
            telegram_id = original.sender_id

        config = get_system_config()
        # 优先从配置计算VIP总价，确保和层级设置一致
        vip_price = compute_vip_price_from_config(config)
        balance = member['balance'] if member else 0

        # 【修复】更新文案格式
        text = "抱歉 您还不是VIP\n\n"
        text += "不能使用此功能 请先开通VIP\n"
        text += "点击下方「开通VIP」按钮 开通在来哦\n\n"
        text += f"💰 VIP价格: {vip_price} U\n"
        text += f"💵 当前余额: {balance} U\n"

        buttons = []
        # 如果余额足够，提供余额开通按钮；否则只提供充值入口
        if balance >= vip_price:
            buttons = [[Button.inline('💎 余额开通VIP', b'open_vip_balance')]]
        else:
            # 计算差额
            need = vip_price - balance
            text += f"\n\n❌ 余额不足，请先充值"
            buttons = [[Button.inline(f'💳 充值开通VIP', b'recharge_for_vip')]]

        if isinstance(event_or_id, int):
            try:
                if client: await client.send_message(telegram_id, text, buttons=buttons)
            except Exception:
                pass
        else:
            # event-like
            try:
                if reply_method == 'respond':
                    await event_or_id.respond(text, buttons=buttons)
                else:
                    await event_or_id.answer(text, alert=True)
            except Exception:
                try:
                    await event_or_id.answer(text, alert=True)
                except Exception:
                    pass
    except Exception as e:
        print(f"[VIP提示] 发送失败: {e}")

# ==================== 多机器人初始化逻辑 ====================

def get_active_bot_tokens():
    """获取所有活跃的机器人token"""
    try:
        conn = get_db_conn()
        c = conn.cursor()
        c.execute('SELECT id, bot_token FROM bot_configs WHERE is_active = 1 ORDER BY id ASC')
        rows = c.fetchall()
        conn.close()
        # 返回 (id, token) 列表
        tokens = [(row[0], row[1]) for row in rows if row[1]]
        print(f"[机器人初始化] 找到 {len(tokens)} 个活跃机器人token")
        return tokens
    except Exception as e:
        print(f"[机器人初始化] 获取活跃token失败: {e}")
        return []

# 初始化客户端列表
clients = []
active_tokens = get_active_bot_tokens()

# 权限检查控制变量
permission_check_triggered = False

# 如果数据库没配置，尝试读取环境变量配置作为默认
if not active_tokens:
    from config import BOT_TOKEN
    if BOT_TOKEN:
        print("[机器人初始化] 数据库无配置，使用默认配置文件Token")
        active_tokens.append((0, BOT_TOKEN))
    else:
        print("[机器人初始化] ❌ 错误：没有找到任何机器人配置！")

# 代理设置
proxy = None
if USE_PROXY:
    if PROXY_TYPE.lower() == 'socks5':
        proxy = (socks.SOCKS5, PROXY_HOST, PROXY_PORT)
    elif PROXY_TYPE.lower() == 'socks4':
        proxy = (socks.SOCKS4, PROXY_HOST, PROXY_PORT)
    elif PROXY_TYPE.lower() == 'http':
        proxy = (socks.HTTP, PROXY_HOST, PROXY_PORT)
    else:
        proxy = (socks.SOCKS5, PROXY_HOST, PROXY_PORT)

# 确保 session 目录存在
from config import SESSION_DIR
os.makedirs(SESSION_DIR, exist_ok=True)

# 创建所有机器人客户端
for db_id, token in active_tokens:
    try:
        # 【关键修复】使用独立的 Session 文件名，防止冲突
        # 使用数据库ID作为区分，ID为0的是配置文件默认Bot
        session_name = f'bot_{db_id}'
        session_path = os.path.join(SESSION_DIR, session_name)

        print(f"[机器人初始化] 正在启动 Bot ID {db_id} (Session: {session_name})...")

        # 【新增】添加重试机制，解决网络连接问题
        max_retries = 3
        for attempt in range(max_retries):
            try:
                client = TelegramClient(session_path, API_ID, API_HASH, proxy=proxy)
                # 启动客户端，设置较长的超时时间
                client.start(bot_token=token)
                clients.append(client)
                print(f"[机器人初始化] ✅ 成功启动: {token[:10]}... (尝试 {attempt + 1}/{max_retries})")
                break  # 成功启动，跳出重试循环
            except Exception as retry_e:
                print(f"[机器人初始化] 尝试 {attempt + 1}/{max_retries} 失败: {retry_e}")
                if attempt == max_retries - 1:
                    raise retry_e  # 最后一次尝试失败，抛出异常
                import time
                time.sleep(2)  # 等待2秒后重试

    except Exception as e:
        print(f"[机器人初始化] ❌ 启动失败 (ID: {db_id}): {e}")
        print(f"[机器人初始化] 🔄 将跳过此机器人，继续启动其他机器人...")

if not clients:
    print("[机器人初始化] ❌ 严重错误：无法启动任何机器人")
    print("[机器人初始化] 💡 Web管理后台仍可正常使用，请检查机器人Token配置")
    bot = None
else:
    # 定义 bot 为第一个客户端 (主要用于后台任务的主动发送)
    bot = clients[0]
    print(f"[机器人初始化] 🎉 成功启动 {len(clients)} 个机器人客户端")

# 自定义装饰器：注册事件到所有机器人
def multi_bot_on(event_builder):
    def decorator(handler):
        for client in clients:
            client.add_event_handler(handler, event_builder)
        return handler
    return decorator

print(f"[机器人初始化] ✅ 全部启动完成，共 {len(clients)} 个机器人在线")

# 全局队列
pending_broadcasts = []
notify_queue = []
process_recharge_queue = []
waiting_for_group_link = {}
waiting_for_backup = {}
waiting_for_recharge_amount = {}
waiting_for_withdraw_amount = {}
waiting_for_withdraw_address = {}
withdraw_temp_data = {}
admin_waiting = {}

# 导入支付模块
from payment import create_recharge_order, PAYMENT_CONFIG, generate_payment_sign

# ==================== 账号关联逻辑 ====================

def get_main_account_id(telegram_id, username=None):
    """获取主账号ID（精准ID匹配版）"""
    try:
        target_id_str = str(telegram_id).strip()
        clean_username = (username or '').strip().lstrip('@')
        
        conn = get_db_conn()
        c = conn.cursor()
        
        # 核心查询：查找是否有人的 backup_account 字段等于当前访问者的 ID
        query = "SELECT telegram_id FROM members WHERE backup_account = ?"
        c.execute(query, (target_id_str,))
        row = c.fetchone()
        
        # 如果ID没查到，再尝试查用户名
        if not row and clean_username:
            c.execute(
                'SELECT telegram_id FROM members WHERE backup_account = ? OR backup_account = ?',
                (clean_username, f"@{clean_username}")
            )
            row = c.fetchone()
            
        # 捡漏账号逻辑
        if not row:
            c.execute(
                'SELECT main_account_id FROM fallback_accounts '
                'WHERE telegram_id = ? AND main_account_id IS NOT NULL LIMIT 1',
                (telegram_id,)
            )
            fallback_result = c.fetchone()
            if fallback_result and fallback_result[0]:
                conn.close()
                return fallback_result[0]
        
        conn.close()
        
        if row:
            print(f"✅ [账号映射] {target_id_str} -> 主账号 {row[0]}")
            return int(row[0]) # 确保返回整数
        
        return telegram_id
    except Exception as e:
        print(f"[关联查询出错] {e}")
        return telegram_id

def format_backup_account_display(backup_account):
    """格式化备用号显示"""
    if not backup_account:
        return "未设置"
    
    backup_account_str = str(backup_account).strip()
    
    if backup_account_str.startswith('@'):
        return backup_account_str
    if not backup_account_str.isdigit():
        return f"@{backup_account_str}"
    
    try:
        backup_id = int(backup_account_str)
        backup_member = DB.get_member(backup_id)
        if backup_member and backup_member.get('username'):
            return f"@{backup_member['username']}"
        else:
            return backup_account_str
    except (ValueError, Exception):
        return backup_account_str

def resolve_sender_id(event):
    """解析发送者ID，支持备用号映射"""
    original_id = event.sender_id
    main_id = get_main_account_id(original_id, getattr(event.sender, 'username', None))

    # 如果映射成功，返回主号ID；否则返回原始ID
    return main_id if main_id != original_id else original_id

def get_resolved_sender_info(event):
    """获取解析后的发送者信息，返回 (original_id, resolved_id)"""
    original_id = event.sender_id
    resolved_id = resolve_sender_id(event)
    return original_id, resolved_id

def with_account_resolution(func):
    """装饰器：自动处理账号解析"""
    async def wrapper(event, *args, **kwargs):
        # 为事件对象添加解析后的ID属性
        original_id, resolved_id = get_resolved_sender_info(event)
        event._original_sender_id = original_id
        event._resolved_sender_id = resolved_id
        # 保持向后兼容
        event.sender_id = resolved_id
        return await func(event, *args, **kwargs)
    return wrapper

async def check_user_group_binding_status(user_id, clients):
    """检查用户的群组绑定是否仍然有效"""
    try:
        # 获取用户的群组绑定信息
        member = DB.get_member(user_id)
        if not member or not member.get('group_link') or not member.get('is_group_bound'):
            return False

        group_link = member['group_link']
        print(f'[群组检测] 检查用户 {user_id} 的群组绑定: {group_link}')

        # 使用多机器人逻辑检查是否有机器人仍在群组中且为管理员
        is_any_bot_in_group, admin_bot_id = await check_any_bot_in_group(clients, group_link)

        if not is_any_bot_in_group:
            # 没有机器人加入群组，标记绑定失效
            print(f'[群组检测] 用户 {user_id} 的群组绑定失效：没有机器人加入群组')
            # 更新数据库状态
            conn = get_db_conn()
            c = conn.cursor()
            c.execute('UPDATE members SET is_group_bound = 0, is_bot_admin = 0 WHERE telegram_id = ?', (user_id,))
            conn.commit()
            conn.close()
            return False
        elif admin_bot_id is None:
            # 有机器人加入但不是管理员，标记管理员权限失效
            print(f'[群组检测] 用户 {user_id} 的管理员权限失效：机器人不在群组或不是管理员')
            # 更新数据库状态
            conn = get_db_conn()
            c = conn.cursor()
            c.execute('UPDATE members SET is_bot_admin = 0 WHERE telegram_id = ?', (user_id,))
            conn.commit()
            conn.close()
            return True  # 绑定仍然有效，只是管理员权限失效

        # 绑定完全有效
        print(f'[群组检测] 用户 {user_id} 的群组绑定完全有效')
        return True

    except Exception as e:
        print(f'[群组检测] 检查用户 {user_id} 群组绑定失败: {e}')
        return False

async def notify_group_binding_invalid(chat_id, bot_id=None, reason="群组状态异常", notify_bot=None):
    """通知所有绑定指定群组的用户，群组绑定已失效"""
    try:
        conn = get_db_conn()
        c = conn.cursor()

        # 【核心修复】ID 格式兼容处理
        # 尝试查找匹配的 ID，考虑到 -100 前缀的情况
        target_ids = [chat_id]
        if isinstance(chat_id, int):
            # 如果是正数，尝试添加 -100 前缀 (Telegram 超级群组 ID)
            if chat_id > 0:
                target_ids.append(int(f"-100{chat_id}"))
            # 如果是负数且以 -100 开头，尝试去掉前缀 (以防数据库存的是短 ID)
            elif str(chat_id).startswith('-100'):
                try:
                    target_ids.append(int(str(chat_id)[4:]))
                except:
                    pass

        placeholders = ','.join(['?'] * len(target_ids))
        query = f'SELECT telegram_id, group_name, group_link, group_id FROM member_groups WHERE group_id IN ({placeholders})'

        print(f'[通知] 正在查找绑定群组的用户，尝试匹配ID: {target_ids}')
        c.execute(query, target_ids)
        bound_users = c.fetchall()
        conn.close()

        if not bound_users:
            print(f'[通知] ❌ 未在数据库中找到绑定群组 {chat_id} (或变体 {target_ids}) 的用户')
            return

        print(f'[通知] ✅ 找到 {len(bound_users)} 个绑定用户，准备发送通知')

        # 重置这些用户的群组绑定状态
        for user_id, group_name, group_link, db_group_id in bound_users:
            try:
                # 为每个用户单独处理数据库操作，避免并发问题
                # 添加重试机制处理数据库锁定
                max_retries = 5
                retry_delay = 0.2
                username = f'用户{user_id}'

                for attempt in range(max_retries):
                    try:
                        user_conn = get_db_conn()
                        user_cursor = user_conn.cursor()

                        # 获取用户真实姓名
                        user_cursor.execute('SELECT username FROM members WHERE telegram_id = ?', (user_id,))
                        user_row = user_cursor.fetchone()
                        username = user_row[0] if user_row else f'用户{user_id}'

                        # 更新数据库：清除群组绑定和管理员状态，并重置加群任务状态
                        user_cursor.execute('''
                            UPDATE members
                            SET is_group_bound = 0, is_bot_admin = 0, is_joined_upline = 0
                            WHERE telegram_id = ?
                        ''', (user_id,))

                        # 同时删除member_groups表中的记录
                        user_cursor.execute('DELETE FROM member_groups WHERE telegram_id = ? AND group_id = ?', (user_id, chat_id))

                        user_conn.commit()
                        user_conn.close()
                        break  # 成功后跳出重试循环

                    except Exception as db_err:
                        if user_conn:
                            try:
                                user_conn.close()
                            except:
                                pass

                        if 'locked' in str(db_err).lower() and attempt < max_retries - 1:
                            print(f'[通知] 数据库锁定，重试 {attempt + 1}/{max_retries} 用户 {user_id}: {db_err}')
                            await asyncio.sleep(retry_delay * (attempt + 1))  # 递增延迟
                            continue
                        else:
                            print(f'[通知] 处理用户 {user_id} 数据库操作失败 (尝试 {attempt + 1}/{max_retries}): {db_err}')
                            raise db_err

                # 如果数据库操作失败，继续处理通知（不阻断通知发送）
                print(f'[通知] 开始向用户 {user_id} ({username}) 发送通知')

                # 通知用户
                notification_msg = f'''
⚠️ **群组绑定状态异常**

您的群组绑定已失效，原因：{reason}

原群组：{group_name}
原群链接：{group_link}

请重新设置群组绑定以继续获得分红收益。
                '''.strip()

                # 使用指定的机器人发送通知，如果没有指定则使用全局bot
                notification_sent = False
                if notify_bot:
                    try:
                        bot_info = await notify_bot.get_me()
                        bot_name = bot_info.username or str(bot_info.id)
                        await notify_bot.send_message(user_id, notification_msg)
                        print(f'[通知] ✅ 使用指定机器人({bot_name}) 已通知用户 {user_id} ({username}) 群组绑定失效')
                        notification_sent = True
                    except Exception as e:
                        print(f'[通知] ❌ 使用指定机器人向用户 {user_id} 发送通知失败: {e}')

                if not notification_sent:
                    # 回退到使用所有活跃的机器人发送通知
                    for client in clients:
                        try:
                            await client.send_message(user_id, notification_msg)
                            print(f'[通知] ✅ 使用机器人已通知用户 {user_id} ({username}) 群组绑定失效')
                            notification_sent = True
                            break
                        except Exception as e:
                            print(f'[通知] ❌ 使用机器人向用户 {user_id} 发送通知失败: {e}')
                            continue

                if not notification_sent:
                    print(f'[通知] ❌ 所有机器人向用户 {user_id} ({username}) 发送通知都失败了')

            except Exception as user_err:
                print(f'[通知] 处理用户 {user_id} 失败: {user_err}')
                continue

            except Exception as user_err:
                print(f'[通知] 处理用户 {user_id} 失败: {user_err}')
                continue

            except Exception as e:
                print(f'[通知] 处理用户 {user_id} 失败: {e}')
                continue

    except Exception as e:
        print(f'[通知] 群组绑定失效通知失败: {e}')

def link_account(main_id, backup_id, backup_username):
    """关联备用号到主账号"""
    clean_username = (backup_username or '').strip().lstrip('@')
    
    if clean_username:
        value_to_store = f"@{clean_username}"
    elif backup_id:
        value_to_store = str(backup_id)
    else:
        return False, "❌ 无效的备用账号信息"
        
    if str(main_id) == str(backup_id) or value_to_store == str(main_id):
        return False, "❌ 不能将自己设置为备用号"

    try:
        if backup_id:
            existing_member = DB.get_member(backup_id)
            if existing_member and str(backup_id) != str(main_id):
                # 如果备用号已经注册，使用fallback_accounts表建立关联
                print(f"[备用号已注册] {backup_id} 已注册，将使用fallback_accounts建立关联")
                conn = get_db_conn()
                c = conn.cursor()
                try:
                    # 检查是否已经存在关联
                    c.execute('SELECT main_account_id FROM fallback_accounts WHERE telegram_id = ?', (backup_id,))
                    existing_fallback = c.fetchone()

                    if existing_fallback and str(existing_fallback[0]) != str(main_id):
                        conn.close()
                        return False, "❌ 该账号已经是其他人的备用号了，无法重复绑定"

                    # 插入或更新fallback_accounts
                    c.execute('''
                        INSERT OR REPLACE INTO fallback_accounts (telegram_id, main_account_id, username)
                        VALUES (?, ?, ?)
                    ''', (backup_id, main_id, clean_username or None))
                    conn.commit()
                    conn.close()
                    return True, f"✅ 备用账号关联成功！\n绑定值: {value_to_store}\n\n备用号已注册，将使用备用关联模式。\n\n请使用备用号访问个人中心测试。"
                except Exception as e:
                    try:
                        conn.close()
                    except:
                        pass
                    return False, f"备用关联设置失败: {e}"
    except Exception as e:
        print(f"[检查备用号是否已注册失败] {e}")

    conn = get_db_conn()
    c = conn.cursor()
    try:
        c.execute('SELECT telegram_id FROM members WHERE backup_account = ?', (str(backup_id),))
        existing_by_id = c.fetchone()
        
        c.execute(
            'SELECT telegram_id FROM members WHERE backup_account = ? OR backup_account = ?',
            (clean_username, f"@{clean_username}")
        )
        existing_by_name = c.fetchone()
        
        existing = existing_by_id or existing_by_name
        
        if existing and str(existing[0]) != str(main_id):
            conn.close()
            return False, "❌ 该账号已经是其他人的备用号了，无法重复绑定"

        c.execute('UPDATE members SET backup_account = ? WHERE telegram_id = ?', (value_to_store, main_id))
        conn.commit()
        conn.close()
        return True, f"✅ 备用账号关联成功！\n绑定值: {value_to_store}\n\n请使用备用号发送 /start 测试。"
        
    except Exception as e:
        try:
            conn.close()
        except:
            pass
        return False, f"关联失败: {str(e)}"

def get_fallback_resource(resource_type='group'):
    """获取捡漏账号资源"""
    try:
        conn = get_db_conn()
        c = conn.cursor()
        if resource_type == 'group':
            # 返回包含群组名称和链接的列表
            c.execute("SELECT username, group_link FROM fallback_accounts WHERE is_active = 1 AND group_link IS NOT NULL AND group_link != '' ORDER BY id ASC")
            results = c.fetchall()
            conn.close()
            if results:
                groups = []
                seen = set()
                for username, group_link in results:
                    if not group_link:
                        continue
                    g_links = group_link.split('\n')
                    for link in g_links:
                        link = link.strip()
                        if link and link not in seen:
                            # 默认使用用户名，如果没有则使用链接最后一部分
                            default_name = username or link.split('/')[-1].replace('+', '')
                            groups.append({
                                'username': username or '',
                                'link': link,
                                'name': default_name  # 默认名称，后续可以通过Telegram API获取实际名称
                            })
                            seen.add(link)
                return groups if groups else None
        elif resource_type == 'account':
            c.execute("SELECT telegram_id, username FROM fallback_accounts WHERE is_active = 1 ORDER BY RANDOM() LIMIT 1")
            result = c.fetchone()
            conn.close()
            if result:
                return {'telegram_id': result[0], 'username': result[1]}
        conn.close()
    except Exception as e:
        print(f"[捡漏错误] {e}")
    return None

async def get_group_title(bot, group_link):
    """从Telegram API获取群组实际名称"""
    try:
        # 提取群组用户名
        if 't.me/' in group_link:
            group_username = group_link.split('t.me/')[-1].split('/')[0].split('?')[0]
        elif group_link.startswith('@'):
            group_username = group_link[1:]
        else:
            return None
        
        # 跳过私有群链接
        if group_username.startswith('+'):
            return None
        
        # 获取群组实体
        group_entity = await bot.get_entity(group_username)
        title = getattr(group_entity, 'title', None)
        return title
    except Exception as e:
        print(f"[获取群组名称失败] {group_link}: {e}")
    return None

def get_main_keyboard(user_id=None):
    """主菜单键盘"""
    keyboard = [
        [Button.text(BTN_VIP, resize=True), Button.text(BTN_VIEW_FISSION, resize=True), Button.text(BTN_MY_PROMOTE, resize=True)],
        [Button.text(BTN_RESOURCES, resize=True), Button.text(BTN_FISSION, resize=True), Button.text(BTN_PROFILE, resize=True)],
        [Button.text(BTN_SUPPORT, resize=True)]
    ]
    if user_id and user_id in ADMIN_IDS:
        keyboard[-1].append(Button.text(BTN_ADMIN, resize=True))
    return keyboard

# ==================== 【核心修复】VIP开通逻辑 ====================
# 所有VIP开通路径都统一调用 distribute_vip_rewards，删除冗余的手写分红代码

async def process_vip_upgrade(telegram_id, vip_price, config, deduct_balance=True):
    """
    统一的VIP开通处理函数
    【核心】所有VIP开通都调用这个函数，确保逻辑一致
    
    Args:
        telegram_id: 用户ID
        vip_price: VIP价格（用于分红计算）
        config: 系统配置
        deduct_balance: 是否扣除余额（True=用户自己开通，False=管理员赠送）
    """
    # 1. 检查用户状态
    member = DB.get_member(telegram_id)
    if not member:
        return False, "用户不存在"
    
    if member.get('is_vip'):
        return False, "用户已是VIP"
    
    # 2. 扣除余额（如果需要）
    print(f'[process_vip_upgrade] 开始处理: telegram_id={telegram_id}, deduct_balance={deduct_balance}, 当前余额={member["balance"]}, vip_price={vip_price}')
    if deduct_balance:
        if member['balance'] < vip_price:
            print(f'[process_vip_upgrade] 余额不足: 需要{vip_price}, 当前{member["balance"]}')
            return False, "余额不足"
        new_balance = member['balance'] - vip_price
        print(f'[process_vip_upgrade] 扣费: {member["balance"]} -> {new_balance}')
        DB.update_member(telegram_id, balance=new_balance, is_vip=1, vip_time=get_cn_time())
    else:
        # 管理员赠送，不扣除余额
        new_balance = member['balance']
        print(f'[process_vip_upgrade] 管理员赠送VIP: 余额保持{new_balance}')
        DB.update_member(telegram_id, is_vip=1, vip_time=get_cn_time())
    
    # 3. 更新层级路径
    update_level_path(telegram_id)
    
    # 4. 【核心】调用统一分红函数（替代所有手写循环）
    # 使用主bot发送分红通知
    if bot:
        stats = await distribute_vip_rewards(bot, telegram_id, vip_price, config)
    else:
        stats = {'real': 0, 'total': 0}  # 如果bot未启动，返回空统计
    
    return True, {
        'new_balance': new_balance,
        'stats': stats
    }

# ==================== 辅助函数：检测并处理上级群失效 ====================

async def verify_and_handle_upline_group(bot, upline_id, group_link, clients):
    """
    检测上级群是否有效（机器人是否在群且为管理）。
    如果失效：
    1. 更新数据库标记该用户群绑定失效
    2. 发送通知给该上级用户
    3. 返回 False (表示不可用)
    """
    try:
        # 使用 check_any_bot_in_group 检查 (多机器人支持)
        is_in_group, admin_bot_id = await check_any_bot_in_group(clients, group_link)

        if is_in_group and admin_bot_id:
            return True # 有效：在群且是管理

        # --- 处理失效逻辑 ---
        print(f"[懒加载检测] 上级 {upline_id} 群组失效: {group_link}")

        # 1. 更新数据库
        conn = get_db_conn()
        c = conn.cursor()
        # 撤销群管状态，保留群链接以便用户知道是哪个群
        c.execute('UPDATE members SET is_bot_admin = 0 WHERE telegram_id = ?', (upline_id,))
        conn.commit()
        conn.close()

        # 2. 通知上级用户 (异步发送，不阻塞当前流程)
        try:
            fail_reason = "机器人不是管理员" if is_in_group else "机器人不在群组内"
            msg = f"⚠️ **群组权限异常通知**\n\n检测到您的群组状态异常：{fail_reason}\n\n这导致您的下级无法加入您的群组，您将**失去分红收益**！\n\n请尽快将机器人重新设为管理员。"
            await bot.send_message(upline_id, msg)
        except:
            pass # 可能被拉黑，忽略

        return False

    except Exception as e:
        print(f"[懒加载检测] 检查失败: {e}")
        return False # 保守起见，出错视为无效，转为捡漏

# ==================== 事件处理器 ====================

@multi_bot_on(events.NewMessage(pattern='/check_permission'))
async def check_permission_handler(event):
    """手动检查权限状态的命令"""
    original_id = event.sender_id
    sender_id = get_main_account_id(original_id, getattr(event.sender, 'username', None))

    member = DB.get_member(sender_id)
    if not member or not member.get('is_vip'):
        await event.respond("❌ 仅限VIP用户使用此功能")
        return

    await event.respond("🔍 正在检查您的群组权限状态...")

    # 立即触发权限检查
    global permission_check_triggered
    permission_check_triggered = True

    await event.respond("✅ 已触发权限检查，请等待系统自动检测并通知")

@multi_bot_on(events.NewMessage(pattern='/bind'))
async def bind_command_handler(event):
    """群内绑定命令：在群组中发送 /bind 绑定当前群"""
    if event.is_private:
        await event.respond("❌ 请在您需要绑定的**群组**内发送此命令")
        return

    try:
        # 1. 获取群组信息
        chat = await event.get_chat()
        if not chat:
            return

        chat_id = chat.id
        chat_title = chat.title or "未命名群组"

        # 获取群链接（如果有公开username）
        chat_username = getattr(chat, 'username', None)
        group_link = f"https://t.me/{chat_username}" if chat_username else ""

        # 2. 解析发送者（支持备用号）
        original_id = event.sender_id
        sender_id = get_main_account_id(original_id, getattr(event.sender, 'username', None))

        # 3. 检查用户是否注册
        member = DB.get_member(sender_id)
        if not member:
            await event.respond(f"❌ 未找到您的账号信息 (ID: {sender_id})\n请先私聊机器人发送 /start 注册")
            return

        if not member['is_vip']:
            await event.respond("❌ 仅限VIP用户绑定群组")
            return

        # 4. 检查发送者是否为群管理员
        try:
            perms = await event.client.get_permissions(event.chat_id, event.sender_id)
            if not perms.is_admin and not perms.is_creator:
                await event.respond("❌ 您必须是该群组的管理员才能绑定")
                return
        except Exception as e:
            print(f"[群内绑定] 权限检查失败: {e}")
            # 尝试继续，如果无法获取权限信息

        # 5. 更新数据库
        # 更新 members 表
        is_bot_admin = 1 # 既然机器人在群里能收到命令，且能响应，大概率状态正常，后续由后台任务校验

        # 如果没有公开链接，尝试保留旧链接或提示用户
        final_link = group_link
        if not final_link and member.get('group_link'):
            final_link = member['group_link'] # 保留原有链接

        if not final_link:
            # 如果完全没有链接，生成一个伪链接或提示
            final_link = "Private Group (ID: " + str(chat_id) + ")"

        # 更新
        conn = get_db_conn()
        c = conn.cursor()
        c.execute('''
            UPDATE members
            SET group_link = ?, is_group_bound = 1, is_bot_admin = ?
            WHERE telegram_id = ?
        ''', (final_link, is_bot_admin, sender_id))
        conn.commit()
        conn.close()

        # 更新 member_groups 表 (upsert)
        from database import upsert_member_group
        upsert_member_group(sender_id, final_link, member['username'], is_bot_admin, group_id=chat_id)

        await event.respond(
            f"✅ **群组绑定成功！**\n\n"
            f"群组名称: {chat_title}\n"
            f"群组ID: `{chat_id}`\n"
            f"绑定账号: `{sender_id}`\n\n"
            f"💡 机器人已记录群组ID，后续将自动检测状态。"
        )

    except Exception as e:
        print(f"[群内绑定错误] {e}")
        import traceback
        traceback.print_exc()
        await event.respond("❌ 绑定失败，请稍后重试")

@multi_bot_on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    """启动命令"""
    original_id = event.sender_id
    original_username = getattr(event.sender, 'username', None)
    telegram_id = get_main_account_id(original_id, original_username)
    
    username = event.sender.username or f'user_{original_id}'
    
    if original_id != telegram_id:
        print(f"⚠️ [Start命令] 检测到备用号登录: {original_id} -> 切换至主账号 {telegram_id}")
    
    # 解析推荐人ID
    referrer_id = None
    if event.message.text and len(event.message.text.split()) > 1:
        try:
            referrer_id = int(event.message.text.split()[1])
        except:
            pass
    
    member = DB.get_member(telegram_id)
    
    if not member:
        created = DB.create_member(telegram_id, username, referrer_id)
        member = DB.get_member(telegram_id)
        if not created and not member:
            await event.respond('❌ 账号信息创建失败，请稍后再试')
            return
        
        # 通知推荐人
        if referrer_id:
            referrer = DB.get_member(referrer_id)
            if referrer:
                try:
                    user_full_name = event.sender.first_name or f'user_{telegram_id}'
                    await bot.send_message(
                        referrer_id,
                        f'🎉 新成员加入!\n用户: [{user_full_name}](tg://user?id={telegram_id})\n通过您的推广链接加入了机器人',
                        parse_mode='markdown'
                    )
                except:
                    pass
    
    sys_config = get_system_config()
    pinned_ad = sys_config.get('pinned_ad', '')
    
    welcome_text = (
        f'👋 欢迎使用裂变推广机器人!\n\n'
        f'👤 当前显示身份ID: `{telegram_id}`\n'
        f'💎 VIP状态: {"✅ 已开通" if member["is_vip"] else "❌ 未开通"}\n'
        f'💰 余额: {member["balance"]} U\n\n'
        f'请选择功能:'
    )
    
    if pinned_ad:
        welcome_text += f'\n\n━━━━━━━━━━━━━━━\n📢 {pinned_ad}'
    
    await event.respond(welcome_text, buttons=get_main_keyboard(telegram_id))

@multi_bot_on(events.CallbackQuery(data=b'open_vip_balance'))
async def open_vip_balance_callback(event):
    """【已修复】使用余额开通VIP - 统一调用 distribute_vip_rewards"""
    original_sender_id, resolved_id = get_resolved_sender_info(event)

    telegram_id = resolved_id
    member = DB.get_member(telegram_id)
    
    if not member:
        await event.answer("❌ 用户信息不存在", alert=True)
        return
    
    if member.get('is_vip'):
        await event.answer("✅ 您已经是VIP会员", alert=True)
        return
    
    config = get_system_config()
    vip_price = compute_vip_price_from_config(config)
    user_balance = member.get('balance', 0)
    
    if user_balance < vip_price:
        await event.answer(f"❌ 余额不足\n当前余额: {user_balance} U\nVIP价格: {vip_price} U", alert=True)
        return
    
    # 【核心修复】调用统一处理函数
    success, result = await process_vip_upgrade(telegram_id, vip_price, config)
    
    if not success:
        await event.answer(f"❌ {result}", alert=True)
        return
    
    stats = result['stats']
    new_balance = result['new_balance']
    
    text = f"""🎉 恭喜! VIP开通成功!

✅ 您已成为VIP会员
💰 消费金额: {vip_price} U
💵 剩余余额: {new_balance} U

🎁 上级获得 {stats["real"]} 次奖励
💎 推荐账号获得 {stats["fallback"]} 次奖励"""
    
    # 以消息形式发送开通成功通知（避免弹窗 alert），并尝试删除之前的交互消息
    try:
        await event.respond(text)
    except:
        await event.answer(text, alert=True)
    try:
        await event.delete()
    except:
        pass

@multi_bot_on(events.CallbackQuery(pattern=b'confirm_vip'))
async def confirm_vip_callback(event):
    """【已修复】确认开通VIP - 统一调用 distribute_vip_rewards"""
    config = get_system_config()
    original_sender_id, resolved_id = get_resolved_sender_info(event)

    member = DB.get_member(resolved_id)
    if not member:
        await event.answer('请先发送 /start 注册')
        return
    
    if member['is_vip']:
        await event.answer('您已经是VIP了!')
        return
    
    vip_price = compute_vip_price_from_config(config)
    if member['balance'] < vip_price:
        await event.answer(f'余额不足! 还需 {vip_price - member["balance"]} U', alert=True)
        return
    
    # 【核心修复】调用统一处理函数
    success, result = await process_vip_upgrade(event.sender_id, vip_price, config)
    
    if not success:
        await event.answer(f"❌ {result}", alert=True)
        return
    
    stats = result['stats']
    
    await event.respond(
        f'🎉 恭喜! VIP开通成功!\n\n'
        f'您现在可以:\n'
        f'✅ 查看裂变数据\n'
        f'✅ 获得下级开通VIP的奖励\n'
        f'✅ 加入上级群组\n'
        f'✅ 推广赚钱',
        buttons=[[Button.inline('🔙 返回主菜单', b'back_to_profile')]]
    )
    await event.answer()

# ==================== 充值处理 ====================

async def send_recharge_notification(telegram_id, amount):
    """发送充值成功通知"""
    try:
        message = f"""✅ 充值成功

💰 充值金额: {amount} USDT
📝 订单状态: 已完成
⏰ 到账时间: {get_cn_time()}

您的余额已自动增加，可以在个人中心查看。"""
        
        await bot.send_message(telegram_id, message)
        print(f'[充值通知] 已发送通知给用户 {telegram_id}')
    except Exception as e:
        print(f'[充值通知] 发送失败: {e}')

async def process_recharge(telegram_id, amount, is_vip_order=False):
    """处理充值后续逻辑"""
    try:
        config = get_system_config()
        member = DB.get_member(telegram_id)
        if not member:
            return False
            
        # Web端已经增加了余额，这里直接获取最新余额
        current_balance = member.get('balance', 0)
        vip_price = compute_vip_price_from_config(config)

        if is_vip_order and not member.get('is_vip', False) and current_balance >= vip_price:
            print(f'[充值处理] 开始VIP自动开通: telegram_id={telegram_id}')
            new_balance = current_balance - vip_price
            DB.update_member(telegram_id, balance=new_balance, is_vip=1, vip_time=get_cn_time())
            update_level_path(telegram_id)
            if bot:
                await distribute_vip_rewards(bot, telegram_id, vip_price, config)

            from core_functions import generate_vip_success_message
            msg = generate_vip_success_message(telegram_id, amount, vip_price, new_balance)
            if bot:
                try: await bot.send_message(telegram_id, msg, parse_mode='markdown')
                except: pass
        else:
            if not is_vip_order and bot:
                try:
                    await bot.send_message(telegram_id, f'✅ 充值到账通知\n\n💰 金额: {amount} U\n💵 当前余额: {current_balance} U')
                except: pass
    except Exception as e:
        print(f"[充值处理异常] {e}")
        return False

# ==================== 管理员手动开通VIP ====================

async def admin_manual_vip_handler(telegram_id, config):
    """
    【已修复】管理员手动开通VIP
    统一调用 distribute_vip_rewards，删除所有手写分红逻辑
    """
    member = DB.get_member(telegram_id)
    if not member:
        return False, "用户不存在"
    
    if member.get('is_vip'):
        return False, "用户已是VIP"
    
    # 【核心修复】调用统一处理函数（不扣除余额，因为是管理员赠送）
    vip_price = compute_vip_price_from_config(config)
    success, result = await process_vip_upgrade(telegram_id, vip_price, config, deduct_balance=False)
    
    if not success:
        return False, result
    
    stats = result['stats']
    
    # 通知用户
    try:
        await bot.send_message(
            telegram_id,
            f'🎉 恭喜! 管理员已为您开通VIP!\n\n'
            f'您现在可以:\n'
            f'✅ 查看裂变数据\n'
            f'✅ 获得下级开通VIP的奖励\n'
            f'✅ 加入上级群组\n'
            f'✅ 推广赚钱\n\n'
            f'感谢您的支持!'
        )
    except Exception as e:
        print(f"通知用户失败: {e}")
    
    return True, {
        'stats': stats,
        'username': member.get('username', '')
    }

# ==================== 群裂变加入（修复版）====================

@multi_bot_on(events.NewMessage(pattern=BTN_FISSION))
async def fission_handler(event):
    """群裂变加入（修复版 - 使用 get_upline_chain）"""
    telegram_id = get_main_account_id(event.sender_id, getattr(event.sender, 'username', None))
    member = DB.get_member(telegram_id)
    
    if not member:
        await event.respond("❌ 请先使用 /start 开始")
        return
    
    config = get_system_config()
    
    # 检查VIP
    if not member.get('is_vip'):
        vip_price = config.get('vip_price', 10)
        user_balance = member.get('balance', 0)
        need_recharge = vip_price - user_balance
        
        text = f"""❌ 您还未开通VIP

开通VIP后可获得以下权益:
✅ 查看裂变数据
✅ 获得下级开通VIP的奖励
✅ 加入上级群组

💰 VIP价格: {vip_price} U
💵 您的余额: {user_balance} U"""
        
        if user_balance >= vip_price:
            buttons = [[Button.inline('💎 余额开通VIP', b'open_vip_balance')]]
        else:
            text += f"\n\n❌ 余额不足，请先充值"
            buttons = [[Button.inline(f'💰 充值{need_recharge}U开通VIP', b'recharge_for_vip')]]
        
        await event.respond(text, buttons=buttons)
        return
    
    # 已开通VIP，统一显示所有需要加入的群组（1-10层）
    text = "🔗 **群裂变加入列表**\n━━━━━━━━━━━━━━━━\n\n"
    
    # 获取系统配置
    level_count = min(config.get('level_count', 10), 10)
    
    # 使用 get_upline_chain 获取完整的10层关系
    chain = get_upline_chain(telegram_id, level_count)
    
    # 获取所有捡漏群组
    fb_groups = get_fallback_resource('group')
    # Debug: 打印捡漏群组原始返回，便于诊断为何为空或不包含链接
    print(f"[fission debug] get_fallback_resource('group') returned: {fb_groups}")
    try:
        conn_dbg = get_db_conn()
        c_dbg = conn_dbg.cursor()
        c_dbg.execute("SELECT id, telegram_id, username, group_link, is_active FROM fallback_accounts ORDER BY id ASC")
        fb_rows = c_dbg.fetchall()
        print(f"[fission debug] fallback_accounts count: {len(fb_rows)}")
        for r in fb_rows:
            print(f"[fission debug] fallback_accounts row: id={r[0]}, telegram_id={r[1]}, username={r[2]}, is_active={r[4]}, group_link={r[3]}")
        conn_dbg.close()
    except Exception as dbg_e:
        print(f"[fission debug] error reading fallback_accounts: {dbg_e}")

    if not fb_groups:
        await event.respond("❌ 系统错误：捡漏群组未配置，请联系管理员")
        return
    
    # 构建层级映射：level -> 上级信息（如果存在且完成任务）
    upline_map = {}
    for item in chain:
        if item.get('is_fallback'):
            continue
        level = item['level']
        upline_id = item['id']
        up_member = DB.get_member(upline_id)
        if up_member and up_member.get('group_link'):
            # 检查上级是否完成任务
            try:
                conds = await check_user_conditions(bot, upline_id)
                if conds and conds['all_conditions_met']:
                    group_links = up_member['group_link'].split('\n')
                    for link in group_links:
                        if link.strip():
                            upline_map[level] = {
                                'link': link.strip(),
                                'upline_id': upline_id
                            }
                            break
            except Exception as e:
                print(f"[群裂变列表] 检查第{level}层上级条件失败: {e}")
    
    # 构建最终显示的群组列表（按显示顺序填充：第1..第N）
    # 规则调整：如果上级存在并完成任务，应该替换显示列表的从后向前位置：
    #   上1级 (level=1) -> 替换显示第 N 项（最后一项）
    #   上2级 (level=2) -> 替换显示第 N-1 项，依此类推
    groups_to_show = [None] * level_count  # 0-based positions

    # 先把上级群放到对应显示位置（增加实时群权检测）
    for item in chain:
        if item.get('is_fallback'):
            continue

        level = item['level']
        upline_id = item['id']
        up_member = DB.get_member(upline_id)

        # 只有当上级设置了群链接，才进行深入检测
        if up_member and up_member.get('group_link'):
            try:
                # 1. 基础条件检查 (DB层面)
                conds = await check_user_conditions(bot, upline_id)

                # 2. 实时权限检查 (API层面 - 核心修改)
                # 只有当 DB 显示条件满足时，才去 verify 真实权限，节省资源
                is_valid = False
                if conds and conds['all_conditions_met']:
                    group_link = up_member['group_link'].split('\n')[0].strip()
                    # 【核心】调用懒加载检测
                    is_valid = await verify_and_handle_upline_group(bot, upline_id, group_link, clients)

                if is_valid:
                    pos = level_count - level  # 0-based index
                    if pos < 0 or pos >= level_count:
                        continue

                    group_name = f"第{level}层上级"
                    # 尝试获取群名 (代码保持不变...)
                    try:
                        if 't.me/' in group_link:
                            group_username = group_link.split('t.me/')[-1].split('/')[0].split('?')[0]
                        elif group_link.startswith('@'):
                            group_username = group_link[1:]
                        else:
                            group_username = group_link

                        if not group_username.startswith('+'):
                            try:
                                group_entity = await bot.get_entity(group_username)
                                title = getattr(group_entity, 'title', None)
                                if title:
                                    group_name = title
                            except Exception:
                                # 获取实体或标题失败，使用默认 group_name
                                pass
                    except Exception:
                        # group_link 解析异常，继续使用默认 group_name
                        pass

                    # 填充显示数组
                    groups_to_show[pos] = {
                        'level': level,
                        'link': group_link,
                        'name': group_name,
                        'type': 'upline'
                    }
                else:
                    # 检测不通过，该位置留空，后续会自动填充捡漏
                    pass

            except Exception as e:
                print(f"[群裂变列表] 检查第{level}层上级条件失败: {e}")

    # 用捡漏群补全剩余位置（按从前到后映射级别）
    for display_idx in range(level_count):
        if groups_to_show[display_idx] is None:
            # 要计算该显示位对应的层级（反向）： display_idx = level_count - level
            level_for_slot = level_count - display_idx
            fb_index = (level_for_slot - 1) % len(fb_groups)
            fb_group = fb_groups[fb_index]
            group_link = (fb_group.get('link') or '').strip()
            group_name = fb_group.get('name') or fb_group.get('username') or f'推荐群组 {level_for_slot}'
            try:
                if group_link:
                    actual_title = await get_group_title(bot, group_link)
                    if actual_title:
                        group_name = actual_title
            except:
                pass
            # Always fill the slot; if link missing, leave empty string and display as plain text
            groups_to_show[display_idx] = {
                'level': level_for_slot,
                'link': group_link,
                'name': group_name,
                'type': 'fallback'
            }
    
    # 统一显示在"推荐加入的群组"中
    if groups_to_show:
        text += "🔥 **推荐加入的群组：**\n"
        for idx, group_info in enumerate(groups_to_show, 1):
            # 显示编号为从后向前（例如 level_count=10 则首项显示为 10）
            display_num = level_count - (idx - 1)
            if not group_info:
                text += f"{display_num}. 未配置\n"
                continue
            name = group_info.get('name') or f'推荐群组 {display_num}'
            link = group_info.get('link') or ''
            if link:
                text += f"{display_num}. [{name}]({link})\n"
            else:
                text += f"{display_num}. {name}\n"
    else:
        await event.respond("❌ 暂无可用群组，请联系管理员配置捡漏账号群链接。")
        return
        
    buttons = [[Button.inline('🔍 验证已加群', f'verify_groups_{telegram_id}'.encode())]]
    await event.respond(text, buttons=buttons, parse_mode='markdown')

# ==================== 注册其他命令处理器 ====================

@multi_bot_on(events.NewMessage(pattern=BTN_PROFILE))
async def profile_handler(event):
    """个人中心 (修复版)"""
    original_id = event.sender_id
    print(f"[个人中心] 原始请求者ID: {original_id}")

    # 【核心修复】解析正确的账号ID（支持备用号映射）
    resolved_id = resolve_sender_id(event)
    print(f"[个人中心] 解析结果: {original_id} -> {resolved_id}")

    # 直接使用resolved_id查询
    print(f"[个人中心] 查询数据库: telegram_id = {resolved_id}")
    member = DB.get_member(resolved_id)
    print(f"[个人中心] 数据库查询结果: {member is not None}")

    if not member:
        # 只有当确实查不到记录时，才提示注册
        print(f"[个人中心] 未找到会员信息: {resolved_id}")
        await event.respond('❌ 未找到账号信息，请先发送 /start 注册')
        return
    
    print(f"[个人中心] 找到会员: {member.get('username')}")

    # 记住解析后的ID，用于后续逻辑
    main_id = resolved_id

    # 4. 构建界面 (保持原样)
    buttons = [
        [Button.inline('🔗 设置群链接', b'set_group'), Button.inline('✏️ 设置备用号', b'set_backup')],
        [Button.inline('💳 提现', b'withdraw'), Button.inline('💰 充值', b'do_recharge'), Button.inline('💎 开通VIP', b'open_vip')],
        [Button.inline('📊 收益记录', b'earnings_history')],
    ]
    
    backup_display = format_backup_account_display(member.get("backup_account"))
    
    # 获取推荐人信息
    referrer_info = ""
    if member.get("referrer_id"):
        referrer = DB.get_member(member["referrer_id"])
        if referrer:
            r_name = referrer.get("username", "")
            referrer_info = f'👥 推荐人: @{r_name}' if r_name else f'👥 推荐人ID: {member["referrer_id"]}'

    # 显示信息
    text = f'👤 个人中心\n\n'
    text += f'🆔 账号ID: `{member["telegram_id"]}`\n'  # 显示主ID
    if original_id != main_id:
        text += f'📱 当前登录: 备用号 ({original_id})\n'
    text += f'👤 用户名: @{member["username"]}\n'
    if referrer_info: text += f'{referrer_info}\n'
    text += f'💎 VIP状态: {"✅ 已开通" if member["is_vip"] else "❌ 未开通"}\n'
    text += f'💰 余额: {member["balance"]} U\n'
    text += f'📉 错过余额: {member["missed_balance"]} U\n'
    text += f'🔗 群链接: {member["group_link"] or "未设置"}\n'
    text += f'📱 绑定备用号: {backup_display}\n'
    
    await event.respond(text, buttons=buttons)

# ==================== 个人中心按钮回调处理 ====================

@multi_bot_on(events.CallbackQuery(pattern=b'set_group'))
async def set_group_callback(event):
    """设置群链接回调"""
    # 账号关联处理（备用号->主账号）
    original_sender_id = event.sender_id
    main_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))

    member = DB.get_member(main_id)
    if not member:
        await event.answer('请先发送 /start 注册')
        return

    # 记住解析后的ID用于后续逻辑
    resolved_id = main_id

    # VIP check
    if not member.get('is_vip'):
        await send_vip_required_prompt(event)
        return
    
    # 切换到群链接输入时，清理备用号等待状态
    waiting_for_backup.pop(resolved_id, None)
    waiting_for_group_link[resolved_id] = True
    await event.respond(
        '🔗 **设置群链接**\n\n'
        '**方法 A (推荐)：**\n'
        '1. 将机器人拉入您的群组\n'
        '2. 将机器人设为管理员\n'
        '3. 在**群组内**发送命令 `/bind`\n'
        '✅ 这种方式最准确，能自动识别私有群ID\n\n'
        '**方法 B (发送链接)：**\n'
        '请直接发送群链接给我 (格式: https://t.me/+xxx 或 @username)\n'
        '⚠️ 注意：如果是私有链接，请**先将机器人拉进群**再发送，否则无法识别！\n\n'
        '发送 /cancel 取消操作'
    )
    await event.answer()

@multi_bot_on(events.CallbackQuery(pattern=b'set_backup'))
async def set_backup_callback(event):
    """设置备用号回调"""
    # 账号关联处理（备用号->主账号）
    original_sender_id, resolved_id = get_resolved_sender_info(event)

    member = DB.get_member(resolved_id)
    if not member:
        await event.answer('请先发送 /start 注册')
        return

    # VIP check
    if not member.get('is_vip'):
        await send_vip_required_prompt(event)
        return
    
    # 切换到备用号输入时，清理群链接等待状态
    waiting_for_group_link.pop(resolved_id, None)
    waiting_for_backup[resolved_id] = True
    await event.respond(
        '✏️ 设置备用号\n\n'
        '请发送您的备用飞机号 (不带@的用户名或ID)\n\n'
        '发送 /cancel 取消操作'
    )
    await event.answer()

@multi_bot_on(events.CallbackQuery(pattern=b'earnings_history'))
async def earnings_history_callback(event):
    """查看个人收益记录"""
    # 账号关联处理（备用号->主账号）
    original_sender_id, resolved_id = get_resolved_sender_info(event)

    member = DB.get_member(resolved_id)
    
    if not member:
        await event.answer("❌ 用户信息不存在", alert=True)
        return

    # VIP check
    if not member.get('is_vip'):
        await send_vip_required_prompt(event)
        return
    
    conn = DB.get_conn()
    c = conn.cursor()
    # 新表结构：记录 upgraded_user (谁触发升级), earning_user (谁获得收益), amount, description, create_time
    c.execute('''
        SELECT upgraded_user, amount, description, create_time
        FROM earnings_records
        WHERE earning_user = ?
        ORDER BY create_time DESC
        LIMIT 50
    ''', (member["telegram_id"],))
    records = c.fetchall()
    conn.close()
    
    if not records:
        text = "📊 收益记录\n\n暂无收益记录"
        buttons = [[Button.inline('🔙 返回', b'back_to_profile')]]
    else:
        total = sum(r[1] for r in records)
        text = f"📊 收益记录\n\n"
        text += f"💰 累计收益: {total} U\n"
        text += f"📝 记录数: {len(records)} 条\n\n"
        text += "最近收益记录:\n"
        text += "━━━━━━━━━━━━━━\n"
        
        for i, (upgraded_user, amount, desc, create_time) in enumerate(records[:20], 1):
            # 尝试获取升级者用户名
            try:
                upm = DB.get_member(upgraded_user) if upgraded_user else None
                up_name = f"@{upm['username']}" if upm and upm.get('username') else str(upgraded_user)
            except:
                up_name = str(upgraded_user)
            time_str = create_time[:16] if create_time else "未知"
            text += f"{i}. +{amount} U — 升级用户: {up_name}\n"
            text += f"   {desc or ''}\n"
            text += f"   {time_str}\n\n"
        
        if len(records) > 20:
            text += f"... 还有 {len(records) - 20} 条记录\n"
        
        buttons = [[Button.inline('🔙 返回', b'back_to_profile')]]
    
    try:
        await event.edit(text, buttons=buttons)
    except:
        await event.respond(text, buttons=buttons)
    await event.answer()

@multi_bot_on(events.CallbackQuery(pattern=b'withdraw'))
async def withdraw_callback(event):
    """提现回调"""
    config = get_system_config()
    member = DB.get_member(event.sender_id)
    if not member:
        await event.answer('请先发送 /start 注册')
        return

    if member['balance'] < config['withdraw_threshold']:
        await event.respond(
            '💳 提现\n\n'
            f'❌ 余额未达到提现门槛\n\n'
            f'当前余额: {member["balance"]} U\n'
            f'提现门槛: {config["withdraw_threshold"]} U\n'
            f'还需: {config["withdraw_threshold"] - member["balance"]} U'
        )
    else:
        waiting_for_withdraw_amount[event.sender_id] = True
        await event.respond(
            f'💳 提现申请\n\n'
            f'当前余额: {member["balance"]} U\n'
            f'提现门槛: {config["withdraw_threshold"]} U\n\n'
            f'请输入提现金额：'
        )
    await event.answer()

@multi_bot_on(events.CallbackQuery(pattern=b'do_recharge'))
async def do_recharge_callback(event):
    """充值回调"""
    # 账号关联处理（备用号->主账号）
    try:
        original_sender_id = event.sender_id
        event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
    except:
        pass
    telegram_id = event.sender_id
    member = DB.get_member(telegram_id)
    
    if not member:
        await event.answer("❌ 用户信息不存在", alert=True)
        return
    
    waiting_for_recharge_amount[telegram_id] = True
    
    text = """💰 充值余额

请输入您要充值的金额（USDT）

例如: 200

⚠️ 注意:
• 仅支持TRC-20网络USDT
• 最低充值金额: 10 USDT
• 充值后自动到账"""
    
    try:
        await event.edit(text)
    except:
        await event.respond(text)
    await event.answer()

@multi_bot_on(events.CallbackQuery(pattern=b'open_vip'))
async def open_vip_callback(event):
    """开通VIP"""
    # 账号关联处理（备用号->主账号）
    try:
        original_sender_id = event.sender_id
        event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
    except:
        pass
    telegram_id = event.sender_id
    member = DB.get_member(telegram_id)
    
    if not member:
        await event.answer("❌ 用户信息不存在", alert=True)
        return
    
    if member.get('is_vip'):
        await event.answer("✅ 您已经是VIP会员", alert=True)
        return
    
    config = get_system_config()
    vip_price = config.get('vip_price', 10)
    user_balance = member.get('balance', 0)
    need_recharge = vip_price - user_balance
    
    text = f"""💎 开通VIP会员

VIP价格: {vip_price} U
当前余额: {user_balance} U
还需充值: {need_recharge} U

开通VIP后您将获得:
✅ 查看裂变数据
✅ 获得下级开通VIP的奖励
✅ 加入上级群组
✅ 推广赚钱功能"""
    
    if user_balance >= vip_price:
        # 余额足够，直接尝试开通（跳过额外确认）
        try:
            success, result = await process_vip_upgrade(telegram_id, vip_price, config)
            if success:
                # 显示成功提示
                stats = result.get('stats', {})
                new_balance = result.get('new_balance', 0)
                text = f'🎉 恭喜! VIP开通成功!\n\n您现在可以使用所有VIP功能。\n\n消费: {vip_price} U\n剩余余额: {new_balance} U'
                try:
                    await event.edit(text)
                except:
                    await event.respond(text)
                await event.answer()
                return
            else:
                # 如果处理失败，回退到展示充值/确认界面
                text += f"\n\n❌ 开通失败: {result}\n"
                buttons = [[Button.inline(f'💰 充值{need_recharge}U开通VIP', b'recharge_for_vip')]]
        except Exception as e:
            print(f"[open_vip] 直接开通失败: {e}")
            text += f"\n\n❌ 开通失败，请稍后重试"
            buttons = [[Button.inline(f'💰 充值{need_recharge}U开通VIP', b'recharge_for_vip')]]
    else:
        # 余额不足，显示充值按钮
        text += f"\n\n❌ 余额不足，请先充值"
        buttons = [[Button.inline(f'💰 充值{need_recharge}U开通VIP', b'recharge_for_vip')]]
    
    try:
        await event.edit(text, buttons=buttons)
    except:
        await event.respond(text, buttons=buttons)
    await event.answer()

# 返回个人中心
@multi_bot_on(events.CallbackQuery(pattern=b'back_to_profile'))
async def back_to_profile_callback(event):
    """返回个人中心"""
    # 账号关联处理（备用号->主账号）
    try:
        original_sender_id = event.sender_id
        event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
    except:
        pass
    member = DB.get_member(event.sender_id)
    if not member:
        await event.answer("❌ 用户信息不存在", alert=True)
        return
    
    buttons = [
        [Button.inline('🔗 设置群链接', b'set_group'), Button.inline('✏️ 设置备用号', b'set_backup')],
        [Button.inline('📊 收益记录', b'earnings_history')],
        [Button.inline('💳 提现', b'withdraw'), Button.inline('💰 充值', b'do_recharge'), Button.inline('💎 开通VIP', b'open_vip')],
    ]
    
    # 格式化备用号显示（显示用户名而不是ID）
    backup_display = format_backup_account_display(member.get("backup_account"))
    
    text = (
        f'👤 个人中心\n\n'
        f'🆔 ID: {member["telegram_id"]}\n'
        f'👤 用户名: @{member["username"]}\n'
        f'💎 VIP状态: {"✅ 已开通" if member["is_vip"] else "❌ 未开通"}\n'
        f'💰 余额: {member["balance"]} U\n'
        f'📉 错过余额: {member["missed_balance"]} U\n'
        f'💵 累计收益: {member.get("total_earned", 0)} U\n'
        f'🔗 群链接: {member["group_link"] or "未设置"}\n'
        f'📱 备用号: {backup_display}\n'
        f'📅 注册时间: {member["register_time"][:10] if member["register_time"] else "未知"}'
    )
    
    try:
        await event.edit(text, buttons=buttons)
    except:
        await event.respond(text, buttons=buttons)
    await event.answer()

@multi_bot_on(events.CallbackQuery(data=b'recharge_for_vip'))
async def recharge_for_vip_callback(event):
    """充值开通VIP - 调用充值输入金额功能"""
    # 账号关联处理（备用号->主账号）
    try:
        original_sender_id = event.sender_id
        event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
    except:
        pass
    telegram_id = event.sender_id
    member = DB.get_member(telegram_id)
    
    if not member:
        await event.answer("❌ 用户信息不存在", alert=True)
        return
    
    # 获取VIP价格，计算需要充值的金额
    config = get_system_config()
    vip_price = config.get('vip_price', 10)
    user_balance = member.get('balance', 0)
    need_recharge = vip_price - user_balance
    
    if need_recharge <= 0:
        await event.answer("✅ 余额充足，可以直接开通VIP", alert=True)
        return
    
    # 调用充值订单创建函数（传入bot参数）
    try:
        from payment import create_recharge_order
        await create_recharge_order(bot, event, need_recharge, is_vip_order=True)
    except Exception as e:
        print(f"[充值VIP订单创建失败] {e}")
        import traceback
        traceback.print_exc()
        await event.respond("❌ 创建充值订单失败，请稍后重试")
    await event.answer()

@multi_bot_on(events.CallbackQuery(pattern=rb'verify_groups_.*'))
async def verify_groups_callback(event):
    """验证用户是否加入所有需要加入的群组（上级群 + 捡漏群组，共10个）"""
    # 账号关联处理（备用号->主账号）
    try:
        original_sender_id = event.sender_id
        event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
    except:
        pass
    
    telegram_id = event.sender_id
    member = DB.get_member(telegram_id)
    
    if not member:
        await event.answer("❌ 用户信息不存在", alert=True)
        return
    
    # 【核心修复】如果该用户已经完成过"加群任务"，则永久锁死，不再重新检测
    if member.get('is_joined_upline'):
        await event.answer("✅ 加群任务已完成（永久锁定）", alert=False)
        try:
            await event.edit("✅ **加群任务已完成**\n\n🎉 您已完成加入所有需要加入的群组！\n\n您现在可以获得下级开通VIP的分红了！")
        except:
            pass
        return
    
    await event.answer("🔍 正在检测群组加入情况，请稍候...", alert=False)
    
    # 【核心修复】加群任务 = 必须加入1-10层的群组（每层：有上级且完成任务用上级群，否则用捡漏群）
    config = get_system_config()
    required_groups_count = min(config.get('level_count', 10), 10)
    
    groups_to_check = []
    
    # 获取完整的10层关系
    from core_functions import get_upline_chain
    chain = get_upline_chain(telegram_id, required_groups_count)
    
    # 获取所有捡漏群组
    fb_groups = get_fallback_resource('group')
    if not fb_groups:
        await event.respond("❌ 系统错误：捡漏群组未配置，请联系管理员")
        return
    
    # 构建层级映射：level -> 上级信息（如果存在且完成任务）
    upline_map = {}
    for item in chain:
        if item.get('is_fallback'):
            continue
        level = item['level']
        upline_id = item['id']
        up_member = DB.get_member(upline_id)
        if up_member and up_member.get('group_link'):
            # 检查上级是否完成任务
            try:
                conds = await check_user_conditions(bot, upline_id)
                if conds and conds['all_conditions_met']:
                    group_links = up_member.get('group_link', '').split('\n')
                    for link in group_links:
                        link = link.strip()
                        if link:
                            upline_map[level] = {
                                'link': link,
                                'upline_id': upline_id
                            }
                            break
            except Exception as e:
                print(f"[验证加群] 检查第{level}层上级条件失败: {e}")
    
    # 构建需要检查的群组列表（按显示顺序，采用与 fission_handler 相同的从后向前替换策略）
    groups_to_check = [None] * required_groups_count

    # 先把真实上级放到对应显示位置（上1级 -> 最后一个位置，含实时检测）
    for level, info in upline_map.items():
        try:
            pos = required_groups_count - level
            if pos < 0 or pos >= required_groups_count:
                continue

            # 【核心】实时检测上级群有效性
            upline_id = info.get('upline_id')
            group_link = info['link']
            is_valid = False

            if upline_id:
                # 调用懒加载检测
                is_valid = await verify_and_handle_upline_group(bot, upline_id, group_link, clients)

            if is_valid:
                groups_to_check[pos] = {
                    'display_index': pos + 1,
                    'link': group_link,
                    'level': level,
                    'type': 'upline',
                    'group_name': f"第{level}层上级",
                    'upline_id': upline_id
                }
            # 如果检测不通过，该位置留空，后续用捡漏补全

        except Exception as e:
            print(f"[验证加群] 构建上级映射失败: {e}")

    # 补全空位为捡漏群组
    for display_pos in range(required_groups_count):
        if groups_to_check[display_pos] is None:
            # 对应的层级（反向映射）
            level_for_slot = required_groups_count - display_pos
            fb_index = (level_for_slot - 1) % len(fb_groups)
            fb_group = fb_groups[fb_index]
            group_link = fb_group.get('link', '').strip()
            if group_link:
                groups_to_check[display_pos] = {
                    'display_index': display_pos + 1,
                    'link': group_link,
                    'level': level_for_slot,
                    'type': 'fallback',
                    'username': fb_group.get('username', ''),
                    'group_name': fb_group.get('name', '')
                }
    
    # 过滤空
    groups_to_check = [g for g in groups_to_check if g is not None]
    if not groups_to_check:
        await event.respond("❌ 没有可验证的群组")
        return
    
    # 去重群组（按 link 保持顺序），检测用户是否在群组中
    seen_links = set()
    dedup_groups = []
    for g in groups_to_check:
        link = g.get('link') or ''
        if link and link not in seen_links:
            dedup_groups.append(g)
            seen_links.add(link)

    not_joined = []
    joined = []
    
    for group_info in dedup_groups:
        group_link = group_info['link']
        print(f"[verify_groups] 检查群: display_index={group_info.get('display_index')} level={group_info.get('level')} link={group_link}")
        try:
            # 提取群组用户名或ID
            if 't.me/' in group_link:
                group_username = group_link.split('t.me/')[-1].split('/')[0].split('?')[0].replace('+', '')
            elif group_link.startswith('@'):
                group_username = group_link[1:]
            else:
                group_username = group_link
                
            # 跳过私有群链接（无法通过用户名检查成员）
            if group_username.startswith('+'):
                not_joined.append(group_info)
                continue
            
            # 尝试获取群组实体
            try:
                group_entity = await bot.get_entity(group_username)
                
                # 记录更友好的群名称，方便后面展示（优先使用实际群组名称）
                try:
                    title = getattr(group_entity, 'title', None)
                    if title:
                        group_info['group_name'] = title
                except Exception:
                    pass
                
                # 检查用户是否在群组中
                try:
                    from telethon.tl.functions.channels import GetParticipantRequest
                    participant = await bot(GetParticipantRequest(
                        channel=group_entity,
                        participant=telegram_id
                    ))
                    joined.append(group_info)
                    print(f"[verify_groups] 已检测到用户加入: {group_username}")
                except Exception as part_err:
                    not_joined.append(group_info)
                    print(f"[verify_groups] 用户未加入: {group_username} ({part_err})")
            except Exception as e:
                # 无法获取群组信息，可能是私有群或链接无效
                not_joined.append(group_info)
                print(f"[verify_groups] 获取群信息失败: {group_link} ({e})")
        except Exception as e:
            not_joined.append(group_info)
            print(f"[verify_groups] 内部异常: {e}")
    
    # 构建结果消息
    total_groups = len(dedup_groups)
    joined_count = len(joined)
    not_joined_count = max(total_groups - joined_count, 0)
    print(f"[verify_groups] 统计: total_groups={total_groups}, joined_count={joined_count}, not_joined_count={not_joined_count}")
    
    # 【核心修复】更新数据库中的 is_joined_upline 标志（永久锁死）
    # 必须全部10个群组都加入才算完成，一旦完成永久锁死
    is_completed = False
    try:
        # 必须全部加入才算完成
        if total_groups == required_groups_count and joined_count == total_groups and not member.get('is_joined_upline'):
            DB.update_member(telegram_id, is_joined_upline=1)
            is_completed = True
            print(f"[验证加群] 用户 {telegram_id} 已完成加群任务，状态已永久锁定")
        elif member.get('is_joined_upline'):
            # 如果已经完成过，直接标记为完成（永久锁死）
            is_completed = True
    except Exception as e:
        print(f"[verify_groups] 更新 is_joined_upline 失败: {e}")
    
    # 构建结果消息 - 始终显示统计信息
    text = f"🔍 **群组加入验证结果**\n\n"
    text += f"📊 **总计**: {total_groups} 个群组\n"
    text += f"✅ **已加入**: {joined_count} 个\n"
    text += f"❌ **未加入**: {not_joined_count} 个\n\n"
    
    # 如果已完成，显示完成提示
    if is_completed:
        text += "🎉 **恭喜！您已加入所有需要加入的群组！**\n\n"
        text += "✅ 您现在可以获得下级开通VIP的分红了！\n\n"
        if joined:
            text += "**已加入的群组列表：**\n"
            for g in joined:
                group_name = g.get('group_name') or (g['link'].split('t.me/')[-1].split('/')[0] if 't.me/' in g['link'] else g['link'])
                idx = g.get('display_index', g.get('level', '?'))
                text += f"  ✅ {idx}. {group_name}\n"
    else:
        # 未完成时，显示详细检测结果
        if joined:
            text += f"✅ **已加入的群组** ({joined_count}个):\n"
            for g in joined:
                group_name = g.get('group_name') or (g['link'].split('t.me/')[-1].split('/')[0] if 't.me/' in g['link'] else g['link'])
                idx = g.get('display_index', g.get('level', '?'))
                text += f"  ✅ {idx}. {group_name}\n"
            text += "\n"
        
        if not_joined:
            text += f"❌ **未加入的群组** ({not_joined_count}个，请点击加入):\n"
            for g in not_joined:
                group_name = g.get('group_name') or (g['link'].split('t.me/')[-1].split('/')[0] if 't.me/' in g['link'] else g['link'])
                idx = g.get('display_index', g.get('level', '?'))
                link = g['link']
                # 确保链接格式正确，避免Markdown解析错误
                if link and (link.startswith('http://') or link.startswith('https://') or link.startswith('@')):
                    # 对链接中的特殊字符进行转义
                    safe_link = link.replace('(', '\\(').replace(')', '\\)')
                    text += f"  ❌ {idx}. [{group_name}]({safe_link})\n"
                else:
                    # 如果链接格式不正确，只显示名称不加链接
                    text += f"  ❌ {idx}. {group_name}\n"
            text += "\n⚠️ **重要提示**：请加入以上未加入的群组，才能获得分红！"
    
    try:
        await event.edit(text, parse_mode='markdown')
    except Exception as e:
        print(f"[verify_groups] edit失败，尝试respond: {e}")
        try:
            await event.respond(text, parse_mode='markdown')
        except Exception as e2:
            print(f"[verify_groups] respond也失败: {e2}")
            # 如果Markdown也失败，尝试不使用Markdown
            try:
                plain_text = text.replace('[', '').replace(']', '').replace('(', '').replace(')', '').replace('*', '').replace('_', '')
                await event.respond(plain_text)
            except Exception as e3:
                print(f"[verify_groups] 所有发送方式都失败: {e3}")
                await event.answer("验证完成，但显示结果时出现错误", alert=True)

@multi_bot_on(events.NewMessage(pattern='/bind_group'))
async def bind_group_cmd(event):
    """绑定群组命令 (修复：传入 event.client)"""
    # 传递 event.client 作为 bot 参数，确保使用正确的机器人实例检测权限
    await handle_bind_group(event, event.client, DB)

@multi_bot_on(events.NewMessage(pattern='/join_upline'))
async def join_upline_cmd(event):
    """加入上层群命令"""
    await handle_join_upline(event, event.client, DB, get_system_config)

@multi_bot_on(events.NewMessage(pattern='/check_status'))
async def check_status_cmd(event):
    """检查状态命令"""
    await handle_check_status(event, event.client, DB)

@multi_bot_on(events.NewMessage(pattern='/my_team'))
async def my_team_cmd(event):
    """我的团队命令"""
    await handle_my_team(event, event.client, DB)

# ==================== 其他事件处理器 ====================

@multi_bot_on(events.NewMessage(pattern=BTN_VIEW_FISSION))
async def view_fission_handler(event):
    """查看裂变数据"""
    try:
        original_sender_id = event.sender_id
        event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
    except:
        pass
    
    config = get_system_config()
    member = DB.get_member(event.sender_id)
    if not member:
        await event.respond('请先发送 /start 注册')
        return

    if not member['is_vip']:
        # 使用和"群裂变加入"一样的VIP提示
        vip_price = config.get('vip_price', 10)
        user_balance = member.get('balance', 0)
        need_recharge = vip_price - user_balance

        text = f"""❌ 您还未开通VIP

开通VIP后可获得以下权益:
✅ 查看裂变数据
✅ 获得下级开通VIP的奖励
✅ 加入上级群组

💰 VIP价格: {vip_price} U
💵 您的余额: {user_balance} U"""

        if user_balance >= vip_price:
            buttons = [[Button.inline('💎 余额开通VIP', b'open_vip_balance')]]
        else:
            text += f"\n\n❌ 余额不足，请先充值"
            buttons = [[Button.inline(f'💰 充值{need_recharge}U开通VIP', b'recharge_for_vip')]]

        await event.respond(text, buttons=buttons)
        return

    conn = get_db_conn()
    c = conn.cursor()

    text = '📊 我的裂变数据\n'
    text += '━━━━━━━━━━━━━━\n\n'

    total_members = 0
    total_vip = 0
    buttons = []

    # 获取各级下级用户并生成按钮（固定10层，从第10层到第1层）
    level_counts = {}  # 存储每一层的人数

    # 计算每一层的下级人数
    current_level_users = [member['telegram_id']]  # 从自己开始

    for level in range(1, 11):  # 固定计算10层
        if not current_level_users:
            # 如果上一层没有用户，这一层肯定也是0
            level_counts[level] = 0
            continue

        # 查询当前层级的下级用户
        placeholders = ','.join(['?' for _ in current_level_users])
        c.execute(f"""
            SELECT telegram_id FROM members WHERE referrer_id IN ({placeholders})
        """, current_level_users)

        next_level_users = [row[0] for row in c.fetchall()]
        level_count = len(next_level_users)

        level_counts[level] = level_count
        total_members += level_count

        # 计算VIP数量
        if next_level_users:
            placeholders = ','.join(['?' for _ in next_level_users])
            c.execute(f"""
                SELECT COUNT(*) FROM members WHERE telegram_id IN ({placeholders}) AND is_vip = 1
            """, next_level_users)
            level_vip = c.fetchone()[0]
        else:
            level_vip = 0

        total_vip += level_vip

        # 为下一层循环准备数据
        current_level_users = next_level_users

    # 生成按钮（从第10层到第1层倒序显示）
    # 【修改1】生成按钮（从第1层到第10层正序显示）
    for level in range(1, 11):
        level_count = level_counts.get(level, 0)
        btn_text = f'第{level}层: {level_count}人'
        buttons.append([Button.inline(btn_text, f'flv_{level}_1'.encode())])

    conn.close()

    text += f'━━━━━━━━━━━━━━\n'
    text += f'📈 团队总计：{total_members}人\n'
    text += f'💎 VIP会员：{total_vip}人\n'

    buttons.append([Button.inline('🏠 主菜单', b'fission_main_menu')])

    await event.respond(text, buttons=buttons)


@multi_bot_on(events.CallbackQuery(pattern=rb'flv_(\d+)_(\d+)'))
async def flv_level_callback(event):
    """查看指定层的下级成员列表：flv_{level}_{page}"""
    try:
        import re
        m = re.match(rb'flv_(\d+)_(\d+)', event.data)
        if not m:
            await event.answer('参数错误', alert=True)
            return
        level = int(m.group(1))
        page = int(m.group(2))
        if page < 1:
            page = 1

        telegram_id = get_main_account_id(event.sender_id, getattr(event.sender, 'username', None))
        conn = get_db_conn()
        c = conn.cursor()

        # 逐层查找下级：从当前用户开始，循环 level 次
        current_ids = [telegram_id]
        for _ in range(level):
            if not current_ids:
                break
            placeholders = ','.join(['?'] * len(current_ids))
            c.execute(f"SELECT telegram_id FROM members WHERE referrer_id IN ({placeholders})", current_ids)
            rows = c.fetchall()
            current_ids = [r[0] for r in rows]

        members = []
        if current_ids:
            placeholders = ','.join(['?'] * len(current_ids))
            c.execute(f"SELECT telegram_id, username, is_vip FROM members WHERE telegram_id IN ({placeholders}) ORDER BY id DESC", current_ids)
            rows = c.fetchall()
            for r in rows:
                members.append({'telegram_id': r[0], 'username': r[1] or '', 'is_vip': bool(r[2])})

        conn.close()

        per_page = 15
        total = len(members)
        pages = (total + per_page - 1) // per_page if total > 0 else 1
        page = max(1, min(page, pages if pages > 0 else 1))
        start = (page - 1) * per_page
        end = start + per_page
        page_items = members[start:end]

        if not page_items:
            await event.answer(f'第{level}层暂无成员', alert=True)
            return

        text = f'📋 第{level}层成员（第{page}/{pages}页）\n\n'
        for idx, m in enumerate(page_items, start + 1):
            name_display = f'@{m["username"]}' if m['username'] else str(m['telegram_id'])
            vip_tag = ' VIP' if m['is_vip'] else ''
            text += f'{idx}. {name_display} {vip_tag}\n'

        # 构建分页和返回按钮（不在下面显示每个成员的跳转按钮）
        btns = []
        nav = []
        if page > 1:
            nav.append(Button.inline('⬅️ 上页', f'flv_{level}_{page-1}'.encode()))
        if page < pages:
            nav.append(Button.inline('下页 ➡️', f'flv_{level}_{page+1}'.encode()))
        if nav:
            btns.append(nav)
        btns.append([Button.inline('🔙 返回', b'fission_main_menu')])

        try:
            await event.edit(text, buttons=btns)
        except:
            await event.respond(text, buttons=btns)
    except Exception as e:
        print(f"[flv_callback] 错误: {e}")
        await event.answer('加载失败', alert=True)


@multi_bot_on(events.CallbackQuery(pattern=b'fission_main_menu'))
async def fission_main_menu_callback(event):
    """返回主菜单"""
    try:
        # 获取用户信息
        telegram_id = get_main_account_id(event.sender_id, getattr(event.sender, 'username', None))
        member = DB.get_member(telegram_id)

        if not member:
            await event.answer("❌ 用户信息不存在", alert=True)
            return

        # 生成主菜单内容（与start_handler相同）
        sys_config = get_system_config()
        pinned_ad = sys_config.get('pinned_ad', '')

        welcome_text = (
            f'👋 欢迎使用裂变推广机器人!\n\n'
            f'👤 当前显示身份ID: `{telegram_id}`\n'
            f'💎 VIP状态: {"✅ 已开通" if member["is_vip"] else "❌ 未开通"}\n'
            f'💰 余额: {member["balance"]} U\n\n'
            f'请选择功能:'
        )

        if pinned_ad:
            welcome_text += f'\n\n━━━━━━━━━━━━━━━\n📢 {pinned_ad}'

        # 编辑当前消息为新的主菜单内容
        await event.edit(welcome_text, buttons=get_main_keyboard(telegram_id))

    except Exception as e:
        print(f"[fission_main_menu] 错误: {e}")
        await event.answer('返回失败', alert=True)


@multi_bot_on(events.CallbackQuery(pattern=b'back_handler'))
async def back_handler_callback(event):
    """Callback 版本的返回主菜单"""
    await event.delete()
    # 触发 /start 效果或发送主菜单
    await start_handler(event)


@multi_bot_on(events.NewMessage(pattern=BTN_PROMOTE))
async def promote_handler(event):
    """赚钱推广"""
    try:
        original_sender_id = event.sender_id
        event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
    except:
        pass
    
    config = get_system_config()
    member = DB.get_member(event.sender_id)
    if not member:
        await event.respond('请先发送 /start 注册')
        return
    
    # 【修复】移除了强制VIP检查，非VIP也可以推广赚钱
    
    # 未完成上级加群任务
    if not member.get('is_joined_upline', 0):
        await event.respond(
            "抱歉，您还没加入上级群，不能使用此功能\n\n"
            "请先按照要求加入 10 级共 10 个上级群，\n"
            "完成后再回来使用推广功能。",
            buttons=[[Button.inline('🔍 验证未加群', f'verify_groups_{event.sender_id}'.encode())]]
        )
        return
    
    # 未绑定自己群
    if not member.get('group_link'):
        await event.respond(
            "抱歉，您还没有绑定自己的群，不能使用此功能\n\n"
            "请先绑定自己的群，并确保已将机器人拉入群并设置为管理员。",
            buttons=[[Button.inline('🔗 绑定我的群', b'set_group')]]
        )
        return
    
    # 生成推广链接
    bot_info = await event.client.get_me()
    invite_link = f'https://t.me/{bot_info.username}?start={event.sender_id}'
    
    text = f'💰 赚钱推广\n\n'
    text += f'您的专属推广链接:\n{invite_link}\n\n'
    text += f'📊 推广规则:\n'
    text += f'• 每有一人通过您的链接开通VIP\n'
    text += f'• 您将获得 {config["level_reward"]} U 奖励\n'
    text += f'• 最多可获得 {config["level_count"]} 层下级奖励\n\n'
    text += f'💡 分享此链接给好友即可开始赚钱!'
    
    # 【修改3】改为调用Telegram原生分享功能
    share_text = f"🔥 推荐一个非常棒的群裂变工具！\n\n💰 自动管理群组，自动分红，多层级收益！\n\n👇 点击下方链接加入：\n{invite_link}"
    share_url = f"https://t.me/share/url?url={quote(invite_link)}&text={quote(share_text)}"

    await event.respond(text, buttons=[[Button.url('📤 立即推广 (选择好友/群)', share_url)]])

@multi_bot_on(events.NewMessage(pattern=BTN_RESOURCES))
async def resources_handler(event):
    """行业资源"""
    try:
        original_sender_id = event.sender_id
        event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
    except:
        pass
    await show_resource_categories(event, page=1, is_new=True)

async def show_resource_categories(event, page=1, is_new=False):
    """显示资源分类（文本列表，分页，每页25条）"""
    categories = DB.get_resource_categories(0)

    if not categories:
        msg = '📁 行业资源\n\n暂无资源分类'
        if is_new:
            await event.respond(msg)
        else:
            await event.edit(msg)
        return

    # 文本列表分页：每页25个分类（适合显示为列表）
    per_page = 25
    total = len(categories)
    total_pages = (total + per_page - 1) // per_page
    page = max(1, min(page, total_pages))

    start = (page - 1) * per_page
    end = start + per_page
    page_categories = categories[start:end]

    # 构建文本列表（编号 + 名称），下方放按钮（每行3个）用于进入分类资源
    text_lines = [f'📁 行业资源\n\n共 {total} 个分类 （第 {page}/{total_pages} 页）\n']
    buttons = []
    for idx, cat in enumerate(page_categories, start + 1):
        text_lines.append(f'{idx}. {cat["name"]}')

    # 每行3个按钮排列
    current_row = []
    for cat in page_categories:
        current_row.append(Button.inline(cat["name"], f'cat_{cat["id"]}'.encode()))
        if len(current_row) == 3:
            buttons.append(current_row)
            current_row = []
    # 处理剩余的按钮
    if current_row:
        buttons.append(current_row)

    # 分页控制按钮
    nav = []
    if page > 1:
        nav.append(Button.inline('< 上一页', f'catpg_{page-1}'.encode()))
    if page < total_pages:
        nav.append(Button.inline('下一页 >', f'catpg_{page+1}'.encode()))
    if nav:
        buttons.append(nav)

    buttons.append([Button.inline('< 返回', b'res_back_main')])

    text = '\n'.join(text_lines)
    try:
        if is_new:
            await event.respond(text, buttons=buttons, parse_mode='markdown')
        else:
            await event.edit(text, buttons=buttons, parse_mode='markdown')
    except:
        # fallback without buttons
        if is_new:
            await event.respond(text)
        else:
            await event.edit(text)


# 点击分类回调：显示该分类下的资源
@multi_bot_on(events.CallbackQuery(pattern=rb'cat_(\d+)'))
async def category_callback(event):
    try:
        data = event.data.decode()
        cid = int(data.replace('cat_', ''))
        # 使用DB.get_resources进行分页读取
        per_page = 25
        page = 1
        result = DB.get_resources(cid, page=page, per_page=per_page)

        items = result.get('items', [])
        total = result.get('total', 0)
        pages = result.get('pages', 1)

        if not items:
            await event.answer('该分类暂无资源', alert=True)
            return

        def fmt_count(n):
            try:
                n = int(n)
            except:
                return str(n)
            if n >= 1000:
                v = round(n / 1000.0, 1)
                if v.is_integer():
                    return f'{int(v)}K'
                return f'{v}K'
            return str(n)

        # 构建文本列表（每行包含图标、名称、人数和链接）
        text_lines = [f'📂 资源列表（分类ID: {cid}）\n共 {total} 条，显示第 {page}/{pages} 页\n']
        for it in items:
            icon = '👥' if (it.get('type') or '').lower() == 'group' else '📣'
            name = it.get('name') or '未命名'
            link = it.get('link') or ''
            count_str = fmt_count(it.get('count') or 0)
            # 安全转义中括号和圆括号 in markdown link text
            safe_name = name.replace('[','\\[').replace(']','\\]').replace('(','\\(').replace(')','\\)')
            if link:
                text_lines.append(f'{icon} [{safe_name}]({link}) {count_str}')
            else:
                text_lines.append(f'{icon} {safe_name} {count_str}')

        text = '\n'.join(text_lines)

        # 构建分页按钮
        btns = []
        nav = []
        if page > 1:
            nav.append(Button.inline('< 上一页', f'res_page_{cid}_{page-1}'.encode()))
        if page < pages:
            nav.append(Button.inline('下一页 >', f'res_page_{cid}_{page+1}'.encode()))
        if nav:
            btns.append(nav)
        btns.append([Button.inline('🔙 返回分类', b'back_to_categories')])

        try:
            await event.edit(text, buttons=btns, parse_mode='markdown')
        except:
            await event.respond(text, buttons=btns, parse_mode='markdown')
    except Exception as e:
        print(f"[category_callback] 错误: {e}")
        await event.answer('加载失败', alert=True)


@multi_bot_on(events.CallbackQuery(pattern=rb'back_to_categories'))
async def back_to_categories_callback(event):
    """返回分类列表（同 show_resource_categories 第1页）"""
    try:
        await show_resource_categories(event, page=1, is_new=False)
        await event.answer()
    except Exception as e:
        print(f"[back_to_categories] 错误: {e}")
        await event.answer('返回失败', alert=True)


@multi_bot_on(events.CallbackQuery(pattern=rb'res_page_(\d+)_(\d+)'))
async def resource_page_callback(event):
    """分页资源显示：res_page_{category_id}_{page}"""
    try:
        data = event.data.decode()
        parts = data.replace('res_page_', '').split('_')
        cid = int(parts[0])
        page = int(parts[1])
        per_page = 25
        result = DB.get_resources(cid, page=page, per_page=per_page)
        items = result.get('items', [])
        total = result.get('total', 0)
        pages = result.get('pages', 1)

        if not items:
            await event.answer('该页暂无资源', alert=True)
            return

        def fmt_count(n):
            try:
                n = int(n)
            except:
                return str(n)
            if n >= 1000:
                v = round(n / 1000.0, 1)
                if v.is_integer():
                    return f'{int(v)}K'
                return f'{v}K'
            return str(n)

        text_lines = [f'📂 资源列表（分类ID: {cid}）\n共 {total} 条，显示第 {page}/{pages} 页\n']
        for it in items:
            icon = '👥' if (it.get('type') or '').lower() == 'group' else '📣'
            name = it.get('name') or '未命名'
            link = it.get('link') or ''
            count_str = fmt_count(it.get('count') or 0)
            safe_name = name.replace('[','\\[').replace(']','\\]').replace('(','\\(').replace(')','\\)')
            if link:
                text_lines.append(f'{icon} [{safe_name} ({count_str})]({link})')
            else:
                text_lines.append(f'{icon} {safe_name} ({count_str})')

        text = '\n'.join(text_lines)
        btns = []
        nav = []
        if page > 1:
            nav.append(Button.inline('< 上一页', f'res_page_{cid}_{page-1}'.encode()))
        if page < pages:
            nav.append(Button.inline('下一页 >', f'res_page_{cid}_{page+1}'.encode()))
        if nav:
            btns.append(nav)
        btns.append([Button.inline('🔙 返回分类', b'back_to_categories')])

        try:
            await event.edit(text, buttons=btns, parse_mode='markdown')
        except:
            await event.respond(text, buttons=btns, parse_mode='markdown')
    except Exception as e:
        print(f"[resource_page_callback] 错误: {e}")
        await event.answer('加载失败', alert=True)

@multi_bot_on(events.NewMessage(pattern=BTN_SUPPORT))
async def support_handler(event):
    """在线客服"""
    try:
        original_sender_id = event.sender_id
        event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
    except:
        pass
    
    # 获取客服列表
    services = DB.get_customer_services()
    
    if not services:
        # 如果没有客服，显示后台配置的文本
        config = get_system_config()
        await event.respond(config['support_text'])
        return
    
    # 构建客服列表
    text = '👩‍💼 在线客服\n\n请选择客服进行咨询:\n\n'
    buttons = []
    
    for service in services:
        text += f'• {service["name"]}\n'
        # 转换链接格式
        link = service['link']
        if link.startswith('@'):
            link = f'https://t.me/{link[1:]}'
        elif not link.startswith('http'):
            link = f'https://t.me/{link}'
        
        buttons.append([Button.url(f'💬 联系 {service["name"]}', link)])
    
    await event.respond(text, buttons=buttons, parse_mode='md')

@multi_bot_on(events.NewMessage(pattern=BTN_VIP))
async def vip_handler(event):
    """开通会员"""
    try:
        original_sender_id = event.sender_id
        event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
    except:
        pass
    
    member = DB.get_member(event.sender_id)
    if not member:
        await event.respond('请先发送 /start 注册')
        return
    
    if member['is_vip']:
        await event.respond(
            '💎 您已经是VIP会员!\n\n'
            f'开通时间: {member["vip_time"][:10] if member["vip_time"] else "未知"}'
        )
        return
    
    # 获取最新配置
    config = get_system_config()
    
    # 检查余额是否足够
    if member['balance'] >= config['vip_price']:
        await event.respond(
            f'💎 开通VIP会员\n\n'
            f'VIP价格: {config["vip_price"]} U\n'
            f'当前余额: {member["balance"]} U\n\n'
            f'开通VIP后您将获得:\n'
            f'✅ 查看裂变数据\n'
            f'✅ 获得下级开通VIP的奖励\n'
            f'✅ 加入上级群组\n'
            f'✅ 推广赚钱功能\n\n'
            f'✅ 余额充足，可以直接开通',
            buttons=[[Button.inline('💳 确认开通', b'confirm_vip')]]
        )
    else:
        await event.respond(
            f'💎 开通VIP会员\n\n'
            f'VIP价格: {config["vip_price"]} U\n'
            f'当前余额: {member["balance"]} U\n'
            f'还需充值: {config["vip_price"] - member["balance"]} U\n\n'
            f'开通VIP后您将获得:\n'
            f'✅ 查看裂变数据\n'
            f'✅ 获得下级开通VIP的奖励\n'
            f'✅ 加入上级群组\n'
            f'✅ 推广赚钱功能\n\n'
            f'❌ 余额不足，请先充值',
            buttons=[[Button.inline(f'💰 充值 {config["vip_price"]} U 开通VIP', b'recharge_for_vip')]]
        )

@multi_bot_on(events.NewMessage(pattern=BTN_MY_PROMOTE))
async def my_promote_handler(event):
    """我的推广"""
    try:
        original_sender_id = event.sender_id
        event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
    except:
        pass
    
    config = get_system_config()
    member = DB.get_member(event.sender_id)
    if not member:
        await event.respond('请先发送 /start 注册')
        return
    
    # 【修复】移除了强制VIP检查，非VIP也可以查看自己的推广数据
    
    # 获取下级统计
    counts = DB.get_downline_count(event.sender_id, config['level_count'])
    total_members = sum(c['total'] for c in counts)
    total_vip = sum(c['vip'] for c in counts)
    
    # 生成推广链接
    bot_info = await event.client.get_me()
    invite_link = f'https://t.me/{bot_info.username}?start={event.sender_id}'
    
    text = f'💫 我的推广\n\n'
    text += f'📊 推广统计:\n'
    text += f'• 总下级: {total_members} 人\n'
    text += f'• VIP下级: {total_vip} 人\n'
    text += f'• 累计收益: {member["balance"]} U\n'
    text += f'• 错过收益: {member["missed_balance"]} U\n\n'
    text += f'🔗 您的推广链接:\n{invite_link}\n\n'
    text += f'💡 分享链接邀请好友，好友开通VIP您即可获得 {config["level_reward"]} U 奖励!'
    
    # 【修改3】改为调用Telegram原生分享功能
    share_text = f"🔥 推荐一个非常棒的群裂变工具！\n\n💰 自动管理群组，自动分红，多层级收益！\n\n👇 点击下方链接加入：\n{invite_link}"
    share_url = f"https://t.me/share/url?url={quote(invite_link)}&text={quote(share_text)}"

    buttons = [[Button.url('📤 立即推广 (选择好友/群)', share_url)]]
    
    await event.respond(text, buttons=buttons, parse_mode='md')

@multi_bot_on(events.NewMessage(pattern=BTN_BACK))
async def back_handler(event):
    """返回主菜单"""
    try:
        original_sender_id = event.sender_id
        event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
    except:
        pass
    
    member = DB.get_member(event.sender_id)
    if not member:
        await event.respond('请先发送 /start 注册')
        return
    
    await event.respond(
        f'🤖 裂变推广机器人\n\n'
        f'👤 用户: @{member["username"]}\n'
        f'💎 VIP状态: {"✅ 已开通" if member["is_vip"] else "❌ 未开通"}\n'
        f'💰 余额: {member["balance"]} U\n\n'
        f'请选择功能:',
        buttons=get_main_keyboard(event.sender_id)
    )

@multi_bot_on(events.NewMessage(pattern=BTN_ADMIN))
async def admin_handler(event):
    """管理后台"""
    try:
        original_sender_id = event.sender_id
        event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
    except:
        pass
    
    if event.sender_id not in ADMIN_IDS:
        return
    
    # 获取系统配置
    config = get_system_config()
    
    text = f'⚙️ 管理后台\n\n'
    text += f'当前设置:\n'
    text += f'📊 层数: {config["level_count"]} 层\n'
    text += f'💰 每层返利: {config["level_reward"]} U\n'
    text += f'💎 VIP价格: {config["vip_price"]} U\n'
    _fb_group = get_fallback_resource("group")
    if _fb_group:
        text += f"\n\n💡 推荐群组:\n{_fb_group}"
    text += f'💳 提现门槛: {config["withdraw_threshold"]} U\n'
    text += f'💵 USDT地址: {config["usdt_address"][:10] if config["usdt_address"] else "未设置"}...{config["usdt_address"][-10:] if config["usdt_address"] and len(config["usdt_address"]) > 20 else ""}\n\n'
    text += f'客服文本:\n{config["support_text"]}\n\n'
    from config import USE_PROXY
    web_url = 'http://154.201.68.178:5051' if not USE_PROXY else 'http://localhost:5051'
    text += f'🌐 Web管理后台: {web_url}'
    
    buttons = [
        [Button.inline('📊 设置层数', b'admin_set_level'), Button.inline('💰 设置返利', b'admin_set_reward')],
        [Button.inline('💎 设置VIP价格', b'admin_set_vip_price'), Button.inline('💳 设置提现门槛', b'admin_set_withdraw')],
        [Button.inline('👩‍💼 设置客服文本', b'admin_set_support'), Button.inline('💫 查看会员统计', b'admin_stats')],
        [Button.inline('🎁 手动充值VIP', b'admin_manual_vip'), Button.inline('📢 用户广播', b'admin_broadcast')]
    ]
    
    await event.respond(text, buttons=buttons, parse_mode='md')

# ==================== 群组欢迎和自动注册 ====================

@multi_bot_on(events.Raw)
async def raw_update_handler(event):
    """监听原始Telegram更新，检测管理员权限变化"""
    try:
        # 首先记录所有Raw更新，便于调试（生产环境可注释掉）
        if hasattr(event, 'update') and hasattr(event.update, '__class__'):
            update_type = type(event.update).__name__
            print(f'[Raw事件] 📡 收到更新: {update_type}')

            # 打印更详细的调试信息
            update = event.update
            print(f'[Raw事件] 详细内容: {update}')

        # 仅处理权限变更相关的 Update 类型
        if not hasattr(event, 'update'):
            return

        update = event.update
        update_type = type(update).__name__

        # 我们只关心机器人本身权限变动
        target_user_id = None
        target_chat_id = None
        permission_changed = False

        # 记录所有可能的权限相关更新类型
        print(f'[Raw权限检测] 分析更新类型: {update_type}')

        # 1. 普通群组管理员变动
        if update_type == 'UpdateChatParticipantAdmin':
            target_user_id = getattr(update, 'user_id', None)
            target_chat_id = getattr(update, 'chat_id', None)
            is_admin = getattr(update, 'is_admin', False)
            permission_changed = not is_admin  # 如果不是管理员，说明权限被撤销
            if permission_changed:
                print(f'[Raw权限检测] 检测到普通群组 {target_chat_id} 移除管理员 {target_user_id}')

        # 2. 超级群组/频道成员变动 (包括权限变动)
        elif update_type == 'UpdateChannelParticipant':
            target_user_id = getattr(update, 'user_id', None)
            target_chat_id = getattr(update, 'channel_id', None)

            # prev_participant 是旧状态，new_participant 是新状态
            prev = getattr(update, 'prev_participant', None)
            new_p = getattr(update, 'new_participant', None)

            from telethon.tl.types import ChannelParticipantAdmin, ChannelParticipantCreator, ChannelParticipant

            was_admin = isinstance(prev, (ChannelParticipantAdmin, ChannelParticipantCreator))
            is_now_admin = isinstance(new_p, (ChannelParticipantAdmin, ChannelParticipantCreator))

            permission_changed = was_admin and not is_now_admin
            print(f'[Raw权限检测] 频道参与者更新: user={target_user_id}, chat={target_chat_id}, was_admin={was_admin}, is_now_admin={is_now_admin}, changed={permission_changed}')
            if permission_changed:
                print(f'[Raw权限检测] 🚨 检测到超级群组 {target_chat_id} 移除管理员 {target_user_id}')

        # 3. 【新增】检测其他可能的权限变更事件
        elif update_type in ['UpdateChatParticipant', 'UpdateChannel', 'UpdateChat']:
            print(f'[Raw权限检测] 检测到可能的权限相关更新: {update_type}')
            # 尝试提取用户信息
            target_user_id = getattr(update, 'user_id', None) or getattr(update, 'participant', None)
            target_chat_id = getattr(update, 'chat_id', None) or getattr(update, 'channel_id', None)

            if hasattr(update, 'participant'):
                participant = update.participant
                if hasattr(participant, 'user_id'):
                    target_user_id = participant.user_id

            print(f'[Raw权限检测] 从{update_type}提取到: user={target_user_id}, chat={target_chat_id}')

        # 4. 【新增】监听所有可能的管理员相关更新
        elif 'Admin' in update_type or 'Participant' in update_type:
            print(f'[Raw权限检测] 发现管理员/参与者相关更新: {update_type}')
            # 打印完整更新内容用于调试
            print(f'[Raw权限检测] 完整更新内容: {update}')

            # 尝试提取所有可能的信息
            for attr in dir(update):
                if not attr.startswith('_'):
                    try:
                        value = getattr(update, attr)
                        if 'admin' in attr.lower() or 'user' in attr.lower() or 'chat' in attr.lower() or 'channel' in attr.lower():
                            print(f'[Raw权限检测] {attr}: {value}')
                    except:
                        pass

        # 3. 【新增】更宽泛的权限变更检测 - 监听所有可能的权限相关更新
        if not permission_changed:
            # 检查是否有任何Participant相关的更新
            if 'Participant' in update_type:
                print(f'[Raw权限检测] 🎯 发现Participant相关更新: {update_type}')

                # 尝试从所有可能的字段中提取用户信息
                if not target_user_id:
                    target_user_id = getattr(update, 'user_id', None)
                if not target_chat_id:
                    target_chat_id = getattr(update, 'chat_id', getattr(update, 'channel_id', None))

                # 从participant相关字段提取
                if not target_user_id:
                    for attr in ['participant', 'new_participant', 'prev_participant']:
                        if hasattr(update, attr):
                            participant = getattr(update, attr)
                            if hasattr(participant, 'user_id'):
                                target_user_id = participant.user_id
                                break

                # 如果找到了用户和群组信息，进行权限检查
                if target_user_id and target_chat_id:
                    print(f'[Raw权限检测] 发现用户 {target_user_id} 在群组 {target_chat_id} 的更新，开始权限验证...')

                    # 检查是否是我们的机器人
                    target_bot = None
                    for client in clients:
                        try:
                            me = await client.get_me()
                            if me.id == target_user_id:
                                target_bot = client
                                break
                        except:
                            continue

                    if target_bot:
                        print(f'[Raw权限检测] ✅ 确认是本机机器人 {target_user_id}，执行权限检查')

                        # 执行权限检查
                        await check_and_notify_permission_change(target_bot, target_user_id, target_chat_id, update_type)
                    else:
                        print(f'[Raw权限检测] 非本机机器人，跳过处理')
                else:
                    print(f'[Raw权限检测] 未找到完整的用户或群组信息')

        # 如果前面已经检测到权限变更，直接处理
        if permission_changed and target_user_id and target_chat_id:
            print(f'[Raw权限检测] 🚨 确认权限变更: 用户 {target_user_id}, 群组 {target_chat_id}')

            target_bot = None
            for client in clients:
                try:
                    me = await client.get_me()
                    if me.id == target_user_id:
                        target_bot = client
                        break
                except:
                    continue

            if target_bot:
                await check_and_notify_permission_change(target_bot, target_user_id, target_chat_id, update_type)
            else:
                print(f'[Raw权限检测] 未找到对应的机器人客户端，无法发送通知')

        # 【新增】对于所有检测到的机器人相关更新，都进行权限检查
        if target_user_id and target_chat_id:
            # 检查是否是我们的机器人
            is_our_bot = False
            target_bot = None
            for client in clients:
                try:
                    me = await client.get_me()
                    if me.id == target_user_id:
                        is_our_bot = True
                        target_bot = client
                        break
                except:
                    continue

            if is_our_bot and target_bot:
                print(f'[Raw权限检测] 发现本机机器人 {target_user_id} 的更新，执行主动权限检查')
                try:
                    # 无论什么更新类型，都主动检查当前权限状态
                    full_chat_id = target_chat_id if str(target_chat_id).startswith('-100') else f"-100{target_chat_id}"
                    perms = await target_bot.get_permissions(full_chat_id, target_user_id)
                    current_is_admin = perms.is_admin or perms.is_creator
                    print(f'[Raw权限检测] 当前权限状态检查: admin={current_is_admin}')

                    if not current_is_admin:
                        print(f'[Raw权限检测] ✅ 确认机器人已失去管理员权限，发送通知')
                        await notify_group_binding_invalid(target_chat_id, target_user_id, f"Raw事件检测到管理员权限被撤销 ({update_type})", target_bot)
                    else:
                        print(f'[Raw权限检测] 机器人仍具有管理员权限')
                except Exception as check_err:
                    print(f'[Raw权限检测] 主动权限检查失败: {check_err}')
                    # 如果检查失败，也发送通知（保守策略）
                    await notify_group_binding_invalid(target_chat_id, target_user_id, f"Raw事件检测且权限检查失败，可能权限被撤销 ({update_type})", target_bot)

    except Exception as e:
        # 避免日志刷屏，仅在严重错误时打印
        if 'Connection' not in str(e):
            print(f'[Raw事件处理异常] {e}')

# ==================== 权限检查和通知函数 ====================

async def check_permission_changes():
    """定期检查所有绑定群组的机器人权限状态"""
    try:
        print("[权限检查] 开始定期权限状态检查...")

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

        print(f"[权限检查] 找到 {len(bound_groups)} 个需要检查的群组绑定")

        for user_id, group_id, group_name, username in bound_groups:
            try:
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
                    print(f"[权限检查] 未找到用户 {user_id} 对应的机器人，跳过")
                    continue

                # 检查权限状态
                try:
                    perms = await target_bot.get_permissions(group_id, user_id)
                    is_admin = perms.is_admin or perms.is_creator

                    if not is_admin:
                        print(f"[权限检查] 🚨 发现机器人 {user_id} 在群组 {group_id} 失去管理员权限")

                        # 触发全局状态刷新
                        global permission_check_triggered
                        permission_check_triggered = True

                        # 发送通知 - 转换group_id格式用于匹配
                        raw_chat_id = int(str(group_id).replace('-100', '')) if str(group_id).startswith('-100') else group_id
                        await notify_group_binding_invalid(raw_chat_id, user_id, "定期检查发现管理员权限被撤销", target_bot)

                        # 更新数据库状态 - 添加重试机制
                        max_db_retries = 3
                        for db_attempt in range(max_db_retries):
                            try:
                                conn = get_db_conn()
                                c = conn.cursor()
                                c.execute('UPDATE member_groups SET is_bot_admin = 0 WHERE telegram_id = ? AND group_id = ?',
                                        (user_id, group_id))
                                c.execute('UPDATE members SET is_bot_admin = 0 WHERE telegram_id = ?', (user_id,))
                                conn.commit()
                                conn.close()
                                break
                            except Exception as db_err:
                                if conn:
                                    try:
                                        conn.close()
                                    except:
                                        pass
                                if 'locked' in str(db_err).lower() and db_attempt < max_db_retries - 1:
                                    print(f'[权限检查] 数据库锁定，重试 {db_attempt + 1}/{max_db_retries}: {db_err}')
                                    await asyncio.sleep(0.5)
                                    continue
                                else:
                                    print(f'[权限检查] 更新数据库失败: {db_err}')
                                    break

                        print(f"[权限检查] 已更新数据库状态并发送通知")
                    else:
                        print(f"[权限检查] ✅ 机器人 {user_id} 在群组 {group_id} 仍具有管理员权限")

                except Exception as perm_err:
                    print(f"[权限检查] 检查机器人 {user_id} 在群组 {group_id} 权限失败: {perm_err}")
                    # 如果检查失败，可能意味着机器人被踢出
                    raw_chat_id = int(str(group_id).replace('-100', '')) if str(group_id).startswith('-100') else group_id
                    await notify_group_binding_invalid(raw_chat_id, user_id, "定期检查发现机器人无法访问群组，可能已被踢出", target_bot)

            except Exception as e:
                print(f"[权限检查] 检查用户 {user_id} 权限失败: {e}")

        print("[权限检查] 定期权限检查完成")

    except Exception as e:
        print(f"[权限检查] 定期检查过程出错: {e}")

async def check_and_notify_permission_change(bot, user_id, chat_id, update_type):
    """检查机器人权限状态并发送通知"""
    try:
        # 构建完整的chat_id
        full_chat_id = int(f"-100{chat_id}") if chat_id > 0 else chat_id

        print(f'[权限检查] 正在验证机器人 {user_id} 在群组 {full_chat_id} 的权限...')

        # 调用API检查当前权限
        perms = await bot.get_permissions(full_chat_id, user_id)
        is_admin = perms.is_admin or perms.is_creator

        print(f'[权限检查] 当前权限状态: admin={is_admin}')

        if not is_admin:
            print(f'[权限检查] ✅ 确认机器人已失去管理员权限，发送通知')

            # 触发全局状态刷新
            global permission_check_triggered
            permission_check_triggered = True

            # 发送通知 - 使用原始chat_id进行匹配
            await notify_group_binding_invalid(chat_id, user_id, f"机器人管理员权限被撤销 ({update_type})", bot)
        else:
            print(f'[权限检查] 机器人仍具有管理员权限')

    except Exception as e:
        print(f'[权限检查] 权限验证失败: {e}')
        # 保守处理：如果验证失败，假设权限被撤销
        print(f'[权限检查] 由于验证失败，保守处理为权限被撤销')
        await notify_group_binding_invalid(chat_id, user_id, f"机器人权限验证失败，可能已被撤销 ({update_type})", bot)

# ==================== 备用Raw事件监听器 ====================

@multi_bot_on(events.Raw)
async def raw_update_handler_backup(event):
    """备用Raw事件监听器，捕获所有可能的权限变更"""
    try:
        if not hasattr(event, 'update'):
            return

        update = event.update
        update_type = type(update).__name__

        # 只记录我们关心的更新类型
        if 'Participant' in update_type or 'Chat' in update_type or 'Channel' in update_type:
            print(f'[Raw备用] 📡 捕获更新: {update_type}')

            # 尝试提取所有可能的用户和群组信息
            user_id = None
            chat_id = None

            # 从各种可能的字段提取信息
            for attr in ['user_id', 'participant', 'new_participant', 'prev_participant']:
                if hasattr(update, attr):
                    val = getattr(update, attr)
                    if isinstance(val, int):
                        user_id = val
                        break
                    elif hasattr(val, 'user_id'):
                        user_id = val.user_id
                        break

            for attr in ['chat_id', 'channel_id']:
                if hasattr(update, attr):
                    chat_id = getattr(update, attr)
                    break

            if user_id and chat_id:
                print(f'[Raw备用] 发现用户 {user_id} 在群组 {chat_id} 的更新')

    except Exception as e:
        pass  # 备用监听器不打印错误，避免刷屏

@multi_bot_on(events.ChatAction)
async def group_welcome_handler(event):
    """处理群组相关事件：加入、离开、权限变化等"""
    try:
        print(f'[ChatAction] 收到事件: {type(event.action_message.action).__name__ if event.action_message else "无"}')
        
        # 检查是否是用户加入事件
        if event.user_joined or event.user_added:
            sys_config = get_system_config()
            
            # 获取新成员信息
            user = await event.get_user()
            if not user:
                print('[群事件] 无法获取用户信息')
                return
            
            new_user_id = user.id
            new_username = user.username or f'user_{new_user_id}'
            user_name = user.first_name or ''
            if user.last_name:
                user_name += f' {user.last_name}'
            user_name = user_name.strip() or f'用户{new_user_id}'
            
            # 获取群信息
            chat = await event.get_chat()
            chat_id = chat.id if chat else None
            print(f'[群事件] 群ID={chat_id}, 新用户={new_user_id}({new_username})')
            
            # ===== 自动注册功能 =====
            auto_register_enabled = sys_config.get('auto_register_enabled', '0')
            print(f'[自动注册] 开关状态={auto_register_enabled}')
            
            if auto_register_enabled == '1' or auto_register_enabled == 1:
                try:
                    # 获取邀请者ID - 尝试多种方式
                    added_by = None
                    
                    # 方式1: event.added_by
                    if hasattr(event, 'added_by') and event.added_by:
                        added_by = event.added_by
                        print(f'[自动注册] 方式1获取邀请者: {added_by}')
                    
                    # 方式2: action_message.action
                    if not added_by and hasattr(event, 'action_message') and event.action_message:
                        action = event.action_message.action
                        print(f'[自动注册] action类型: {type(action).__name__}')
                        if hasattr(action, 'inviter_id') and action.inviter_id:
                            added_by = action.inviter_id
                            print(f'[自动注册] 方式2a获取邀请者: {added_by}')
                    
                    # 方式3: 从消息发送者获取
                    if not added_by and event.action_message:
                        from_id = event.action_message.from_id
                        if from_id:
                            if hasattr(from_id, 'user_id'):
                                added_by = from_id.user_id
                            elif hasattr(from_id, 'id'):
                                added_by = from_id.id
                            elif isinstance(from_id, int):
                                added_by = from_id
                            print(f'[自动注册] 方式3获取邀请者: {added_by}')
                    
                    # 确保 added_by 是整数ID
                    if added_by and not isinstance(added_by, int):
                        if hasattr(added_by, 'id'):
                            added_by = added_by.id
                        elif hasattr(added_by, 'user_id'):
                            added_by = added_by.user_id
                        print(f'[自动注册] 转换后邀请者ID: {added_by}')
                    
                    # 方式4: 如果是通过群链接加入，尝试找群主
                    if not added_by and chat_id:
                        conn = get_db_conn()
                        c = conn.cursor()
                        c.execute('SELECT telegram_id FROM members WHERE group_link LIKE ?', (f'%{chat_id}%',))
                        owner = c.fetchone()
                        conn.close()
                        if owner:
                            added_by = owner[0]
                            print(f'[自动注册] 方式4获取群主: {added_by}')
                    
                    print(f'[自动注册] 最终邀请者={added_by}, 新用户={new_user_id}')
                    
                    if added_by and added_by != new_user_id:
                        # 检查邀请者是否是会员
                        inviter = DB.get_member(added_by)
                        print(f'[自动注册] 邀请者是会员: {inviter is not None}')
                        if inviter:
                            # ===== 检测邀请者群组绑定状态 =====
                            inviter_group_valid = await check_user_group_binding_status(inviter['telegram_id'], clients)
                            if not inviter_group_valid:
                                print(f'[自动注册] 邀请者 {added_by} 群组绑定失效，跳过自动注册')
                                # 由于群组绑定失效，跳过自动注册
                                return

                            # 检查新用户是否已注册
                            existing = DB.get_member(new_user_id)
                            print(f'[自动注册] 新用户已注册: {existing is not None}')
                            if not existing:
                                # 注册新用户为邀请者的下级
                                DB.create_member(new_user_id, new_username, added_by)
                                print(f'✅ 自动注册成功: {new_username} 成为 {inviter["username"]} 的下级')
                                
                                # 通知邀请者
                                try:
                                    await bot.send_message(
                                        added_by,
                                        (
                                            "📨 邀请成功通知\n\n"
                                            f"👥 您的下级新成员加入：[{user_name}](tg://user?id={new_user_id})\n"
                                            "🎯 您的直推好友数量 +1\n\n"
                                            "💡 快去带领他开通 VIP，发展更多团队吧～"
                                        ),
                                        parse_mode='markdown'
                                    )
                                    print(f'✅ 已通知邀请者 {added_by}')
                                except Exception as notify_err:
                                    print(f'通知邀请者失败: {notify_err}')
                            else:
                                print(f'[自动注册] 跳过: 用户已存在')
                        else:
                            print(f'[自动注册] 跳过: 邀请者不是会员')
                    else:
                        print(f'[自动注册] 跳过: 无法获取邀请者或是自己')
                except Exception as e:
                    print(f'自动注册处理失败: {e}')
                    import traceback
                    traceback.print_exc()
            
            # ===== 欢迎语功能 =====
            welcome_enabled = sys_config.get('welcome_enabled', '1')
            if welcome_enabled == '1' or welcome_enabled == 1:
                welcome_message = sys_config.get('welcome_message', '')
                
                if welcome_message:
                    # 替换欢迎语中的变量
                    msg = welcome_message.replace('{name}', user_name)
                    msg = msg.replace('{username}', f'@{new_username}' if user.username else user_name)
                    msg = msg.replace('{id}', str(new_user_id))
                    
                    await event.respond(f'👋 {msg}')

        # ===== 机器人离开/权限变化检测 =====
        elif event.user_left or event.user_kicked:
            # 检查是否有机器人被踢出
            if hasattr(event, 'user_id'):
                kicked_user_id = event.user_id
                print(f'[机器人检测] 用户离开/被踢出: {kicked_user_id}')

                # 检查是否是我们的机器人被踢出
                if not clients:
                    print(f'[机器人检测] ⚠️ 警告：clients列表为空，无法检测机器人状态')
                    print(f'[机器人检测] 当前活跃机器人数量: {len(clients)}')
                    return

                bot_ids = []
                for client in clients:
                    try:
                        bot_ids.append((await client.get_me()).id)
                    except Exception as e:
                        print(f'[机器人检测] 获取机器人ID失败: {e}')
                        continue

                print(f'[机器人检测] 当前活跃机器人ID: {bot_ids}')

                if kicked_user_id in bot_ids:
                    print(f'[机器人检测] ✅ 检测到我们的机器人被踢出群组: {kicked_user_id}')
                    # 找到被踢出的机器人实例
                    kicked_bot = None
                    for client in clients:
                        try:
                            if (await client.get_me()).id == kicked_user_id:
                                kicked_bot = client
                                break
                        except Exception as e:
                            continue

                    # 使用被踢出的机器人发送通知
                    await notify_group_binding_invalid(event.chat_id, kicked_user_id, "机器人被踢出群组", kicked_bot)
                    return
                else:
                    print(f'[机器人检测] 普通用户离开/被踢出: {kicked_user_id}')

        # ===== 增强：机器人管理员权限撤销检测 =====
        print(f'[权限检测] ChatAction详情: user_id={getattr(event, "user_id", None)}, '
            f'user_joined={event.user_joined}, user_left={event.user_left}, '
            f'action={type(event.action_message.action).__name__ if event.action_message else "None"}')

        # 检测管理员权限变化 - 通过ChatAction事件
        # 虽然ChatAction不直接包含权限信息，但我们可以检测到相关事件后主动检查
        user_id = getattr(event, 'user_id', None)
        if user_id:
            # 检查是否是我们的机器人
            is_our_bot = False
            target_bot = None
            for client in clients:
                try:
                    me = await client.get_me()
                    if me.id == user_id:
                        is_our_bot = True
                        target_bot = client
                        break
                except:
                    continue

            if is_our_bot and target_bot:
                print(f'[权限检测] 检测到本机机器人 {user_id} 的ChatAction事件，检查权限状态...')

                # 获取群组ID
                chat_id = getattr(event, 'chat_id', None)
                if not chat_id and hasattr(event, 'chat'):
                    chat_id = event.chat.id

                if chat_id:
                    # 转换chat_id格式
                    full_chat_id = int(f"-100{chat_id}") if chat_id > 0 else chat_id

                    try:
                        # 检查当前权限状态
                        perms = await target_bot.get_permissions(full_chat_id, user_id)
                        is_admin = perms.is_admin or perms.is_creator

                        print(f'[权限检测] 机器人 {user_id} 在群组 {full_chat_id} 的权限状态: admin={is_admin}')

                        if not is_admin:
                            print(f'[权限检测] ✅ 检测到机器人失去管理员权限，发送通知')

                            # 触发全局状态刷新
                            global permission_check_triggered
                            permission_check_triggered = True

                            # 发送通知
                            await notify_group_binding_invalid(chat_id, user_id, "检测到机器人管理员权限被撤销", target_bot)
                        else:
                            print(f'[权限检测] 机器人仍具有管理员权限')

                    except Exception as perm_err:
                        print(f'[权限检测] 权限检查失败: {perm_err}')
                        # 如果权限检查失败，可能意味着机器人被踢出或权限被撤销
                        print(f'[权限检测] 由于权限检查失败，假设权限被撤销，发送通知')
                        await notify_group_binding_invalid(chat_id, user_id, "机器人权限检查失败，可能已被撤销", target_bot)

        # ===== 群组解散检测 =====
        if hasattr(event, 'chat_deleted') and event.chat_deleted:
            print(f'[群组检测] 群组被解散: {event.chat_id}')
            # 通知所有绑定此群组的用户
            await notify_group_binding_invalid(event.chat_id, None, "群组已被解散")
            return

    except Exception as e:
        print(f'群事件处理失败: {e}')

# ==================== 完整的消息处理器 ====================

@multi_bot_on(events.NewMessage())
async def message_handler(event):
    """完整的消息处理器 - 处理提现、管理员设置、群链接等"""
    # 账号关联处理
    try:
        original_sender_id = event.sender_id
        event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
    except:
        pass
    
    # 忽略命令和按钮文字
    if not event.message.text:
        return
    
    text = event.message.text.strip()
    sender_id = event.sender_id
    
    # 处理提现金额输入
    if sender_id in waiting_for_withdraw_amount:
        del waiting_for_withdraw_amount[sender_id]
        try:
            amount = float(text)
            config = get_system_config()
            member = DB.get_member(sender_id)
            
            if amount < config['withdraw_threshold']:
                await event.respond(f'❌ 提现金额不能小于 {config["withdraw_threshold"]} U')
                return
            
            if amount > member['balance']:
                await event.respond(f'❌ 余额不足\n\n当前余额: {member["balance"]} U')
                return
            
            withdraw_temp_data[sender_id] = amount
            waiting_for_withdraw_address[sender_id] = True
            await event.respond(
                f'💳 提现申请\n\n'
                f'提现金额: {amount} U\n\n'
                f'请输入您的USDT收款地址（TRC20）：'
            )
        except ValueError:
            await event.respond('❌ 请输入有效的数字金额')
        return
    
    # 处理提现地址输入
    if sender_id in waiting_for_withdraw_address:
        del waiting_for_withdraw_address[sender_id]
        usdt_address = text.strip()
        
        if not usdt_address or len(usdt_address) < 20:
            await event.respond('❌ 请输入有效的USDT地址')
            return
        
        amount = withdraw_temp_data.get(sender_id, 0)
        if amount <= 0:
            await event.respond('❌ 提现金额错误，请重新申请')
            return
        
        del withdraw_temp_data[sender_id]
        
        try:
            import datetime
            import time
            
            # 重试机制处理数据库锁
            max_retries = 3
            for retry in range(max_retries):
                try:
                    conn = get_db_conn()
                    conn.execute("PRAGMA busy_timeout = 5000")
                    c = conn.cursor()
                    
                    # 扣除余额
                    c.execute("UPDATE members SET balance = balance - ? WHERE telegram_id = ?", (amount, sender_id))
                    
                    # 插入提现记录
                    now = get_cn_time()
                    
                    # 检查表是否有usdt_address字段
                    c.execute("PRAGMA table_info(withdrawals)")
                    columns = [col[1] for col in c.fetchall()]
                    if 'usdt_address' in columns:
                        c.execute("INSERT INTO withdrawals (member_id, amount, usdt_address, status, create_time) VALUES (?, ?, ?, 'pending', ?)",
                                 (sender_id, amount, usdt_address, now))
                    else:
                        c.execute("INSERT INTO withdrawals (member_id, amount, status, create_time) VALUES (?, ?, 'pending', ?)",
                                 (sender_id, amount, now))
                    
                    conn.commit()
                    
                    # 获取新余额
                    c.execute("SELECT balance FROM members WHERE telegram_id = ?", (sender_id,))
                    new_balance = c.fetchone()[0]
                    conn.close()
                    break
                    
                except Exception as e:
                    if 'locked' in str(e) and retry < max_retries - 1:
                        time.sleep(0.5)
                        continue
                    else:
                        raise
            
            await event.respond(
                f'✅ 提现申请已提交\n\n'
                f'提现金额: {amount} U\n'
                f'收款地址: {usdt_address}\n'
                f'剩余余额: {new_balance} U\n\n'
                f'⏳ 请等待管理员审核\n'
                f'审核结果将通过机器人通知您'
            )
        except Exception as e:
            await event.respond(f'❌ 提现申请失败: {str(e)}')
        return
    
    # 忽略命令
    if text.startswith('/'):
        if text == '/cancel':
            waiting_for_group_link.pop(sender_id, None)
            waiting_for_backup.pop(sender_id, None)
            waiting_for_recharge_amount.pop(sender_id, None)
            admin_waiting.pop(sender_id, None)
            await event.respond('已取消操作', buttons=get_main_keyboard(sender_id))
        return
    
    # 忽略主菜单按钮
    if text in [BTN_PROFILE, BTN_FISSION, BTN_VIEW_FISSION, BTN_RESOURCES, BTN_PROMOTE, BTN_SUPPORT, BTN_BACK, BTN_ADMIN, BTN_VIP, BTN_MY_PROMOTE]:
        return
    
    # 管理员设置处理
    if sender_id in admin_waiting:
        wait_type = admin_waiting[sender_id]
        config = get_system_config()
        
        if wait_type == 'level_count':
            try:
                value = int(text)
                if 1 <= value <= 20:
                    from database import update_system_config
                    update_system_config('level_count', value)
                    # 初始化或调整每层金额配置为当前每层返利（或1）* value 层，便于前端显示
                    try:
                        import json
                        per_level = float(config.get('level_reward', 1))
                        amounts = [per_level for _ in range(value)]
                        update_system_config('level_amounts', json.dumps(amounts))
                    except Exception as e:
                        print(f"[admin_set_level] 无法初始化 level_amounts: {e}")
                    del admin_waiting[sender_id]
                    await event.respond(f'✅ 层数设置成功!\n\n当前层数: {value} 层')
                else:
                    await event.respond('❌ 请输入1-20之间的数字')
            except ValueError:
                await event.respond('❌ 请输入有效的数字')
            return
        
        elif wait_type == 'level_reward':
            try:
                value = float(text)
                if value > 0:
                    from database import update_system_config
                    update_system_config('level_reward', value)
                    del admin_waiting[sender_id]
                    await event.respond(f'✅ 返利设置成功!\n\n每层返利: {value} U')
                else:
                    await event.respond('❌ 请输入大于0的数字')
            except ValueError:
                await event.respond('❌ 请输入有效的数字')
            return
        
        elif wait_type == 'vip_price':
            try:
                value = float(text)
                if value > 0:
                    from database import update_system_config
                    update_system_config('vip_price', value)
                    del admin_waiting[sender_id]
                    await event.respond(f'✅ VIP价格设置成功!\n\n当前价格: {value} U')
                else:
                    await event.respond('❌ 请输入大于0的数字')
            except ValueError:
                await event.respond('❌ 请输入有效的数字')
            return
        
        elif wait_type == 'withdraw_threshold':
            try:
                value = float(text)
                if value >= 0:
                    from database import update_system_config
                    update_system_config('withdraw_threshold', value)
                    del admin_waiting[sender_id]
                    await event.respond(f'✅ 提现门槛设置成功!\n\n当前门槛: {value} U')
                else:
                    await event.respond('❌ 请输入大于等于0的数字')
            except ValueError:
                await event.respond('❌ 请输入有效的数字')
            return
        
        elif wait_type == 'support_text':
            from database import update_system_config
            update_system_config('support_text', text)
            del admin_waiting[sender_id]
            await event.respond(f'✅ 客服文本设置成功!\n\n当前文本:\n{text}')
            return
        
        elif wait_type == 'manual_vip':
            # 手动充值VIP - 调用统一处理函数
            target_user = None
            
            # 尝试按用户ID查找
            try:
                user_id = int(text.strip())
                target_user = DB.get_member(user_id)
                if not target_user:
                    await event.respond(f'❌ 未找到用户ID: {user_id}\n\n该用户可能未使用过机器人')
                    return
            except ValueError:
                # 按用户名查找
                username = text.strip().lstrip('@')
                conn = get_db_conn()
                c = conn.cursor()
                c.execute('SELECT * FROM members WHERE username = ?', (username,))
                row = c.fetchone()
                conn.close()
                
                if row:
                    target_user = {
                        'id': row[0], 'telegram_id': row[1], 'username': row[2],
                        'backup_account': row[3], 'referrer_id': row[4], 'balance': row[5],
                        'missed_balance': row[6], 'group_link': row[7], 'is_vip': row[8],
                        'register_time': row[9], 'vip_time': row[10]
                    }
                else:
                    await event.respond(f'❌ 未找到用户名: @{username}\n\n该用户可能未使用过机器人')
                    return
            
            # 检查是否已经是VIP
            if target_user['is_vip']:
                await event.respond(
                    f'⚠️ 用户已是VIP\n\n'
                    f'用户ID: {target_user["telegram_id"]}\n'
                    f'用户名: @{target_user["username"]}\n'
                    f'VIP开通时间: {target_user["vip_time"][:10] if target_user["vip_time"] else "未知"}'
                )
                del admin_waiting[sender_id]
                return
            
            # 【核心修复】调用统一处理函数
            success, result = await admin_manual_vip_handler(target_user['telegram_id'], config)
            
            if success:
                stats = result['stats']
                await event.respond(
                    f'✅ VIP充值成功!\n\n'
                    f'用户ID: {target_user["telegram_id"]}\n'
                    f'用户名: @{target_user["username"]}\n'
                    f'用户已收到开通通知'
                )
            else:
                await event.respond(f'❌ {result}')
            
            del admin_waiting[sender_id]
            return
        
        elif wait_type == 'broadcast':
            # 用户广播
            broadcast_message = text
            
            # 获取所有用户
            conn = get_db_conn()
            c = conn.cursor()
            c.execute('SELECT telegram_id, username FROM members')
            all_users = c.fetchall()
            conn.close()
            
            if not all_users:
                await event.respond('❌ 暂无用户')
                del admin_waiting[sender_id]
                return
            
            # 发送确认消息
            await event.respond(
                f'📢 开始广播...\n\n'
                f'目标用户数: {len(all_users)} 人\n'
                f'预计耗时: {len(all_users) * 0.05:.1f} 秒\n\n'
                f'广播内容:\n'
                f'---\n{broadcast_message}\n---\n\n'
                f'正在发送中，请稍候...'
            )
            
            # 发送广播
            success_count = 0
            failed_count = 0
            
            for user_id, username in all_users:
                try:
                    await bot.send_message(
                        user_id,
                        f'📢 系统广播\n\n{broadcast_message}',
                        parse_mode='markdown'
                    )
                    success_count += 1
                    await asyncio.sleep(0.05)
                except Exception as e:
                    failed_count += 1
                    print(f"发送广播给用户 {user_id} (@{username}) 失败: {e}")
            
            # 发送统计结果
            await event.respond(
                f'✅ 广播发送完成!\n\n'
                f'📊 发送统计:\n'
                f'• 总用户数: {len(all_users)} 人\n'
                f'• 发送成功: {success_count} 人\n'
                f'• 发送失败: {failed_count} 人\n'
                f'• 成功率: {success_count / len(all_users) * 100:.1f}%\n\n'
                f'💡 失败原因可能:\n'
                f'• 用户已删除或拉黑机器人\n'
                f'• 用户账号被封禁\n'
                f'• 用户隐私设置限制'
            )
            
            del admin_waiting[sender_id]
            return
    
    # 处理充值金额输入
    if sender_id in waiting_for_recharge_amount and waiting_for_recharge_amount[sender_id]:
        try:
            amount = float(text)
            if amount <= 0:
                await event.respond('❌ 金额必须大于0')
                return
            if amount > 99999:
                await event.respond('❌ 单次充值金额不能超过99999 U')
                return
            
            del waiting_for_recharge_amount[sender_id]
            await create_recharge_order(bot, event, amount)
        except ValueError:
            await event.respond('❌ 请输入有效的数字')
        return
    
    # 设置备用号
    if sender_id in waiting_for_backup and waiting_for_backup[sender_id]:
        backup_raw = text.strip().lstrip('@')
        backup_id = None
        backup_username = None
        
        # 尝试解析数字ID
        if backup_raw.isdigit():
            backup_id = int(backup_raw)
        
        # 无论是ID还是用户名，都尝试通过 Telegram 获取实体
        try:
            entity_query = backup_id if backup_id is not None else backup_raw
            entity = await bot.get_entity(entity_query)
            if getattr(entity, 'id', None):
                backup_id = entity.id
                backup_username = getattr(entity, 'username', None)
        except Exception as e:
            print(f"[备用号解析失败] {e}")
        
        if not backup_id:
            await event.respond('❌ 未找到该备用号，请发送正确的用户名或ID')
            return
        
        success, message = link_account(sender_id, backup_id, backup_username)
        del waiting_for_backup[sender_id]
        await event.respond(message)
        return
    
    # 设置群链接
    if sender_id in waiting_for_group_link and waiting_for_group_link[sender_id]:
        link = text
        # 只允许 http(s)://t.me/ 开头的链接
        if link.startswith('http://t.me/') or link.startswith('https://t.me/'):
            # 验证群链接（使用多机器人逻辑）
            print(f'[群绑定] 开始处理链接: {link}')
            bot_client = event.client if hasattr(event, 'client') else bot
            print(f'[群绑定] 使用机器人客户端: {bot_client}')
            verification_result = await verify_group_link(bot_client, link, clients)
            print(f'[群绑定] verify_group_link结果: {verification_result}')
            print(f'[群绑定] group_id: {verification_result.get("group_id")}, success: {verification_result.get("success")}')
            
            if verification_result['success']:
                # 获取 verify_group_link 返回的 ID (现在核心函数保证成功即返回ID)
                group_id = verification_result.get('group_id')
                group_name = verification_result.get('group_name')
                is_admin_flag = 1 if verification_result.get('admin_checked') else 0
                
                print(f'[群绑定] 准备存储: user={sender_id}, group_id={group_id}, link={link}')

                # 更新数据库 - 分步骤进行，确保每一步都成功
                try:
                    # 1. 更新members表
                    print('[群绑定] 更新members表...')
                    DB.update_member(sender_id, group_link=link, is_group_bound=1, is_bot_admin=is_admin_flag)
                    print('[群绑定] ✅ members表更新成功')

                    # 2. 更新member_groups表
                    print('[群绑定] 更新member_groups表...')
                    sender_username = getattr(event.sender, 'username', None) if hasattr(event, 'sender') else None
                    from database import upsert_member_group
                    upsert_member_group(sender_id, link, sender_username, is_bot_admin=is_admin_flag, group_id=group_id)
                    print('[群绑定] ✅ member_groups表更新成功')

                    # 3. 如果有群名，更新群名
                    if group_name and group_id:
                        print(f'[群绑定] 更新群名: {group_name}')
                        conn = get_db_conn()
                        c = conn.cursor()
                        c.execute("UPDATE member_groups SET group_name = ? WHERE group_id = ?", (group_name, group_id))
                        conn.commit()
                        conn.close()
                        print('[群绑定] ✅ 群名更新成功')

                    print(f'[群绑定] 🎉 绑定完成! user={sender_id}, group_id={group_id}')

                except Exception as sync_err:
                    print(f'[绑定群写入数据库失败] {sync_err}')
                    import traceback
                    traceback.print_exc()
                    # 如果数据库操作失败，不显示成功消息
                    await event.respond(f'❌ 绑定失败: {str(sync_err)}')
                    return

                del waiting_for_group_link[sender_id]
                
                # 构造提示文案
                if verification_result.get('admin_checked'):
                    await event.respond(
                        f'✅ 群链接设置成功!\n\n'
                        f'链接: {link}\n'
                        f'✅ 机器人已在群内\n'
                        f'✅ 机器人具有管理员权限'
                    )
                else:
                    await event.respond(
                        f'✅ 群组链接已记录\n\n'
                        f'链接: {link}\n\n'
                        f'ℹ️ 由于是私有邀请链接，Telegram 限制无法自动检测是否加群 / 是否设置群管。\n'
                        f'👉 建议为该群设置一个公开用户名，并发送公开群链接（例如 https://t.me/群用户名），\n'
                        f'这样系统才能自动检测您是否已加群并且机器人是否为群管。'
                    )
            else:
                reason = verification_result.get("message", "未知错误")
                await event.respond(
                    f'❌ 群链接验证失败\n\n'
                    f'原因: {reason}\n\n'
                    f'请确保:\n'
                    f'1. 机器人已被添加到群内\n'
                    f'2. 机器人具有管理员权限\n\n'
                    f'3. 使用 http://t.me/群用户名 或 https://t.me/群用户名 的公开群链接\n\n'
                    f'完成后请重新发送群链接'
                )
        else:
            await event.respond('❌ 链接格式不正确，请发送正确的Telegram群链接\n例如: http://t.me/群用户名 或 https://t.me/群用户名')
        return

# ==================== 通知队列处理 ====================

async def process_notify_queue():
    """处理通知队列"""
    while True:
        try:
            await asyncio.sleep(1)
            while notify_queue:
                item = notify_queue.pop(0)
                try:
                    await bot.send_message(item['member_id'], item['message'])
                    print(f"✅ 通知已发送: 用户{item['member_id']}")
                except Exception as e:
                    print(f"发送通知失败: {e}")
        except Exception as e:
            print(f"[通知队列] 错误: {e}")
            await asyncio.sleep(5)

# ==================== 后台定时任务 ====================

async def auto_broadcast_timer():
    """定时自动群发 - 根据 assignment 中每条消息的 broadcast_interval 和 last_sent_time 调度发送"""
    import json
    from datetime import datetime

    check_interval_seconds = 10  # 每10秒扫描一次
    
    while True:
        try:
            await asyncio.sleep(check_interval_seconds)
            now_ts = time.time()
            print("[定时群发] 扫描分配任务...", flush=True)
            
            conn = get_db_conn()
            c = conn.cursor()
            
            # 全局开关：允许管理员关闭定时分发
            c.execute("SELECT value FROM system_config WHERE key = 'broadcast_enabled'")
            row = c.fetchone()
            broadcast_enabled = row[0] == '1' if row else True
            if not broadcast_enabled:
                conn.close()
                continue
            
            # 查询所有启用分配：关联 member_groups、broadcast_assignments、broadcast_messages
            c.execute("""
                SELECT ba.id, ba.group_id, ba.message_id, ba.last_sent_time,
                       mg.group_link, mg.group_name,
                       bm.content, bm.image_url, bm.video_url, bm.buttons, bm.buttons_per_row, bm.broadcast_interval, bm.create_time
                FROM broadcast_assignments ba
                JOIN broadcast_messages bm ON ba.message_id = bm.id
                JOIN member_groups mg ON ba.group_id = mg.id
                WHERE ba.is_active = 1 AND bm.is_active = 1 AND mg.schedule_broadcast = 1
                ORDER BY bm.create_time ASC, bm.id ASC
            """)
            rows = c.fetchall()

            if not rows:
                conn.close()
                continue
            
            to_enqueue = []
            for r in rows:
                assign_id, group_id, message_id, last_sent_time, group_link, group_name, content, image_url, video_url, buttons_json, buttons_per_row, b_interval, bm_create = r
                try:
                    interval_minutes = int(b_interval) if b_interval else 120
                except:
                    interval_minutes = 120
                interval_seconds = interval_minutes * 60

                # parse last_sent_time (ISO) to timestamp
                last_ts = 0
                if last_sent_time:
                    try:
                        # handle timezone-aware ISO strings
                        dt = datetime.fromisoformat(last_sent_time)
                        last_ts = dt.timestamp()
                    except Exception:
                        try:
                            last_ts = float(last_sent_time)
                        except:
                            last_ts = 0

                # if never sent or interval elapsed, enqueue
                if now_ts - last_ts >= interval_seconds:
                    # prepare message content (simple: content only; buttons/media handled by process_broadcast_queue)
                    to_enqueue.append({
                        'assign_id': assign_id,
                        'group_id': group_id,
                        'group_link': group_link,
                        'group_name': group_name,
                        'message_id': message_id,
                        'content': content or '',
                        'image_url': image_url or '',
                        'video_url': video_url or '',
                        'buttons': buttons_json or '',
                        'buttons_per_row': buttons_per_row or 2
                    })

            # 插入到 broadcast_queue 并更新 last_sent_time
            if to_enqueue:
                now_iso = get_cn_time()
                for item in to_enqueue:
                    try:
                        # insert queue entry (store JSON if item contains media)
                        import json as _json
                        msg_payload = _json.dumps({
                            'content': item.get('content') or '',
                            'image_url': item.get('image_url') or '',
                            'video_url': item.get('video_url') or '',
                            'buttons': item.get('buttons') or '',
                            'buttons_per_row': item.get('buttons_per_row') or 2
                        }, ensure_ascii=False)
                        c.execute('INSERT INTO broadcast_queue (group_link, group_name, message, status, create_time) VALUES (?, ?, ?, ?, ?)',
                                  (item['group_link'], item['group_name'], msg_payload, 'pending', now_iso))
                        # update last_sent_time for assignment
                        c.execute('UPDATE broadcast_assignments SET last_sent_time = ? WHERE id = ?', (now_iso, item['assign_id']))
                    except Exception as e:
                        print(f"[定时群发] 入队失败 assign_id={item.get('assign_id')}: {e}")
                conn.commit()
                print(f"[定时群发] 已入队 {len(to_enqueue)} 条消息")
            
            conn.close()
        except Exception as e:
            print(f"[定时群发] 错误: {e}")
            await asyncio.sleep(30)

async def process_broadcast_queue():
    """处理群发队列（数据库队列）"""
    while True:
        try:
            await asyncio.sleep(5)  # 每5秒检查一次
            conn = get_db_conn()
            c = conn.cursor()
            
            # 获取待发送的任务
            c.execute("SELECT id, group_link, group_name, message FROM broadcast_queue WHERE status = 'pending' LIMIT 10")
            tasks = c.fetchall()
            
            for task in tasks:
                task_id, group_link, group_name, message = task
                try:
                    if group_link and 't.me/' in group_link:
                        chat_username = group_link.split('t.me/')[-1].split('/')[0].split('?')[0]
                        if not chat_username.startswith('+'):
                            # 支持 message 存储为纯文本或 JSON 字符串（包含 content/image_url/video_url/buttons）
                            send_text = None
                            send_image = None
                            send_video = None
                            send_buttons = None
                            try:
                                import json as _json
                                parsed = _json.loads(message)
                                if isinstance(parsed, dict):
                                    send_text = parsed.get('content') or ''
                                    send_image = parsed.get('image_url') or ''
                                    send_video = parsed.get('video_url') or ''
                                    send_buttons = parsed.get('buttons') or ''
                                else:
                                    send_text = str(parsed)
                            except Exception:
                                send_text = message

                            # send file if image or video present
                            if send_image:
                                file_path = send_image
                                if send_image.startswith('/static/uploads/'):
                                    # prefer local file path using UPLOAD_DIR from config
                                    try:
                                        from config import UPLOAD_DIR
                                        filename = os.path.basename(send_image)
                                        local_path = os.path.join(UPLOAD_DIR, filename)
                                    except Exception:
                                        local_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), send_image.lstrip('/'))

                                    if os.path.exists(local_path):
                                        await bot.send_file(f'@{chat_username}', local_path, caption=send_text)
                                    else:
                                        # fallback to sending as URL and log error
                                        print(f"[群发错误] 找不到本地图片文件: {local_path}")
                                        await bot.send_message(f'@{chat_username}', send_text + '\n' + send_image)
                                else:
                                    await bot.send_message(f'@{chat_username}', send_text + '\n' + send_image)
                            elif send_video:
                                file_path = send_video
                                if send_video.startswith('/static/uploads/'):
                                    try:
                                        from config import UPLOAD_DIR
                                        filename = os.path.basename(send_video)
                                        local_path = os.path.join(UPLOAD_DIR, filename)
                                    except Exception:
                                        local_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), send_video.lstrip('/'))

                                    if os.path.exists(local_path):
                                        await bot.send_file(f'@{chat_username}', local_path, caption=send_text)
                                    else:
                                        print(f"[群发错误] 找不到本地视频文件: {local_path}")
                                        await bot.send_message(f'@{chat_username}', send_text + '\n' + send_video)
                                else:
                                    await bot.send_message(f'@{chat_username}', send_text + '\n' + send_video)
                            else:
                                # try to build buttons if any
                                buttons_obj = None
                                if send_buttons:
                                    try:
                                        import json as _json2
                                        btns = _json2.loads(send_buttons)
                                        per_row = 2
                                        # if buttons_per_row present in parsed, use it
                                        if isinstance(parsed, dict) and parsed.get('buttons_per_row'):
                                            per_row = int(parsed.get('buttons_per_row') or per_row)
                                        rows = []
                                        row_buf = []
                                        for b in btns:
                                            if b.get('name') and b.get('url'):
                                                row_buf.append(Button.url(b['name'], b['url']))
                                                if len(row_buf) >= per_row:
                                                    rows.append(row_buf)
                                                    row_buf = []
                                        if row_buf:
                                            rows.append(row_buf)
                                        if rows:
                                            buttons_obj = rows
                                    except Exception:
                                        buttons_obj = None

                                if buttons_obj:
                                    await bot.send_message(f'@{chat_username}', send_text, buttons=buttons_obj)
                                else:
                                    await bot.send_message(f'@{chat_username}', send_text)

                            c.execute("UPDATE broadcast_queue SET status = 'sent', result = '发送成功' WHERE id = ?", (task_id,))
                            print(f"[群发队列] 已发送到 {group_name}")
                        else:
                            c.execute("UPDATE broadcast_queue SET status = 'failed', result = '私有群链接' WHERE id = ?", (task_id,))
                    else:
                        c.execute("UPDATE broadcast_queue SET status = 'failed', result = '无效链接' WHERE id = ?", (task_id,))
                except Exception as e:
                    c.execute("UPDATE broadcast_queue SET status = 'failed', result = ? WHERE id = ?", (str(e)[:200], task_id))
                    print(f"[群发队列] 发送到 {group_name} 失败: {e}")
                
                conn.commit()
                await asyncio.sleep(1)  # 每条消息间隔1秒，避免频率限制
            
            conn.close()
        except Exception as e:
            print(f"[群发队列] 处理错误: {e}")
            await asyncio.sleep(10)

async def process_broadcasts():
    """定期检查并处理待发送的群发任务（内存队列）"""
    while True:
        try:
            if pending_broadcasts:
                task = pending_broadcasts.pop(0)
                task_type = task.get('type', 'broadcast')
                
                # 处理置顶广告任务
                if task_type == 'pinned_ad':
                    content = task['content']
                    groups = task['groups']  # [(telegram_id, group_link), ...]
                    
                    print(f'开始发布置顶广告到 {len(groups)} 个群')
                    success_count = 0
                    fail_count = 0
                    
                    for telegram_id, group_link in groups:
                        try:
                            if not group_link:
                                continue
                            # 从群链接提取群ID或用户名
                            if group_link.startswith('https://t.me/'):
                                group_username = group_link.replace('https://t.me/', '')
                            elif group_link.startswith('@'):
                                group_username = group_link
                            else:
                                group_username = group_link
                            
                            # 发送广告消息
                            msg = await bot.send_message(group_username, f'📢 公告\n\n{content}')
                            
                            # 尝试置顶消息（需要管理员权限）
                            try:
                                await bot.pin_message(group_username, msg.id, notify=False)
                            except Exception as pin_err:
                                print(f'置顶失败(可能无权限): {pin_err}')
                            
                            success_count += 1
                            await asyncio.sleep(0.5)
                        except Exception as e:
                            fail_count += 1
                            print(f'发送到群组失败 {group_link}: {e}')
                    
                    print(f'置顶广告发布完成: 成功{success_count}个群，失败{fail_count}个')
                
                # 处理普通群发任务
                else:
                    log_id = task.get('log_id')
                    message_content = task.get('message_content', '')
                    group_links = task.get('group_links', [])
                    
                    print(f'开始群发到群组: {len(group_links)}个群')
                    success_count = 0
                    fail_count = 0
                    
                    for group_link in group_links:
                        try:
                            # 从群链接提取群ID或用户名
                            if group_link.startswith('https://t.me/'):
                                group_username = group_link.replace('https://t.me/', '')
                            elif group_link.startswith('@'):
                                group_username = group_link
                            else:
                                group_username = '@' + group_link
                            
                            await bot.send_message(group_username, message_content)
                            success_count += 1
                            await asyncio.sleep(0.5)
                        except Exception as e:
                            fail_count += 1
                            print(f'发送到群组失败 {group_link}: {e}')
                    
                    # 更新日志状态
                    if log_id:
                        conn = get_db_conn()
                        c = conn.cursor()
                        c.execute('''
                            UPDATE broadcast_logs 
                            SET status = 'completed', 
                                sent_count = ?, 
                                failed_count = ?
                            WHERE id = ?
                        ''', (success_count, fail_count, log_id))
                        conn.commit()
                        conn.close()
                    
                    print(f'群组群发完成: 成功发送到{success_count}个群，失败{fail_count}个')
            
            await asyncio.sleep(1)  # 每秒检查一次
        except Exception as e:
            print(f'群发任务处理异常: {e}')
            await asyncio.sleep(5)

async def check_member_status_task():
    """定期检查会员状态（核心修复：逻辑判断和通知）"""

    while True:
        try:
            global permission_check_triggered
            if permission_check_triggered:
                permission_check_triggered = False
            else:
                await asyncio.sleep(30)

            # 先执行一次全量权限检查
            await check_permission_changes()
            
            conn = get_db_conn()
            c = conn.cursor()
            c.execute("SELECT telegram_id, group_link, is_bot_admin FROM members WHERE group_link IS NOT NULL AND group_link != ''")
            members = c.fetchall()
            
            for telegram_id, group_link, db_is_bot_admin in members:
                try:
                    original_is_bot_admin = db_is_bot_admin or 0
                    
                    # 尝试从 member_groups 获取更准确的 ID
                    c.execute("SELECT group_id FROM member_groups WHERE telegram_id = ?", (telegram_id,))
                    mg_row = c.fetchone()
                    group_identifier = mg_row[0] if mg_row and mg_row[0] else None
                    
                    if not group_identifier:
                        if 't.me/' in group_link:
                            group_identifier = group_link.split('t.me/')[-1].split('/')[0].split('?')[0]
                        elif group_link.startswith('@'):
                            group_identifier = group_link[1:]
                        else: continue # 无法检测
                    
                    is_group_bound = 0
                    current_is_bot_admin = 0
                    
                    try:
                        is_in_group, admin_bot_id = await check_any_bot_in_group(clients, group_identifier)
                        if is_in_group:
                            is_group_bound = 1
                            if admin_bot_id:
                                current_is_bot_admin = 1
                    except:
                        # 检测失败保持原状，避免误报
                        current_is_bot_admin = original_is_bot_admin
                    
                    # 【核心修复】检测到权限丢失
                    if original_is_bot_admin == 1 and current_is_bot_admin == 0:
                        print(f"[权限检测] ⚠️ 会员 {telegram_id} 机器人权限丢失")
                        # 找到一个可用的 bot 发通知
                        notify_bot = clients[0] if clients else None
                        
                        # 确定用于通知的 group_id
                        notify_group_id = group_identifier
                        if isinstance(notify_group_id, str) and not notify_group_id.isdigit():
                            # 如果是用户名，尝试获取ID，或者直接传用户名给 notify 函数可能需要修改
                            # 这里为了兼容，尽量传 ID。如果只有用户名，notify_group_binding_invalid 可能会查不到 member_groups
                            # 但我们已经在 loop 开头查到了 group_id
                            pass
                        
                        await notify_group_binding_invalid(notify_group_id, telegram_id, "检测到机器人管理员权限被撤销", notify_bot)
                        
                        # 更新 member_groups
                        c.execute('UPDATE member_groups SET is_bot_admin = 0 WHERE telegram_id = ?', (telegram_id,))

                    # 更新 members 表状态
                    c.execute("UPDATE members SET is_group_bound = ?, is_bot_admin = ? WHERE telegram_id = ?", 
                             (is_group_bound, current_is_bot_admin, telegram_id))
                    
                    await asyncio.sleep(0.5)
                except Exception as e:
                    print(f"[状态检测] 单用户错误 {telegram_id}: {e}")
            
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[状态检测] 任务错误: {e}")
            await asyncio.sleep(30)

async def check_permission_changes():
    """定期检查绑定群组权限"""
    try:
        conn = get_db_conn()
        c = conn.cursor()
        c.execute("SELECT telegram_id, group_id FROM member_groups WHERE is_bot_admin = 1")
        rows = c.fetchall()
        conn.close()

        for uid, gid in rows:
            if not gid: continue
            target_bot = None
            for client in clients:
                try:
                    me = await client.get_me()
                    if me.id == uid: target_bot = client; break
                except: continue
            
            if not target_bot: continue
            
            try:
                full_chat_id = int(f"-100{gid}") if gid > 0 else gid
                perms = await target_bot.get_permissions(full_chat_id, uid)
                if not (perms.is_admin or perms.is_creator):
                    print(f"[权限检查] 机器人 {uid} 在群 {gid} 失去权限")
                    await notify_group_binding_invalid(gid, uid, "定期检查发现权限丢失", target_bot)
                    conn = get_db_conn()
                    c = conn.cursor()
                    c.execute('UPDATE member_groups SET is_bot_admin = 0 WHERE telegram_id = ? AND group_id = ?', (uid, gid))
                    c.execute('UPDATE members SET is_bot_admin = 0 WHERE telegram_id = ?', (uid,))
                    conn.commit()
                    conn.close()
            except: pass
    except Exception as e:
        print(f"[权限检查] 错误: {e}")

def run_bot():
    """Bot 启动入口"""
    print("🚀 Telegram Bots (Multi) 启动中...")

    if not clients:
        print("❌ 没有活跃的机器人客户端，跳过Bot启动")
        print("💡 请在Web后台的机器人设置中添加并启用机器人")
        return

    try:
        # 启动后台任务
        loop = asyncio.get_event_loop()
        loop.create_task(process_notify_queue())
        loop.create_task(auto_broadcast_timer())
        loop.create_task(check_member_status_task())
        loop.create_task(process_broadcast_queue())
        loop.create_task(process_broadcasts())

        async def _process_recharge_queue_worker():
            while True:
                try:
                    if process_recharge_queue:
                        item = process_recharge_queue.pop(0)
                        await process_recharge(item.get('member_id'), item.get('amount'), item.get('is_vip_order'))
                except Exception as e:
                    print(f"[充值队列] 处理失败: {e}")
                await asyncio.sleep(1)

        loop.create_task(_process_recharge_queue_worker())

        # 在机器人启动后同步会员群组数据 (延迟执行，确保连接完成)
        async def sync_after_start():
            global clients  # 声明全局变量
            try:
                # 等待一段时间，确保机器人完全连接
                await asyncio.sleep(10)
                print("🔄 同步会员群组数据...")

                # 检查机器人连接状态 (机器人API兼容的检查)
                connected_clients = []
                for i, client in enumerate(clients):
                    try:
                        # 机器人只能使用允许的API方法：get_me()
                        me = await client.get_me()
                        if me and me.id:
                            connected_clients.append(client)
                            print(f"✅ 机器人 {i+1} 连接正常 (ID: {me.id})")
                        else:
                            print(f"⚠️ 机器人 {i+1} 无法获取机器人信息")
                    except Exception as e:
                        print(f"⚠️ 机器人 {i+1} 连接异常: {e}")

                if not connected_clients:
                    print("❌ 没有可用的机器人连接，跳过同步")
                    return

                print(f"📊 共有 {len(connected_clients)} 个机器人可用于同步")

                try:
                    from database import sync_member_groups_from_members
                    # 传递已连接的客户端列表给同步函数
                    await sync_member_groups_from_members(connected_clients)
                    print("✅ 会员群组数据同步完成")
                except Exception as e:
                    print(f"⚠️ 会员群组数据同步失败: {e}")
                    import traceback
                    traceback.print_exc()

            except Exception as e:
                print(f"⚠️ 会员群组数据同步失败: {e}")
                import traceback
                traceback.print_exc()

        loop.create_task(sync_after_start())

        print("✅ 所有后台任务已挂载")
        print(f"✅ {len(clients)} 个机器人正在监听消息...")

        # 所有机器人共享同一个事件循环并发运行
        print("🔄 正在连接到Telegram服务器...")

        async def run_all_bots():
            """运行所有机器人直到断开"""
            try:
                # 客户端已经在初始化时启动了，这里只需要等待断开
                print("🔄 所有机器人正在运行，等待消息...")

                # 等待任一客户端断开
                disconnect_futures = [client.disconnected for client in clients]
                done, pending = await asyncio.wait(disconnect_futures, return_when=asyncio.FIRST_COMPLETED)

                print("🛑 一个或多个机器人已断开连接，正在停止其他机器人...")
                # 取消其他待处理的 Future
                for future in pending:
                    if not future.done():
                        future.cancel()

            except Exception as e:
                print(f"❌ 多机器人运行失败: {e}")
                import traceback
                traceback.print_exc()

        # 运行所有机器人
        try:
            loop.run_until_complete(run_all_bots())
        except KeyboardInterrupt:
            print("🛑 收到停止信号，正在关闭机器人...")
        except Exception as e:
            print(f"❌ 机器人运行失败: {e}")
            import traceback
            traceback.print_exc()

    except Exception as e:
        print(f"❌ 机器人运行过程中出现错误: {e}")
        import traceback
        traceback.print_exc()
        print("💡 机器人已停止，但Web服务可能仍在运行")

# 导出
__all__ = [
    'bot', 'clients', 'process_vip_upgrade', 'process_recharge',
    'admin_manual_vip_handler', 'get_main_account_id', 'run_bot',
    'pending_broadcasts', 'notify_queue'
    # 后台任务（供调试使用）
    'auto_broadcast_timer',
    'process_broadcast_queue',
    'process_broadcasts',
    'check_member_status_task',
    'process_notify_queue'
]

