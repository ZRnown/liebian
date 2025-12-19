"""
数据库层 - 统一管理所有数据库操作
"""
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash
from flask_login import UserMixin
from config import DB_PATH

# 定义中国时区
CN_TIMEZONE = timezone(timedelta(hours=8))

def get_cn_time():
    """获取中国时间字符串"""
    return datetime.now(CN_TIMEZONE).isoformat()

def get_db_conn():
    """获取数据库连接，设置超时和 WAL 模式以避免锁定"""
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=10000')
    return conn

def init_db():
    """初始化数据库表结构"""
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
        is_group_bound INTEGER DEFAULT 0,
        is_bot_admin INTEGER DEFAULT 0,
        is_joined_upline INTEGER DEFAULT 0,
        level_path TEXT,
        direct_count INTEGER DEFAULT 0,
        team_count INTEGER DEFAULT 0,
        total_earned REAL DEFAULT 0,
        withdraw_address TEXT,
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
        usdt_address TEXT,
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
    
    # 充值记录表
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
    
    # 捡漏账号表
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
    
    # 群发日志表
    c.execute('''CREATE TABLE IF NOT EXISTS broadcast_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id INTEGER,
        group_ids TEXT,
        status TEXT DEFAULT 'pending',
        sent_count INTEGER DEFAULT 0,
        failed_count INTEGER DEFAULT 0,
        create_time TEXT
    )''')
    
    # 广告表
    c.execute('''CREATE TABLE IF NOT EXISTS advertisements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        content TEXT,
        position TEXT DEFAULT 'top',
        is_active INTEGER DEFAULT 1,
        create_time TEXT
    )''')
    
    # 欢迎语表
    c.execute('''CREATE TABLE IF NOT EXISTS welcome_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id TEXT,
        message TEXT,
        is_active INTEGER DEFAULT 1,
        create_time TEXT
    )''')
    
    # 机器人配置表
    c.execute('''CREATE TABLE IF NOT EXISTS bot_configs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bot_token TEXT,
        bot_username TEXT,
        is_active INTEGER DEFAULT 1,
        api_id INTEGER,
        api_hash TEXT,
        create_time TEXT
    )''')

    # 检查是否有管理员，如果没有则创建默认管理员
    c.execute('SELECT COUNT(*) FROM admin_users')
    if c.fetchone()[0] == 0:
        default_password_hash = generate_password_hash('admin')
        c.execute('INSERT INTO admin_users (username, password_hash) VALUES (?, ?)', ('admin', default_password_hash))
        print('⚠️ 创建默认管理员账号: admin / admin')
    
    conn.commit()
    conn.close()

# 数据库操作类
class DB:
    @staticmethod
    def get_conn():
        """获取数据库连接"""
        return get_db_conn()
    
    @staticmethod
    def get_member(telegram_id):
        """获取会员信息"""
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
        """创建会员记录，带重试"""
        max_retries = 5
        for retry in range(max_retries):
            conn = DB.get_conn()
            c = conn.cursor()
            try:
                c.execute(
                    '''INSERT INTO members (telegram_id, username, referrer_id, register_time)
                        VALUES (?, ?, ?, ?)''',
                    (telegram_id, username, referrer_id, get_cn_time())
                )
                conn.commit()
                conn.close()
                return True
            except sqlite3.IntegrityError:
                conn.close()
                return True
            except sqlite3.OperationalError as e:
                conn.close()
                if 'locked' in str(e).lower() and retry < max_retries - 1:
                    time.sleep(0.2)
                    continue
                return False
            except Exception:
                conn.close()
                return False
        return False
    
    @staticmethod
    def update_member(telegram_id, **kwargs):
        """更新会员信息"""
        conn = DB.get_conn()
        c = conn.cursor()
        sets = ', '.join([f'{k} = ?' for k in kwargs.keys()])
        values = list(kwargs.values()) + [telegram_id]
        c.execute(f'UPDATE members SET {sets} WHERE telegram_id = ?', values)
        conn.commit()
        conn.close()
    
    @staticmethod
    def get_upline_members(telegram_id, levels=10):
        """获取上N层推荐人（已废弃，请使用 core_functions.get_upline_chain）"""
        members = []
        conn = DB.get_conn()
        c = conn.cursor()
        current_id = telegram_id
        
        for _ in range(levels):
            c.execute('SELECT referrer_id FROM members WHERE telegram_id = ?', (current_id,))
            row = c.fetchone()
            if row and row[0]:
                c.execute('SELECT telegram_id, username, is_vip, balance FROM members WHERE telegram_id = ?', (row[0],))
                member_row = c.fetchone()
                if member_row:
                    members.append({
                        'telegram_id': member_row[0],
                        'username': member_row[1],
                        'is_vip': member_row[2],
                        'balance': member_row[3]
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
        """获取客服列表"""
        conn = DB.get_conn()
        c = conn.cursor()
        c.execute('SELECT * FROM customer_service')
        rows = c.fetchall()
        conn.close()
        return [{'id': r[0], 'name': r[1], 'link': r[2]} for r in rows]
    
    @staticmethod
    def get_resource_categories(parent_id=0):
        """获取资源分类"""
        conn = DB.get_conn()
        c = conn.cursor()
        c.execute('SELECT * FROM resource_categories WHERE parent_id = ?', (parent_id,))
        rows = c.fetchall()
        conn.close()
        return [{'id': r[0], 'name': r[1]} for r in rows]
    
    @staticmethod
    def get_resources(category_id, page=1, per_page=20):
        """获取资源列表"""
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

def get_system_config():
    """从数据库动态读取系统配置"""
    conn = get_db_conn()
    c = conn.cursor()
    c.execute('SELECT key, value FROM system_config')
    config_rows = c.fetchall()
    
    # 默认配置
    config = {
        'level_count': 10,
        'level_reward': 1,
        'vip_price': 10,
        'withdraw_threshold': 50,
        'support_text': '👩‍💼 在线客服\n\n暂无客服信息，请联系管理员',
        'usdt_address': 'TUnpYkxUeawyGeMD3PGzhDkdkNYhRJcLfD',
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
    c.execute('''
        INSERT INTO system_config (key, value) 
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
    ''', (db_key, str(value)))
    conn.commit()
    conn.close()

# Web后台数据库操作类（从原WebDB类迁移）
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
            return AdminUser(row[0], row[1], row[2])
        return None

    @staticmethod
    def get_user_by_id(user_id):
        conn = DB.get_conn()
        c = conn.cursor()
        c.execute('SELECT id, username, password_hash FROM admin_users WHERE id = ?', (user_id,))
        row = c.fetchone()
        conn.close()
        if row:
            return AdminUser(row[0], row[1], row[2])
        return None
        
    @staticmethod
    def update_password(user_id, new_password):
        from werkzeug.security import generate_password_hash
        conn = DB.get_conn()
        c = conn.cursor()
        new_hash = generate_password_hash(new_password)
        c.execute('UPDATE admin_users SET password_hash = ? WHERE id = ?', (new_hash, user_id))
        conn.commit()
        conn.close()
        return True

    @staticmethod
    def get_all_members(page=1, per_page=20, search='', filter_type='all'):
        """获取所有会员列表（简化版，完整版在web_app.py中）"""
        conn = DB.get_conn()
        c = conn.cursor()
        offset = (page - 1) * per_page
        
        conditions = []
        params = []
        
        if filter_type == 'vip':
            conditions.append('is_vip = 1')
        elif filter_type == 'normal':
            conditions.append('is_vip = 0')
        
        if search:
            if search.isdigit():
                conditions.append('(CAST(telegram_id AS TEXT) LIKE ? OR username LIKE ?)')
                params.extend([f'%{search}%', f'%{search}%'])
            else:
                conditions.append('username LIKE ?')
                params.append(f'%{search}%')
        
        search_condition = 'WHERE ' + ' AND '.join(conditions) if conditions else ''
        
        c.execute(f'SELECT COUNT(*) FROM members {search_condition}', params)
        total = c.fetchone()[0]
        
        query = f'''
            SELECT id, telegram_id, username, balance, is_vip, register_time
            FROM members 
            {search_condition}
            ORDER BY id DESC 
            LIMIT ? OFFSET ?
        '''
        c.execute(query, params + [per_page, offset])
        rows = c.fetchall()
        
        members = []
        for row in rows:
            members.append({
                'id': row[0],
                'telegram_id': row[1],
                'username': row[2] or '',
                'balance': row[3],
                'is_vip': row[4],
                'register_time': row[5][:19] if row[5] else ''
            })
        
        conn.close()
        
        return {
            'members': members,
            'total': total,
            'page': page,
            'per_page': per_page,
            'pages': (total + per_page - 1) // per_page
        }

class AdminUser(UserMixin):
    """管理员用户类"""
    def __init__(self, id, username, password_hash):
        self.id = id
        self.username = username
        self.password_hash = password_hash

class WebDB:
    """Web管理后台数据库操作"""
    
    @staticmethod
    def get_user_by_username(username):
        """根据用户名获取用户"""
        conn = get_db_conn()
        c = conn.cursor()
        c.execute('SELECT id, username, password_hash FROM admin_users WHERE username = ?', (username,))
        row = c.fetchone()
        conn.close()
        if row:
            return AdminUser(row[0], row[1], row[2])
        return None
    
    @staticmethod
    def get_user_by_id(user_id):
        """根据ID获取用户"""
        conn = get_db_conn()
        c = conn.cursor()
        c.execute('SELECT id, username, password_hash FROM admin_users WHERE id = ?', (user_id,))
        row = c.fetchone()
        conn.close()
        if row:
            return AdminUser(row[0], row[1], row[2])
        return None
    
    @staticmethod
    def update_password(user_id, new_password):
        """更新密码"""
        from werkzeug.security import generate_password_hash
        conn = get_db_conn()
        c = conn.cursor()
        password_hash = generate_password_hash(new_password)
        c.execute('UPDATE admin_users SET password_hash = ? WHERE id = ?', (password_hash, user_id))
        conn.commit()
        conn.close()
    
    @staticmethod
    def get_statistics():
        """获取统计数据"""
        conn = get_db_conn()
        c = conn.cursor()
        
        c.execute('SELECT COUNT(*) FROM members')
        total_members = c.fetchone()[0] or 0
        
        c.execute('SELECT COUNT(*) FROM members WHERE is_vip = 1')
        vip_members = c.fetchone()[0] or 0
        
        c.execute('SELECT COALESCE(SUM(balance), 0) FROM members')
        total_balance = c.fetchone()[0] or 0
        
        c.execute('SELECT COALESCE(SUM(missed_balance), 0) FROM members')
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
        conn = get_db_conn()
        c = conn.cursor()
        
        # 获取近7天的注册趋势
        from datetime import datetime, timedelta
        today = datetime.now().date()
        dates = []
        counts = []
        
        for i in range(6, -1, -1):
            date = today - timedelta(days=i)
            date_str = date.strftime('%Y-%m-%d')
            dates.append(date.strftime('%m-%d'))
            
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
        conn = get_db_conn()
        c = conn.cursor()
        offset = (page - 1) * per_page
        
        try:
            search_term = search.lstrip('@').strip() if search else ''
            
            if status != 'all':
                c.execute('SELECT id, member_id, amount, usdt_address, status, create_time, process_time FROM withdrawals WHERE status = ? ORDER BY id DESC', (status,))
            else:
                c.execute('SELECT id, member_id, amount, usdt_address, status, create_time, process_time FROM withdrawals ORDER BY id DESC')
            
            all_rows = c.fetchall()
            
            results = []
            for row in all_rows:
                member_id = row[1]
                c.execute('SELECT username FROM members WHERE telegram_id = ?', (member_id,))
                user_row = c.fetchone()
                username = user_row[0] if user_row else str(member_id)
                
                if search_term:
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
        conn = get_db_conn()
        c = conn.cursor()
        
        try:
            c.execute('SELECT member_id, amount, status FROM withdrawals WHERE id = ?', (withdrawal_id,))
            row = c.fetchone()
            
            if not row:
                return False, "记录不存在"
                
            member_id, amount, status = row
            
            from datetime import datetime
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            if action == 'approve':
                if status == 'rejected':
                    c.execute('UPDATE members SET balance = balance - ? WHERE telegram_id = ?', 
                             (amount, member_id))
                
                c.execute('UPDATE withdrawals SET status = ?, process_time = ? WHERE id = ?', 
                         ('approved', now, withdrawal_id))
                
            elif action == 'reject':
                if status != 'pending':
                    return False, "只能拒绝待处理的提现"
                
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
    
    @staticmethod
    def get_all_members(page=1, per_page=20, search='', filter_type='all'):
        """获取会员列表"""
        conn = get_db_conn()
        c = conn.cursor()
        offset = (page - 1) * per_page
        
        search_term = search.lstrip('@').strip() if search else ''
        
        # 构建查询条件
        where_clauses = []
        params = []
        
        if filter_type == 'vip':
            where_clauses.append('is_vip = 1')
        elif filter_type == 'normal':
            where_clauses.append('is_vip = 0')
        
        if search_term:
            where_clauses.append('(username LIKE ? OR telegram_id LIKE ?)')
            params.extend([f'%{search_term}%', f'%{search_term}%'])
        
        where_sql = ' AND '.join(where_clauses) if where_clauses else '1=1'
        
        # 获取总数
        c.execute(f'SELECT COUNT(*) FROM members WHERE {where_sql}', params)
        total = c.fetchone()[0]
        
        # 获取分页数据
        c.execute(f'''
            SELECT telegram_id, username, balance, is_vip, register_time, vip_time, 
                   referrer_id, group_link, missed_balance, total_earned
            FROM members 
            WHERE {where_sql}
            ORDER BY id DESC
            LIMIT ? OFFSET ?
        ''', params + [per_page, offset])
        
        rows = c.fetchall()
        members = []
        for row in rows:
            members.append({
                'telegram_id': row[0],
                'username': row[1] or '',
                'balance': row[2] or 0,
                'is_vip': bool(row[3]),
                'register_time': row[4][:19] if row[4] else '',
                'vip_time': row[5][:19] if row[5] else '',
                'referrer_id': row[6],
                'group_link': row[7] or '',
                'missed_balance': row[8] or 0,
                'total_earned': row[9] or 0
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
        conn = get_db_conn()
        c = conn.cursor()
        
        c.execute('''
            SELECT telegram_id, username, balance, is_vip, register_time, vip_time,
                   referrer_id, group_link, missed_balance, total_earned, backup_account
            FROM members WHERE telegram_id = ?
        ''', (telegram_id,))
        
        row = c.fetchone()
        conn.close()
        
        if not row:
            return None
        
        return {
            'telegram_id': row[0],
            'username': row[1] or '',
            'balance': row[2] or 0,
            'is_vip': bool(row[3]),
            'register_time': row[4][:19] if row[4] else '',
            'vip_time': row[5][:19] if row[5] else '',
            'referrer_id': row[6],
            'group_link': row[7] or '',
            'missed_balance': row[8] or 0,
            'total_earned': row[9] or 0,
            'backup_account': row[10] or ''
        }
    
    @staticmethod
    def update_member(telegram_id, data):
        """更新会员信息"""
        conn = get_db_conn()
        c = conn.cursor()
        
        allowed_fields = ['username', 'balance', 'is_vip', 'group_link', 'missed_balance', 'total_earned']
        updates = []
        params = []
        
        for field in allowed_fields:
            if field in data:
                updates.append(f'{field} = ?')
                params.append(data[field])
        
        if updates:
            params.append(telegram_id)
            c.execute(f'UPDATE members SET {", ".join(updates)} WHERE telegram_id = ?', params)
            conn.commit()
        
        conn.close()
    
    @staticmethod
    def delete_member(telegram_id):
        """删除会员"""
        conn = get_db_conn()
        c = conn.cursor()
        c.execute('DELETE FROM members WHERE telegram_id = ?', (telegram_id,))
        conn.commit()
        conn.close()

# ==================== 数据库升级函数 ====================

def upgrade_members_table():
    """升级members表结构"""
    conn = get_db_conn()
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

def upgrade_member_groups_table():
    """升级member_groups表结构"""
    conn = get_db_conn()
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

def upgrade_broadcast_table():
    """升级broadcast_messages表结构"""
    conn = get_db_conn()
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

def upsert_member_group(telegram_id, group_link, owner_username=None, is_bot_admin=1):
    """
    写入或更新 member_groups 表，便于后台列表展示。
    默认 is_bot_admin=1，因为验证通过后才会调用。
    """
    if not group_link:
        return
    try:
        conn = get_db_conn()
        c = conn.cursor()
        c.execute('SELECT id FROM member_groups WHERE telegram_id = ?', (telegram_id,))
        row = c.fetchone()
        now = get_cn_time()
        if row:
            c.execute(
                '''UPDATE member_groups 
                   SET group_link = ?, owner_username = COALESCE(?, owner_username)
                 WHERE id = ?''',
                (group_link, owner_username, row[0])
            )
        else:
            c.execute(
                '''INSERT INTO member_groups 
                   (telegram_id, group_name, group_link, is_bot_admin, create_time, owner_username, group_type, schedule_broadcast)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (telegram_id, '', group_link, is_bot_admin, now, owner_username or '', 'group', 1)
            )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f'[member_groups upsert] error: {e}')

def sync_member_groups_from_members():
    """启动时同步已存在的会员群链接到 member_groups，避免后台列表为空"""
    try:
        conn = get_db_conn()
        c = conn.cursor()
        c.execute("SELECT telegram_id, username, group_link FROM members WHERE group_link IS NOT NULL AND group_link != ''")
        rows = c.fetchall()
        conn.close()
        for r in rows:
            tg_id, uname, glink = r
            try:
                upsert_member_group(tg_id, glink, uname or None, is_bot_admin=1)
            except Exception as inner_err:
                print(f'[sync_member_groups] 单条失败 {tg_id}: {inner_err}')
    except Exception as e:
        print(f'[sync_member_groups] 失败: {e}')

# 在模块加载时执行数据库升级
upgrade_members_table()
upgrade_member_groups_table()
upgrade_broadcast_table()

