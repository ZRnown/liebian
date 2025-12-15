import sqlite3
import asyncio
from datetime import datetime, timedelta, timezone
from telethon import TelegramClient, events
from telethon.sessions import MemorySession
from telethon.tl.types import ChannelParticipantsAdmins
from telethon.tl.custom import Button
from telethon.tl.functions.channels import GetParticipantRequest
import requests
import qrcode
import random
import threading
import time
import socks
from flask import Flask, render_template, jsonify, request, redirect, url_for
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

# 导入核心功能模块
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    DB_PATH, DATA_DIR, LOG_PATH, PID_PATH, SESSION_PATH, UPLOAD_DIR,
    API_ID, API_HASH, BOT_TOKEN, ADMIN_IDS, USE_PROXY, PROXY_TYPE, PROXY_HOST, PROXY_PORT
)
from core_functions import (
    check_user_in_group, check_bot_is_admin, get_upline_chain,
    get_downline_tree, calculate_team_stats, check_user_conditions,
    update_level_path, get_fallback_account
)

# 导入命令扩展模块
from bot_commands_addon import (
    handle_bind_group, handle_join_upline, handle_group_link_message,
    handle_check_status, handle_my_team
)

# 配置已从 config.py 导入
# API_ID, API_HASH, BOT_TOKEN, ADMIN_IDS 等配置现在从 .env 文件或环境变量读取

# 定义中国时区
CN_TIMEZONE = timezone(timedelta(hours=8))

# USDT充值配置
usdt_address = "TUnpYkxUeawyGeMD3PGzhDkdkNYhRJcLfD"  # 默认USDT地址
interval_time_in_seconds = 9  # 检查支付间隔（秒）
check_duration_seconds = 1200  # 订单有效期（秒），20分钟
payment_orders = {}  # 存储充值订单
payment_tasks = {}  # 存储支付检查任务

# 系统设置 (可通过管理后台修改)
settings = {
    'level_count': 10,      # 层数设置，默认10层
    'level_reward': 1,      # 每层奖励 (U)，默认1U
    'vip_price': 10,        # VIP价格 (U)
    'withdraw_threshold': 50,  # 提现门槛 (U)，默认50U
    'support_text': '👩‍💼 在线客服\n\n暂无客服信息，请联系管理员'  # 客服文本
}

# 生成USDT地址二维码
try:
    img = qrcode.make(usdt_address)
    img.save("usdt_qr.png")
except:
    pass

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

# 主菜单键盘
def get_fallback_resource(resource_type='group'):
    """获取捡漏账号资源"""
    try:
        import sqlite3
        conn = get_db_conn()
        c = conn.cursor()
        if resource_type == 'group':
            c.execute("SELECT group_link FROM fallback_accounts WHERE group_link IS NOT NULL AND group_link != ''")
            results = c.fetchall()
            conn.close()
            if results:
                return '\n'.join([r[0] for r in results if r[0]])
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


def get_main_keyboard(user_id=None):
    keyboard = [
        [Button.text(BTN_VIP, resize=True), Button.text(BTN_VIEW_FISSION, resize=True), Button.text(BTN_MY_PROMOTE, resize=True)],
        [Button.text(BTN_RESOURCES, resize=True), Button.text(BTN_FISSION, resize=True), Button.text(BTN_PROFILE, resize=True)],
        [Button.text(BTN_SUPPORT, resize=True)]
    ]
    # 管理员显示管理后台按钮
    if user_id and user_id in ADMIN_IDS:
        keyboard[-1].append(Button.text(BTN_ADMIN, resize=True))
    return keyboard

# 初始化数据库
def init_db():
    conn = get_db_conn()
    c = conn.cursor()
    
    # 会员表
    c.execute('''CREATE TABLE IF NOT EXISTS members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER UNIQUE,
        username TEXT,
        backup_account TEXT,
        referrer_id INTEGER,
        balance REAL DEFAULT 0,
        missed_balance REAL DEFAULT 0,
        group_link TEXT,
        is_vip INTEGER DEFAULT 0,
        register_time TEXT,
        vip_time TEXT,
        FOREIGN KEY (referrer_id) REFERENCES members(telegram_id)
    )''')
    
    # 客服表
    c.execute('''CREATE TABLE IF NOT EXISTS customer_service (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        link TEXT
    )''')
    
    # 行业资源分类表
    c.execute('''CREATE TABLE IF NOT EXISTS resource_categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        parent_id INTEGER DEFAULT 0
    )''')
    
    # 行业资源表
    c.execute('''CREATE TABLE IF NOT EXISTS resources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category_id INTEGER,
        name TEXT,
        link TEXT,
        type TEXT,
        member_count INTEGER DEFAULT 0,
        FOREIGN KEY (category_id) REFERENCES resource_categories(id)
    )''')
    
    # 提现记录表
    c.execute('''CREATE TABLE IF NOT EXISTS withdrawals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id INTEGER,
        amount REAL,
        status TEXT DEFAULT 'pending',
        create_time TEXT,
        process_time TEXT,
        FOREIGN KEY (member_id) REFERENCES members(telegram_id)
    )''')
    
    # 系统配置表
    c.execute('''CREATE TABLE IF NOT EXISTS system_config (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')

    # 管理员表
    c.execute('''CREATE TABLE IF NOT EXISTS admin_users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password_hash TEXT
    )''')
    
    # 收益记录表
    c.execute('''CREATE TABLE IF NOT EXISTS earnings_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id INTEGER,
        amount REAL,
        source_type TEXT,
        source_id INTEGER,
        description TEXT,
        create_time TEXT,
        FOREIGN KEY (member_id) REFERENCES members(telegram_id)
    )''')
    
    # 充值记录表（如果不存在）
    c.execute('''CREATE TABLE IF NOT EXISTS recharge_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id INTEGER,
        amount REAL,
        order_id TEXT,
        status TEXT,
        payment_method TEXT,
        create_time TEXT,
        FOREIGN KEY (member_id) REFERENCES members(telegram_id)
    )''')
    
    # 捡漏账号表（如果不存在）
    c.execute('''CREATE TABLE IF NOT EXISTS fallback_accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER UNIQUE,
        username TEXT,
        group_link TEXT,
        total_earned REAL DEFAULT 0,
        is_active INTEGER DEFAULT 1,
        main_account_id INTEGER
    )''')

    # 群发队列表
    c.execute('''CREATE TABLE IF NOT EXISTS broadcast_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_link TEXT,
        group_name TEXT,
        message TEXT,
        status TEXT DEFAULT 'pending',
        result TEXT,
        create_time TEXT
    )''')

    # 群发消息表
    c.execute('''CREATE TABLE IF NOT EXISTS broadcast_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        content TEXT,
        media_type TEXT,
        media_url TEXT,
        image_url TEXT,
        video_url TEXT,
        buttons TEXT,
        buttons_per_row INTEGER DEFAULT 2,
        schedule_enabled INTEGER DEFAULT 0,
        schedule_time TEXT,
        is_active INTEGER DEFAULT 1,
        create_time TEXT
    )''')

    # 会员群组表
    c.execute('''CREATE TABLE IF NOT EXISTS member_groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER,
        group_id INTEGER,
        group_name TEXT,
        group_link TEXT,
        member_count INTEGER DEFAULT 0,
        bot_id INTEGER,
        is_bot_admin INTEGER DEFAULT 0,
        owner_username TEXT,
        group_type TEXT DEFAULT 'group',
        schedule_broadcast INTEGER DEFAULT 1,
        create_time TEXT,
        FOREIGN KEY (telegram_id) REFERENCES members(telegram_id)
    )''')

    # 检查是否有管理员，如果没有则创建默认管理员
    c.execute('SELECT COUNT(*) FROM admin_users')
    if c.fetchone()[0] == 0:
        from werkzeug.security import generate_password_hash
        default_password_hash = generate_password_hash('admin')
        c.execute('INSERT INTO admin_users (username, password_hash) VALUES (?, ?)', ('admin', default_password_hash))
        print('⚠️ 创建默认管理员账号: admin / admin')
    
    conn.commit()
    
    # 从数据库加载配置
    c.execute('SELECT key, value FROM system_config')
    config_rows = c.fetchall()
    for key, value in config_rows:
        if key == 'usdt_address':
            global usdt_address
            usdt_address = value
        elif key in ['levels', 'reward_per_level', 'vip_price', 'withdraw_threshold']:
            try:
                settings[key] = float(value) if '.' in str(value) else int(value)
            except (ValueError, TypeError):
                pass  # 保持默认值
        elif key == 'service_text':
            settings[key] = value
    
    conn.close()

# 动态获取系统配置
def get_system_config():
    """从数据库动态读取系统配置"""
    conn = get_db_conn()
    c = conn.cursor()
    c.execute('SELECT key, value FROM system_config')
    config_rows = c.fetchall()
    
    config = {
        'level_count': 10,
        'level_reward': 1,
        'vip_price': 10,
        'withdraw_threshold': 50,
        'support_text': '👩‍💼 在线客服\n\n暂无客服信息，请联系管理员',
        'usdt_address': usdt_address,
        'pinned_ad': '',
        'welcome_message': '',
        'welcome_enabled': '1',
        'auto_register_enabled': '0'
    }
    
    key_mapping = {
        'levels': 'level_count',
        'reward_per_level': 'level_reward',
        'vip_price': 'vip_price',
        'withdraw_threshold': 'withdraw_threshold',
        'service_text': 'support_text',
        'usdt_address': 'usdt_address',
        'pinned_ad': 'pinned_ad',
        'welcome_message': 'welcome_message',
        'welcome_enabled': 'welcome_enabled',
        'auto_register_enabled': 'auto_register_enabled'
    }
    
    for key, value in config_rows:
        if key in key_mapping:
            config_key = key_mapping[key]
            if key in ['levels', 'reward_per_level', 'vip_price', 'withdraw_threshold']:
                config[config_key] = float(value) if '.' in str(value) else int(value)
            else:
                config[config_key] = value
    
    conn.close()
    return config

def update_system_config(key, value):
    """更新系统配置到数据库"""
    # 键名映射 - 将内部键名映射到数据库键名
    reverse_key_mapping = {
        'level_count': 'levels',
        'level_reward': 'reward_per_level',
        'vip_price': 'vip_price',
        'withdraw_threshold': 'withdraw_threshold',
        'support_text': 'service_text',
        'usdt_address': 'usdt_address'
    }
    
    db_key = reverse_key_mapping.get(key, key)
    
    conn = get_db_conn()
    c = conn.cursor()
    
    # 插入或更新配置
    c.execute('''
        INSERT INTO system_config (key, value) 
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
    ''', (db_key, str(value)))
    
    conn.commit()
    conn.close()

# 数据库连接辅助函数
def get_db_conn():
    """获取数据库连接，设置超时和 WAL 模式以避免锁定"""
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    # 启用 WAL 模式，提高并发性能
    conn.execute('PRAGMA journal_mode=WAL')
    # 设置忙等待超时（10秒）
    conn.execute('PRAGMA busy_timeout=10000')
    return conn

# 数据库操作类
class DB:
    @staticmethod
    def get_conn():
        """获取数据库连接，设置超时和 WAL 模式以避免锁定"""
        return get_db_conn()
    
    @staticmethod
    def get_member(telegram_id):
        conn = DB.get_conn()
        c = conn.cursor()
        c.execute('''
            SELECT 
                id, telegram_id, username, backup_account, referrer_id,
                balance, missed_balance, group_link, is_vip, register_time, vip_time,
                is_group_bound, is_bot_admin, is_joined_upline, level_path,
                direct_count, team_count, total_earned, withdraw_address
            FROM members WHERE telegram_id = ?
        ''', (telegram_id,))
        row = c.fetchone()
        conn.close()
        if row:
            return {
                'id': row[0], 'telegram_id': row[1], 'username': row[2],
                'backup_account': row[3], 'referrer_id': row[4], 'balance': row[5],
                'missed_balance': row[6], 'group_link': row[7], 'is_vip': row[8],
                'register_time': row[9], 'vip_time': row[10],
                'is_group_bound': row[11], 'is_bot_admin': row[12],
                'is_joined_upline': row[13], 'level_path': row[14],
                'direct_count': row[15], 'team_count': row[16],
                'total_earned': row[17], 'withdraw_address': row[18]
            }
        return None
    
    @staticmethod
    def create_member(telegram_id, username, referrer_id=None):
        conn = DB.get_conn()
        c = conn.cursor()
        try:
            c.execute('''INSERT INTO members (telegram_id, username, referrer_id, register_time)
                        VALUES (?, ?, ?, ?)''',
                     (telegram_id, username, referrer_id, datetime.now().isoformat()))
            conn.commit()
        except sqlite3.IntegrityError:
            pass
        except sqlite3.OperationalError as e:
            # 如果数据库被锁定，等待后重试
            if 'locked' in str(e).lower():
                import time
                time.sleep(0.1)
                try:
                    c.execute('''INSERT INTO members (telegram_id, username, referrer_id, register_time)
                                VALUES (?, ?, ?, ?)''',
                             (telegram_id, username, referrer_id, datetime.now().isoformat()))
                    conn.commit()
                except:
                    pass
        finally:
            conn.close()
    
    @staticmethod
    def update_member(telegram_id, **kwargs):
        conn = DB.get_conn()
        c = conn.cursor()
        sets = ', '.join([f'{k} = ?' for k in kwargs.keys()])
        values = list(kwargs.values()) + [telegram_id]
        c.execute(f'UPDATE members SET {sets} WHERE telegram_id = ?', values)
        conn.commit()
        conn.close()
    
    @staticmethod
    def get_upline_members(telegram_id, levels=10):
        """获取上N层推荐人"""
        members = []
        conn = DB.get_conn()
        c = conn.cursor()
        current_id = telegram_id
        
        for _ in range(levels):
            c.execute('SELECT referrer_id FROM members WHERE telegram_id = ?', (current_id,))
            row = c.fetchone()
            if row and row[0]:
                c.execute('SELECT * FROM members WHERE telegram_id = ?', (row[0],))
                member_row = c.fetchone()
                if member_row:
                    members.append({
                        'telegram_id': member_row[1],
                        'username': member_row[2],
                        'is_vip': member_row[8],
                        'balance': member_row[5]
                    })
                    current_id = row[0]
                else:
                    break
            else:
                break
        conn.close()
        return members
    
    @staticmethod
    def get_downline_count(telegram_id, level=1):
        """获取下N层会员数量"""
        conn = DB.get_conn()
        c = conn.cursor()
        
        current_level_ids = [telegram_id]
        counts = []
        
        for _ in range(level):
            if not current_level_ids:
                counts.append({'total': 0, 'vip': 0})
                continue
            placeholders = ','.join(['?' for _ in current_level_ids])
            c.execute(f'SELECT telegram_id, is_vip FROM members WHERE referrer_id IN ({placeholders})', 
                     current_level_ids)
            rows = c.fetchall()
            counts.append({'total': len(rows), 'vip': sum(1 for r in rows if r[1])})
            current_level_ids = [r[0] for r in rows]
        
        conn.close()
        return counts

    @staticmethod
    def get_customer_services():
        conn = DB.get_conn()
        c = conn.cursor()
        c.execute('SELECT * FROM customer_service')
        rows = c.fetchall()
        conn.close()
        return [{'id': r[0], 'name': r[1], 'link': r[2]} for r in rows]
    
    @staticmethod
    def get_resource_categories(parent_id=0):
        conn = DB.get_conn()
        c = conn.cursor()
        c.execute('SELECT * FROM resource_categories WHERE parent_id = ?', (parent_id,))
        rows = c.fetchall()
        conn.close()
        return [{'id': r[0], 'name': r[1]} for r in rows]
    
    @staticmethod
    def get_resources(category_id, page=1, per_page=20):
        conn = DB.get_conn()
        c = conn.cursor()
        offset = (page - 1) * per_page
        c.execute('SELECT * FROM resources WHERE category_id = ? LIMIT ? OFFSET ?', 
                 (category_id, per_page, offset))
        rows = c.fetchall()
        c.execute('SELECT COUNT(*) FROM resources WHERE category_id = ?', (category_id,))
        total = c.fetchone()[0]
        conn.close()
        return {
            'items': [{'id': r[0], 'name': r[2], 'link': r[3], 'type': r[4], 'count': r[5]} for r in rows],
            'total': total,
            'pages': (total + per_page - 1) // per_page
        }


# 代理配置 - 从配置文件读取
if USE_PROXY:
    if PROXY_TYPE.lower() == 'socks5':
        proxy = (socks.SOCKS5, PROXY_HOST, PROXY_PORT)
    elif PROXY_TYPE.lower() == 'socks4':
        proxy = (socks.SOCKS4, PROXY_HOST, PROXY_PORT)
    elif PROXY_TYPE.lower() == 'http':
        proxy = (socks.HTTP, PROXY_HOST, PROXY_PORT)
    else:
        proxy = (socks.SOCKS5, PROXY_HOST, PROXY_PORT)
    bot = TelegramClient('bot', API_ID, API_HASH, proxy=proxy).start(bot_token=BOT_TOKEN)
else:
    bot = TelegramClient(MemorySession(), API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# 全局变量
pending_broadcasts = []  # 待发送的群发任务队列

# 等待输入状态
waiting_for_group_link = {}
waiting_for_backup = {}
waiting_for_recharge_amount = {}
waiting_for_withdraw_amount = {}
waiting_for_withdraw_address = {}
withdraw_temp_data = {}

# 通知消息队列
notify_queue = []

# 验证群链接功能
async def verify_group_link(link):
    """验证群链接，检查机器人是否在群内且为管理员"""
    try:
        # 提取群用户名
        username = None
        if link.startswith('https://t.me/'):
            username = link.replace('https://t.me/', '').split('?')[0]
        elif link.startswith('t.me/'):
            username = link.replace('t.me/', '').split('?')[0]
        elif link.startswith('@'):
            username = link[1:]
        else:
            return {'success': False, 'message': '链接格式不正确'}
        
        # 移除可能的+号（私有群）
        username = username.replace('+', '')
        
        try:
            # 尝试获取实体
            entity = await bot.get_entity(username)
            
            # 检查是否是群组或超级群
            if not hasattr(entity, 'broadcast') or entity.broadcast:
                return {'success': False, 'message': '这不是一个群组链接'}
            
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
                    return {'success': False, 'message': '机器人不是群管理员'}
                
                return {'success': True, 'message': '验证成功'}
                
            except Exception as e:
                print(f'获取权限失败: {e}')
                return {'success': False, 'message': '机器人不在该群内或无法获取权限'}
                
        except Exception as e:
            print(f'获取实体失败: {e}')
            return {'success': False, 'message': '无法访问该群，可能是私有群或链接无效'}
            
    except Exception as e:
        print(f'验证群链接失败: {e}')
        return {'success': False, 'message': f'验证失败: {str(e)}'}

# ============ USDT充值功能 ============

# 查询USDT TRC20交易

def get_main_account_id(telegram_id, username=None):
    """
    核心逻辑：
    检查当前用户(telegram_id 或 username)是否被设置为其他人的备用号(backup_account)。
    如果是，返回主号的ID；如果不是，返回自己的ID。
    """
    try:
        conn = DB.get_conn()
        c = conn.cursor()
        
        # 准备查询参数
        tid_str = str(telegram_id)
        # 去掉 @ 符号的用户名
        clean_username = username.lstrip('@') if username else ""
        
        # 构建查询条件：
        # 1. 备用号填的是 ID
        # 2. 备用号填的是 用户名 (不带@)
        # 3. 备用号填的是 @用户名
        sql = '''
            SELECT telegram_id 
            FROM members 
            WHERE 
                backup_account = ? 
                OR backup_account = ? 
                OR backup_account = ?
                OR backup_account = ?
            LIMIT 1
        '''
        
        params = [
            tid_str,                # 匹配 ID
            clean_username,         # 匹配 Thy1cc
            f"@{clean_username}",   # 匹配 @Thy1cc
            username                # 匹配 原始username
        ]
        
        c.execute(sql, params)
        result = c.fetchone()
        
        conn.close()
        
        if result:
            # 找到了！当前用户是 result[0] 的备用号
            main_id = result[0]
            print(f"[账号映射] 检测到备用号登录: {username}({telegram_id}) -> 映射为主号: {main_id}")
            return main_id
            
        # 没找到，说明不是备用号，或者是主号自己
        return telegram_id
        
    except Exception as e:
        print(f"[账号映射] 错误: {e}")
        return telegram_id

def link_account(main_id, backup_id, backup_username):
    """关联备用号到主账号（支持用户名存储，避免自绑，并增加锁重试）"""
    normalized_username = (backup_username or '').lstrip('@')
    # 优先存用户名，便于后台展示；没有用户名则存ID
    value_to_store = f'@{normalized_username}' if normalized_username else str(backup_id)
    
    # 禁止将自己设置为备用号
    if str(main_id) == str(backup_id) or value_to_store == str(main_id):
        return False, "❌ 不能将自己设置为备用号，请换一个账号"
    
    max_retries = 3
    for retry in range(max_retries):
        conn = DB.get_conn()
        c = conn.cursor()
        try:
            # 更新members表的backup_account字段
            c.execute('UPDATE members SET backup_account = ? WHERE telegram_id = ?', (value_to_store, main_id))
            conn.commit()
            return True, f"✅ 备用账号关联成功：{value_to_store}"
        except Exception as e:
            conn.rollback()
            # 针对数据库锁重试
            if 'locked' in str(e).lower() and retry < max_retries - 1:
                time.sleep(0.3)
                continue
            return False, f"关联失败: {str(e)}"
        finally:
            try:
                conn.close()
            except:
                pass

def check_usdt_transaction(usdt_address):
    """查询USDT TRC20地址的交易记录"""
    try:
        api_url = f"https://api.trongrid.io/v1/accounts/{usdt_address}/transactions/trc20?limit=200&contract_address=TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
        response = requests.get(api_url, timeout=10)
        if response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        print(f"查询USDT交易失败: {e}")
        return None

# 充值到账处理
async def process_recharge(telegram_id, amount, is_vip_order=False):
    """处理充值到账"""
    try:
        # 获取最新配置
        config = get_system_config()
        
        # 更新用户余额
        member = DB.get_member(telegram_id)
        if member:
            new_balance = member['balance'] + amount
            DB.update_member(telegram_id, balance=new_balance)
            
            # 如果是VIP充值订单且余额足够，自动开通VIP
            if is_vip_order and new_balance >= config['vip_price'] and not member['is_vip']:
                # 扣除VIP费用
                new_balance = new_balance - config['vip_price']
                DB.update_member(telegram_id, balance=new_balance, is_vip=1, vip_time=datetime.now().isoformat())
                
                # 更新层级路径
                update_level_path(telegram_id)
                
                # 获取上级链（包含捡漏账号补足）
                max_level = int(config['level_count'])
                upline_chain = get_upline_chain(telegram_id, max_level)
                
                rewarded_count = 0
                fallback_count = 0
                
                # 逐层检查并分配分红
                for level, upline_id in upline_chain:
                    up_member = DB.get_member(upline_id)
                    if not up_member:
                        continue
                    
                    # 检查上级是否满足所有条件
                    conditions = await check_user_conditions(bot, upline_id)
                    
                    if conditions and conditions['all_conditions_met'] and up_member['is_vip']:
                        # 上级满足所有条件，正常发放分红
                        up_new_balance = up_member['balance'] + config['level_reward']
                        total_earned = up_member.get('total_earned', 0) + config['level_reward']
                        DB.update_member(upline_id, balance=up_new_balance, total_earned=total_earned)
                        rewarded_count += 1
                        
                        # 记录收益
                        conn = DB.get_conn()
                        c = conn.cursor()
                        c.execute('''INSERT INTO earnings_records 
                                   (member_id, amount, source_type, source_id, description, create_time)
                                   VALUES (?, ?, ?, ?, ?, ?)''',
                                (upline_id, config['level_reward'], 'vip_commission', telegram_id,
                                 f'第{level}层下级开通VIP', datetime.now().isoformat()))
                        conn.commit()
                        conn.close()
                        
                        try:
                            await bot.send_message(upline_id,
                                f'🎉 恭喜！您获得了 {config["level_reward"]} U 分红！\n\n'
                                f'来自第 {level} 层下级开通VIP\n'
                                f'下级用户: @{member["username"]}\n'
                                f'当前余额: {up_new_balance} U\n'
                                f'累计获得: {total_earned} U')
                        except:
                            pass
                    else:
                        # 上级未满足条件，分红转入捡漏账号
                        fallback_id = get_fallback_account(level)
                        if fallback_id:
                            fb_member = DB.get_member(fallback_id)
                            if fb_member:
                                fb_new_balance = fb_member['balance'] + config['level_reward']
                                fb_total_earned = fb_member.get('total_earned', 0) + config['level_reward']
                                DB.update_member(fallback_id, balance=fb_new_balance, total_earned=fb_total_earned)
                                fallback_count += 1
                        
                        # 记录错过的金额（如果上级是VIP但未完成其他条件）
                        if up_member['is_vip'] and conditions:
                            new_missed = up_member['missed_balance'] + config['level_reward']
                            DB.update_member(upline_id, missed_balance=new_missed)
                            
                            missing_tips = '\n'.join([f'❌ {c}' for c in conditions['missing_conditions']])
                            try:
                                await bot.send_message(upline_id,
                                    f'⚠️ 您错过了 {config["level_reward"]} U 分红！\n\n'
                                    f'原因：未完成以下条件\n{missing_tips}\n\n'
                                    f'来自第 {level} 层下级开通VIP\n'
                                    f'累计错过: {new_missed} U\n\n'
                                    f'💡 完成所有条件后即可获得分红')
                            except:
                                pass
                
                # 获取上层群列表（需要加入的群）
                upline_groups = []
                for level, upline_id in upline_chain:
                    up_member = DB.get_member(upline_id)
                    if up_member and up_member['group_link']:
                        upline_groups.append({
                            'level': level,
                            'username': up_member['username'],
                            'group_link': up_member['group_link']
                        })
                
                # 发送VIP开通成功通知
                group_list_text = '\n'.join([f'  {g["level"]}. @{g["username"]}的群' for g in upline_groups[:5]])
                await bot.send_message(
                    telegram_id,
                    f'🎉 充值成功！VIP已开通！\n\n'
                    f'💰 充值金额: {amount} U\n'
                    f'💳 VIP费用: {config["vip_price"]} U\n'
                    f'💵 当前余额: {new_balance} U\n\n'
                    f'✅ 已为 {rewarded_count} 位上级发放分红\n'
                    f'📊 捡漏账号获得 {fallback_count} 笔分红\n\n'
                    f'⚠️ 重要：请立即完成以下操作\n\n'
                    f'1️⃣ 绑定您的群组\n'
                    f'   - 将机器人拉入您的群\n'
                    f'   - 设置机器人为管理员\n'
                    f'   - 发送群链接进行绑定\n\n'
                    f'2️⃣ 加入上层群组（共{len(upline_groups)}个）\n'
                    f'{group_list_text}\n\n'
                    f'💡 完成以上操作后，您的下级开通VIP时\n'
                    f'   您才能获得分红！',
                    parse_mode='markdown'
                )
            else:
                # 普通充值通知
                await bot.send_message(
                    telegram_id,
                    f'🎉 充值成功!\n\n'
                    f'充值金额: {amount} U\n'
                    f'当前余额: {new_balance} U\n\n'
                    f'感谢您的支持!',
                    parse_mode='markdown'
                )
            return True
    except Exception as e:
        print(f"处理充值失败: {e}")
    return False

# 检查支付任务
async def check_payment_task(order):
    """持续检查订单支付状态"""
    print(f"开始检查订单 {order['order_number']} 的支付状态")
    
    while True:
        try:
            print(f"正在检查订单 {order['order_number']} - 金额: {order['amount']} U")
            
            # 查询交易记录
            transaction_data = check_usdt_transaction(order['usdt_address'])
            
            if transaction_data and 'data' in transaction_data:
                current_time = datetime.now(CN_TIMEZONE)
                
                for transaction in transaction_data['data']:
                    # 获取交易时间
                    transaction_time = datetime.fromtimestamp(
                        transaction['block_timestamp'] / 2000,
                        tz=CN_TIMEZONE
                    )
                    
                    # 检查交易是否在订单创建后且在有效期内
                    if transaction_time > order['created_at'] and transaction_time < (order['created_at'] + timedelta(seconds=check_duration_seconds)):
                        # 获取交易金额（USDT的精度是6位小数）
                        amount = float(transaction['value']) / 2000000
                        
                        print(f"发现交易 - 金额: {amount} U, 订单金额: {order['amount']} U")
                        
                        # 检查金额是否匹配
                        if abs(float(order['amount']) - amount) < 0.01:  # 允许0.01的误差
                            print(f"订单 {order['order_number']} 支付成功！")
                            
                            # 处理充值（判断是否为VIP订单）
                            is_vip_order = order.get('is_vip_order', False)
                            await process_recharge(order['telegram_id'], amount, is_vip_order)
                            
                            # 清理订单和任务
                            order_number = order['order_number']
                            if order_number in payment_tasks:
                                _, timeout_task = payment_tasks[order_number]
                                timeout_task.cancel()
                                del payment_tasks[order_number]
                            
                            if order_number in payment_orders:
                                del payment_orders[order_number]
                            
                            return
            
            print(f"未发现订单 {order['order_number']} 的支付，{interval_time_in_seconds}秒后重试")
            await asyncio.sleep(interval_time_in_seconds)
            
        except Exception as e:
            print(f"检查支付异常: {e}")
            await asyncio.sleep(interval_time_in_seconds)

# 订单超时处理
async def payment_timeout_handler(order):
    """处理订单超时"""
    await asyncio.sleep(check_duration_seconds)
    
    order_number = order['order_number']
    
    if order_number in payment_orders:
        # 取消支付检查任务
        if order_number in payment_tasks:
            payment_task, _ = payment_tasks[order_number]
            payment_task.cancel()
            del payment_tasks[order_number]
        
        # 删除订单
        del payment_orders[order_number]
        
        # 通知用户订单超时
        try:
            await bot.send_message(
                order['telegram_id'],
                f'⏰ 订单超时\n\n订单号: {order_number}\n金额: {order["amount"]} U\n\n请重新创建充值订单'
            )
        except:
            pass

# 创建充值订单

async def create_recharge_order(event, amount, is_vip_order=False):
    telegram_id = event.sender_id
    order_number = f"RCH_{telegram_id}_{int(time.time())}"
    payment_result = create_payment_order(amount, order_number, f"TG{telegram_id}")
    if not payment_result or payment_result.get("code") != 200:
        await event.respond("创建支付订单失败，请稍后重试")
        return
    
    # 保存充值记录到数据库
    conn = DB.get_conn()
    c = conn.cursor()
    c.execute('''INSERT INTO recharge_records 
                 (member_id, amount, order_id, status, payment_method, create_time) 
                 VALUES (?, ?, ?, ?, ?, ?)''',
              (telegram_id, amount, order_number, 'pending', 'USDT', datetime.now().isoformat()))
    conn.commit()
    conn.close()
    
    # 获取USDT收款地址
    conn2 = DB.get_conn()
    c2 = conn2.cursor()
    c2.execute("SELECT value FROM system_config WHERE key = 'usdt_address'")
    usdt_row = c2.fetchone()
    usdt_address = usdt_row[0] if usdt_row else "未设置"
    conn2.close()
    
    # 显示充值信息
    msg = f'''此订单10分钟内有效，过期后请重新生成订单。
➖➖➖➖➖➖➖➖➖➖
订单号: {order_number}
转账地址: 
`{usdt_address}`
(TRC-20网络)
转账金额: {amount:.2f} USDT
➖➖➖➖➖➖➖➖➖➖
⚠️ 请注意转账金额务必与上方的转账金额一致，否则无法自动到账
✅ 支付完成后，请等待1分钟左右查询，自动到账。'''
    
    buttons = [[Button.inline("返回", b"back")]]
    await event.respond(msg, buttons=buttons)

@bot.on(events.ChatAction)
async def group_welcome_handler(event):
    """新成员加入群时发送欢迎语，并自动注册为邀请者下级"""
    try:
        # 打印所有事件信息用于调试
        print(f'[ChatAction] 收到事件: {type(event.action_message.action).__name__ if event.action_message else "无"}')
        
        # 检查是否是用户加入事件
        if event.user_joined or event.user_added:
            # 获取系统配置
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
            print(f'[群事件] 群ID={chat_id}, 新用户={new_user_id}({new_username}), user_joined={event.user_joined}, user_added={event.user_added}')
            
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
                        elif hasattr(action, 'users') and action.users:
                            # ChatParticipantAdd 事件
                            pass
                    
                    # 方式3: 从消息发送者获取（拉人的人是消息发送者）
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
                    
                    # 确保 added_by 是整数ID而不是对象
                    if added_by and not isinstance(added_by, int):
                        if hasattr(added_by, 'id'):
                            added_by = added_by.id
                        elif hasattr(added_by, 'user_id'):
                            added_by = added_by.user_id
                        print(f'[自动注册] 转换后邀请者ID: {added_by}')
                    
                    # 方式4: 如果是通过群链接加入，尝试找群主
                    if not added_by and chat_id:
                        # 查找这个群属于哪个会员
                        conn = DB.get_conn()
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
                            # 检查新用户是否已注册
                            existing = DB.get_member(new_user_id)
                            print(f'[自动注册] 新用户已注册: {existing is not None}')
                            if not existing:
                                # 注册新用户为邀请者的下级
                                DB.create_member(new_user_id, new_username, added_by)
                                print(f'✅ 自动注册成功: {new_username} 成为 {inviter["username"]} 的下级')
                                
                                # 通知邀请者
                                try:
                                    await bot.send_message(added_by, 
                                        f'🎉 新成员加入!\n'
                                        f'用户: [{user_name}](tg://user?id={new_user_id})\n'
                                        f'已自动注册为您的下级',
                                        parse_mode='markdown')
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
    except Exception as e:
        print(f'群事件处理失败: {e}')

# /start 命令处理
@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    # 账号关联处理
    try:
        original_sender_id = event.sender_id
        event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
    except: pass
    telegram_id = event.sender_id
    username = event.sender.username or f'user_{telegram_id}'
    
    # 调试：打印用户ID
    print(f'用户ID: {telegram_id}, 是否管理员: {telegram_id in ADMIN_IDS}')
    
    # 解析推荐人ID
    referrer_id = None
    if event.message.text and len(event.message.text.split()) > 1:
        try:
            referrer_id = int(event.message.text.split()[1])
        except:
            pass
    
    # 创建或获取会员
    member = DB.get_member(telegram_id)
    if not member:
        DB.create_member(telegram_id, username, referrer_id)
        member = DB.get_member(telegram_id)
        
        # 通知推荐人
        if referrer_id:
            referrer = DB.get_member(referrer_id)
            if referrer:
                try:
                    # 获取用户完整昵称
                    user_full_name = event.sender.first_name or ''
                    if event.sender.last_name:
                        user_full_name += f' {event.sender.last_name}'
                    user_full_name = user_full_name.strip() or f'user_{telegram_id}'
                    
                    await bot.send_message(referrer_id, 
                        f'🎉 新成员加入!\n用户: [{user_full_name}](tg://user?id={telegram_id})\n通过您的推广链接加入了机器人',
                        parse_mode='markdown')
                except:
                    pass
    
    # 获取系统配置
    sys_config = get_system_config()
    pinned_ad = sys_config.get('pinned_ad', '')
    
    welcome_text = (
        f'👋 欢迎使用裂变推广机器人!\n\n'
        f'👤 用户: @{username}\n'
        f'💎 VIP状态: {"✅ 已开通" if member["is_vip"] else "❌ 未开通"}\n'
        f'💰 余额: {member["balance"]} U\n\n'
        f'请选择功能:'
    )
    
    # 如果有置顶广告，附加在消息末尾
    if pinned_ad:
        welcome_text += f'\n\n━━━━━━━━━━━━━━━\n📢 {pinned_ad}'
    
    await event.respond(welcome_text, buttons=get_main_keyboard(telegram_id))


# 个人中心
@bot.on(events.NewMessage(pattern=BTN_PROFILE))
async def profile_handler(event):
    # 账号关联处理
    try:
        original_sender_id = event.sender_id
        event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
    except: pass
    member = DB.get_member(event.sender_id)
    if not member:
        await event.respond('请先发送 /start 注册')
        return
    
    buttons = [
        [Button.inline('🔗 设置群链接', b'set_group'), Button.inline('✏️ 设置备用号', b'set_backup')],
        [Button.inline('💳 提现', b'withdraw'), Button.inline('💰 充值', b'do_recharge'), Button.inline('💎 开通VIP', b'open_vip')],
        [Button.inline('📊 收益记录', b'earnings_history')],
    ]
    
    await event.respond(
        f'👤 个人中心\n\n'
        f'🆔 ID: {member["telegram_id"]}\n'
        f'👤 用户名: @{member["username"]}\n'
        f'💎 VIP状态: {"✅ 已开通" if member["is_vip"] else "❌ 未开通"}\n'
        f'💰 余额: {member["balance"]} U\n'
        f'📉 错过余额: {member["missed_balance"]} U\n'
        f'🔗 群链接: {member["group_link"] or "未设置"}\n'
        f'📱 备用号: {member["backup_account"] or "未设置"}\n'
        f'📅 注册时间: {member["register_time"][:10] if member["register_time"] else "未知"}',
        buttons=buttons
    )

# 查看裂变
# 我的裂变数据
@bot.on(events.NewMessage(pattern=BTN_VIEW_FISSION))
async def view_fission_handler(event):
    # 账号关联处理
    try:
        original_sender_id = event.sender_id
        event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
    except: pass
    config = get_system_config()
    member = DB.get_member(event.sender_id)
    if not member:
        await event.respond('请先发送 /start 注册')
        return

    if not member['is_vip']:
        text = '❌ 您还未开通VIP\n\n'
        text += f'开通VIP后可获得以下权益:\n'
        text += f'✅ 查看裂变数据\n'
        text += f'✅ 获得下级开通VIP的奖励\n'
        text += f'✅ 加入上级群组\n\n'
        text += f'💰 VIP价格: {config["vip_price"]} U'
        # 添加捡漏群
        _fb_group = get_fallback_resource("group")
        if _fb_group:
            text += f"\n\n💡 推荐群组:\n{_fb_group}"
        await event.respond(text)
        return

    conn = DB.get_conn()
    c = conn.cursor()

    text = '📊 我的裂变数据\n'
    text += '━━━━━━━━━━━━━━\n\n'

    total_members = 0
    total_vip = 0
    buttons = []

    for level in range(1, config['level_count'] + 1):
        # 查询第N层：直接下级的level是1，下级的下级是2，以此类推
        if level == 1:
            # 第1层：直接下级
            c.execute("""
                SELECT COUNT(*), SUM(CASE WHEN is_vip = 1 THEN 1 ELSE 0 END)
                FROM members WHERE referrer_id = ?
            """, (member['telegram_id'],))
        else:
            # 第N层：通过level_path查询
            c.execute("""
                SELECT COUNT(*), SUM(CASE WHEN is_vip = 1 THEN 1 ELSE 0 END)
                FROM members
                WHERE level_path LIKE ?
            """, (f'%,{member["id"]},%',))

        result = c.fetchone()
        level_total = result[0] if result[0] else 0
        level_vip = result[1] if result[1] else 0

        total_members += level_total
        total_vip += level_vip

        # 每层一行一个按钮
        btn_text = f'第{level}层: {level_total}人'
        buttons.append([Button.inline(btn_text, f'flv_{level}_1'.encode())])

    conn.close()

    text += f'━━━━━━━━━━━━━━\n'
    text += f'📈 团队总计：{total_members}人\n'
    text += f'💎 VIP会员：{total_vip}人\n'

    buttons.append([Button.inline('🏠 主菜单', b'fission_main_menu')])

    await event.respond(text, buttons=buttons)

# 查看某层成员列表
@bot.on(events.CallbackQuery(pattern=b'flv_(\\d+)_(\\d+)'))
async def view_level_members(event):
    import re
    match = re.match(b'flv_(\\d+)_(\\d+)', event.data)
    if not match:
        return
    level = int(match.group(1))
    page = int(match.group(2))
    per_page = 15

    member = DB.get_member(event.sender_id)
    if not member or not member['is_vip']:
        await event.answer('请先开通VIP', alert=True)
        return

    conn = DB.get_conn()
    c = conn.cursor()

    if level == 1:
        c.execute("SELECT COUNT(*) FROM members WHERE referrer_id = ?", (member['telegram_id'],))
    else:
        c.execute("SELECT COUNT(*) FROM members WHERE level_path LIKE ?", (f'%,{member["id"]},%',))
    total = c.fetchone()[0]

    if total == 0:
        await event.answer(f'第{level}层暂无成员', alert=True)
        return

    offset = (page - 1) * per_page
    if level == 1:
        c.execute("""
            SELECT telegram_id, username, is_vip
            FROM members WHERE referrer_id = ?
            ORDER BY is_vip DESC, id ASC
            LIMIT ? OFFSET ?
        """, (member['telegram_id'], per_page, offset))
    else:
        c.execute("""
            SELECT telegram_id, username, is_vip
            FROM members WHERE level_path LIKE ?
            ORDER BY is_vip DESC, id ASC
            LIMIT ? OFFSET ?
        """, (f'%,{member["id"]},%', per_page, offset))

    members_list = c.fetchall()
    conn.close()

    total_pages = (total + per_page - 1) // per_page

    level_names = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十']
    level_name = level_names[level-1] if level <= 10 else str(level)
    
    text = f'👥 {level_name}级好友\n\n'

    for i, m in enumerate(members_list, 1 + offset):
        tg_id = m[0]
        username = m[1] or f'用户{tg_id}'
        # 转义markdown特殊字符
        safe_username = username.replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').replace(']', '\\]').replace('`', '\\`')
        is_vip = m[2]
        vip_text = 'VIP' if is_vip else ''
        
        text += f'{i} [👤{safe_username}](tg://user?id={tg_id})    {vip_text}\n'

    buttons = []
    nav_row = []
    if page > 1:
        nav_row.append(Button.inline('⬅️ 上页', f'flv_{level}_{page-1}'.encode()))
    if page < total_pages:
        nav_row.append(Button.inline('下页 ➡️', f'flv_{level}_{page+1}'.encode()))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([Button.inline('🏠 主菜单', b'fission_main_menu')])

    try:
        await event.edit(text, buttons=buttons, parse_mode='md')
    except:
        await event.respond(text, buttons=buttons, parse_mode='md')
    await event.answer()

# 返回裂变主菜单
@bot.on(events.CallbackQuery(pattern=b'fission_main_menu'))
async def fission_main_menu(event):
    await event.delete()
    await event.answer()

# 查看层级详情回调
@bot.on(events.CallbackQuery(pattern=b'view_level_(\d+)'))
async def view_level_detail_callback(event):
    level = int(event.data.decode().split('_')[-1])
    config = get_system_config()
    member = DB.get_member(event.sender_id)
    
    if not member or not member['is_vip']:
        await event.answer('请先开通VIP', alert=True)
        return
    
    # 获取该层所有成员（分页，每页20人）
    page = 1  # 默认第一页
    per_page = 20
    
    conn = DB.get_conn()
    c = conn.cursor()
    
    # 查询总数
    c.execute('''
        SELECT COUNT(*) FROM members
        WHERE level_path LIKE ?
    ''', (f'%,{member["id"]},%',))
    total = c.fetchone()[0]
    
    # 查询该页数据
    offset = (page - 1) * per_page
    c.execute('''
        SELECT telegram_id, username, is_vip, balance, register_time
        FROM members
        WHERE level_path LIKE ?
        ORDER BY is_vip DESC, register_time DESC
        LIMIT ? OFFSET ?
    ''', (f'%,{member["id"]},%', per_page, offset))
    
    members = c.fetchall()
    conn.close()
    
    if not members:
        await event.answer(f'第{level}层暂无成员', alert=True)
        return
    
    text = f'📋 第{level}层成员详情\n'
    text += f'━━━━━━━━━━━━━━\n\n'
    text += f'共{total}人，当前显示第{(page-1)*per_page+1}-{min(page*per_page, total)}人\n\n'
    
    for i, m in enumerate(members, 1 + (page-1)*per_page):
        vip_icon = '💎' if m[2] else '👤'
        text += f'{i}. {vip_icon} @{m[1] or "未知"}\n'
        if m[2]:  # 如果是VIP显示余额
            text += f'   余额: {m[3] or 0} U\n'
        text += f'   注册: {m[4][:10] if m[4] else "未知"}\n'
    
    # 分页按钮
    buttons = []
    if total > per_page:
        nav_buttons = []
        if page > 1:
            nav_buttons.append(Button.inline('⬅️ 上一页', f'level_page_{level}_{page-1}'.encode()))
        if page * per_page < total:
            nav_buttons.append(Button.inline('➡️ 下一页', f'level_page_{level}_{page+1}'.encode()))
        if nav_buttons:
            buttons.append(nav_buttons)
    
    buttons.append([Button.inline('🔙 返回', b'back_to_fission')])
    
    await event.edit(text, buttons=buttons, parse_mode='md')

# 返回裂变统计
@bot.on(events.CallbackQuery(pattern=b'back_to_fission'))
async def back_to_fission_callback(event):
    # 重新触发查看裂变功能
    await view_fission_handler(event)
    await event.answer()

# 裂变机器
@bot.on(events.NewMessage(pattern=BTN_FISSION))
async def fission_handler(event):
    """群裂变加入"""
    telegram_id = get_main_account_id(event.sender_id, getattr(event.sender, 'username', None))
    member = DB.get_member(telegram_id)
    
    if not member:
        await event.respond("❌ 请先使用 /start 开始")
        return
    
    config = get_system_config()
    
    # 检查是否开通VIP
    if not member.get('is_vip'):
        # 未开通VIP，只显示VIP权益，不显示任何群组
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
        
        from telethon import Button
        if user_balance >= vip_price:
            buttons = [[Button.inline('💎 余额开通VIP', b'open_vip_balance')]]
        else:
            text += f"\n\n❌ 余额不足，请先充值"
            buttons = [[Button.inline(f'💰 充值{need_recharge}U开通VIP', b'recharge_for_vip')]]
        
        await event.respond(text, buttons=buttons)
        return
    
    # 已开通VIP，显示上级群（新格式）
    referrer_id = member.get('referrer_id')
    
    if referrer_id:
        # 有上级，获取上级的群
        referrer = DB.get_member(referrer_id)
        if referrer and referrer.get('group_link'):
            groups = referrer.get('group_link', '').split('\n')
            valid_groups = [g.strip() for g in groups[:10] if g.strip()]
            
            if valid_groups:
                # 获取每个群的名称
                from telethon import Button
                
                # 构建消息文本
                text = f"加入您上层1-{len(valid_groups)}级群{len(valid_groups)}个群\n\n"
                text += "上级群    点击加入群\n"
                text += "━━━━━━━━━━━━━━━━\n\n"
                
                buttons = []
                
                # 从第10层到上级（第1层）倒序显示
                for idx in range(len(valid_groups) - 1, -1, -1):
                    group_link = valid_groups[idx]
                    level = idx + 1
                    
                    # 获取群名称
                    group_name = "未知群组"
                    try:
                        if 't.me/' in group_link:
                            group_username = group_link.split('t.me/')[-1].replace('+', '')
                            try:
                                group_entity = await bot.get_entity(group_username)
                                group_name = group_entity.title if hasattr(group_entity, 'title') else group_username
                            except:
                                group_name = group_username
                    except:
                        group_name = f"群{level}"
                    
                    # 显示层级
                    if level == 1:
                        level_text = "上级"
                    else:
                        level_text = str(level)
                    
                    # 添加文本行（使用Markdown超链接）
                    text += f"{level_text:>3}    [{group_name}]({group_link})\n"
                
                # 添加验证未加群按钮
                buttons.append([Button.inline('🔍 验证未加群', f'verify_groups_{telegram_id}'.encode())])
                
                await event.respond(text, buttons=buttons, parse_mode='markdown')
                return
    
    # 无上级或上级没有群，显示推荐群组（新格式）
    fb_groups = get_fallback_resource('group')
    if fb_groups:
        groups = fb_groups.split('\n')
        valid_groups = [g.strip() for g in groups[:10] if g.strip()]
        
        if valid_groups:
            from telethon import Button
            
            text = f"加入推荐群组{len(valid_groups)}个群\n\n"
            text += "推荐群    点击加入群\n"
            text += "━━━━━━━━━━━━━━━━\n\n"
            
            buttons = []
            
            for idx, group_link in enumerate(valid_groups, 1):
                # 获取群名称
                group_name = "未知群组"
                try:
                    if 't.me/' in group_link:
                        group_username = group_link.split('t.me/')[-1].replace('+', '')
                        try:
                            group_entity = await bot.get_entity(group_username)
                            group_name = group_entity.title if hasattr(group_entity, 'title') else group_username
                        except:
                            group_name = group_username
                except:
                    group_name = f"群{idx}"
                
                text += f"{idx:>3}    [{group_name}]({group_link})\n"
            
            buttons.append([Button.inline('🔍 验证未加群', f'verify_groups_{telegram_id}'.encode())])
            
            await event.respond(text, buttons=buttons, parse_mode='markdown')
        else:
            await event.respond("❌ 暂无可用群组")
    else:
        await event.respond("❌ 暂无可用群组")


@bot.on(events.NewMessage(pattern=BTN_PROMOTE))
async def promote_handler(event):
    # 账号关联处理
    try:
        original_sender_id = event.sender_id
        event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
    except: pass
    config = get_system_config()
    member = DB.get_member(event.sender_id)
    if not member:
        await event.respond('请先发送 /start 注册')
        return
    
    # 检查条件
    if not member['is_vip']:
        await event.respond(
            '❌ 推广功能需要先开通VIP\n\n'
            f'VIP价格: {config["vip_price"]} U\n'
            '开通后即可开始推广赚钱!',
            buttons=[[Button.inline('💎 立即开通VIP', b'open_vip')]]
        )
        return
    
    if not member['group_link']:
        await event.respond(
            '❌ 请先设置您的群链接\n\n'
            '设置群链接后才能开始推广',
            buttons=[[Button.inline('🔗 设置群链接', b'set_group')]]
        )
        return
    
    # 生成推广链接
    bot_info = await bot.get_me()
    invite_link = f'https://t.me/{bot_info.username}?start={event.sender_id}'
    
    text = f'💰 赚钱推广\n\n'
    text += f'您的专属推广链接:\n{invite_link}\n\n'
    text += f'📊 推广规则:\n'
    text += f'• 每有一人通过您的链接开通VIP\n'
    text += f'• 您将获得 {config["level_reward"]} U 奖励\n'
    text += f'• 最多可获得 {config["level_count"]} 层下级奖励\n\n'
    text += f'💡 分享此链接给好友即可开始赚钱!'
    
    await event.respond(text, buttons=[[Button.inline('📤 分享推广', b'share_promote')]])

# 行业资源
@bot.on(events.NewMessage(pattern=BTN_RESOURCES))
async def resources_handler(event):
    # 账号关联处理
    try:
        original_sender_id = event.sender_id
        event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
    except: pass
    await show_resource_categories(event, page=1, is_new=True)

async def show_resource_categories(event, page=1, is_new=False):
    """显示资源分类（分页，每行3个）"""
    categories = DB.get_resource_categories(0)

    if not categories:
        msg = '📁 行业资源\n\n暂无资源分类'
        if is_new:
            await event.respond(msg)
        else:
            await event.edit(msg)
        return

    # 分页设置：每页9个（3行x3列）
    per_page = 9
    total = len(categories)
    total_pages = (total + per_page - 1) // per_page
    page = max(1, min(page, total_pages))
    
    start = (page - 1) * per_page
    end = start + per_page
    page_categories = categories[start:end]

    # 构建按钮（每行3个）
    buttons = []
    row = []
    for cat in page_categories:
        row.append(Button.inline(cat["name"], f'cat_{cat["id"]}'.encode()))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    # 分页按钮
    nav_buttons = []
    if page > 1:
        nav_buttons.append(Button.inline('< 上一页', f'catpg_{page-1}'.encode()))
    if page < total_pages:
        nav_buttons.append(Button.inline('下一页 >', f'catpg_{page+1}'.encode()))
    if nav_buttons:
        buttons.append(nav_buttons)

    # 返回按钮
    buttons.append([Button.inline('< 返回', b'res_back_main')])

    text = f'📁 行业资源\n\n请选择分类: ({page}/{total_pages})'
    
    if is_new:
        await event.respond(text, buttons=buttons, parse_mode='md')
    else:
        await event.edit(text, buttons=buttons)

# 分类分页回调
@bot.on(events.CallbackQuery(pattern=b'catpg_'))
async def category_page_callback(event):
    try:
        data = event.data.decode()
        page = int(data.replace('catpg_', ''))
        await show_resource_categories(event, page=page, is_new=False)
        await event.answer()
    except Exception as e:
        print(f'分类分页错误: {e}')
        await event.answer('加载失败', alert=True)

# 返回主菜单
@bot.on(events.CallbackQuery(pattern=b'res_back_main'))
async def res_back_main_callback(event):
    await event.delete()
    await event.answer()

# 资源分类回调
@bot.on(events.CallbackQuery(pattern=b'cat_'))
async def category_callback(event):
    try:
        data = event.data.decode()
        category_id = int(data.replace('cat_', ''))
        
        # 获取资源列表（第一页）
        result = DB.get_resources(category_id, page=1, per_page=25)
        
        if not result['items']:
            await event.answer('该分类下暂无资源', alert=True)
            return
        
        # 构建资源列表文本（使用markdown链接）
        text = f'📁 资源列表\n\n'
        for item in result['items']:
            icon = '👥' if item['type'] == 'group' else '📢'
            count_display = f"{item['count'] // 2000}K" if item['count'] >= 1000 else str(item['count'])
            # 使用markdown格式的可点击链接
            text += f'{icon} [{item["name"]} ({count_display})]({item["link"]})\n\n'
        
        # 构建分页按钮
        buttons = []
        if result['pages'] > 1:
            page_buttons = []
            if result['pages'] > 1:
                page_buttons.append(Button.inline('下一页 >', f'res_page_{category_id}_2'.encode()))
            buttons.append(page_buttons)
        
        buttons.append([Button.inline('🔙 返回分类', b'back_to_categories')])
        
        await event.respond(text, buttons=buttons, parse_mode='md')
        await event.answer()
    except Exception as e:
        print(f'资源分类回调错误: {e}')
        await event.answer('加载失败，请稍后再试', alert=True)

# 资源分页回调
@bot.on(events.CallbackQuery(pattern=b'res_page_'))
async def resource_page_callback(event):
    try:
        data = event.data.decode()
        parts = data.replace('res_page_', '').split('_')
        category_id = int(parts[0])
        page = int(parts[1])
        
        result = DB.get_resources(category_id, page=page, per_page=25)
        
        if not result['items']:
            await event.answer('没有更多资源了', alert=True)
            return
        
        # 构建资源列表文本（使用markdown链接）
        text = f'📁 资源列表 (第{page}页)\n\n'
        for item in result['items']:
            icon = '👥' if item['type'] == 'group' else '📢'
            count_display = f"{item['count'] // 2000}K" if item['count'] >= 1000 else str(item['count'])
            text += f'{icon} [{item["name"]} ({count_display})]({item["link"]})\n\n'
        
        # 构建分页按钮
        buttons = []
        page_buttons = []
        if page > 1:
            page_buttons.append(Button.inline('< 上一页', f'res_page_{category_id}_{page-1}'.encode()))
        if page < result['pages']:
            page_buttons.append(Button.inline('下一页 >', f'res_page_{category_id}_{page+1}'.encode()))
        if page_buttons:
            buttons.append(page_buttons)
        
        buttons.append([Button.inline('🔙 返回分类', b'back_to_categories')])
        
        await event.edit(text, buttons=buttons)
        await event.answer()
    except Exception as e:
        print(f'资源分页回调错误: {e}')
        await event.answer('加载失败，请稍后再试', alert=True)

# 返回资源分类
@bot.on(events.CallbackQuery(pattern=b'back_to_categories'))
async def back_to_categories_callback(event):
    # 直接调用显示分类函数，保持一致的布局和翻页
    await show_resource_categories(event, page=1, is_new=False)
    await event.answer()


# 在线客服
@bot.on(events.NewMessage(pattern=BTN_SUPPORT))
async def support_handler(event):
    # 账号关联处理
    try:
        original_sender_id = event.sender_id
        event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
    except: pass
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
        # 转换链接格式：如果是@username格式，转换为https://t.me/username
        link = service['link']
        if link.startswith('@'):
            link = f'https://t.me/{link[1:]}'  # 去掉@符号
        elif not link.startswith('http'):
            link = f'https://t.me/{link}'
        
        buttons.append([Button.url(f'💬 联系 {service["name"]}', link)])
    
    await event.respond(text, buttons=buttons, parse_mode='md')

# 开通会员
@bot.on(events.NewMessage(pattern=BTN_VIP))
async def vip_handler(event):
    # 账号关联处理
    try:
        original_sender_id = event.sender_id
        event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
    except: pass
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
            buttons=[[Button.inline(f'💰 充值 {config["vip_price"]} U 开通VIP', b'recharge_vip')]]
        )

# 我的推广
@bot.on(events.NewMessage(pattern=BTN_MY_PROMOTE))
async def my_promote_handler(event):
    # 账号关联处理
    try:
        original_sender_id = event.sender_id
        event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
    except: pass
    config = get_system_config()
    member = DB.get_member(event.sender_id)
    if not member:
        await event.respond('请先发送 /start 注册')
        return
    
    # 获取下级统计
    counts = DB.get_downline_count(event.sender_id, config['level_count'])
    total_members = sum(c['total'] for c in counts)
    total_vip = sum(c['vip'] for c in counts)
    
    # 生成推广链接
    bot_info = await bot.get_me()
    invite_link = f'https://t.me/{bot_info.username}?start={event.sender_id}'
    
    text = f'💫 我的推广\n\n'
    text += f'📊 推广统计:\n'
    text += f'• 总下级: {total_members} 人\n'
    text += f'• VIP下级: {total_vip} 人\n'
    text += f'• 累计收益: {member["balance"]} U\n'
    text += f'• 错过收益: {member["missed_balance"]} U\n\n'
    text += f'🔗 您的推广链接:\n{invite_link}\n\n'
    text += f'💡 分享链接邀请好友，好友开通VIP您即可获得 {config["level_reward"]} U 奖励!'
    
    buttons = [[Button.inline('📤 分享推广', b'share_promote')]]
    if not member['is_vip']:
        buttons.append([Button.inline('💎 开通VIP解锁全部功能', b'open_vip')])
    
    await event.respond(text, buttons=buttons, parse_mode='md')


# 返回主菜单
@bot.on(events.NewMessage(pattern=BTN_BACK))
async def back_handler(event):
    # 账号关联处理
    try:
        original_sender_id = event.sender_id
        event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
    except: pass
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

# ============ 管理后台 ============

# 管理员等待输入状态
admin_waiting = {}

# 管理后台
@bot.on(events.NewMessage(pattern=BTN_ADMIN))
async def admin_handler(event):
    # 账号关联处理
    try:
        original_sender_id = event.sender_id
        event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
    except: pass
    if event.sender_id not in ADMIN_IDS:
        return
    
    # 获取系统配置
    config = get_system_config()
    
    text = f'⚙️ 管理后台\n\n'
    text += f'当前设置:\n'
    text += f'📊 层数: {config["level_count"]} 层\n'
    text += f'💰 每层返利: {config["level_reward"]} U\n'
    text += f'💎 VIP价格: {config["vip_price"]} U\n'
    # 添加捡漏群
    _fb_group = get_fallback_resource("group")
    if _fb_group:
        text += f"\n\n💡 推荐群组:\n{_fb_group}"
    text += f'💳 提现门槛: {config["withdraw_threshold"]} U\n'
    text += f'💵 USDT地址: {config["usdt_address"][:10] if config["usdt_address"] else "未设置"}...{config["usdt_address"][-10:] if config["usdt_address"] and len(config["usdt_address"]) > 20 else ""}\n\n'
    text += f'客服文本:\n{config["support_text"]}\n\n'
    # 根据环境自动选择地址
    web_url = 'http://liebian.mifzla.top' if not USE_PROXY else 'http://localhost:5051'
    text += f'🌐 Web管理后台: {web_url}'
    
    buttons = [
        [Button.inline('📊 设置层数', b'admin_set_level'), Button.inline('💰 设置返利', b'admin_set_reward')],
        [Button.inline('💎 设置VIP价格', b'admin_set_vip_price'), Button.inline('💳 设置提现门槛', b'admin_set_withdraw')],
        [Button.inline('💵 设置USDT地址', b'admin_set_usdt'), Button.inline('👩‍💼 设置客服文本', b'admin_set_support')],
        [Button.inline('💫 查看会员统计', b'admin_stats'), Button.inline('🎁 手动充值VIP', b'admin_manual_vip')],
        [Button.inline('📢 用户广播', b'admin_broadcast')]
    ]
    
    await event.respond(text, buttons=buttons, parse_mode='md')

# 设置层数
@bot.on(events.CallbackQuery(pattern=b'admin_set_level'))
async def admin_set_level_callback(event):
    if event.sender_id not in ADMIN_IDS:
        await event.answer('无权限')
        return
    
    config = get_system_config()
    admin_waiting[event.sender_id] = 'level_count'
    await event.respond(
        f'📊 设置层数\n\n'
        f'当前层数: {config["level_count"]} 层\n'
        f'请输入新的层数 (1-20):\n\n'
        f'发送 /cancel 取消'
    )
    await event.answer()

# 设置返利
@bot.on(events.CallbackQuery(pattern=b'admin_set_reward'))
async def admin_set_reward_callback(event):
    if event.sender_id not in ADMIN_IDS:
        await event.answer('无权限')
        return
    
    config = get_system_config()
    admin_waiting[event.sender_id] = 'level_reward'
    await event.respond(
        f'💰 设置每层返利\n\n'
        f'当前返利: {config["level_reward"]} U\n'
        f'请输入新的返利金额:\n\n'
        f'发送 /cancel 取消'
    )
    await event.answer()

# 设置VIP价格
@bot.on(events.CallbackQuery(pattern=b'admin_set_vip_price'))
async def admin_set_vip_price_callback(event):
    if event.sender_id not in ADMIN_IDS:
        await event.answer('无权限')
        return
    
    config = get_system_config()
    admin_waiting[event.sender_id] = 'vip_price'
    await event.respond(
        f'💎 设置VIP价格\n\n'
        f'当前价格: {config["vip_price"]} U\n'
        f'请输入新的VIP价格:\n\n'
        f'发送 /cancel 取消'
    )
    await event.answer()

# 设置提现门槛
@bot.on(events.CallbackQuery(pattern=b'admin_set_withdraw'))
async def admin_set_withdraw_callback(event):
    if event.sender_id not in ADMIN_IDS:
        await event.answer('无权限')
        return
    
    config = get_system_config()
    admin_waiting[event.sender_id] = 'withdraw_threshold'
    await event.respond(
        f'💳 设置提现门槛\n\n'
        f'当前门槛: {config["withdraw_threshold"]} U\n'
        f'请输入新的提现门槛:\n\n'
        f'发送 /cancel 取消'
    )
    await event.answer()

# 设置USDT地址
@bot.on(events.CallbackQuery(pattern=b'admin_set_usdt'))
async def admin_set_usdt_callback(event):
    if event.sender_id not in ADMIN_IDS:
        await event.answer('无权限')
        return
    
    config = get_system_config()
    admin_waiting[event.sender_id] = 'usdt_address'
    await event.respond(
        f'💵 设置USDT地址\n\n'
        f'当前地址:\n<code>{config["usdt_address"]}</code>\n\n'
        f'请输入新的USDT TRC20地址:\n\n'
        f'发送 /cancel 取消',
        parse_mode='html'
    )
    await event.answer()

# 设置客服文本
@bot.on(events.CallbackQuery(pattern=b'admin_set_support'))
async def admin_set_support_callback(event):
    if event.sender_id not in ADMIN_IDS:
        await event.answer('无权限')
        return
    
    config = get_system_config()
    admin_waiting[event.sender_id] = 'support_text'
    await event.respond(
        f'👩‍💼 设置客服文本\n\n'
        f'当前文本:\n{config["support_text"]}\n\n'
        f'请输入新的客服文本 (支持换行):\n\n'
        f'发送 /cancel 取消'
    )
    await event.answer()

# 查看会员统计
@bot.on(events.CallbackQuery(pattern=b'admin_stats'))
async def admin_stats_callback(event):
    if event.sender_id not in ADMIN_IDS:
        await event.answer('无权限')
        return
    
    conn = DB.get_conn()
    c = conn.cursor()
    
    c.execute('SELECT COUNT(*) FROM members')
    total = c.fetchone()[0]
    
    c.execute('SELECT COUNT(*) FROM members WHERE is_vip = 1')
    vip_count = c.fetchone()[0]
    
    c.execute('SELECT SUM(balance) FROM members')
    total_balance = c.fetchone()[0] or 0
    
    conn.close()
    
    text = f'👥 会员统计\n\n'
    text += f'总会员数: {total}\n'
    text += f'VIP会员数: {vip_count}\n'
    text += f'总余额: {total_balance} U'
    
    await event.respond(text)
    await event.answer()

# 手动充值VIP
@bot.on(events.CallbackQuery(pattern=b'admin_manual_vip'))
async def admin_manual_vip_callback(event):
    if event.sender_id not in ADMIN_IDS:
        await event.answer('无权限')
        return
    
    admin_waiting[event.sender_id] = 'manual_vip'
    await event.respond(
        f'🎁 手动充值VIP\n\n'
        f'请输入要充值的用户ID或用户名\n\n'
        f'格式示例:\n'
        f'• 用户ID: 123456789\n'
        f'• 用户名: @username (带@)\n'
        f'• 用户名: username (不带@)\n\n'
        f'发送 /cancel 取消'
    )
    await event.answer()

# 用户广播
@bot.on(events.CallbackQuery(pattern=b'admin_broadcast'))
async def admin_broadcast_callback(event):
    if event.sender_id not in ADMIN_IDS:
        await event.answer('无权限')
        return
    
    # 获取用户总数
    conn = DB.get_conn()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM members')
    total_users = c.fetchone()[0]
    conn.close()
    
    admin_waiting[event.sender_id] = 'broadcast'
    await event.respond(
        f'📢 用户广播\n\n'
        f'当前用户总数: {total_users} 人\n\n'
        f'请输入要广播的内容:\n'
        f'• 支持文字消息\n'
        f'• 支持换行（直接回车即可）\n'
        f'• 支持Markdown格式\n\n'
        f'⚠️ 广播将发送给所有用户，请谨慎操作\n\n'
        f'发送 /cancel 取消'
    )
    await event.answer()


# ============ 内联按钮回调处理 ============

# 设置群链接
@bot.on(events.CallbackQuery(pattern=b'set_group'))
async def set_group_callback(event):
    member = DB.get_member(event.sender_id)
    if not member:
        await event.answer('请先发送 /start 注册')
        return
    
    # 切换到群链接输入时，清理备用号等待状态
    waiting_for_backup.pop(event.sender_id, None)
    waiting_for_group_link[event.sender_id] = True
    await event.respond(
        '🔗 设置群链接\n\n'
        '请发送您的群链接 (格式: https://t.me/xxx)\n\n'
        '发送 /cancel 取消操作'
    )
    await event.answer()

# 设置备用号
@bot.on(events.CallbackQuery(pattern=b'set_backup'))
async def set_backup_callback(event):
    member = DB.get_member(event.sender_id)
    if not member:
        await event.answer('请先发送 /start 注册')
        return
    
    # 切换到备用号输入时，清理群链接等待状态
    waiting_for_group_link.pop(event.sender_id, None)
    waiting_for_backup[event.sender_id] = True
    await event.respond(
        '✏️ 设置备用号\n\n'
        '请发送您的备用飞机号 (用户名或ID)\n\n'
        '发送 /cancel 取消操作'
    )
    await event.answer()

# 开通VIP
@bot.on(events.CallbackQuery(pattern=b'open_vip'))
async def open_vip_callback(event):
    """开通VIP"""
    telegram_id = get_main_account_id(event.sender_id, getattr(event.sender, 'username', None))
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
    
    from telethon import Button
    if user_balance >= vip_price:
        # 余额足够，显示余额开通按钮
        buttons = [[Button.inline(f'💎 余额开通VIP', b'open_vip_balance')]]
    else:
        # 余额不足，显示充值按钮
        text += f"\n\n❌ 余额不足，请先充值"
        buttons = [[Button.inline(f'💰 充值{need_recharge}U开通VIP', b'recharge_for_vip')]]
    
    try:
        await event.edit(text, buttons=buttons)
    except:
        await event.respond(text, buttons=buttons)


@bot.on(events.CallbackQuery(data=b'open_vip_balance'))
async def open_vip_balance_callback(event):
    """使用余额开通VIP"""
    telegram_id = get_main_account_id(event.sender_id, getattr(event.sender, 'username', None))
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
    
    if user_balance < vip_price:
        await event.answer(f"❌ 余额不足\n当前余额: {user_balance} U\nVIP价格: {vip_price} U", alert=True)
        return
    
    # 扣除余额并开通VIP
    new_balance = user_balance - vip_price
    from datetime import datetime
    vip_time = datetime.now().isoformat()
    
    DB.update_member(telegram_id, balance=new_balance, is_vip=1, vip_time=vip_time)
    
    # 发放奖励给上级
    uplines = DB.get_upline_members(telegram_id, config.get('level_count', 10))
    level_reward = config.get('level_reward', 1)
    
    reward_count = 0
    fallback_count = 0
    
    # 如果没有上级，奖励给捡漏账号
    if not uplines:
        import random
        _conn = DB.get_conn()
        _c = _conn.cursor()
        _c.execute("SELECT telegram_id FROM fallback_accounts WHERE is_active = 1")
        _fallback_list = [row[0] for row in _c.fetchall()]
        _conn.close()
        if _fallback_list:
            for _ in range(config.get("level_count", 10)):
                _fb_id = random.choice(_fallback_list)
                _conn2 = DB.get_conn()
                _c2 = _conn2.cursor()
                _c2.execute("UPDATE fallback_accounts SET total_earned = total_earned + ? WHERE telegram_id = ?", (level_reward, _fb_id))
                _conn2.commit()
                _conn2.close()
                fallback_count += 1
    else:
        for upline in uplines:
            if upline.get('is_vip'):
                upline_id = upline['telegram_id']
                up_member = DB.get_member(upline_id)
                if up_member:
                    up_new_balance = up_member.get('balance', 0) + level_reward
                    total_earned = up_member.get('total_earned', 0) + level_reward
                    DB.update_member(upline_id, balance=up_new_balance, total_earned=total_earned)
                    reward_count += 1
    
    text = f"""🎉 恭喜! VIP开通成功!

✅ 您已成为VIP会员
💰 消费金额: {vip_price} U
💵 剩余余额: {new_balance} U

🎁 上级获得 {reward_count} 次奖励
💎 推荐账号获得 {fallback_count} 次奖励"""
    
    await event.answer(text, alert=True)
    
    # 刷新消息
    try:
        await event.delete()
    except:
        pass

@bot.on(events.CallbackQuery(data=b'recharge_balance'))
async def recharge_balance_callback(event):
    """充值余额"""
    telegram_id = get_main_account_id(event.sender_id, getattr(event.sender, 'username', None))
    member = DB.get_member(telegram_id)
    
    if not member:
        await event.answer("❌ 用户信息不存在", alert=True)
        return
    
    # 调用充值功能（与do_recharge相同的逻辑）
    await event.answer("💰 请输入充值金额（USDT）:", alert=False)
    
    # 设置状态等待用户输入金额
    # 这里简化处理，直接显示充值说明
    text = """💰 充值说明

请按以下步骤操作:
1️⃣ 点击下方"💳 充值"按钮
2️⃣ 输入充值金额
3️⃣ 获取充值地址
4️⃣ 转账到指定地址
5️⃣ 等待自动到账

⚠️ 注意事项:
• 仅支持TRC-20网络USDT
• 转账金额必须与订单金额一致
• 订单10分钟内有效"""
    
    from telethon import Button
    buttons = [[Button.inline('💳 立即充值', b'do_recharge')]]
    
    try:
        await event.edit(text, buttons=buttons)
    except:
        await event.respond(text, buttons=buttons)


@bot.on(events.CallbackQuery(data=b'recharge_for_vip'))
async def recharge_for_vip_callback(event):
    """充值开通VIP - 调用充值输入金额功能"""
    telegram_id = get_main_account_id(event.sender_id, getattr(event.sender, 'username', None))
    member = DB.get_member(telegram_id)
    
    if not member:
        await event.answer("❌ 用户信息不存在", alert=True)
        return
    
    # 设置用户状态为等待输入充值金额
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


@bot.on(events.CallbackQuery(pattern=rb'verify_groups_.*'))
async def verify_groups_callback(event):
    """验证用户是否加入所有上级群（最多10个）"""
    telegram_id = get_main_account_id(event.sender_id, getattr(event.sender, 'username', None))
    member = DB.get_member(telegram_id)
    
    if not member:
        await event.answer("❌ 用户信息不存在", alert=True)
        return
    
    await event.answer("🔍 正在检测群组加入情况，请稍候...", alert=False)
    
    # 获取需要加入的群组列表（最多10个）
    config = get_system_config()
    max_groups = min(config.get('level_count', 10), 10)
    
    # 获取上级链
    upline_chain = get_upline_chain(telegram_id, max_groups)
    groups_to_check = []
    
    # 从上级链获取群组
    for level, upline_id in upline_chain:
        up_member = DB.get_member(upline_id)
        if up_member and up_member.get('group_link'):
            group_links = up_member.get('group_link', '').split('\n')
            for gl in group_links:
                gl = gl.strip()
                if gl and gl not in [g['link'] for g in groups_to_check]:
                    groups_to_check.append({
                        'level': level,
                        'link': gl,
                        'upline_username': up_member.get('username', '')
                    })
                    if len(groups_to_check) >= max_groups:
                        break
        if len(groups_to_check) >= max_groups:
            break
    
    # 如果不足10个，用推荐群组补足
    if len(groups_to_check) < max_groups:
        fb_groups = get_fallback_resource('group')
        if fb_groups:
            for gl in fb_groups.split('\n'):
                gl = gl.strip()
                if gl and gl not in [g['link'] for g in groups_to_check]:
                    groups_to_check.append({
                        'level': len(groups_to_check) + 1,
                        'link': gl,
                        'upline_username': '推荐群组'
                    })
                    if len(groups_to_check) >= max_groups:
                        break
    
    if not groups_to_check:
        await event.respond("❌ 没有可验证的群组")
        return
    
    # 重新编号，避免出现缺号或重复号（例如出现两个10缺少9的情况）
    for idx, g in enumerate(groups_to_check, 1):
        g['display_index'] = idx
    
    # 检测用户是否在群组中
    not_joined = []
    joined = []
    
    for group_info in groups_to_check:
        group_link = group_info['link']
        try:
            # 提取群组用户名或ID
            if 't.me/' in group_link:
                group_username = group_link.split('t.me/')[-1].split('/')[0].split('?')[0].replace('+', '')
            elif group_link.startswith('@'):
                group_username = group_link[1:]
            else:
                group_username = group_link
                
            # 跳过私有群链接
            if group_username.startswith('+'):
                not_joined.append(group_info)
                continue
                
            try:
                # 尝试获取群组实体
                group_entity = await bot.get_entity(group_username)
                
                # 检查用户是否在群组中
                try:
                    participant = await bot(GetParticipantRequest(
                        channel=group_entity,
                        participant=telegram_id
                    ))
                    joined.append(group_info)
                except:
                    not_joined.append(group_info)
            except:
                # 无法获取群组信息，可能是私有群或链接无效
                not_joined.append(group_info)
        except Exception as e:
            not_joined.append(group_info)
    
    # 构建结果消息
    total_groups = len(groups_to_check)
    joined_count = len(joined)
    not_joined_count = len(not_joined)
    
    text = f"🔍 群组加入验证结果\n\n"
    text += f"📊 总计: {total_groups} 个群组\n"
    text += f"✅ 已加入: {joined_count} 个\n"
    text += f"❌ 未加入: {not_joined_count} 个\n\n"
    
    if joined_count == total_groups:
        text += "🎉 恭喜！您已加入所有 {total_groups} 个群组！\n\n"
        text += "✅ 所有条件已满足，可以正常获得分红！"
    else:
        if joined:
            text += "✅ 已加入的群组:\n"
            for g in joined:
                group_name = g['link'].split('t.me/')[-1].split('/')[0] if 't.me/' in g['link'] else g['link']
                idx = g.get('display_index', g.get('level', '?'))
                text += f"  {idx}. {group_name}\n"
            text += "\n"
        
        if not_joined:
            text += "❌ 未加入的群组（请点击加入）:\n"
            for g in not_joined:
                group_name = g['link'].split('t.me/')[-1].split('/')[0] if 't.me/' in g['link'] else g['link']
                idx = g.get('display_index', g.get('level', '?'))
                text += f"  {idx}. [{group_name}]({g['link']})\n"
            text += "\n⚠️ 请加入以上未加入的群组，才能获得分红！"
    
    await event.respond(text, parse_mode='markdown')

@bot.on(events.CallbackQuery(pattern=b'recharge_vip'))
async def recharge_vip_callback(event):
    member = DB.get_member(event.sender_id)
    if not member:
        await event.answer('请先发送 /start 注册')
        return
    
    if member['is_vip']:
        await event.answer('您已经是VIP了!')
        return
    
    # 创建VIP充值订单
    config = get_system_config()
    vip_price = config['vip_price']
    await create_recharge_order(event, vip_price, is_vip_order=True)
    await event.answer()

# 确认开通VIP (余额支付)
@bot.on(events.CallbackQuery(pattern=b'confirm_vip'))
async def confirm_vip_callback(event):
    config = get_system_config()
    member = DB.get_member(event.sender_id)
    if not member:
        await event.answer('请先发送 /start 注册')
        return
    
    if member['is_vip']:
        await event.answer('您已经是VIP了!')
        return
    
    # 检查余额是否足够
    if member['balance'] < config['vip_price']:
        await event.answer(f'余额不足! 还需 {config["vip_price"] - member["balance"]} U', alert=True)
        return
    
    # 扣除余额并更新VIP状态
    new_balance = member['balance'] - config['vip_price']
    DB.update_member(event.sender_id, balance=new_balance, is_vip=1, vip_time=datetime.now().isoformat())
    
    # 给上级发放奖励
    uplines = DB.get_upline_members(event.sender_id, config['level_count'])
    rewarded_count = 0
    fallback_count = 0

    # 如果没有上级，奖励给捡漏账号
    if not uplines:
        import random
        _conn = DB.get_conn()
        _c = _conn.cursor()
        _c.execute("SELECT telegram_id FROM fallback_accounts WHERE is_active = 1")
        _fallback_list = [row[0] for row in _c.fetchall()]
        _conn.close()
        if _fallback_list:
            for _ in range(config.get("level_count", 10)):
                _fb_id = random.choice(_fallback_list)
                _conn2 = DB.get_conn()
                _c2 = _conn2.cursor()
                _c2.execute("UPDATE fallback_accounts SET total_earned = total_earned + ? WHERE telegram_id = ?", (config["level_reward"], _fb_id))
                _conn2.commit()
                _conn2.close()
                fallback_count += 1

    for upline in uplines:
        up_member = DB.get_member(upline['telegram_id'])
        if up_member:
            # 检查上级是否满足所有条件：VIP + 拉群 + 群管 + 加群
            if (up_member['is_vip'] and 
                up_member.get('is_group_bound', 0) and 
                up_member.get('is_bot_admin', 0) and 
                up_member.get('is_joined_upline', 0)):
                # 上级符合条件，发放奖励
                new_balance = up_member['balance'] + config['level_reward']
                DB.update_member(upline['telegram_id'], balance=new_balance)
                rewarded_count += 1
                try:
                    await bot.send_message(upline['telegram_id'],
                        f'🎉 恭喜! 您获得了 {config["level_reward"]} U 奖励!\n'
                        f'来自下级 @{member["username"]} 开通VIP\n'
                        f'当前余额: {new_balance} U')
                except:
                    pass
            else:
                # 上级不符合条件，分配给随机捡漏账号
                import random
                conn = DB.get_conn()
                c = conn.cursor()
                c.execute("SELECT telegram_id FROM members WHERE telegram_id >= 9000000000 AND is_vip = 1")
                fallback_accounts = [row[0] for row in c.fetchall()]
                conn.close()
                
                if fallback_accounts:
                    fallback_id = random.choice(fallback_accounts)
                    fallback_member = DB.get_member(fallback_id)
                    if fallback_member:
                        new_balance = fallback_member['balance'] + config['level_reward']
                        DB.update_member(fallback_id, balance=new_balance)
                        fallback_count += 1
                
                # 记录上级错过的奖励
                new_missed = up_member['missed_balance'] + config['level_reward']
                DB.update_member(upline['telegram_id'], missed_balance=new_missed)
                try:
                    reasons = []
                    if not up_member['is_vip']:
                        reasons.append('未开通VIP')
                    if not up_member.get('is_group_bound', 0):
                        reasons.append('未拉群')
                    if not up_member.get('is_bot_admin', 0):
                        reasons.append('机器人非群管')
                    if not up_member.get('is_joined_upline', 0):
                        reasons.append('未加入上级群')
                    
                    await bot.send_message(upline['telegram_id'],
                        f'⚠️ 您错过了 {config["level_reward"]} U 奖励!\n'
                        f'来自下级 @{member["username"]} 开通VIP\n'
                        f'原因: {", ".join(reasons)}\n'
                        f'已错过: {new_missed} U\n\n'
                        f'💡 完成所有条件后即可获得奖励')
                except:
                    pass

    await event.respond(
        f'🎉 恭喜! VIP开通成功!\n\n'
        f'您现在可以:\n'
        f'✅ 查看裂变数据\n'
        f'✅ 获得下级开通VIP的奖励\n'
        f'✅ 加入上级群组\n'
        f'✅ 推广赚钱\n\n'
        f'已为 {rewarded_count} 位上级发放奖励\n捡漏账号获得 {fallback_count} 次奖励'
    )
    await event.answer()

# 收益记录
@bot.on(events.CallbackQuery(pattern=b'earnings_history'))
async def earnings_history_callback(event):
    """查看个人收益记录"""
    telegram_id = get_main_account_id(event.sender_id, getattr(event.sender, 'username', None))
    member = DB.get_member(telegram_id)
    
    if not member:
        await event.answer("❌ 用户信息不存在", alert=True)
        return
    
    conn = DB.get_conn()
    c = conn.cursor()
    c.execute('''
        SELECT amount, source_type, description, create_time
        FROM earnings_records
        WHERE member_id = ?
        ORDER BY create_time DESC
        LIMIT 50
    ''', (telegram_id,))
    records = c.fetchall()
    conn.close()
    
    if not records:
        text = "📊 收益记录\n\n暂无收益记录"
        buttons = [[Button.inline('🔙 返回', b'back_to_profile')]]
    else:
        total = sum(r[0] for r in records)
        text = f"📊 收益记录\n\n"
        text += f"💰 累计收益: {total} U\n"
        text += f"📝 记录数: {len(records)} 条\n\n"
        text += "最近收益记录:\n"
        text += "━━━━━━━━━━━━━━\n"
        
        for i, (amount, source_type, desc, create_time) in enumerate(records[:20], 1):
            time_str = create_time[:16] if create_time else "未知"
            text += f"{i}. +{amount} U\n"
            text += f"   {desc or source_type}\n"
            text += f"   {time_str}\n\n"
        
        if len(records) > 20:
            text += f"... 还有 {len(records) - 20} 条记录\n"
        
        buttons = [[Button.inline('🔙 返回', b'back_to_profile')]]
    
    try:
        await event.edit(text, buttons=buttons)
    except:
        await event.respond(text, buttons=buttons)
    await event.answer()

# 返回个人中心
@bot.on(events.CallbackQuery(pattern=b'back_to_profile'))
async def back_to_profile_callback(event):
    """返回个人中心"""
    telegram_id = get_main_account_id(event.sender_id, getattr(event.sender, 'username', None))
    member = DB.get_member(telegram_id)
    if not member:
        await event.answer("❌ 用户信息不存在", alert=True)
        return
    
    buttons = [
        [Button.inline('🔗 设置群链接', b'set_group'), Button.inline('✏️ 设置备用号', b'set_backup')],[Button.inline('📊 收益记录', b'earnings_history')],
        [Button.inline('💳 提现', b'withdraw'), Button.inline('💰 充值', b'do_recharge'), Button.inline('💎 开通VIP', b'open_vip')],
    ]
    
    text = (
        f'👤 个人中心\n\n'
        f'🆔 ID: {member["telegram_id"]}\n'
        f'👤 用户名: @{member["username"]}\n'
        f'💎 VIP状态: {"✅ 已开通" if member["is_vip"] else "❌ 未开通"}\n'
        f'💰 余额: {member["balance"]} U\n'
        f'📉 错过余额: {member["missed_balance"]} U\n'
        f'💵 累计收益: {member.get("total_earned", 0)} U\n'
        f'🔗 群链接: {member["group_link"] or "未设置"}\n'
        f'📱 备用号: {member["backup_account"] or "未设置"}\n'
        f'📅 注册时间: {member["register_time"][:10] if member["register_time"] else "未知"}'
    )
    
    try:
        await event.edit(text, buttons=buttons)
    except:
        await event.respond(text, buttons=buttons)
    await event.answer()

# 提现
@bot.on(events.CallbackQuery(pattern=b'withdraw'))
async def withdraw_callback(event):
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



@bot.on(events.CallbackQuery(pattern=b'do_recharge'))
async def do_recharge_callback(event):
    await event.respond('请输入充值金额（USDT，例如：200）:')
    waiting_for_recharge_amount[event.sender_id] = True
    await event.answer()

# 充值金额选择回调（仅用于VIP充值）
@bot.on(events.CallbackQuery(pattern=b'recharge_'))
async def recharge_amount_callback(event):
    data = event.data.decode()
    
    # VIP充值专用回调已在上面处理
    if data == 'recharge_vip':
        return

# 取消充值订单
@bot.on(events.CallbackQuery(pattern=b'cancel_order_'))
async def cancel_order_callback(event):
    data = event.data.decode()
    order_number = data.replace('cancel_order_', '')
    
    if order_number in payment_orders:
        order = payment_orders[order_number]
        
        # 检查是否是订单创建者
        if order['telegram_id'] == event.sender_id:
            # 取消任务
            if order_number in payment_tasks:
                payment_task, timeout_task = payment_tasks[order_number]
                payment_task.cancel()
                timeout_task.cancel()
                del payment_tasks[order_number]
            
            # 删除订单
            del payment_orders[order_number]
            
            await event.respond(f'✅ 订单 {order_number} 已取消')
            await event.answer()
        else:
            await event.answer('这不是您的订单', alert=True)
    else:
        await event.answer('订单不存在或已失效', alert=True)

# 分享推广
@bot.on(events.CallbackQuery(pattern=b'share_promote'))
async def share_promote_callback(event):
    config = get_system_config()
    member = DB.get_member(event.sender_id)
    bot_info = await bot.get_me()
    invite_link = f'https://t.me/{bot_info.username}?start={event.sender_id}'
    
    share_text = f'''🎉 加入裂变推广机器人，轻松赚钱!

💰 开通VIP即可开始推广
💎 推广一人奖励 {config["level_reward"]} U
🔗 最多 {config["level_count"]} 层收益

👇 点击下方按钮立即加入
{invite_link}'''
    
    await event.respond(
        f'📤 分享内容已生成\n\n'
        f'请复制以下内容分享给好友:\n\n'
        f'---\n{share_text}\n---'
    )
    await event.answer()

# 查看层级详情
@bot.on(events.CallbackQuery(pattern=b'level_detail_'))
async def level_detail_callback(event):
    level = int(event.data.decode().split('_')[-1])
    member = DB.get_member(event.sender_id)
    
    if not member or not member['is_vip']:
        await event.answer('请先开通VIP')
        return
    
    # 获取该层会员列表
    conn = DB.get_conn()
    c = conn.cursor()
    
    current_ids = [event.sender_id]
    for _ in range(level):
        if not current_ids:
            break
        placeholders = ','.join(['?' for _ in current_ids])
        c.execute(f'SELECT telegram_id FROM members WHERE referrer_id IN ({placeholders})', current_ids)
        current_ids = [r[0] for r in c.fetchall()]
    
    if current_ids:
        placeholders = ','.join(['?' for _ in current_ids])
        c.execute(f'SELECT telegram_id, username, is_vip FROM members WHERE telegram_id IN ({placeholders})', current_ids)
        members = c.fetchall()
    else:
        members = []
    
    conn.close()
    
    text = f'👁 第{level}层会员详情\n\n'
    if members:
        for m in members[:20]:
            vip_mark = ' ✅VIP' if m[2] else ''
            text += f'• @{m[1] or m[0]}{vip_mark}\n'
        if len(members) > 20:
            text += f'\n... 共 {len(members)} 人'
    else:
        text += '暂无会员'
    
    await event.respond(text)
    await event.answer()


# ============ 文本消息处理 ============

# 处理文本输入 (群链接、备用号等)
@bot.on(events.NewMessage())
async def message_handler(event):
    # 账号关联处理
    try:
        original_sender_id = event.sender_id
        event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
    except: pass
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
                    conn = DB.get_conn()
                    conn.execute("PRAGMA busy_timeout = 5000")  # 5秒超时
                    c = conn.cursor()
                    
                    # 扣除余额
                    c.execute("UPDATE members SET balance = balance - ? WHERE telegram_id = ?", (amount, sender_id))
                    
                    # 插入提现记录
                    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    
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
                    break  # 成功则跳出重试循环
                    
                except Exception as e:
                    if 'locked' in str(e) and retry < max_retries - 1:
                        time.sleep(0.5)  # 等待0.5秒后重试
                        continue
                    else:
                        raise  # 如果不是锁问题或已达最大重试次数，抛出异常
            
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
        
        if wait_type == 'level_count':
            try:
                value = int(text)
                if 1 <= value <= 20:
                    update_system_config('level_count', value)
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
                    update_system_config('withdraw_threshold', value)
                    del admin_waiting[sender_id]
                    await event.respond(f'✅ 提现门槛设置成功!\n\n当前门槛: {value} U')
                else:
                    await event.respond('❌ 请输入大于等于0的数字')
            except ValueError:
                await event.respond('❌ 请输入有效的数字')
            return
        
        elif wait_type == 'usdt_address':
            if len(text) > 200:
                await event.respond('❌ USDT地址长度不能超过200个字符')
                return
            
            # 更新配置中的USDT地址
            update_system_config('usdt_address', text)
            
            # 更新全局USDT地址
            
            # 生成新的二维码
            try:
                img = qrcode.make(usdt_address)
                img.save("usdt_qr.png")
                await event.respond(f'✅ USDT地址已更新!\n\n新地址:\n<code>{usdt_address}</code>\n\n二维码已重新生成', parse_mode='html')
            except Exception as e:
                await event.respond(f'✅ USDT地址已更新，但二维码生成失败\n\n新地址:\n<code>{usdt_address}</code>', parse_mode='html')
            
            del admin_waiting[sender_id]
            return
        
        elif wait_type == 'support_text':
            update_system_config('support_text', text)
            del admin_waiting[sender_id]
            await event.respond(f'✅ 客服文本设置成功!\n\n当前文本:\n{text}')
            return
        
        elif wait_type == 'manual_vip':
            # 手动充值VIP
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
                conn = DB.get_conn()
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
            
            # 开通VIP
            DB.update_member(target_user['telegram_id'], is_vip=1, vip_time=datetime.now().isoformat())
            
            # 给上级发放奖励
            uplines = DB.get_upline_members(target_user['telegram_id'], config['level_count'])
            rewarded_count = 0
            
            # 如果没有上级，奖励给捡漏账号
            if not uplines:
                import random
                _conn = DB.get_conn()
                _c = _conn.cursor()
                _c.execute("SELECT telegram_id FROM fallback_accounts WHERE is_active = 1")
                _fallback_list = [row[0] for row in _c.fetchall()]
                _conn.close()
                if _fallback_list:
                    for _ in range(config.get("level_count", 10)):
                        _fb_id = random.choice(_fallback_list)
                        _conn2 = DB.get_conn()
                        _c2 = _conn2.cursor()
                        _c2.execute("UPDATE fallback_accounts SET total_earned = total_earned + ? WHERE telegram_id = ?", (config["level_reward"], _fb_id))
                        _conn2.commit()
                        _conn2.close()
                        fallback_count += 1

            for upline in uplines:
                up_member = DB.get_member(upline['telegram_id'])
                if up_member:
                    if up_member['is_vip']:
                        up_new_balance = up_member['balance'] + config['level_reward']
                        DB.update_member(upline['telegram_id'], balance=up_new_balance)
                        rewarded_count += 1
                        try:
                            await bot.send_message(upline['telegram_id'],
                                f'🎉 恭喜! 您获得了 {config["level_reward"]} U 奖励!\n'
                                f'来自下级 @{target_user["username"]} 开通VIP\n'
                                f'当前余额: {up_new_balance} U')
                        except:
                            pass
                    else:
                        new_missed = up_member['missed_balance'] + config['level_reward']
                        DB.update_member(upline['telegram_id'], missed_balance=new_missed)
                        try:
                            await bot.send_message(upline['telegram_id'],
                                f'⚠️ 您错过了 {config["level_reward"]} U 奖励!\n'
                                f'来自下级 @{target_user["username"]} 开通VIP\n'
                                f'开通VIP后即可获得奖励，已错过: {new_missed} U')
                        except:
                            pass
            
            # 通知用户VIP已开通
            try:
                await bot.send_message(
                    target_user['telegram_id'],
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
            
            # 通知管理员成功
            await event.respond(
                f'✅ VIP充值成功!\n\n'
                f'用户ID: {target_user["telegram_id"]}\n'
                f'用户名: @{target_user["username"]}\n'
                f'已为 {rewarded_count} 位上级发放奖励\n'
                f'用户已收到开通通知'
            )
            
            del admin_waiting[sender_id]
            return
        
        elif wait_type == 'broadcast':
            # 用户广播
            broadcast_message = text
            
            # 获取所有用户
            conn = DB.get_conn()
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
                    # 避免发送过快被限制
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
                f'• 成功率: {success_count / len(all_users) * 200:.1f}%\n\n'
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
            await create_recharge_order(event, amount)
        except ValueError:
            await event.respond('❌ 请输入有效的数字')
        return
    
    # 设置备用号（优先处理，避免与群链接等待状态冲突）
    if sender_id in waiting_for_backup and waiting_for_backup[sender_id]:
        backup_raw = text.strip().lstrip('@')
        backup_id = None
        backup_username = backup_raw
        
        # 尝试解析数字ID
        if backup_raw.isdigit():
            backup_id = int(backup_raw)
        else:
            # 尝试通过用户名解析为账号ID
            try:
                entity = await bot.get_entity(backup_raw)
                if getattr(entity, 'id', None):
                    backup_id = entity.id
                    backup_username = getattr(entity, 'username', backup_raw) or backup_raw
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
        if link.startswith('https://t.me/') or link.startswith('t.me/') or link.startswith('@'):
            # 验证群链接
            verification_result = await verify_group_link(link)
            
            if verification_result['success']:
                DB.update_member(sender_id, group_link=link)
                del waiting_for_group_link[sender_id]
                await event.respond(
                    f'✅ 群链接设置成功!\n\n'
                    f'链接: {link}\n'
                    f'✅ 机器人已在群内\n'
                    f'✅ 机器人具有管理员权限'
                )
            else:
                await event.respond(
                    f'❌ 群链接验证失败\n\n'
                    f'原因: {verification_result["message"]}\n\n'
                    f'请确保:\n'
                    f'1. 机器人已被添加到群内\n'
                    f'2. 机器人具有管理员权限\n\n'
                    f'完成后请重新发送群链接'
                )
        else:
            await event.respond('❌ 链接格式不正确，请发送正确的Telegram群链接\n例如: https://t.me/xxx')
        return


# ============ Web管理后台 (集成在同一程序中) ============

# Flask应用
# 指定模板目录和静态文件目录（项目根目录下的 templates 和 static）
# os 已在文件开头导入，这里直接使用
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates')
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static')

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)
app.secret_key = 'fission-bot-secret-key-2025' # 请修改此密钥
app.config['REMEMBER_COOKIE_DURATION'] = timedelta(days=90)
app.config['TEMPLATES_AUTO_RELOAD'] = True  # 禁用模板缓存
app.jinja_env.auto_reload = True

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


# ============ 支付系统配置 ============
PAYMENT_CONFIG = {
    'api_url': 'https://usdt.qxzy7888.org/pay/',
    'partner_id': '15',
    'key': '5c9dd0b054b184f964',
    'notify_url': 'http://liebian.mifzla.top:5051/api/payment/notify',
    'return_url': 'http://liebian.mifzla.top:5051/payment/success',
    'pay_type': 'trc20',
    'version': '1.0'
}

import hashlib
import requests as req

def generate_payment_sign(params, key):
    sorted_params = sorted([(k, v) for k, v in params.items() if v is not None and v != ''])
    sign_str = '&'.join([f'{k}={v}' for k, v in sorted_params])
    sign_str += f'&key={key}'
    return hashlib.md5(sign_str.encode()).hexdigest().upper()

def create_payment_order(amount, out_trade_no, remark=''):
    params = {
        'amount': f'{amount:.2f}',
        'partnerid': PAYMENT_CONFIG['partner_id'],
        'notifyUrl': PAYMENT_CONFIG['notify_url'],
        'out_trade_no': out_trade_no,
        'payType': PAYMENT_CONFIG['pay_type'],
        'returnUrl': PAYMENT_CONFIG['return_url'],
        'version': PAYMENT_CONFIG['version'],
        'format': 'json'
    }
    params['sign'] = generate_payment_sign(params, PAYMENT_CONFIG['key'])
    if remark:
        params['remark'] = remark
    try:
        print(f'[支付API] 请求参数: {params}')
        response = req.post(PAYMENT_CONFIG['api_url'], data=params, timeout=10)
        result = response.json()
        print(f'[支付API] 响应: {result}')
        return result
    except Exception as e:
        print(f'[支付API错误] {e}')
        import traceback
        traceback.print_exc()
        return None

async def send_recharge_notification(telegram_id, amount):
    """发送充值成功通知"""
    try:
        message = f"""✅ 充值成功

💰 充值金额: {amount} USDT
📝 订单状态: 已完成
⏰ 到账时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

您的余额已自动增加，可以在个人中心查看。"""
        
        await bot.send_message(telegram_id, message)
        print(f'[充值通知] 已发送通知给用户 {telegram_id}')
    except Exception as e:
        print(f'[充值通知] 发送失败: {e}')

@app.route('/api/payment/notify', methods=['POST'])
def payment_notify():
    try:
        data = request.form.to_dict()
        print(f'[支付回调] 收到数据: {data}')
        
        # 提取签名和备注
        sign = data.pop('sign', '')
        remark = data.pop('remark', '')
        
        # 验证签名
        calculated_sign = generate_payment_sign(data, PAYMENT_CONFIG['key'])
        print(f'[支付回调] 收到签名: {sign}')
        print(f'[支付回调] 计算签名: {calculated_sign}')
        
        if sign != calculated_sign:
            print(f'[支付回调] 签名验证失败')
            return 'fail'
        
        # 检查支付状态
        if data.get('status') == '4' and data.get('callbacks') == 'ORDER_SUCCESS':
            out_trade_no = data.get('out_trade_no')
            amount = float(data.get('amount', 0))
            print(f'[支付回调] 订单: {out_trade_no}, 金额: {amount}')
            
            if out_trade_no and out_trade_no.startswith('RCH_'):
                parts = out_trade_no.split('_')
                if len(parts) >= 2:
                    telegram_id = int(parts[1])
                    conn = DB.get_conn()
                    c = conn.cursor()
                    
                    # 检查订单是否已存在（使用正确的字段名order_id）
                    c.execute('SELECT id, status FROM recharge_records WHERE order_id = ?', (out_trade_no,))
                    existing = c.fetchone()
                    
                    if existing:
                        # 订单已存在，更新状态
                        if existing[1] != 'completed':
                            c.execute('UPDATE recharge_records SET status = ? WHERE order_id = ?', 
                                    ('completed', out_trade_no))
                            c.execute('UPDATE members SET balance = balance + ? WHERE telegram_id = ?', 
                                    (amount, telegram_id))
                            conn.commit()
                            print(f'[支付回调] 订单已更新为completed')
                            
                            # 发送充值成功通知
                            try:
                                msg = f"✅ 充值成功\n\n💰 金额: {amount} USDT\n📝 订单号: {out_trade_no}\n\n余额已到账，感谢您的支持！"
                                notify_queue.append({'member_id': telegram_id, 'message': msg})
                                print(f'[支付回调] 充值通知已加入队列')
                            except Exception as notify_err:
                                print(f'[支付回调] 发送通知失败: {notify_err}')
                        else:
                            print(f'[支付回调] 订单已经是completed状态')
                        conn.close()
                        return 'success'
                    else:
                        # 订单不存在，创建新订单（使用正确的字段名）
                        c.execute('''INSERT INTO recharge_records 
                                   (member_id, amount, order_id, status, payment_method, create_time) 
                                   VALUES (?, ?, ?, ?, ?, ?)''',
                                (telegram_id, amount, out_trade_no, 'completed', 'USDT', 
                                 datetime.now().isoformat()))
                        c.execute('UPDATE members SET balance = balance + ? WHERE telegram_id = ?', 
                                (amount, telegram_id))
                        conn.commit()
                        conn.close()
                        print(f'[支付回调] 新订单已创建并充值成功')
                        
                        # 发送充值成功通知
                        try:
                            msg = f"✅ 充值成功\n\n💰 金额: {amount} USDT\n📝 订单号: {out_trade_no}\n\n余额已到账，感谢您的支持！"
                            notify_queue.append({'member_id': telegram_id, 'message': msg})
                            print(f'[支付回调] 充值通知已加入队列')
                        except Exception as notify_err:
                            print(f'[支付回调] 发送通知失败: {notify_err}')
                        return 'success'
        
        print(f'[支付回调] 状态不符合要求: status={data.get("status")}, callbacks={data.get("callbacks")}')
        return 'success'
    except Exception as e:
        print(f'[支付回调] 错误: {e}')
        import traceback
        traceback.print_exc()
        return 'fail'

@app.route('/payment/success')
def payment_success():
    return '<html><head><meta charset=utf-8><title>支付成功</title></head><body style=text-align:center;padding:50px><h1>支付成功</h1><p>充值订单已提交</p></body></html>'


class User(UserMixin):
    def __init__(self, id, username, password_hash):
        self.id = id
        self.username = username
        self.password_hash = password_hash

@login_manager.user_loader
def load_user(user_id):
    return WebDB.get_user_by_id(int(user_id))

class WebDB:
    """Web管理后台数据库操作"""
    
    @staticmethod
    def get_user_by_username(username):
        conn = DB.get_conn()
        c = conn.cursor()
        c.execute('SELECT id, username, password_hash FROM admin_users WHERE username = ?', (username,))
        row = c.fetchone()
        conn.close()
        if row:
            return User(row[0], row[1], row[2])
        return None

    @staticmethod
    def get_user_by_id(user_id):
        conn = DB.get_conn()
        c = conn.cursor()
        c.execute('SELECT id, username, password_hash FROM admin_users WHERE id = ?', (user_id,))
        row = c.fetchone()
        conn.close()
        if row:
            return User(row[0], row[1], row[2])
        return None
        
    @staticmethod
    def update_password(user_id, new_password):
        conn = DB.get_conn()
        c = conn.cursor()
        new_hash = generate_password_hash(new_password)
        c.execute('UPDATE admin_users SET password_hash = ? WHERE id = ?', (new_hash, user_id))
        conn.commit()
        conn.close()
        return True

    @staticmethod
    def get_all_members(page=1, per_page=20, search='', filter_type='all'):
        """获取所有会员列表"""
        conn = DB.get_conn()
        c = conn.cursor()
        
        offset = (page - 1) * per_page
        
        # 筛选条件
        conditions = []
        params = []
        
        # VIP筛选
        if filter_type == 'vip':
            conditions.append('is_vip = 1')
        elif filter_type == 'normal':
            conditions.append('is_vip = 0')
        
        # 搜索条件
        if search:
            # 如果搜索词是纯数字，使用精确匹配telegram_id或模糊匹配username
            if search.isdigit():
                conditions.append('(CAST(telegram_id AS TEXT) LIKE ? OR username LIKE ?)')
                params.extend([f'%{search}%', f'%{search}%'])
            else:
                conditions.append('username LIKE ?')
                params.append(f'%{search}%')
        
        # 组合WHERE条件
        search_condition = ''
        if conditions:
            search_condition = 'WHERE ' + ' AND '.join(conditions)
        
        # 获取总数
        c.execute(f'SELECT COUNT(*) FROM members {search_condition}', params)
        total = c.fetchone()[0]
        
        # 获取会员列表（包含所有新字段）
        query = f'''
            SELECT 
                id, telegram_id, username, backup_account, referrer_id, 
                balance, missed_balance, group_link, is_vip, 
                register_time, vip_time,
                is_group_bound, is_bot_admin, is_joined_upline,
                direct_count, team_count, total_earned, withdraw_address
            FROM members 
            {search_condition}
            ORDER BY id DESC 
            LIMIT ? OFFSET ?
        '''
        c.execute(query, params + [per_page, offset])
        rows = c.fetchall()
        
        members = []
        for row in rows:
            # 获取推荐人信息
            referrer_name = ''
            if row[4]:
                c.execute('SELECT username FROM members WHERE telegram_id = ?', (row[4],))
                ref = c.fetchone()
                if ref:
                    referrer_name = ref[0]
            
            # 获取下级总数（如果direct_count为0，实时计算）
            direct_count = row[14] if row[14] else 0
            if direct_count == 0:
                c.execute('SELECT COUNT(*) FROM members WHERE referrer_id = ?', (row[1],))
                direct_count = c.fetchone()[0]

            # 实时计算团队总人数
            tg_id = row[1]
            c.execute("SELECT COUNT(*) FROM members WHERE level_path LIKE ? AND telegram_id != ?", (f'%/{tg_id}/%', tg_id))
            team_count = c.fetchone()[0]
            
            # 检查是否是捡漏账号
            c.execute('SELECT id FROM fallback_accounts WHERE telegram_id = ?', (row[1],))
            is_fallback = c.fetchone() is not None

            # 备用号展示：优先显示备用号的用户名
            backup_raw = row[3] or ''
            backup_username = ''
            if backup_raw:
                if str(backup_raw).isdigit():
                    c.execute('SELECT username FROM members WHERE telegram_id = ?', (int(backup_raw),))
                    b_row = c.fetchone()
                    backup_username = b_row[0] if b_row and b_row[0] else f'{backup_raw}'
                else:
                    backup_username = backup_raw
            
            members.append({
                'id': row[0],
                'telegram_id': row[1],
                'username': row[2] or '',
                'backup_account': backup_raw,
                'backup_username': backup_username,
                'referrer_id': row[4] or '',
                'referrer_name': referrer_name,
                'balance': row[5],
                'missed_balance': row[6],
                'group_link': row[7] or '',
                'is_vip': row[8],
                'register_time': row[9][:19] if row[9] else '',
                'vip_time': row[10][:19] if row[10] else '',
                'is_group_bound': row[11],
                'is_bot_admin': row[12],
                'is_joined_upline': row[13],
                'direct_count': direct_count,
                'team_count': team_count,
                'total_earned': row[16] or 0,
                'withdraw_address': row[17] or '',
                'downline_count': direct_count,  # 使用direct_count作为downline_count
                'is_fallback': is_fallback  # 是否是捡漏账号
            })
        
        conn.close()
        
        return {
            'members': members,
            'total': total,
            'page': page,
            'per_page': per_page,
            'pages': (total + per_page - 1) // per_page
        }
    
    @staticmethod
    def get_member_detail(telegram_id):
        """获取会员详情"""
        conn = DB.get_conn()
        c = conn.cursor()
        
        c.execute('SELECT * FROM members WHERE telegram_id = ?', (telegram_id,))
        row = c.fetchone()
        
        if not row:
            conn.close()
            return None
        
        # 获取推荐人信息
        referrer_name = ''
        if row[4]:
            c.execute('SELECT username FROM members WHERE telegram_id = ?', (row[4],))
            ref = c.fetchone()
            if ref:
                referrer_name = ref[0]
        
        # 获取下级列表
        c.execute('SELECT telegram_id, username, is_vip FROM members WHERE referrer_id = ? LIMIT 50', (telegram_id,))
        downlines = [{'telegram_id': d[0], 'username': d[1], 'is_vip': d[2]} for d in c.fetchall()]
        
        conn.close()
        
        return {
            'id': row[0],
            'telegram_id': row[1],
            'username': row[2] or '',
            'backup_account': row[3] or '',
            'referrer_id': row[4] or '',
            'referrer_name': referrer_name,
            'balance': row[5],
            'missed_balance': row[6],
            'group_link': row[7] or '',
            'is_vip': row[8],
            'register_time': row[9][:19] if row[9] else '',
            'vip_time': row[10][:19] if row[10] else '',
            'is_group_bound': row[11] if len(row) > 11 else 0,
            'is_bot_admin': row[12] if len(row) > 12 else 0,
            'is_joined_upline': row[13] if len(row) > 13 else 0,
            'level_path': row[14] if len(row) > 14 else '',
            'direct_count': row[15] if len(row) > 15 else 0,
            'team_count': row[16] if len(row) > 16 else 0,
            'total_earned': row[17] if len(row) > 17 else 0,
            'withdraw_address': row[18] if len(row) > 18 else '',
            'downlines': downlines
        }
    
    @staticmethod
    def update_member(telegram_id, data):
        """更新会员信息"""
        conn = DB.get_conn()
        c = conn.cursor()

        updates = []
        params = []

        if 'username' in data and data['username']:
            updates.append('username = ?')
            params.append(data['username'])
        if 'referrer_id' in data and data['referrer_id']:
            updates.append('referrer_id = ?')
            params.append(data['referrer_id'])
        if 'balance' in data:
            updates.append('balance = ?')
            params.append(data['balance'])
        if 'missed_balance' in data:
            updates.append('missed_balance = ?')
            params.append(data['missed_balance'])
        if 'is_vip' in data:
            updates.append('is_vip = ?')
            params.append(data['is_vip'])
            if data['is_vip'] and 'vip_time' not in data:
                updates.append('vip_time = ?')
                params.append(datetime.now().isoformat())
        if 'group_link' in data:
            updates.append('group_link = ?')
            params.append(data['group_link'])
        if 'backup_account' in data:
            updates.append('backup_account = ?')
            params.append(data['backup_account'])
        if 'is_group_bound' in data:
            updates.append('is_group_bound = ?')
            params.append(data['is_group_bound'])
        if 'is_bot_admin' in data:
            updates.append('is_bot_admin = ?')
            params.append(data['is_bot_admin'])
        if 'is_joined_upline' in data:
            updates.append('is_joined_upline = ?')
            params.append(data['is_joined_upline'])

        if updates:
            params.append(telegram_id)
            query = f"UPDATE members SET {', '.join(updates)} WHERE telegram_id = ?"
            print(f"[会员更新] SQL: {query}, params: {params}")
            c.execute(query, params)
            conn.commit()

        # 处理捡漏账号状态
        if 'is_fallback' in data:
            if data['is_fallback']:
                c.execute('SELECT id FROM fallback_accounts WHERE telegram_id = ?', (telegram_id,))
                if not c.fetchone():
                    c.execute('SELECT username FROM members WHERE telegram_id = ?', (telegram_id,))
                    row = c.fetchone()
                    username = row[0] if row else ''
                    c.execute('INSERT INTO fallback_accounts (telegram_id, username, is_active) VALUES (?, ?, 1)', (telegram_id, username))
                    conn.commit()
            else:
                c.execute('DELETE FROM fallback_accounts WHERE telegram_id = ?', (telegram_id,))
                conn.commit()

        conn.close()
        return True

    @staticmethod
    def delete_member(telegram_id):
        """删除会员"""
        conn = DB.get_conn()
        c = conn.cursor()
        c.execute('DELETE FROM members WHERE telegram_id = ?', (telegram_id,))
        conn.commit()
        conn.close()
        return True
    
    @staticmethod
    def get_statistics():
        """获取统计数据"""
        conn = DB.get_conn()
        c = conn.cursor()
        
        c.execute('SELECT COUNT(*) FROM members')
        total_members = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM members WHERE is_vip = 1')
        vip_members = c.fetchone()[0]
        
        c.execute('SELECT SUM(balance) FROM members')
        total_balance = c.fetchone()[0] or 0
        
        c.execute('SELECT SUM(missed_balance) FROM members')
        total_missed = c.fetchone()[0] or 0
        
        conn.close()
        
        return {
            'total_members': total_members,
            'vip_members': vip_members,
            'total_balance': total_balance,
            'total_missed': total_missed
        }

    @staticmethod
    def get_chart_data():
        """获取图表统计数据"""
        conn = DB.get_conn()
        c = conn.cursor()
        
        # 获取近7天的注册趋势
        import datetime
        today = datetime.datetime.now().date()
        dates = []
        counts = []
        
        for i in range(6, -1, -1):
            date = today - datetime.timedelta(days=i)
            date_str = date.strftime('%Y-%m-%d')
            dates.append(date.strftime('%m-%d'))
            
            # 这是一个简单的模糊匹配，实际情况可能需要根据具体时间格式调整
            # 假设 register_time 格式包含 YYYY-MM-DD
            c.execute("SELECT COUNT(*) FROM members WHERE register_time LIKE ?", (f"{date_str}%",))
            count = c.fetchone()[0]
            counts.append(count)
            
        # 获取VIP比例
        c.execute('SELECT COUNT(*) FROM members WHERE is_vip = 1')
        vip_count = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM members WHERE is_vip = 0')
        normal_count = c.fetchone()[0]
        
        conn.close()
        
        return {
            'growth': {'labels': dates, 'data': counts},
            'composition': {'vip': vip_count, 'normal': normal_count}
        }

    @staticmethod
    def get_withdrawals(page=1, per_page=20, status='all', search=''):
        """获取提现列表"""
        conn = DB.get_conn()
        c = conn.cursor()
        offset = (page - 1) * per_page
        
        try:
            # 去掉搜索词中的@符号
            search_term = search.lstrip('@').strip() if search else ''
            
            # 先获取所有提现记录的member_id
            if status != 'all':
                c.execute('SELECT id, member_id, amount, usdt_address, status, create_time, process_time FROM withdrawals WHERE status = ? ORDER BY id DESC', (status,))
            else:
                c.execute('SELECT id, member_id, amount, usdt_address, status, create_time, process_time FROM withdrawals ORDER BY id DESC')
            
            all_rows = c.fetchall()
            
            # 获取用户名并过滤
            results = []
            for row in all_rows:
                member_id = row[1]
                c.execute('SELECT username FROM members WHERE telegram_id = ?', (member_id,))
                user_row = c.fetchone()
                username = user_row[0] if user_row else str(member_id)
                
                # 如果有搜索词，进行过滤
                if search_term:
                    # 搜索用户名或member_id
                    if search_term.lower() not in username.lower() and search_term not in str(member_id):
                        continue
                
                results.append({
                    'id': row[0],
                    'member_id': row[1],
                    'amount': row[2],
                    'usdt_address': row[3],
                    'status': row[4],
                    'create_time': row[5],
                    'process_time': row[6],
                    'username': username
                })
            
            # 分页
            total = len(results)
            withdrawals = results[offset:offset + per_page]
            
            return {
                'withdrawals': withdrawals,
                'total': total,
                'page': page,
                'pages': (total + per_page - 1) // per_page if total > 0 else 1,
                'per_page': per_page
            }
        except Exception as e:
            print(f"get_withdrawals error: {e}")
            import traceback
            traceback.print_exc()
            return {'withdrawals': [], 'total': 0, 'page': 1, 'pages': 1, 'per_page': per_page}
        finally:
            conn.close()


    @staticmethod
    def process_withdrawal(withdrawal_id, action):
        """处理提现请求"""
        conn = DB.get_conn()
        c = conn.cursor()
        
        try:
            # 获取提现记录
            c.execute('SELECT member_id, amount, status FROM withdrawals WHERE id = ?', (withdrawal_id,))
            row = c.fetchone()
            
            if not row:
                return False, "记录不存在"
                
            member_id, amount, status = row
            
            import datetime
            now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            if action == 'approve':
                # 同意提现：更新状态（允许从已拒绝改为已完成）
                if status == 'rejected':
                    # 从已拒绝改为已完成，需要再次扣除余额（因为拒绝时已经返还了）
                    c.execute('UPDATE members SET balance = balance - ? WHERE telegram_id = ?', 
                             (amount, member_id))
                
                c.execute('UPDATE withdrawals SET status = ?, process_time = ? WHERE id = ?', 
                         ('approved', now, withdrawal_id))
                
            elif action == 'reject':
                # 拒绝提现：只有待处理状态才能拒绝
                if status != 'pending':
                    return False, "只能拒绝待处理的提现"
                
                # 拒绝提现：更新状态并返还余额
                c.execute('UPDATE withdrawals SET status = ?, process_time = ? WHERE id = ?', 
                         ('rejected', now, withdrawal_id))
                c.execute('UPDATE members SET balance = balance + ? WHERE telegram_id = ?', 
                         (amount, member_id))
            else:
                return False, "无效操作"
                
            conn.commit()
            
            # 发送BOT通知
            try:
                import requests
                if action == 'approve':
                    msg = f"✅ 提现审核通过\n\n💰 金额: {amount} USDT\n📝 订单号: #{withdrawal_id}\n⏰ 时间: {now}\n\n请注意查收，感谢您的耐心等待！"
                else:
                    msg = f"❌ 提现申请被拒绝\n\n💰 金额: {amount} USDT\n📝 订单号: #{withdrawal_id}\n⏰ 时间: {now}\n\n余额已退回账户，如有疑问请联系客服。"
                
                requests.post("http://127.0.0.1:5051/internal/notify", json={
                    'member_id': member_id, 'message': msg
                }, timeout=1)
            except:
                pass
            
            return True, "操作成功"
        except Exception as e:
            return False, str(e)
        finally:
            conn.close()

# Flask路由
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.json
        username = data.get('username')
        password = data.get('password')
        remember = data.get('remember', False)
        
        user = WebDB.get_user_by_username(username)
        if user and check_password_hash(user.password_hash, password):
            login_user(user, remember=remember)
            return jsonify({'success': True, 'message': '登录成功'})
        
        return jsonify({'success': False, 'message': '用户名或密码错误'}), 401
        
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/api/change_password', methods=['POST'])
@login_required
def api_change_password():
    data = request.json
    old_password = data.get('old_password')
    new_password = data.get('new_password')
    
    user = WebDB.get_user_by_id(current_user.id)
    
    if not check_password_hash(user.password_hash, old_password):
        return jsonify({'success': False, 'message': '旧密码错误'}), 400
        
    WebDB.update_password(user.id, new_password)
    return jsonify({'success': True, 'message': '密码修改成功'})

@app.route('/')
@login_required
def index():
    """主页 - 数据统计"""
    return render_template('dashboard.html', active_page='dashboard')

@app.route('/members')
@login_required
def members_page():
    """会员管理页面"""
    return render_template('members.html', active_page='members')

@app.route('/settings')
@login_required
def settings_page():
    """设置页面"""
    return render_template('settings.html', active_page='settings')

@app.route('/statistics')
@login_required
def statistics_page():
    """统计报表页面"""
    return render_template('statistics.html', active_page='statistics')

@app.route('/withdrawals')
@login_required
def withdrawals_page():
    """提现管理页面"""
    return render_template('withdrawals.html', active_page='withdrawals')


# 充值订单管理页面
@app.route('/recharges')
@login_required
def recharges():
    return render_template('recharges.html')

# API: 获取充值订单列表
@app.route('/api/recharges')
@login_required
def api_recharges():
    try:
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
        search = request.args.get('search', '').lstrip('@').strip()
        
        conn = DB.get_conn()
        c = conn.cursor()
        
        # 构建查询
        where_clause = ''
        params = []
        if search:
            where_clause = 'WHERE r.member_id LIKE ? OR r.order_id LIKE ? OR m.username LIKE ?'
            search_param = f'%{search}%'
            params = [search_param, search_param, search_param]
        
        # 获取总数
        count_query = f'SELECT COUNT(*) FROM recharge_records r LEFT JOIN members m ON r.member_id = m.telegram_id {where_clause}'
        c.execute(count_query, params)
        total = c.fetchone()[0]
        
        # 获取数据
        offset = (page - 1) * per_page
        query = f'''
            SELECT r.id, r.member_id, m.username, r.amount, r.order_id, 
                   r.status, r.create_time, r.payment_method
            FROM recharge_records r
            LEFT JOIN members m ON r.member_id = m.telegram_id
            {where_clause}
            ORDER BY r.create_time DESC
            LIMIT ? OFFSET ?
        '''
        c.execute(query, params + [per_page, offset])
        
        recharges = []
        for row in c.fetchall():
            recharges.append({
                'id': row[0],
                'telegram_id': row[1],
                'username': row[2] or '',
                'amount': row[3],
                'order_number': row[4] or '',
                'status': row[5],
                'create_time': row[6][:19] if row[6] else '',
                'payment_method': row[7] or ''
            })
        
        conn.close()
        
        return jsonify({
            'success': True,
            'records': recharges,
            'total': total,
            'page': page,
            'per_page': per_page
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/members')
@login_required
def api_members():
    """获取会员列表API"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '', type=str)

    filter_type = request.args.get('filter', 'all', type=str)

    data = WebDB.get_all_members(page, per_page, search, filter_type)
    return jsonify(data)

@app.route('/api/member/<int:telegram_id>')
@login_required
def api_member_detail(telegram_id):
    """获取会员详情API"""
    member = WebDB.get_member_detail(telegram_id)
    if member:
        return jsonify(member)
    return jsonify({'error': '会员不存在'}), 404

@app.route('/api/member/<int:telegram_id>', methods=['PUT'])
@login_required
def api_update_member(telegram_id):
    """更新会员信息API"""
    data = request.json
    success = WebDB.update_member(telegram_id, data)
    if success:
        return jsonify({'success': True, 'message': '更新成功'})
    return jsonify({'success': False, 'message': '更新失败'}), 400


@app.route('/api/member/add', methods=['POST'])
@login_required
def api_add_member():
    """注册新会员API"""
    data = request.json
    telegram_id = data.get('telegram_id')
    if not telegram_id:
        return jsonify({'success': False, 'message': '缺少用户ID'})
    
    conn = DB.get_conn()
    c = conn.cursor()
    
    # 检查是否已存在
    c.execute('SELECT id FROM members WHERE telegram_id = ?', (telegram_id,))
    if c.fetchone():
        conn.close()
        return jsonify({'success': False, 'message': '用户已存在'})
    
    # 插入新会员
    from datetime import datetime
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    c.execute("""
        INSERT INTO members (telegram_id, username, referrer_id, balance, group_link,
            is_group_bound, is_bot_admin, is_joined_upline, is_vip, register_time, vip_time)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        telegram_id,
        data.get('username', ''),
        data.get('referrer_id'),
        data.get('balance', 0),
        data.get('group_link', ''),
        data.get('is_group_bound', 0),
        data.get('is_bot_admin', 0),
        data.get('is_joined_upline', 0),
        data.get('is_vip', 0),
        now,
        now if data.get('is_vip') else None
    ))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': '注册成功'})

@app.route('/api/member/<int:telegram_id>/graph')
@login_required
def api_member_graph(telegram_id):
    """获取会员关系图谱"""
    conn = DB.get_conn()
    c = conn.cursor()
    
    # 获取当前会员
    c.execute("""SELECT telegram_id, username, balance, is_vip, referrer_id,
        is_group_bound, is_bot_admin, is_joined_upline, direct_count, team_count
        FROM members WHERE telegram_id = ?""", (telegram_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({'error': '会员不存在'}), 404
    
    current = {
        'telegram_id': row[0], 'username': row[1], 'balance': row[2],
        'is_vip': row[3], 'referrer_id': row[4], 'is_group_bound': row[5],
        'is_bot_admin': row[6], 'is_joined_upline': row[7],
        'direct_count': row[8] or 0, 'team_count': row[9] or 0
    }
    
    # 获取上级链
    upline = []
    current_ref = row[4]
    while current_ref and len(upline) < 10:
        c.execute("""SELECT telegram_id, username, is_vip, referrer_id,
            is_group_bound, is_bot_admin, is_joined_upline, direct_count, team_count
            FROM members WHERE telegram_id = ?""", (current_ref,))
        ref_row = c.fetchone()
        if not ref_row:
            break
        is_valid = ref_row[4] and ref_row[5] and ref_row[6]  # 拉群+群管+加群
        upline.append({
            'telegram_id': ref_row[0], 'username': ref_row[1], 'is_vip': ref_row[2],
            'is_group_bound': ref_row[4], 'is_bot_admin': ref_row[5], 'is_joined_upline': ref_row[6],
            'direct_count': ref_row[7] or 0, 'team_count': ref_row[8] or 0, 'is_valid': is_valid
        })
        current_ref = ref_row[3]
    
    # 递归获取多层级下级
    def get_downline_recursive(parent_id, max_level=10):
        result = {}
        for level in range(1, max_level + 1):
            if level == 1:
                # 第1层：直推下级
                c.execute("""SELECT telegram_id, username, is_vip,
                    is_group_bound, is_bot_admin, is_joined_upline
                    FROM members WHERE referrer_id = ? LIMIT 100""", (parent_id,))
            else:
                # 第N层：从上一层的所有成员中查找下级
                if level - 1 not in result or not result[level - 1]:
                    break
                parent_ids = [m['telegram_id'] for m in result[level - 1]]
                if not parent_ids:
                    break
                placeholders = ','.join('?' * len(parent_ids))
                c.execute(f"""SELECT telegram_id, username, is_vip,
                    is_group_bound, is_bot_admin, is_joined_upline
                    FROM members WHERE referrer_id IN ({placeholders}) LIMIT 100""", parent_ids)
            
            level_members = []
            for d in c.fetchall():
                # 实时计算直推人数
                c.execute('SELECT COUNT(*) FROM members WHERE referrer_id = ?', (d[0],))
                d_direct = c.fetchone()[0]
                # 实时计算团队人数
                c.execute("SELECT COUNT(*) FROM members WHERE level_path LIKE ? AND telegram_id != ?", (f'%/{d[0]}/%', d[0]))
                d_team = c.fetchone()[0]
                level_members.append({
                    'telegram_id': d[0], 'username': d[1], 'is_vip': d[2],
                    'is_group_bound': d[3], 'is_bot_admin': d[4], 'is_joined_upline': d[5],
                    'direct_count': d_direct, 'team_count': d_team
                })
            if level_members:
                result[level] = level_members
            else:
                break
        return result
    
    downline_by_level = get_downline_recursive(telegram_id)
    
    conn.close()
    return jsonify({'current': current, 'upline': upline, 'downline_by_level': downline_by_level})


@app.route('/api/member/<int:telegram_id>', methods=['DELETE'])
@login_required
def api_delete_member(telegram_id):
    """删除会员API"""
    success = WebDB.delete_member(telegram_id)
    if success:
        return jsonify({'success': True, 'message': '删除成功'})
    return jsonify({'success': False, 'message': '删除失败'}), 400

@app.route('/api/statistics')
@login_required
def api_statistics():
    """获取统计数据API"""
    stats = WebDB.get_statistics()
    return jsonify(stats)

@app.route('/api/statistics/chart')
@login_required
def api_chart_data():
    """获取图表数据API"""
    data = WebDB.get_chart_data()
    return jsonify(data)

@app.route('/api/dashboard/stats')
@login_required
def api_dashboard_stats():
    """获取仪表盘统计数据"""
    try:
        from datetime import datetime, timedelta
        conn = DB.get_conn()
        c = conn.cursor()
        
        # 获取当前时间信息
        today = datetime.now().strftime('%Y-%m-%d')
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        month_start = datetime.now().strftime('%Y-%m-01')
        
        # 总会员数
        c.execute('SELECT COUNT(*) FROM members')
        total_members = c.fetchone()[0]
        
        # VIP会员数
        c.execute('SELECT COUNT(*) FROM members WHERE is_vip = 1')
        vip_members = c.fetchone()[0]
        
        # 今日注册
        c.execute('SELECT COUNT(*) FROM members WHERE DATE(register_time) = ?', (today,))
        today_register = c.fetchone()[0]
        
        # 昨日注册
        c.execute('SELECT COUNT(*) FROM members WHERE DATE(register_time) = ?', (yesterday,))
        yesterday_register = c.fetchone()[0]
        
        # 本月注册
        c.execute('SELECT COUNT(*) FROM members WHERE DATE(register_time) >= ?', (month_start,))
        month_register = c.fetchone()[0]
        
        # 今日开通VIP
        c.execute('SELECT COUNT(*) FROM members WHERE is_vip = 1 AND DATE(vip_time) = ?', (today,))
        today_vip = c.fetchone()[0]
        
        # 昨日开通VIP
        c.execute('SELECT COUNT(*) FROM members WHERE is_vip = 1 AND DATE(vip_time) = ?', (yesterday,))
        yesterday_vip = c.fetchone()[0]
        
        # 本月开通VIP
        c.execute('SELECT COUNT(*) FROM members WHERE is_vip = 1 AND DATE(vip_time) >= ?', (month_start,))
        month_vip = c.fetchone()[0]
        
        # 捡漏账号收益统计（从fallback_accounts表读取）

        c.execute("SELECT telegram_id, username, total_earned FROM fallback_accounts ORDER BY total_earned DESC LIMIT 10")

        fallback_rows = c.fetchall()

        fallback_accounts = []

        total_income = 0

        for row in fallback_rows:

            total_income += row[2] or 0

            fallback_accounts.append({

                "telegram_id": row[0],

                "username": row[1],

                "balance": row[2] or 0,

                "total_earned": row[2] or 0,

                "is_vip": 1

            })

        today_income = total_income

        yesterday_income = 0

        month_income = total_income

        trend_labels = []
        trend_register = []
        trend_vip = []
        for i in range(6, -1, -1):
            date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
            trend_labels.append((datetime.now() - timedelta(days=i)).strftime('%m-%d'))
            
            c.execute('SELECT COUNT(*) FROM members WHERE DATE(register_time) = ?', (date,))
            trend_register.append(c.fetchone()[0])
            
            c.execute('SELECT COUNT(*) FROM members WHERE is_vip = 1 AND DATE(vip_time) = ?', (date,))
            trend_vip.append(c.fetchone()[0])
        
        conn.close()
        
        return jsonify({
            'success': True,
            'data': {
                'total_members': total_members,
                'vip_members': vip_members,
                'today_register': today_register,
                'yesterday_register': yesterday_register,
                'month_register': month_register,
                'today_vip': today_vip,
                'yesterday_vip': yesterday_vip,
                'month_vip': month_vip,
                'today_income': round(today_income, 2),
                'yesterday_income': round(yesterday_income, 2),
                'month_income': round(month_income, 2),
                'total_income': round(total_income, 2),
                'fallback_accounts': fallback_accounts,
                'trend_data': {
                    'labels': trend_labels,
                    'register_counts': trend_register,
                    'vip_counts': trend_vip
                }
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/withdrawals')
@login_required
def api_withdrawals():
    """获取提现列表API"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    status = request.args.get('status', 'all')
    
    search = request.args.get('search', '').strip()
    data = WebDB.get_withdrawals(page, per_page, status, search)
    return jsonify(data)

@app.route('/api/withdrawals/<int:id>/process', methods=['POST'])
@login_required
def api_process_withdrawal(id):
    """处理提现API"""
    data = request.json
    action = data.get('action')
    
    success, message = WebDB.process_withdrawal(id, action)
    if success:
        return jsonify({'success': True, 'message': message})
    return jsonify({'success': False, 'message': message}), 400

@app.route('/api/settings', methods=['GET'])
@login_required
def api_get_settings():
    """获取系统设置API"""
    try:
        # 从数据库读取所有配置
        conn = DB.get_conn()
        c = conn.cursor()
        c.execute('SELECT key, value FROM system_config')
        config_rows = c.fetchall()
        conn.close()
        
        # 构建配置字典
        db_config = {row[0]: row[1] for row in config_rows}
        
        return jsonify({
            'success': True,
            'settings': {
                'levels': db_config.get('levels', settings.get('levels', 10)),
                'reward_per_level': db_config.get('reward_per_level', settings.get('reward_per_level', 1)),
                'vip_price': db_config.get('vip_price', settings.get('vip_price', 10)),
                'withdraw_threshold': db_config.get('withdraw_threshold', settings.get('withdraw_threshold', 50)),
                'usdt_address': db_config.get('usdt_address', usdt_address if usdt_address else ''),
                'service_text': db_config.get('service_text', settings.get('service_text', '暂无客服信息，请联系管理员')),
                'broadcast_enabled': db_config.get('broadcast_enabled', '0'),
                'broadcast_interval': db_config.get('broadcast_interval', '200'),
                'pinned_ad': db_config.get('pinned_ad', ''),
                'welcome_message': db_config.get('welcome_message', ''),
                'welcome_enabled': db_config.get('welcome_enabled', '1'),
                'auto_register_enabled': db_config.get('auto_register_enabled', '0')
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/payment-config', methods=['GET'])
@login_required
def get_payment_config():
    """获取支付配置"""
    try:
        # 先从数据库读取
        conn = DB.get_conn()
        c = conn.cursor()
        c.execute("SELECT key, value FROM system_config WHERE key LIKE 'payment_%'")
        rows = c.fetchall()
        conn.close()
        
        config = {}
        for row in rows:
            config[row[0]] = row[1]
        
        # 如果数据库没有，从PAYMENT_CONFIG读取默认值
        if not config.get('payment_url'):
            config['payment_url'] = PAYMENT_CONFIG.get('api_url', '')
        if not config.get('payment_token'):
            config['payment_token'] = PAYMENT_CONFIG.get('key', '')
        if not config.get('payment_rate'):
            config['payment_rate'] = '1.00'
        if not config.get('payment_channel'):
            config['payment_channel'] = PAYMENT_CONFIG.get('pay_type', 'trc20')
        if not config.get('payment_user_id'):
            config['payment_user_id'] = PAYMENT_CONFIG.get('partner_id', '')
        
        return jsonify({
            'success': True,
            'config': config
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/payment-config', methods=['POST'])
@login_required
def update_payment_config():
    """更新支付配置"""
    try:
        data = request.json
        conn = DB.get_conn()
        c = conn.cursor()
        
        # 更新各个配置项
        config_keys = ['payment_url', 'payment_token', 'payment_rate', 'payment_channel', 'payment_user_id']
        for key in config_keys:
            if key in data:
                value = str(data[key])
                c.execute("SELECT id FROM system_config WHERE key = ?", (key,))
                existing = c.fetchone()
                if existing:
                    c.execute("UPDATE system_config SET value = ? WHERE key = ?", (value, key))
                else:
                    c.execute("INSERT INTO system_config (key, value) VALUES (?, ?)", (key, value))
        
        conn.commit()
        conn.close()
        
        # 更新全局PAYMENT_CONFIG
        global PAYMENT_CONFIG
        if 'payment_url' in data:
            PAYMENT_CONFIG['api_url'] = data['payment_url']
        if 'payment_token' in data:
            PAYMENT_CONFIG['key'] = data['payment_token']
        if 'payment_user_id' in data:
            PAYMENT_CONFIG['partner_id'] = data['payment_user_id']
        if 'payment_channel' in data:
            PAYMENT_CONFIG['pay_type'] = data['payment_channel']
        
        print(f"[支付配置] 已更新: api_url={PAYMENT_CONFIG.get('api_url')}, partner_id={PAYMENT_CONFIG.get('partner_id')}, pay_type={PAYMENT_CONFIG.get('pay_type')}")
        
        return jsonify({'success': True, 'message': '支付配置已保存'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/settings', methods=['POST'])
@login_required
def api_update_settings():
    """更新系统设置API"""
    try:
        data = request.json
        key = data.get('key')
        value = data.get('value')
        
        if not key:
            return jsonify({'success': False, 'message': '缺少key参数'}), 400
        
        # 更新全局设置
        if key == 'usdt_address':
            global usdt_address
            usdt_address = value
            # 保存到数据库（可选）
            conn = DB.get_conn()
            c = conn.cursor()
            c.execute('''
                CREATE TABLE IF NOT EXISTS system_config (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')
            c.execute('INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)', 
                     (key, value))
            conn.commit()
            conn.close()
        elif key in ['levels', 'reward_per_level', 'vip_price', 'withdraw_threshold']:
            settings[key] = value
            # 保存到数据库
            conn = DB.get_conn()
            c = conn.cursor()
            c.execute('''
                CREATE TABLE IF NOT EXISTS system_config (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')
            c.execute('INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)', 
                     (key, str(value)))
            conn.commit()
            conn.close()
        elif key == 'service_text':
            settings[key] = value
            # 保存到数据库
            conn = DB.get_conn()
            c = conn.cursor()
            c.execute('''
                CREATE TABLE IF NOT EXISTS system_config (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')
            c.execute('INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)', 
                     (key, value))
            conn.commit()
            conn.close()
        elif key == 'broadcast_enabled':
            # 保存定时群发开关状态
            conn = DB.get_conn()
            c = conn.cursor()
            c.execute('''
                CREATE TABLE IF NOT EXISTS system_config (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')
            c.execute('INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)', 
                     (key, value))
            conn.commit()
            conn.close()
        else:
            # 对于其他未知配置项，也尝试保存到数据库
            conn = DB.get_conn()
            c = conn.cursor()
            c.execute('''
                CREATE TABLE IF NOT EXISTS system_config (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')
            c.execute('INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)', 
                     (key, str(value)))
            conn.commit()
            conn.close()
        
        return jsonify({'success': True, 'message': '设置已更新'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/publish-pinned-ad', methods=['POST'])
@login_required
def api_publish_pinned_ad():
    """发布置顶广告到所有会员群"""
    try:
        data = request.json
        content = data.get('content', '')
        
        if not content:
            return jsonify({'success': False, 'message': '广告内容不能为空'}), 400
        
        # 保存广告内容到数据库
        conn = DB.get_conn()
        c = conn.cursor()
        c.execute('INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)', 
                 ('pinned_ad', content))
        conn.commit()
        
        # 获取所有有群链接的会员
        c.execute('SELECT telegram_id, group_link FROM members WHERE group_link IS NOT NULL AND group_link != ""')
        members_with_groups = c.fetchall()
        conn.close()
        
        # 添加发布任务到队列
        global pending_broadcasts
        task = {
            'type': 'pinned_ad',
            'content': content,
            'groups': members_with_groups,
            'status': 'pending'
        }
        pending_broadcasts.append(task)
        
        return jsonify({
            'success': True, 
            'message': f'置顶广告已加入发布队列，将发送到 {len(members_with_groups)} 个群'
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# ============ 资源管理API ============

@app.route('/resources')
@login_required
def resources_page():
    """行业资源管理页面"""
    return render_template('resources.html', active_page='resources')

@app.route('/api/resource_categories')
@login_required
def api_get_resource_categories():
    """获取资源分类列表"""
    try:
        conn = DB.get_conn()
        c = conn.cursor()
        c.execute('SELECT id, name, parent_id FROM resource_categories ORDER BY id')
        rows = c.fetchall()
        
        categories = []
        for row in rows:
            cat = {'id': row[0], 'name': row[1], 'parent_id': row[2]}
            # 获取父分类名称
            if row[2] and row[2] > 0:
                c.execute('SELECT name FROM resource_categories WHERE id = ?', (row[2],))
                parent = c.fetchone()
                cat['parent_name'] = parent[0] if parent else ''
            else:
                cat['parent_name'] = ''
            categories.append(cat)
        
        conn.close()
        return jsonify({'categories': categories})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/resource_categories/<int:id>')
@login_required
def api_get_resource_category(id):
    """获取单个资源分类"""
    try:
        conn = DB.get_conn()
        c = conn.cursor()
        c.execute('SELECT id, name, parent_id FROM resource_categories WHERE id = ?', (id,))
        row = c.fetchone()
        conn.close()
        
        if row:
            return jsonify({'id': row[0], 'name': row[1], 'parent_id': row[2]})
        return jsonify({'error': '分类不存在'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/resource_categories', methods=['POST'])
@login_required
def api_create_resource_category():
    """创建资源分类"""
    try:
        data = request.json
        conn = DB.get_conn()
        c = conn.cursor()
        c.execute('INSERT INTO resource_categories (name, parent_id) VALUES (?, ?)',
                 (data['name'], data.get('parent_id', 0)))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': '创建成功'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/resource_categories/<int:id>', methods=['PUT'])
@login_required
def api_update_resource_category(id):
    """更新资源分类"""
    try:
        data = request.json
        conn = DB.get_conn()
        c = conn.cursor()
        c.execute('UPDATE resource_categories SET name = ?, parent_id = ? WHERE id = ?',
                 (data['name'], data.get('parent_id', 0), id))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': '更新成功'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/resource_categories/<int:id>', methods=['DELETE'])
@login_required
def api_delete_resource_category(id):
    """删除资源分类"""
    try:
        conn = DB.get_conn()
        c = conn.cursor()
        # 检查是否有子分类
        c.execute('SELECT COUNT(*) FROM resource_categories WHERE parent_id = ?', (id,))
        if c.fetchone()[0] > 0:
            conn.close()
            return jsonify({'success': False, 'message': '该分类下有子分类，无法删除'}), 400
        # 检查是否有资源
        c.execute('SELECT COUNT(*) FROM resources WHERE category_id = ?', (id,))
        if c.fetchone()[0] > 0:
            conn.close()
            return jsonify({'success': False, 'message': '该分类下有资源，无法删除'}), 400
        
        c.execute('DELETE FROM resource_categories WHERE id = ?', (id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': '删除成功'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/resources')
@login_required
def api_get_resources():
    """获取资源列表"""
    try:
        category_id = request.args.get('category_id', type=int)
        conn = DB.get_conn()
        c = conn.cursor()
        
        if category_id:
            c.execute('''
                SELECT r.id, r.name, r.link, r.type, r.member_count, r.category_id, rc.name
                FROM resources r
                LEFT JOIN resource_categories rc ON r.category_id = rc.id
                WHERE r.category_id = ?
                ORDER BY r.id DESC
            ''', (category_id,))
        else:
            c.execute('''
                SELECT r.id, r.name, r.link, r.type, r.member_count, r.category_id, rc.name
                FROM resources r
                LEFT JOIN resource_categories rc ON r.category_id = rc.id
                ORDER BY r.id DESC
            ''')
        
        rows = c.fetchall()
        resources = []
        for row in rows:
            resources.append({
                'id': row[0],
                'name': row[1],
                'link': row[2],
                'type': row[3],
                'member_count': row[4],
                'category_id': row[5],
                'category_name': row[6] or ''
            })
        
        conn.close()
        return jsonify({'resources': resources})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/resources/<int:id>')
@login_required
def api_get_resource(id):
    """获取单个资源"""
    try:
        conn = DB.get_conn()
        c = conn.cursor()
        c.execute('SELECT id, name, link, type, member_count, category_id FROM resources WHERE id = ?', (id,))
        row = c.fetchone()
        conn.close()
        
        if row:
            return jsonify({
                'id': row[0],
                'name': row[1],
                'link': row[2],
                'type': row[3],
                'member_count': row[4],
                'category_id': row[5]
            })
        return jsonify({'error': '资源不存在'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/resources', methods=['POST'])
@login_required
def api_create_resource():
    """创建资源"""
    try:
        data = request.json
        
        # 数据验证
        if not data.get('name') or not data.get('link') or not data.get('type'):
            return jsonify({'success': False, 'message': '必填字段不能为空'}), 400
        
        if data['type'] not in ['group', 'channel']:
            return jsonify({'success': False, 'message': '资源类型不正确'}), 400
        
        # 验证链接格式
        link = data['link']
        if not (link.startswith('https://t.me/') or link.startswith('t.me/') or link.startswith('@')):
            return jsonify({'success': False, 'message': 'Telegram链接格式不正确'}), 400
        
        conn = DB.get_conn()
        c = conn.cursor()
        c.execute('''
            INSERT INTO resources (category_id, name, link, type, member_count)
            VALUES (?, ?, ?, ?, ?)
        ''', (data['category_id'], data['name'], link, data['type'], data.get('member_count', 0)))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': '创建成功'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/resources/<int:id>', methods=['PUT'])
@login_required
def api_update_resource(id):
    """更新资源"""
    try:
        data = request.json
        conn = DB.get_conn()
        c = conn.cursor()
        c.execute('''
            UPDATE resources 
            SET category_id = ?, name = ?, link = ?, type = ?, member_count = ?
            WHERE id = ?
        ''', (data['category_id'], data['name'], data['link'], data['type'], 
              data.get('member_count', 0), id))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': '更新成功'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/resources/<int:id>', methods=['DELETE'])
@login_required
def api_delete_resource(id):
    """删除资源"""
    try:
        conn = DB.get_conn()
        c = conn.cursor()
        c.execute('DELETE FROM resources WHERE id = ?', (id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': '删除成功'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# ============ 客服管理API ============

@app.route('/customer-service')
@login_required
def customer_service_page():
    """客服管理页面"""
    return render_template('customer_service.html', active_page='customer_service')

@app.route('/api/customer_services')
@login_required
def api_get_customer_services():
    """获取客服列表"""
    try:
        services = DB.get_customer_services()
        return jsonify(services)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/customer_services/<int:id>')
@login_required
def api_get_customer_service(id):
    """获取单个客服"""
    try:
        conn = DB.get_conn()
        c = conn.cursor()
        c.execute('SELECT id, name, link FROM customer_service WHERE id = ?', (id,))
        row = c.fetchone()
        conn.close()
        
        if row:
            return jsonify({'id': row[0], 'name': row[1], 'link': row[2]})
        return jsonify({'error': '客服不存在'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/customer_services', methods=['POST'])
@login_required
def api_create_customer_service():
    """创建客服"""
    try:
        data = request.json
        
        # 数据验证
        if not data.get('name') or not data.get('link'):
            return jsonify({'success': False, 'message': '客服名称和链接不能为空'}), 400
        
        # 验证链接格式
        link = data['link']
        if not (link.startswith('https://t.me/') or link.startswith('t.me/') or link.startswith('@')):
            return jsonify({'success': False, 'message': 'Telegram链接格式不正确'}), 400
        
        conn = DB.get_conn()
        c = conn.cursor()
        c.execute('INSERT INTO customer_service (name, link) VALUES (?, ?)',
                 (data['name'], link))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': '创建成功'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/customer_services/<int:id>', methods=['PUT'])
@login_required
def api_update_customer_service(id):
    """更新客服"""
    try:
        data = request.json
        conn = DB.get_conn()
        c = conn.cursor()
        c.execute('UPDATE customer_service SET name = ?, link = ? WHERE id = ?',
                 (data['name'], data['link'], id))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': '更新成功'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/customer_services/<int:id>', methods=['DELETE'])
@login_required
def api_delete_customer_service(id):
    """删除客服"""
    try:
        conn = DB.get_conn()
        c = conn.cursor()
        c.execute('DELETE FROM customer_service WHERE id = ?', (id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': '删除成功'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# ============ 收益记录管理 ============

@app.route('/earnings')
@login_required
def earnings_page():
    """收益记录管理页面"""
    return render_template('earnings.html', active_page='earnings')

@app.route('/api/earnings')
@login_required
def api_get_earnings():
    """获取收益记录列表"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        search = request.args.get('search', '').strip()
        
        conn = DB.get_conn()
        c = conn.cursor()
        offset = (page - 1) * per_page
        
        # 构建查询
        where_clause = ''
        params = []
        
        if search:
            # 搜索用户ID或用户名
            if search.isdigit():
                where_clause = 'WHERE er.member_id = ?'
                params = [int(search)]
            else:
                where_clause = 'WHERE m.username LIKE ?'
                params = [f'%{search}%']
        
        # 获取总数
        count_query = f'''
            SELECT COUNT(*) FROM earnings_records er
            LEFT JOIN members m ON er.member_id = m.telegram_id
            {where_clause}
        '''
        c.execute(count_query, params)
        total = c.fetchone()[0]
        
        # 获取数据
        query = f'''
            SELECT er.id, er.member_id, m.username, er.amount, er.source_type, 
                   er.description, er.create_time
            FROM earnings_records er
            LEFT JOIN members m ON er.member_id = m.telegram_id
            {where_clause}
            ORDER BY er.create_time DESC
            LIMIT ? OFFSET ?
        '''
        c.execute(query, params + [per_page, offset])
        
        records = []
        for row in c.fetchall():
            records.append({
                'id': row[0],
                'member_id': row[1],
                'username': row[2] or '',
                'amount': row[3],
                'source_type': row[4] or '',
                'description': row[5] or '',
                'create_time': row[6][:19] if row[6] else ''
            })
        
        conn.close()
        
        return jsonify({
            'success': True,
            'records': records,
            'total': total,
            'page': page,
            'pages': (total + per_page - 1) // per_page if total > 0 else 1,
            'per_page': per_page
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# ==================== 新增功能路由 ====================


# API: 手动群发消息
@app.route('/api/broadcast/send', methods=['POST'])
@login_required
def api_broadcast_send():
    """手动群发消息到指定群组"""
    import asyncio
    data = request.get_json()
    message = data.get('message', '')
    group_ids = data.get('group_ids', [])
    send_all = data.get('all', False)
    
    if not message:
        return jsonify({'success': False, 'message': '消息内容不能为空'})
    
    conn = DB.get_conn()
    c = conn.cursor()
    
    if send_all:
        c.execute('SELECT id, group_link, group_name FROM member_groups')
    else:
        if not group_ids:
            return jsonify({'success': False, 'message': '请选择群组'})
        placeholders = ','.join(['?' for _ in group_ids])
        c.execute(f'SELECT id, group_link, group_name FROM member_groups WHERE id IN ({placeholders})', group_ids)
    
    groups = c.fetchall()
    conn.close()
    
    if not groups:
        return jsonify({'success': False, 'message': '没有找到群组'})
    
    # 加入发送队列
    sent = 0
    for g in groups:
        group_link = g[1]
        if group_link and 't.me/' in group_link:
            try:
                # 添加到待发送队列
                pending_broadcasts.append({
                    'type': 'broadcast',
                    'group_links': [group_link],
                    'message_content': message
                })
                sent += 1
            except:
                pass
    
    return jsonify({'success': True, 'sent': sent, 'message': f'已加入发送队列: {sent}个群组'})

# API: 捡漏账号列表（按ID排序，只显示会员管理中设置的）
@app.route('/api/fallback_accounts')
@app.route('/api/settings/fallback-accounts')
@app.route('/api/fallback-accounts')
@login_required
def api_fallback_accounts():
    """获取捡漏账号列表（只显示会员管理中设置为捡漏的账号）"""
    try:
        conn = DB.get_conn()
        c = conn.cursor()
        # 只获取在fallback_accounts表中的账号，按ID排序
        c.execute('''
            SELECT fa.id, fa.telegram_id, fa.username, fa.group_link, fa.total_earned, fa.is_active,
                   m.is_vip, m.balance
            FROM fallback_accounts fa
            LEFT JOIN members m ON fa.telegram_id = m.telegram_id
            ORDER BY fa.id ASC
        ''')
        accounts = []
        for row in c.fetchall():
            accounts.append({
                'id': row[0],
                'telegram_id': row[1],
                'username': row[2] or '',
                'group_link': row[3] or '',
                'total_earned': row[4] or 0,
                'is_active': row[5] if row[5] is not None else 1,
                'is_vip': row[6] if row[6] is not None else 0,
                'balance': row[7] if row[7] is not None else 0
            })
        conn.close()
        return jsonify({'success': True, 'accounts': accounts})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# API: 更新捡漏账号
@app.route('/api/fallback-accounts/<int:id>', methods=['PUT'])
@login_required
def api_update_fallback_account(id):
    """更新捡漏账号"""
    try:
        data = request.json
        conn = DB.get_conn()
        c = conn.cursor()
        
        updates = []
        params = []
        
        if 'username' in data:
            updates.append('username = ?')
            params.append(data['username'])
        if 'group_link' in data:
            updates.append('group_link = ?')
            params.append(data['group_link'])
        
        if updates:
            params.append(id)
            c.execute(f'UPDATE fallback_accounts SET {", ".join(updates)} WHERE id = ?', params)
            conn.commit()
        
        conn.close()
        return jsonify({'success': True, 'message': '更新成功'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# API: 删除捡漏账号
@app.route('/api/fallback-accounts/<int:id>', methods=['DELETE'])
@login_required
def api_delete_fallback_account(id):
    """删除捡漏账号"""
    try:
        conn = DB.get_conn()
        c = conn.cursor()
        c.execute('DELETE FROM fallback_accounts WHERE id = ?', (id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': '删除成功'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# API: 更新捡漏账号状态
@app.route('/api/fallback-accounts/<int:id>/status', methods=['PUT'])
@login_required
def api_toggle_fallback_account_status(id):
    """切换捡漏账号启用/停用状态"""
    try:
        data = request.json
        is_active = data.get('is_active', True)
        conn = DB.get_conn()
        c = conn.cursor()
        c.execute('UPDATE fallback_accounts SET is_active = ? WHERE id = ?', (1 if is_active else 0, id))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': '状态更新成功'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# API: Bot Token列表  
@app.route('/api/settings/bot-tokens')
@login_required
def api_bot_tokens():
    """获取Bot Token列表"""
    try:
        conn = DB.get_conn()
        c = conn.cursor()
        c.execute("SELECT value FROM system_config WHERE key LIKE 'bot_token_%'")
        tokens = [row[0] for row in c.fetchall()]
        conn.close()
        return jsonify({'success': True, 'tokens': tokens})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# API: 添加Bot Token
@app.route('/api/settings/bot-tokens', methods=['POST'])
@login_required  
def api_add_bot_token():
    """添加Bot Token"""
    try:
        data = request.json
        token = data.get('token', '').strip()
        if not token:
            return jsonify({'success': False, 'message': 'Token不能为空'}), 400
        
        conn = DB.get_conn()
        c = conn.cursor()
        # 获取下一个序号
        c.execute("SELECT COUNT(*) FROM system_config WHERE key LIKE 'bot_token_%'")
        count = c.fetchone()[0]
        key = f'bot_token_{count + 1}'
        c.execute('INSERT INTO system_config (key, value) VALUES (?, ?)', (key, token))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': 'Token已添加'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# API: 删除Bot Token
@app.route('/api/settings/bot-tokens/<int:index>', methods=['DELETE'])
@login_required
def api_delete_bot_token(index):
    """删除Bot Token"""
    try:
        conn = DB.get_conn()
        c = conn.cursor()
        c.execute("DELETE FROM system_config WHERE key = ?", (f'bot_token_{index + 1}',))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': 'Token已删除'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# 从complete_all_features模块导入并注册所有新路由

# 更新members表结构（添加缺失的字段）
def upgrade_members_table():
    conn = DB.get_conn()
    c = conn.cursor()
    try:
        c.execute('ALTER TABLE members ADD COLUMN is_group_bound INTEGER DEFAULT 0')
    except: pass
    try:
        c.execute('ALTER TABLE members ADD COLUMN is_bot_admin INTEGER DEFAULT 0')
    except: pass
    try:
        c.execute('ALTER TABLE members ADD COLUMN is_joined_upline INTEGER DEFAULT 0')
    except: pass
    try:
        c.execute('ALTER TABLE members ADD COLUMN level_path TEXT')
    except: pass
    try:
        c.execute('ALTER TABLE members ADD COLUMN direct_count INTEGER DEFAULT 0')
    except: pass
    try:
        c.execute('ALTER TABLE members ADD COLUMN team_count INTEGER DEFAULT 0')
    except: pass
    try:
        c.execute('ALTER TABLE members ADD COLUMN total_earned REAL DEFAULT 0')
    except: pass
    try:
        c.execute('ALTER TABLE members ADD COLUMN withdraw_address TEXT')
    except: pass
    conn.commit()
    conn.close()

upgrade_members_table()

# 更新member_groups表结构
def upgrade_member_groups_table():
    conn = DB.get_conn()
    c = conn.cursor()
    try:
        c.execute('ALTER TABLE member_groups ADD COLUMN owner_username TEXT')
    except: pass
    try:
        c.execute('ALTER TABLE member_groups ADD COLUMN group_type TEXT DEFAULT "group"')
    except: pass
    try:
        c.execute('ALTER TABLE member_groups ADD COLUMN schedule_broadcast INTEGER DEFAULT 1')
    except: pass
    conn.commit()
    conn.close()

upgrade_member_groups_table()

# 更新broadcast_messages表结构
def upgrade_broadcast_table():
    conn = DB.get_conn()
    c = conn.cursor()
    try:
        c.execute('ALTER TABLE broadcast_messages ADD COLUMN image_url TEXT')
    except: pass
    try:
        c.execute('ALTER TABLE broadcast_messages ADD COLUMN video_url TEXT')
    except: pass
    try:
        c.execute('ALTER TABLE broadcast_messages ADD COLUMN buttons TEXT')
    except: pass
    try:
        c.execute('ALTER TABLE broadcast_messages ADD COLUMN buttons_per_row INTEGER DEFAULT 2')
    except: pass
    try:
        c.execute('ALTER TABLE broadcast_messages ADD COLUMN schedule_enabled INTEGER DEFAULT 0')
    except: pass
    try:
        c.execute('ALTER TABLE broadcast_messages ADD COLUMN schedule_time TEXT')
    except: pass
    conn.commit()
    conn.close()

upgrade_broadcast_table()
from complete_all_features import add_new_routes_to_app
add_new_routes_to_app(app, DB, login_required, jsonify, request, render_template)

# 导入并注册缺失的功能路由
from missing_routes import add_missing_routes
add_missing_routes(app, DB, login_required, jsonify, request, render_template, pending_broadcasts)

def start_web_server():
    """在后台线程启动Web服务器"""
    app.run(debug=False, host='0.0.0.0', port=5051, use_reloader=False)

# 主函数
def main():
    print('=' * 60)
    print('🤖 裂变推广机器人启动中...')
    print('=' * 60)
    print()
    print('📊 初始化数据库...')
    init_db()
    print('✅ 数据库初始化完成')
    print()
    
    # 启动Web管理后台（后台线程）
    print('🌐 启动Web管理后台...')
    web_thread = threading.Thread(target=start_web_server, daemon=False)
    web_thread.start()
    print('✅ Web管理后台已启动')
    print()
    
    print('🚀 Telegram机器人已启动')
    print()
    print('=' * 60)
    print('📱 访问地址：')
    if USE_PROXY:
        print('   本地访问：http://localhost:5051')
    else:
        print('   服务器访问：http://liebian.mifzla.top')
        print('   IP访问：http://118.107.0.247:5051')
    print('=' * 60)
    print()
    print('💡 提示：')
    print('   - 所有服务正在运行中...')
    print('   - 按 Ctrl+C 停止所有服务')
    print('   - 机器人和Web后台同时运行')
    print('=' * 60)
    print()
    
    # 注册所有消息处理器
    
    # 注册回调处理器
    
    # 注册管理员回调
    
    # 注册群欢迎消息
    
    # 注册消息处理器


    # 注册新增命令
    @bot.on(events.NewMessage(pattern='/bind_group'))
    async def bind_group_cmd(event):
        # 账号关联处理
        try:
            original_sender_id = event.sender_id
            event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
        except: pass
        await handle_bind_group(event, bot, DB)
    
    @bot.on(events.NewMessage(pattern='/join_upline'))
    async def join_upline_cmd(event):
        # 账号关联处理
        try:
            original_sender_id = event.sender_id
            event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
        except: pass
        await handle_join_upline(event, bot, DB, get_system_config)
    
    @bot.on(events.NewMessage(pattern='/check_status'))
    async def check_status_cmd(event):
        # 账号关联处理
        try:
            original_sender_id = event.sender_id
            event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
        except: pass
        await handle_check_status(event, bot, DB)
    
    @bot.on(events.NewMessage(pattern='/my_team'))
    async def my_team_cmd(event):
        # 账号关联处理
        try:
            original_sender_id = event.sender_id
            event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
        except: pass
        await handle_my_team(event, bot, DB)
    
    # 处理群链接消息（非命令的文本消息）
    @bot.on(events.NewMessage(func=lambda e: not e.message.text.startswith('/')))
    async def text_message_handler(event):
        # 账号关联处理
        try:
            original_sender_id = event.sender_id
            event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
        except: pass
        text = event.message.text.strip()
        # 检测是否是群链接
        if text.startswith('https://t.me/') or text.startswith('@'):
            await handle_group_link_message(event, bot, DB)
    
    # 群发任务处理器
    async def auto_broadcast_timer():
        """定时自动群发 - 根据设置的间隔时间自动发送消息"""
        import time
        last_broadcast_time = 0
        
        while True:
            try:
                await asyncio.sleep(10)  # 每10秒检查一次
                # 处理通知队列
                while notify_queue:
                    item = notify_queue.pop(0)
                    try:
                        await bot.send_message(item['member_id'], item['message'])
                        print(f"✅ 通知已发送: 用户{item['member_id']}")
                    except Exception as e:
                        print(f"发送通知失败: {e}")
                
                print("[定时群发] 正在检查...", flush=True)
                
                conn = DB.get_conn()
                c = conn.cursor()
                
                # 检查是否开启定时群发
                c.execute("SELECT value FROM system_config WHERE key = 'broadcast_enabled'")
                row = c.fetchone()
                broadcast_enabled = row[0] == '1' if row else False
                
                if not broadcast_enabled:
                    conn.close()
                    continue
                
                # 获取间隔时间（分钟）
                c.execute("SELECT value FROM system_config WHERE key = 'broadcast_interval'")
                row = c.fetchone()
                interval_minutes = int(row[0]) if row else 200
                interval_seconds = interval_minutes * 60
                
                # 检查是否到达发送时间
                current_time = time.time()
                if current_time - last_broadcast_time < interval_seconds:
                    conn.close()
                    continue
                
                # 获取启用的群发消息
                c.execute("SELECT id, title, content, image_url, video_url, buttons, buttons_per_row FROM broadcast_messages WHERE is_active = 1 LIMIT 1")
                msg = c.fetchone()
                
                if not msg:
                    conn.close()
                    continue
                
                msg_id, title, msg_content, image_url, video_url, buttons_json, buttons_per_row = msg
                
                # 解析按钮
                import json
                inline_buttons = None
                btn_count = 0
                if buttons_json:
                    try:
                        buttons_data = json.loads(buttons_json)
                        if buttons_data:
                            per_row = buttons_per_row or 2
                            button_rows = []
                            current_row = []
                            for btn in buttons_data:
                                if btn.get('name') and btn.get('url'):
                                    current_row.append(Button.url(btn['name'], btn['url']))
                                    if len(current_row) >= per_row:
                                        button_rows.append(current_row)
                                        current_row = []
                            if current_row:
                                button_rows.append(current_row)
                            if button_rows:
                                inline_buttons = button_rows
                                btn_count = len(buttons_data)
                    except Exception as e:
                        print(f"[定时群发] 解析按钮失败: {e}")

                # 获取所有群组
                c.execute("SELECT group_link, group_name FROM member_groups WHERE schedule_broadcast = 1")
                groups = c.fetchall()

                if not groups:
                    conn.close()
                    continue

                print(f"[定时群发] 开始发送消息到 {len(groups)} 个群组, 按钮数: {btn_count}")

                sent_count = 0
                for group_link, group_name in groups:
                    try:
                        if group_link and 't.me/' in group_link:
                            chat_username = group_link.split('t.me/')[-1].split('/')[0].split('?')[0]
                            if not chat_username.startswith('+'):
                                # 发送消息（带按钮）
                                if image_url:
                                    # 处理本地上传的图片路径
                                    file_path = image_url
                                    if image_url.startswith('/static/uploads/'):
                                        file_path = '/www/wwwroot/liebian.mifzla.top' + image_url
                                    await bot.send_file(f'@{chat_username}', file_path, caption=msg_content, buttons=inline_buttons)
                                elif video_url:
                                    # 处理本地上传的视频路径
                                    file_path = video_url
                                    if video_url.startswith('/static/uploads/'):
                                        file_path = '/www/wwwroot/liebian.mifzla.top' + video_url
                                    await bot.send_file(f'@{chat_username}', file_path, caption=msg_content, buttons=inline_buttons)
                                else:
                                    await bot.send_message(f'@{chat_username}', msg_content, buttons=inline_buttons)
                                sent_count += 1
                                print(f"[定时群发] 已发送到 {group_name}")
                                await asyncio.sleep(2)
                    except Exception as e:
                        print(f"[定时群发] 发送到 {group_name} 失败: {e}")

                last_broadcast_time = current_time
                print(f"[定时群发] 本次发送完成，成功 {sent_count}/{len(groups)} 个群")
                
                conn.close()
            except Exception as e:
                print(f"[定时群发] 错误: {e}")
                await asyncio.sleep(60)

    async def process_broadcast_queue():
        """处理群发队列"""
        while True:
            try:
                await asyncio.sleep(5)  # 每5秒检查一次
                conn = DB.get_conn()
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
                                await bot.send_message(f'@{chat_username}', message)
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

    
    async def check_member_status_task():
        """定期检查会员状态（拉群、群管、加群）"""
        while True:
            try:
                await asyncio.sleep(60)  # 每1分钟检查一次
                print("[状态检测] 开始检查会员状态...")
                
                conn = DB.get_conn()
                c = conn.cursor()
                
                # 获取所有有群链接的会员
                c.execute("""
                    SELECT telegram_id, group_link, referrer_id 
                    FROM members 
                    WHERE group_link IS NOT NULL AND group_link != ''
                """)
                members = c.fetchall()
                
                for telegram_id, group_link, referrer_id in members:
                    try:
                        # 提取群组用户名或ID
                        if group_link.startswith('https://t.me/'):
                            group_username = group_link.replace('https://t.me/', '').split('/')[0].split('?')[0]
                        elif group_link.startswith('@'):
                            group_username = group_link[1:]
                        else:
                            group_username = group_link
                        
                        # 跳过私有群链接
                        if group_username.startswith('+'):
                            continue
                        
                        # 检查1：是否已拉群（群链接是否有效）
                        is_group_bound = 0
                        is_bot_admin = 0
                        is_joined_upline = 0
                        
                        try:
                            # 获取群组信息
                            chat = await bot.get_entity(group_username)
                            is_group_bound = 1  # 群链接有效
                            
                            # 检查2：机器人是否是群管理员
                            try:
                                me = await bot.get_me()
                                participants = await bot.get_participants(chat, filter=ChannelParticipantsAdmins())
                                admin_ids = [p.id for p in participants]
                                if me.id in admin_ids:
                                    is_bot_admin = 1
                            except Exception as admin_err:
                                print(f"[状态检测] 检查群管失败 {group_username}: {admin_err}")
                            
                            # 检查3：用户是否加入了上级的群
                            if referrer_id:
                                c.execute("SELECT group_link FROM members WHERE telegram_id = ?", (referrer_id,))
                                upline_row = c.fetchone()
                                if upline_row and upline_row[0]:
                                    upline_group_link = upline_row[0]
                                    if upline_group_link.startswith('https://t.me/'):
                                        upline_group_username = upline_group_link.replace('https://t.me/', '').split('/')[0].split('?')[0]
                                    elif upline_group_link.startswith('@'):
                                        upline_group_username = upline_group_link[1:]
                                    else:
                                        upline_group_username = upline_group_link
                                    
                                    if not upline_group_username.startswith('+'):
                                        try:
                                            upline_chat = await bot.get_entity(upline_group_username)
                                            participants = await bot.get_participants(upline_chat, limit=1000)
                                            member_ids = [p.id for p in participants]
                                            if telegram_id in member_ids:
                                                is_joined_upline = 1
                                        except Exception as upline_err:
                                            print(f"[状态检测] 检查加群失败 {upline_group_username}: {upline_err}")
                        
                        except Exception as e:
                            print(f"[状态检测] 检查群组失败 {group_username}: {e}")
                        
                        # 更新数据库
                        c.execute("""
                            UPDATE members 
                            SET is_group_bound = ?, is_bot_admin = ?, is_joined_upline = ?
                            WHERE telegram_id = ?
                        """, (is_group_bound, is_bot_admin, is_joined_upline, telegram_id))
                        
                        await asyncio.sleep(1)  # 避免频率限制
                        
                    except Exception as member_err:
                        print(f"[状态检测] 处理会员 {telegram_id} 失败: {member_err}")
                        continue
                
                conn.commit()
                conn.close()
                print(f"[状态检测] 完成检查 {len(members)} 个会员")
                
            except Exception as e:
                print(f"[状态检测] 任务错误: {e}")
                await asyncio.sleep(60)
    


    # 启动群发处理任务
    bot.loop.create_task(process_broadcasts())
    bot.loop.create_task(check_member_status_task())
    bot.loop.create_task(process_broadcast_queue())
    bot.loop.create_task(auto_broadcast_timer())
    print("✅ 群发队列处理器已启动")
    print("✅ 定时自动群发已启动")

    bot.run_until_disconnected()


async def process_broadcasts():
        """定期检查并处理待发送的群发任务"""
        while True:
            try:
                global pending_broadcasts
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
                            conn = DB.get_conn()
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





# 内部API：发送提现通知
@app.route('/internal/notify', methods=['POST'])
def internal_notify():
    """内部API：发送通知给用户"""
    try:
        data = request.json
        member_id = data['member_id']
        message = data['message']
        
        # 添加到队列
        notify_queue.append({'member_id': member_id, 'message': message})
        print(f"✅ 通知已加入队列: 用户{member_id}")
        
        return jsonify({'success': True})
    except Exception as e:
        print(f"内部API失败: {e}")
        return jsonify({'success': False, 'error': str(e)})



@bot.on(events.NewMessage(pattern='/myid'))
async def myid_cmd(event):
    # 账号关联处理
    try:
        original_sender_id = event.sender_id
        event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
    except: pass
    try:
        main_id = get_main_account_id(event.sender_id, getattr(event.sender, 'username', None))
        status = "主账号" if main_id == event.sender_id else "备用账号"
        await event.respond(f"👤 账号信息\n├ 当前ID: `{event.sender_id}`\n├ 主账号ID: `{main_id}`\n└ 状态: {status}", parse_mode='Markdown')
    except Exception as e:
        await event.respond(f"❌ 查询失败: {str(e)}")

@bot.on(events.NewMessage(pattern='/link (\d+) @?([a-zA-Z0-9_]+)'))
async def link_account_cmd(event):
    # 账号关联处理
    try:
        original_sender_id = event.sender_id
        event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
    except: pass
    try:
        main_id = event.sender_id
        backup_id = int(event.pattern_match.group(1))
        backup_username = event.pattern_match.group(2)
        success, message = link_account(main_id, backup_id, backup_username)
        await event.respond(message)
    except Exception as e:
        await event.respond(f"❌ 绑定失败: {str(e)}")

if __name__ == '__main__':
    main()
