"""
Web后台层 - 统一管理所有Flask路由
所有路由都在此文件中直接定义，不再依赖外部路由文件
"""
import os
import uuid
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request, redirect, url_for
from flask_login import LoginManager, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

from database import DB, WebDB, AdminUser, get_system_config, get_db_conn, get_cn_time
from config import UPLOAD_DIR

# 延迟导入bot，避免循环依赖
try:
    from bot_logic import bot, process_recharge, admin_manual_vip_handler, notify_queue, pending_broadcasts
except ImportError:
    # 如果导入失败，设置为None，后续使用时再导入
    bot = None
    process_recharge = None
    admin_manual_vip_handler = None
    notify_queue = []
    pending_broadcasts = []

# 初始化Flask
template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates')
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static')
app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
app.secret_key = 'fission-bot-secret-key-2025'
app.config['REMEMBER_COOKIE_DURATION'] = timedelta(days=90)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return WebDB.get_user_by_id(int(user_id))

# ==================== 支付系统配置 ====================
PAYMENT_CONFIG = {
    'api_url': 'https://usdt.qxzy7888.org/pay/',
    'partner_id': '15',
    'key': '5c9dd0b054b184f964',
    'notify_url': 'http://154.201.68.178:5051/api/payment/notify',
    'return_url': 'http://154.201.68.178:5051/payment/success',
    'pay_type': 'trc20',
    'version': '1.0'
}

import hashlib
import requests as req

def generate_payment_sign(params, key):
    """生成支付签名"""
    sorted_params = sorted([(k, v) for k, v in params.items() if v is not None and v != ''])
    sign_str = '&'.join([f'{k}={v}' for k, v in sorted_params])
    sign_str += f'&key={key}'
    return hashlib.md5(sign_str.encode()).hexdigest().upper()

# ==================== 登录认证 ====================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.json
        username = data.get('username')
        password = data.get('password')
        remember = data.get('remember', False)
        
        user = WebDB.get_user_by_username(username)
        if user and check_password_hash(user.password_hash, password):
            from flask_login import login_user
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

# ==================== 基础页面路由 ====================

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

@app.route('/recharges')
@login_required
def recharges():
    """充值订单管理页面"""
    return render_template('recharges.html')

@app.route('/earnings')
@login_required
def earnings_page():
    """收益记录管理页面"""
    return render_template('earnings.html', active_page='earnings')

@app.route('/resources')
@login_required
def resources_page():
    """行业资源管理页面"""
    return render_template('resources.html', active_page='resources')

@app.route('/customer-service')
@login_required
def customer_service_page():
    """客服管理页面"""
    return render_template('customer_service.html', active_page='customer_service')

@app.route('/broadcast')
@login_required
def broadcast_page():
    """群发管理页面"""
    return render_template('broadcast.html', active_page='broadcast')

@app.route('/bot-settings')
@login_required
def bot_settings_page():
    """机器人设置页面"""
    return render_template('bot_settings.html', active_page='bot_settings')

@app.route('/level-settings')
@login_required
def level_settings_page():
    """层级设置页面"""
    return render_template('level_settings.html', active_page='level_settings')

@app.route('/member-groups')
@login_required
def member_groups_page():
    """会员群管理页面"""
    return render_template('member_groups.html', active_page='member_groups')

@app.route('/fallback-accounts')
@login_required
def fallback_accounts_page():
    """捡漏账号管理页面"""
    return render_template('fallback_accounts.html', active_page='fallback_accounts')

@app.route('/team-graph')
@login_required
def team_graph_index():
    """团队图谱入口页"""
    return render_template('team_graph_all.html', active_page='team_graph')

@app.route('/team-graph/<int:telegram_id>')
@login_required
def team_graph_page(telegram_id):
    """团队图谱详情页面"""
    return render_template('team_graph.html', telegram_id=telegram_id, active_page='team_graph')

# ==================== 支付回调 ====================

@app.route('/api/payment/notify', methods=['POST'])
def payment_notify():
    """支付回调处理"""
    try:
        data = request.form.to_dict()
        print(f'[支付回调] 收到数据: {data}')
        
        sign = data.pop('sign', '')
        remark = data.pop('remark', '')
        
        calculated_sign = generate_payment_sign(data, PAYMENT_CONFIG['key'])
        
        if sign != calculated_sign:
            print(f'[支付回调] 签名验证失败')
            return 'fail'
        
        if data.get('status') == '4' and data.get('callbacks') == 'ORDER_SUCCESS':
            out_trade_no = data.get('out_trade_no')
            amount = float(data.get('amount', 0))
            
            if out_trade_no and out_trade_no.startswith('RCH_'):
                parts = out_trade_no.split('_')
                if len(parts) >= 2:
                    telegram_id = int(parts[1])
                    conn = get_db_conn()
                    c = conn.cursor()
                    
                    c.execute('SELECT id, status FROM recharge_records WHERE order_id = ?', (out_trade_no,))
                    existing = c.fetchone()
                    
                    if existing:
                        if existing[1] != 'completed':
                            c.execute('UPDATE recharge_records SET status = ? WHERE order_id = ?', 
                                    ('completed', out_trade_no))
                            c.execute('UPDATE members SET balance = balance + ? WHERE telegram_id = ?', 
                                    (amount, telegram_id))
                            conn.commit()
                            
                            # 发送通知
                            msg = f"✅ 充值成功\n\n💰 金额: {amount} USDT\n📝 订单号: {out_trade_no}\n\n余额已到账，感谢您的支持！"
                            if not notify_queue:
                                from bot_logic import notify_queue
                            notify_queue.append({'member_id': telegram_id, 'message': msg})
                        conn.close()
                        return 'success'
                    else:
                        c.execute('''INSERT INTO recharge_records 
                                   (member_id, amount, order_id, status, payment_method, create_time) 
                                   VALUES (?, ?, ?, ?, ?, ?)''',
                                (telegram_id, amount, out_trade_no, 'completed', 'USDT', get_cn_time()))
                        c.execute('UPDATE members SET balance = balance + ? WHERE telegram_id = ?', 
                                (amount, telegram_id))
                        conn.commit()
                        conn.close()
                        
                        msg = f"✅ 充值成功\n\n💰 金额: {amount} USDT\n📝 订单号: {out_trade_no}\n\n余额已到账，感谢您的支持！"
                        if not notify_queue:
                            from bot_logic import notify_queue
                        notify_queue.append({'member_id': telegram_id, 'message': msg})
                        return 'success'
        
        return 'success'
    except Exception as e:
        print(f'[支付回调] 错误: {e}')
        import traceback
        traceback.print_exc()
        return 'fail'

@app.route('/payment/success')
def payment_success():
    return '<html><head><meta charset=utf-8><title>支付成功</title></head><body style=text-align:center;padding:50px><h1>支付成功</h1><p>充值订单已提交</p></body></html>'

# ==================== 内部API ====================

@app.route('/internal/notify', methods=['POST'])
def internal_notify():
    """内部API：发送通知给用户"""
    try:
        data = request.json
        member_id = data['member_id']
        message = data['message']
        notify_queue.append({'member_id': member_id, 'message': message})
        print(f"✅ 通知已加入队列: 用户{member_id}")
        return jsonify({'success': True})
    except Exception as e:
        print(f"内部API失败: {e}")
        return jsonify({'success': False, 'error': str(e)})

# ==================== 关键API路由 =====================

@app.route('/api/members')
@login_required
def api_members():
    """获取会员列表API"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '', type=str)
    filter_type = request.args.get('filter', 'all', type=str)
    
    # 使用WebDB的完整方法（需要从main.py迁移完整实现）
    # 这里简化处理，实际应该调用完整的 get_all_members
    data = WebDB.get_all_members(page, per_page, search, filter_type)
    return jsonify(data)

@app.route('/api/member/<int:telegram_id>')
@login_required
def api_member_detail(telegram_id):
    """获取会员详情API"""
    member = WebDB.get_member_detail(telegram_id)
    if member:
        return jsonify({'success': True, 'member': member})
    return jsonify({'success': False, 'message': '会员不存在'}), 404

@app.route('/api/member/<int:telegram_id>', methods=['PUT'])
@login_required
def api_update_member(telegram_id):
    """更新会员信息API"""
    data = request.json
    WebDB.update_member(telegram_id, data)
    return jsonify({'success': True, 'message': '更新成功'})

@app.route('/api/member/<int:telegram_id>', methods=['DELETE'])
@login_required
def api_delete_member(telegram_id):
    """删除会员API"""
    WebDB.delete_member(telegram_id)
    return jsonify({'success': True, 'message': '删除成功'})

@app.route('/api/member/add', methods=['POST'])
@login_required
def api_add_member():
    """添加会员API"""
    try:
        data = request.json
        telegram_id = data.get('telegram_id')
        username = data.get('username', '')
        referrer_id = data.get('referrer_id')
        
        if not telegram_id:
            return jsonify({'success': False, 'message': 'telegram_id不能为空'}), 400
        
        # 检查是否已存在
        existing = DB.get_member(telegram_id)
        if existing:
            return jsonify({'success': False, 'message': '会员已存在'}), 400
        
        # 创建会员
        DB.create_member(telegram_id, username, referrer_id)
        return jsonify({'success': True, 'message': '添加成功'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/member/<int:telegram_id>/graph')
@login_required
def api_member_graph(telegram_id):
    """获取会员关系图谱"""
    conn = get_db_conn()
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
        is_valid = ref_row[4] and ref_row[5] and ref_row[6]
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
                c.execute("""SELECT telegram_id, username, is_vip,
                    is_group_bound, is_bot_admin, is_joined_upline
                    FROM members WHERE referrer_id = ? LIMIT 100""", (parent_id,))
            else:
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
                c.execute('SELECT COUNT(*) FROM members WHERE referrer_id = ?', (d[0],))
                d_direct = c.fetchone()[0]
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
    chart_data = WebDB.get_chart_data()
    return jsonify(chart_data)

@app.route('/api/dashboard/stats')
@login_required
def api_dashboard_stats():
    """获取仪表盘统计数据"""
    try:
        from datetime import datetime, timedelta
        conn = get_db_conn()
        c = conn.cursor()
        
        today = datetime.now().strftime('%Y-%m-%d')
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        month_start = datetime.now().strftime('%Y-%m-01')
        
        c.execute('SELECT COUNT(*) FROM members')
        total_members = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM members WHERE is_vip = 1')
        vip_members = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM members WHERE DATE(register_time) = ?', (today,))
        today_register = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM members WHERE DATE(register_time) = ?', (yesterday,))
        yesterday_register = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM members WHERE DATE(register_time) >= ?', (month_start,))
        month_register = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM members WHERE is_vip = 1 AND DATE(vip_time) = ?', (today,))
        today_vip = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM members WHERE is_vip = 1 AND DATE(vip_time) = ?', (yesterday,))
        yesterday_vip = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM members WHERE is_vip = 1 AND DATE(vip_time) >= ?', (month_start,))
        month_vip = c.fetchone()[0]
        
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

@app.route('/api/member-groups')
@login_required
def api_get_member_groups():
    """获取会员群列表"""
    try:
        search = request.args.get('search', '').strip()
        conn = get_db_conn()
        c = conn.cursor()
        
        if search:
            c.execute('''
                SELECT 
                    mg.id, mg.telegram_id, mg.group_id, mg.group_name,
                    mg.group_link, mg.member_count, mg.bot_id, mg.is_bot_admin,
                    mg.create_time, m.username
                FROM member_groups mg
                LEFT JOIN members m ON mg.telegram_id = m.telegram_id
                WHERE mg.group_name LIKE ? OR mg.group_link LIKE ? OR m.username LIKE ?
                ORDER BY mg.id DESC
            ''', (f'%{search}%', f'%{search}%', f'%{search}%'))
        else:
            c.execute('''
                SELECT 
                    mg.id, mg.telegram_id, mg.group_id, mg.group_name,
                    mg.group_link, mg.member_count, mg.bot_id, mg.is_bot_admin,
                    mg.create_time, m.username
                FROM member_groups mg
                LEFT JOIN members m ON mg.telegram_id = m.telegram_id
                ORDER BY mg.id DESC
            ''')
        
        rows = c.fetchall()
        groups = []
        for row in rows:
            groups.append({
                'id': row[0],
                'telegram_id': row[1],
                'group_id': row[2],
                'group_name': row[3] or '',
                'group_link': row[4] or '',
                'member_count': row[5] or 0,
                'bot_id': row[6],
                'is_bot_admin': row[7],
                'create_time': row[8][:19] if row[8] else '',
                'owner_username': row[9] or ''
            })
        
        conn.close()
        return jsonify({'success': True, 'groups': groups})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/fallback-accounts')
@login_required
def api_fallback_accounts():
    """获取捡漏账号列表"""
    try:
        conn = get_db_conn()
        c = conn.cursor()
        c.execute('''
            SELECT fa.id, fa.telegram_id, fa.username, fa.group_link, fa.total_earned, fa.is_active,
                   m.is_vip, m.balance
            FROM fallback_accounts fa
            LEFT JOIN members m ON fa.telegram_id = m.telegram_id
            ORDER BY fa.id ASC
        ''')
        accounts = []
        for row in c.fetchall():
            telegram_id = row[1]
            c.execute('''
                SELECT COALESCE(SUM(amount), 0) 
                FROM earnings_records 
                WHERE member_id = ? AND source_type = 'fallback_commission'
            ''', (telegram_id,))
            calculated_total = c.fetchone()[0] or 0
            
            stored_total = row[4] or 0
            if abs(calculated_total - stored_total) > 0.01:
                c.execute('UPDATE fallback_accounts SET total_earned = ? WHERE telegram_id = ?', 
                         (calculated_total, telegram_id))
                conn.commit()
                stored_total = calculated_total
            
            accounts.append({
                'id': row[0],
                'telegram_id': telegram_id,
                'username': row[2] or str(telegram_id),
                'group_link': row[3] or '',
                'total_earned': stored_total,
                'is_active': row[5] if row[5] is not None else 1,
                'is_vip': row[6] if row[6] is not None else 0,
                'balance': row[7] if row[7] is not None else 0
            })
        conn.close()
        return jsonify({'success': True, 'accounts': accounts})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/earnings')
@login_required
def api_get_earnings():
    """获取收益记录列表"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        search = request.args.get('search', '').strip()
        
        conn = get_db_conn()
        c = conn.cursor()
        offset = (page - 1) * per_page
        
        where_clause = ''
        params = []
        
        if search:
            if search.isdigit():
                where_clause = 'WHERE er.member_id = ?'
                params = [int(search)]
            else:
                where_clause = 'WHERE (m.username LIKE ? OR fa.username LIKE ?)'
                params = [f'%{search}%', f'%{search}%']
        
        count_query = f'''
            SELECT COUNT(*) FROM earnings_records er
            LEFT JOIN members m ON er.member_id = m.telegram_id
            LEFT JOIN fallback_accounts fa ON er.member_id = fa.telegram_id
            {where_clause}
        '''
        c.execute(count_query, params)
        total = c.fetchone()[0]
        
        query = f'''
            SELECT er.id, er.member_id, 
                   COALESCE(m.username, fa.username, '') as username,
                   er.amount, er.source_type, 
                   er.description, er.create_time
            FROM earnings_records er
            LEFT JOIN members m ON er.member_id = m.telegram_id
            LEFT JOIN fallback_accounts fa ON er.member_id = fa.telegram_id
            {where_clause}
            ORDER BY er.create_time DESC
            LIMIT ? OFFSET ?
        '''
        c.execute(query, params + [per_page, offset])
        
        records = []
        for row in c.fetchall():
            member_id = row[1]
            username = row[2] or ''
            
            if member_id and not username:
                c2 = conn.cursor()
                c2.execute('SELECT username, telegram_id FROM fallback_accounts WHERE telegram_id = ?', (member_id,))
                fb_row = c2.fetchone()
                if fb_row:
                    username = fb_row[0] or ''
                    if not username:
                        username = str(fb_row[1]) if fb_row[1] else str(member_id)
                else:
                    c2.execute('SELECT username FROM members WHERE telegram_id = ?', (member_id,))
                    m_row = c2.fetchone()
                    if m_row and m_row[0]:
                        username = m_row[0]
                    else:
                        username = str(member_id)
            
            if not member_id and row[4] == 'fallback_commission':
                c2 = conn.cursor()
                c2.execute('SELECT telegram_id, username FROM fallback_accounts WHERE is_active = 1 ORDER BY id LIMIT 1')
                fb_row = c2.fetchone()
                if fb_row:
                    member_id = fb_row[0]
                    username = fb_row[1] or str(fb_row[0])
                else:
                    username = '未知账号'
                    member_id = 0
            
            records.append({
                'id': row[0],
                'member_id': member_id if member_id is not None else 0,
                'username': username or (str(member_id) if member_id else 'N/A'),
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

@app.route('/api/resource_categories')
@login_required
def api_get_resource_categories():
    """获取资源分类列表"""
    try:
        categories = DB.get_resource_categories(0)
        return jsonify({'success': True, 'categories': categories})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/broadcast/messages')
@login_required
def api_get_broadcast_messages():
    """获取群发内容列表"""
    try:
        conn = get_db_conn()
        c = conn.cursor()
        c.execute("""SELECT id, title, content, media_type, media_url, is_active, create_time,
                    image_url, video_url, buttons, buttons_per_row, schedule_enabled, schedule_time
                    FROM broadcast_messages ORDER BY id DESC""")
        rows = c.fetchall()
        messages = []
        for row in rows:
            messages.append({
                'id': row[0],
                'title': row[1],
                'content': row[2],
                'media_type': row[3],
                'media_url': row[4],
                'is_active': row[5],
                'create_time': row[6],
                'image_url': row[7] or '',
                'video_url': row[8] or '',
                'buttons': row[9] or '[]',
                'buttons_per_row': row[10] or 2,
                'schedule_enabled': row[11] or 0,
                'schedule_time': row[12] or ''
            })
        conn.close()
        return jsonify({'success': True, 'messages': messages})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/bot-configs')
@login_required
def api_bot_configs():
    """获取Bot配置列表"""
    try:
        conn = get_db_conn()
        c = conn.cursor()
        c.execute("SELECT value FROM system_config WHERE key LIKE 'bot_token_%'")
        tokens = [row[0] for row in c.fetchall()]
        conn.close()
        return jsonify({'success': True, 'tokens': tokens})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/welcome-messages')
@login_required
def api_welcome_messages():
    """获取欢迎消息列表"""
    try:
        config = get_system_config()
        return jsonify({
            'success': True,
            'welcome_enabled': config.get('welcome_enabled', '0'),
            'welcome_message': config.get('welcome_message', '')
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/advertisements')
@login_required
def api_advertisements():
    """获取广告列表"""
    try:
        conn = get_db_conn()
        c = conn.cursor()
        c.execute("SELECT id, content, is_active, create_time FROM broadcast_messages WHERE media_type = 'ad' ORDER BY id DESC")
        rows = c.fetchall()
        ads = []
        for row in rows:
            ads.append({
                'id': row[0],
                'content': row[1],
                'is_active': row[2],
                'create_time': row[3]
            })
        conn.close()
        return jsonify({'success': True, 'advertisements': ads})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/level-settings')
@login_required
def api_level_settings():
    """获取层级设置"""
    try:
        config = get_system_config()
        return jsonify({
            'success': True,
            'level_count': config.get('level_count', 10),
            'level_reward': config.get('level_reward', 1.0)
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

@app.route('/api/recharges')
@login_required
def api_recharges():
    """获取充值订单列表"""
    try:
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
        search = request.args.get('search', '').lstrip('@').strip()
        
        conn = get_db_conn()
        c = conn.cursor()
        
        where_clause = ''
        params = []
        if search:
            where_clause = 'WHERE r.member_id LIKE ? OR r.order_id LIKE ? OR m.username LIKE ?'
            search_param = f'%{search}%'
            params = [search_param, search_param, search_param]
        
        count_query = f'SELECT COUNT(*) FROM recharge_records r LEFT JOIN members m ON r.member_id = m.telegram_id {where_clause}'
        c.execute(count_query, params)
        total = c.fetchone()[0]
        
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

@app.route('/api/recharges/<int:recharge_id>/status', methods=['POST'])
@login_required
def api_update_recharge_status(recharge_id):
    """【核心修复】后台手动修改充值订单状态 - 统一调用 process_recharge"""
    try:
        data = request.get_json() or {}
        new_status = (data.get('status') or '').strip()
        if not new_status:
            return jsonify({'success': False, 'message': '缺少状态参数'})

        conn = get_db_conn()
        c = conn.cursor()
        c.execute('SELECT member_id, amount, status, order_id FROM recharge_records WHERE id = ?', (recharge_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            return jsonify({'success': False, 'message': '订单不存在'})

        member_id, amount, old_status, order_id = row
        
        if new_status != 'completed':
            c.execute('UPDATE recharge_records SET status = ? WHERE id = ?', (new_status, recharge_id))
            conn.commit()
            conn.close()
            return jsonify({'success': True, 'message': '订单状态已更新'})

        if old_status == 'completed':
            conn.close()
            return jsonify({'success': True, 'message': '该订单已是已支付状态，无需重复处理'})

        # 标记为已支付，并为用户增加余额
        c.execute('UPDATE recharge_records SET status = ? WHERE id = ?', ('completed', recharge_id))
        c.execute('UPDATE members SET balance = balance + ? WHERE telegram_id = ?', (amount, member_id))
        conn.commit()
        conn.close()

        # 【核心修复】统一走异步充值处理逻辑（process_recharge：自动开VIP + 条件检测 + 捡漏账号）
        try:
            if bot:
                bot.loop.create_task(process_recharge(member_id, amount, is_vip_order=True))
            else:
                from bot_logic import bot, process_recharge
                bot.loop.create_task(process_recharge(member_id, amount, is_vip_order=True))
            print(f'[后台充值状态修改] 已创建 process_recharge 任务: member_id={member_id}, amount={amount}')
        except Exception as async_err:
            print(f'[后台充值状态修改] 调用 process_recharge 失败: {async_err}')
            import traceback
            traceback.print_exc()

        return jsonify({'success': True, 'message': '已标记为已支付并触发统一充值处理逻辑'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/members/broadcast', methods=['POST'])
@login_required
def api_members_broadcast():
    """向会员发送群发消息"""
    try:
        data = request.get_json() or {}
        message = (data.get('message') or '').strip()
        member_ids = data.get('member_ids') or []
        send_all = bool(data.get('all'))

        if not message:
            return jsonify({'success': False, 'message': '消息内容不能为空'})

        conn = get_db_conn()
        c = conn.cursor()

        targets = []
        if send_all:
            c.execute('SELECT telegram_id FROM members')
            targets = [row[0] for row in c.fetchall()]
        else:
            ids = []
            for mid in member_ids:
                try:
                    ids.append(int(mid))
                except (TypeError, ValueError):
                    continue
            if not ids:
                conn.close()
                return jsonify({'success': False, 'message': '请选择要发送的会员'})
            placeholders = ','.join(['?' for _ in ids])
            c.execute(f'SELECT telegram_id FROM members WHERE telegram_id IN ({placeholders})', ids)
            targets = [row[0] for row in c.fetchall()]

        conn.close()

        if not targets:
            return jsonify({'success': False, 'message': '未找到对应的会员'})

        # 确保notify_queue已初始化
        if not notify_queue:
            from bot_logic import notify_queue
        
        for mid in targets:
            notify_queue.append({'member_id': mid, 'message': message})

        count = len(targets)
        return jsonify({'success': True, 'count': count, 'message': f'已加入发送队列，将向 {count} 位会员发送'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/settings', methods=['GET'])
@login_required
def api_get_settings():
    """获取系统设置API"""
    try:
        config = get_system_config()
        return jsonify({
            'success': True,
            'settings': {
                'levels': config.get('level_count', 10),
                'reward_per_level': config.get('level_reward', 1),
                'vip_price': config.get('vip_price', 10),
                'withdraw_threshold': config.get('withdraw_threshold', 50),
                'usdt_address': config.get('usdt_address', ''),
                'service_text': config.get('support_text', ''),
                'pinned_ad': config.get('pinned_ad', ''),
                'welcome_message': config.get('welcome_message', ''),
                'welcome_enabled': config.get('welcome_enabled', '1'),
                'auto_register_enabled': config.get('auto_register_enabled', '0')
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

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
        
        from database import update_system_config
        update_system_config(key, value)
        
        return jsonify({'success': True, 'message': '设置已更新'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# ==================== 管理员手动开通VIP API ====================

@app.route('/api/member/<int:telegram_id>/manual-vip', methods=['POST'])
@login_required
def api_manual_vip(telegram_id):
    """
    【核心修复】管理员手动开通VIP - 统一调用 distribute_vip_rewards
    删除所有手写分红逻辑
    """
    try:
        config = get_system_config()
        
        # 【核心修复】使用bot的事件循环创建异步任务
        # Flask是同步的，所以通过事件循环创建任务，不等待结果
        if bot:
            bot.loop.create_task(admin_manual_vip_handler(telegram_id, config))
        else:
            # 如果bot未初始化，延迟导入
            from bot_logic import bot, admin_manual_vip_handler
            bot.loop.create_task(admin_manual_vip_handler(telegram_id, config))
        
        return jsonify({
            'success': True,
            'message': 'VIP开通任务已提交，正在后台处理中...'
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

def run_web():
    """Web 启动入口"""
    print("🌐 Web管理后台启动中...")
    app.run(debug=False, host='0.0.0.0', port=5051, use_reloader=False)

__all__ = ['app', 'run_web']

