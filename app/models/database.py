"""
数据库模型和操作
"""
import sqlite3
from datetime import datetime
import sys
import os
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
from app.config import DB_PATH

class DB:
    @staticmethod
    def get_conn():
        return sqlite3.connect(DB_PATH)
    
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

