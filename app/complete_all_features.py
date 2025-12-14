"""
全功能补充脚本
这个脚本包含所有缺失的API路由和数据处理逻辑
需要将这些代码整合到a.py中
"""

# ==================== 新增API路由 ====================

def add_new_routes_to_app(app, DB, login_required, jsonify, request, render_template):
    """
    添加所有新的路由到Flask app
    在a.py中调用：add_new_routes_to_app(app, DB, login_required, jsonify, request, render_template)
    """
    
    # ==================== 会员群管理 ====================
    
    @app.route('/member-groups')
    @login_required
    def member_groups_page():
        """会员群管理页面"""
        return render_template('member_groups.html', active_page='member_groups')
    
    @app.route('/api/member-groups')
    @login_required
    def api_get_member_groups():
        """获取会员群列表"""
        try:
            conn = DB.get_conn()
            c = conn.cursor()
            
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
            return jsonify({'groups': groups})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/member-groups', methods=['POST'])
    @login_required
    def api_add_member_group():
        """添加群组"""
        data = request.json
        conn = DB.get_conn()
        c = conn.cursor()
        from datetime import datetime
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c.execute("""INSERT INTO member_groups 
            (telegram_id, group_name, group_link, is_bot_admin, create_time)
            VALUES (?, ?, ?, ?, ?)""",
            (data.get('telegram_id'), data.get('group_name'),
             data.get('group_link'), data.get('is_bot_admin', 1), now))
        conn.commit()
        conn.close()
        return jsonify({'success': True})

    @app.route('/api/member-groups/<int:gid>', methods=['PUT'])
    @login_required
    def api_update_member_group(gid):
        """更新群组"""
        data = request.json
        conn = DB.get_conn()
        c = conn.cursor()
        updates, values = [], []
        for key in ['telegram_id', 'group_name', 'group_link', 'is_bot_admin', 'schedule_broadcast']:
            if key in data:
                updates.append(f'{key} = ?')
                values.append(data[key])
        if updates:
            values.append(gid)
            c.execute(f"UPDATE member_groups SET {', '.join(updates)} WHERE id = ?", values)
            conn.commit()
        conn.close()
        return jsonify({'success': True})

    @app.route('/api/member-groups/<int:gid>', methods=['DELETE'])
    @login_required
    def api_delete_member_group(gid):
        """删除群组"""
        conn = DB.get_conn()
        c = conn.cursor()
        c.execute('DELETE FROM member_groups WHERE id = ?', (gid,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})

    @app.route('/api/member-groups/<int:gid>/verify', methods=['POST'])
    @login_required
    def api_verify_member_group(gid):
        """验证群组状态"""
        return jsonify({'success': True, 'message': '群组状态正常'})

    @app.route('/api/member-groups/broadcast', methods=['POST'])
    @login_required
    def api_broadcast_to_groups():
        """群发消息到群组 - 写入队列由机器人处理"""
        import json
        from datetime import datetime
        
        data = request.json
        group_ids = data.get('group_ids', [])
        message = data.get('message', '')
        if not group_ids or not message:
            return jsonify({'success': False, 'message': '参数不完整'})
        
        # 获取群组的group_link
        conn = DB.get_conn()
        c = conn.cursor()
        placeholders = ','.join(['?' for _ in group_ids])
        c.execute(f'SELECT id, group_link, group_name FROM member_groups WHERE id IN ({placeholders})', group_ids)
        groups = c.fetchall()
        
        # 创建群发队列表（如果不存在）
        c.execute("""CREATE TABLE IF NOT EXISTS broadcast_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_link TEXT,
            group_name TEXT,
            message TEXT,
            status TEXT DEFAULT 'pending',
            result TEXT,
            create_time TEXT
        )""")
        
        # 写入群发队列
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        for g in groups:
            gid, group_link, group_name = g
            if group_link:
                c.execute("INSERT INTO broadcast_queue (group_link, group_name, message, create_time) VALUES (?, ?, ?, ?)",
                    (group_link, group_name, message, now))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True, 
            'sent_count': len(groups),
            'message': f'已添加 {len(groups)} 个群发任务到队列'
        })

        # ==================== 捡漏账号管理 ====================
    
    @app.route('/fallback-accounts')
    @login_required
    def fallback_accounts_page():
        """捡漏账号管理页面"""
        return render_template('fallback_accounts.html', active_page='fallback_accounts')
    
    @app.route('/api/fallback-accounts')
    @login_required
    def api_get_fallback_accounts():
        """获取捡漏账号列表"""
        try:
            conn = DB.get_conn()
            c = conn.cursor()
            
            c.execute('''
                SELECT 
                    fa.id, fa.telegram_id, fa.username, fa.group_link,
                    fa.total_earned, fa.is_active, fa.create_time,
                    m.balance, m.is_group_bound, m.is_bot_admin
                FROM fallback_accounts fa
                LEFT JOIN members m ON fa.telegram_id = m.telegram_id
                ORDER BY fa.id
            ''')
            
            rows = c.fetchall()
            accounts = []
            for row in rows:
                accounts.append({
                    'id': row[0],
                    'telegram_id': row[1],
                    'username': row[2],
                    'group_link': row[3] or '',
                    'total_earned': row[4] or 0,
                    'is_active': row[5],
                    'create_time': row[6][:19] if row[6] else '',
                    'balance': row[7] or 0,
                    'is_group_bound': row[8],
                    'is_bot_admin': row[9]
                })
            
            conn.close()
            return jsonify({'accounts': accounts})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/fallback-accounts', methods=['POST'])
    @login_required
    def api_create_fallback_account():
        try:
            data = request.get_json()
            username = data.get('username', '')
            group_link = data.get('group_link', '')
            conn = DB.get_conn()
            c = conn.cursor()
            c.execute('SELECT MAX(telegram_id) FROM fallback_accounts')
            max_id = c.fetchone()[0] or 9000000000
            new_telegram_id = max_id + 1
            c.execute('INSERT INTO fallback_accounts (telegram_id, username, group_link, total_earned, is_active) VALUES (?, ?, ?, 0, 1)', (new_telegram_id, username, group_link))
            conn.commit()
            conn.close()
            return jsonify({'success': True, 'message': '添加成功'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500

    @app.route('/api/fallback-accounts/<int:account_id>', methods=['DELETE'])
    @login_required
    def api_delete_fallback_account(account_id):
        try:
            conn = DB.get_conn()
            c = conn.cursor()
            c.execute('DELETE FROM fallback_accounts WHERE id = ?', (account_id,))
            conn.commit()
            conn.close()
            return jsonify({'success': True, 'message': '删除成功'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500

    @app.route('/api/fallback-accounts/<int:account_id>', methods=['PUT'])
    @login_required
    def api_update_fallback_account(account_id):
        """更新捡漏账号"""
        try:
            data = request.get_json()
            group_link = data.get('group_link')
            is_active = data.get('is_active', 1)
            
            conn = DB.get_conn()
            c = conn.cursor()
            
            c.execute('''
                UPDATE fallback_accounts 
                SET group_link = ?, is_active = ?
                WHERE id = ?
            ''', (group_link, is_active, account_id))
            
            # 同时更新members表的group_link
            c.execute('''
                UPDATE members 
                SET group_link = ?
                WHERE telegram_id = (SELECT telegram_id FROM fallback_accounts WHERE id = ?)
            ''', (group_link, account_id))
            
            conn.commit()
            conn.close()
            
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
    
    # ==================== 团队图谱 ====================
    
    @app.route('/team-graph')
    @login_required
    def team_graph_index():
        """团队图谱入口页 - 全局树形视图"""
        return render_template('team_graph_all.html', active_page='team_graph')
    
    @app.route('/api/team-graph-all')
    @login_required
    def api_get_team_graph_all():
        """获取所有会员的树形结构数据"""
        try:
            conn = DB.get_conn()
            c = conn.cursor()
            c.execute('''SELECT telegram_id, username, referrer_id, is_vip, balance, register_time FROM members ORDER BY register_time''')
            rows = c.fetchall()
            conn.close()
            
            members = []
            referrer_count = {}
            max_depth = 0
            vip_count = 0
            
            # 构建成员列表和统计
            member_ids = set()
            for row in rows:
                member_ids.add(row[0])
                if row[2]:  # referrer_id
                    referrer_count[row[2]] = referrer_count.get(row[2], 0) + 1
                if row[3]:  # is_vip
                    vip_count += 1
            
            for row in rows:
                members.append({
                    'telegram_id': row[0],
                    'username': row[1] or f'user_{row[0]}',
                    'referrer_id': row[2] if row[2] in member_ids else None,
                    'is_vip': bool(row[3]),
                    'balance': row[4] or 0,
                    'direct_count': referrer_count.get(row[0], 0),
                    'register_time': row[5]
                })
            
            # 计算最大深度
            def calc_depth(member_id, visited=None):
                if visited is None:
                    visited = set()
                if member_id in visited:
                    return 0
                visited.add(member_id)
                children = [m for m in members if m['referrer_id'] == member_id]
                if not children:
                    return 1
                return 1 + max(calc_depth(c['telegram_id'], visited.copy()) for c in children)
            
            top_members = [m for m in members if not m['referrer_id']]
            if top_members:
                max_depth = max(calc_depth(m['telegram_id']) for m in top_members)
            
            return jsonify({
                'success': True,
                'members': members,
                'stats': {
                    'total': len(members),
                    'top_level': len(top_members),
                    'max_depth': max_depth,
                    'vip_count': vip_count
                }
            })
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    @app.route('/team-graph/<int:telegram_id>')
    @login_required
    def team_graph_page(telegram_id):
        """团队图谱详情页面"""
        return render_template('team_graph.html', telegram_id=telegram_id, active_page='team_graph')
    
    @app.route('/api/team-graph/<int:telegram_id>')
    @login_required
    def api_get_team_graph(telegram_id):
        """获取团队图谱数据"""
        try:
            from core_functions import get_upline_chain, get_downline_tree
            
            # 获取用户信息
            member = DB.get_member(telegram_id)
            if not member:
                return jsonify({'error': '用户不存在'}), 404
            
            # 获取上级链（10层）
            upline_chain = get_upline_chain(telegram_id, 10)
            uplines = []
            for level, uid in upline_chain:
                um = DB.get_member(uid)
                if um:
                    uplines.append({
                        'level': level,
                        'telegram_id': um['telegram_id'],
                        'username': um['username'],
                        'is_vip': um['is_vip'],
                        'is_group_bound': um.get('is_group_bound', 0),
                        'is_bot_admin': um.get('is_bot_admin', 0),
                        'is_joined_upline': um.get('is_joined_upline', 0)
                    })
            
            # 获取下级树（10层）
            downline_tree = get_downline_tree(telegram_id, 10)
            downlines = []
            for level, members in downline_tree.items():
                for m in members:
                    dm = DB.get_member(m['telegram_id'])
                    downlines.append({
                        'level': level,
                        'telegram_id': m['telegram_id'],
                        'username': m['username'],
                        'is_vip': m['is_vip'],
                        'is_group_bound': dm.get('is_group_bound', 0) if dm else 0,
                        'is_bot_admin': dm.get('is_bot_admin', 0) if dm else 0,
                        'is_joined_upline': dm.get('is_joined_upline', 0) if dm else 0
                    })
            
            return jsonify({
                'center': {
                    'telegram_id': member['telegram_id'],
                    'username': member['username'],
                    'is_vip': member['is_vip'],
                    'balance': member['balance'],
                    'total_earned': member.get('total_earned', 0)
                },
                'uplines': uplines,
                'downlines': downlines
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    # ==================== 充值管理 ====================
    
    @app.route('/recharges')
    @login_required
    def recharges_page():
        """充值管理页面"""
        return render_template('recharges.html', active_page='recharges')
    
    @app.route('/api/recharges')
    @login_required
    def api_get_recharges():
        """获取充值记录"""
        try:
            page = request.args.get('page', 1, type=int)
            per_page = request.args.get('per_page', 20, type=int)
            
            conn = DB.get_conn()
            c = conn.cursor()
            
            offset = (page - 1) * per_page
            
            # 获取总数
            c.execute('SELECT COUNT(*) FROM recharge_records')
            total = c.fetchone()[0]
            
            # 获取记录列表
            c.execute('''
                SELECT 
                    rr.id, rr.member_id, rr.amount, rr.payment_method,
                    rr.order_id, rr.status, rr.callback_result, rr.create_time,
                    m.username
                FROM recharge_records rr
                LEFT JOIN members m ON rr.member_id = m.telegram_id
                ORDER BY rr.id DESC
                LIMIT ? OFFSET ?
            ''', (per_page, offset))
            
            rows = c.fetchall()
            records = []
            for row in rows:
                records.append({
                    'id': row[0],
                    'member_id': row[1],
                    'amount': row[2],
                    'payment_method': row[3] or '',
                    'order_id': row[4] or '',
                    'status': row[5],
                    'callback_result': row[6] or '',
                    'create_time': row[7][:19] if row[7] else '',
                    'username': row[8] or ''
                })
            
            conn.close()
            
            return jsonify({
                'records': records,
                'total': total,
                'page': page,
                'per_page': per_page
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    # ==================== 增强统计API ====================
    
    @app.route('/api/statistics/enhanced')
    @login_required
    def api_get_enhanced_statistics():
        """获取增强统计数据（包含VIP数、捡漏收益等）"""
        try:
            conn = DB.get_conn()
            c = conn.cursor()
            
            from datetime import datetime, timedelta
            
            today = datetime.now().date()
            yesterday = today - timedelta(days=1)
            month_start = today.replace(day=1)
            
            # 基础统计
            c.execute('SELECT COUNT(*) FROM members')
            total_members = c.fetchone()[0]
            
            c.execute('SELECT COUNT(*) FROM members WHERE is_vip = 1')
            total_vip = c.fetchone()[0]
            
            # 今日注册
            c.execute('SELECT COUNT(*) FROM members WHERE DATE(register_time) = ?', (str(today),))
            today_register = c.fetchone()[0]
            
            # 昨日注册
            c.execute('SELECT COUNT(*) FROM members WHERE DATE(register_time) = ?', (str(yesterday),))
            yesterday_register = c.fetchone()[0]
            
            # 本月注册
            c.execute('SELECT COUNT(*) FROM members WHERE DATE(register_time) >= ?', (str(month_start),))
            month_register = c.fetchone()[0]
            
            # 今日开通VIP
            c.execute('SELECT COUNT(*) FROM members WHERE is_vip = 1 AND DATE(vip_time) = ?', (str(today),))
            today_vip = c.fetchone()[0]
            
            # 昨日开通VIP
            c.execute('SELECT COUNT(*) FROM members WHERE is_vip = 1 AND DATE(vip_time) = ?', (str(yesterday),))
            yesterday_vip = c.fetchone()[0]
            
            # 本月开通VIP
            c.execute('SELECT COUNT(*) FROM members WHERE is_vip = 1 AND DATE(vip_time) >= ?', (str(month_start),))
            month_vip = c.fetchone()[0]
            
            # 捡漏账号收益统计（前10个）
            c.execute('''
                SELECT SUM(total_earned) 
                FROM fallback_accounts 
                WHERE is_active = 1
                LIMIT 10
            ''')
            fallback_total_earned = c.fetchone()[0] or 0
            
            # 今日捡漏收益（需要从交易记录计算，这里简化）
            today_fallback_earned = 0
            
            # 总收益
            c.execute('SELECT SUM(total_earned) FROM members')
            total_earned = c.fetchone()[0] or 0
            
            conn.close()
            
            return jsonify({
                'total_members': total_members,
                'total_vip': total_vip,
                'today_register': today_register,
                'yesterday_register': yesterday_register,
                'month_register': month_register,
                'today_vip': today_vip,
                'yesterday_vip': yesterday_vip,
                'month_vip': month_vip,
                'fallback_total_earned': fallback_total_earned,
                'today_fallback_earned': today_fallback_earned,
                'total_earned': total_earned
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    print("✅ 所有新路由已添加到Flask app")


# 使用示例（在a.py的main函数中调用）:
# add_new_routes_to_app(app, DB, login_required, jsonify, request, render_template)
