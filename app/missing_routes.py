"""
所有缺失功能的API路由
"""
import os
import uuid
import sys

# 导入配置
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
from app.config import UPLOAD_DIR

def add_missing_routes(app, DB, login_required, jsonify, request, render_template, pending_broadcasts_queue):
    """添加所有缺失的路由"""
    
    # ==================== 群发管理 ====================
    # 注意：/broadcast 路由已在 web_app.py 中定义，这里跳过以避免冲突
    # @app.route('/broadcast')
    # @login_required
    # def broadcast_page():
    #     """群发管理页面"""
    #     return render_template('broadcast.html', active_page='broadcast')
    

    # 文件上传API
    UPLOAD_FOLDER = UPLOAD_DIR
    ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'webm', 'mov', 'avi'}
    
    # 确保上传目录存在
    # UPLOAD_FOLDER 已在 config.py 中创建
    
    @app.route('/api/upload', methods=['POST'])
    @login_required
    def api_upload_file():
        """上传文件"""
        try:
            if 'file' not in request.files:
                return jsonify({'success': False, 'message': '没有文件'})
            
            file = request.files['file']
            file_type = request.form.get('type', 'image')
            
            if file.filename == '':
                return jsonify({'success': False, 'message': '没有选择文件'})
            
            # 获取文件扩展名
            ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
            
            # 验证文件类型
            if file_type == 'image':
                if ext not in ALLOWED_IMAGE_EXTENSIONS:
                    return jsonify({'success': False, 'message': '不支持的图片格式'})
            elif file_type == 'video':
                if ext not in ALLOWED_VIDEO_EXTENSIONS:
                    return jsonify({'success': False, 'message': '不支持的视频格式'})
            
            # 生成唯一文件名
            filename = f"{uuid.uuid4().hex}.{ext}"
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            
            # 保存文件
            file.save(filepath)
            
            # 返回访问URL
            url = f"/static/uploads/{filename}"
            return jsonify({'success': True, 'url': url, 'filename': filename})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})

    @app.route('/api/broadcast/messages')
    @login_required
    def api_get_broadcast_messages():
        """获取群发内容列表"""
        try:
            conn = DB.get_conn()
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
            return jsonify({'messages': messages})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/broadcast/message/<int:msg_id>', methods=['GET'])
    @login_required
    def api_get_broadcast_message(msg_id):
        """获取单条群发内容"""
        try:
            conn = DB.get_conn()
            c = conn.cursor()
            c.execute('''
                SELECT id, title, content, media_type, media_url, is_active,
                       image_url, video_url, buttons, buttons_per_row,
                       schedule_enabled, schedule_time
                FROM broadcast_messages WHERE id = ?
            ''', (msg_id,))
            row = c.fetchone()
            conn.close()
            
            if not row:
                return jsonify({'success': False, 'message': '消息不存在'}), 404
            
            return jsonify({
                'success': True,
                'message': {
                    'id': row[0],
                    'title': row[1],
                    'content': row[2],
                    'media_type': row[3],
                    'media_url': row[4],
                    'is_active': row[5],
                    'image_url': row[6] or '',
                    'video_url': row[7] or '',
                    'buttons': row[8] or '[]',
                    'buttons_per_row': row[9] or 2,
                    'schedule_enabled': row[10] or 0,
                    'schedule_time': row[11] or ''
                }
            })
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500

    @app.route('/api/broadcast/message', methods=['POST'])
    @login_required
    def api_create_broadcast_message():
        """创建群发内容"""
        try:
            data = request.get_json()
            conn = DB.get_conn()
            c = conn.cursor()
            c.execute('''
                INSERT INTO broadcast_messages (title, content, media_type, media_url, image_url, video_url, buttons, buttons_per_row, schedule_enabled, schedule_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                data['title'], 
                data['content'], 
                data.get('media_type', 'text'), 
                data.get('media_url', ''),
                data.get('image_url', ''),
                data.get('video_url', ''),
                data.get('buttons', '[]'),
                data.get('buttons_per_row', 2),
                data.get('schedule_enabled', 0),
                data.get('schedule_time', '')
            ))
            conn.commit()
            conn.close()
            return jsonify({'success': True, 'message': '群发内容创建成功'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
    
    @app.route('/api/broadcast/message/<int:msg_id>', methods=['PUT'])
    @login_required
    def api_update_broadcast_message(msg_id):
        """更新群发内容"""
        try:
            data = request.get_json()
            print(f"[更新消息] ID={msg_id}, buttons={data.get('buttons', 'NONE')}")
            conn = DB.get_conn()
            c = conn.cursor()
            c.execute('''
                UPDATE broadcast_messages
                SET title=?, content=?, media_type=?, media_url=?, is_active=?,
                    image_url=?, video_url=?, buttons=?, buttons_per_row=?,
                    schedule_enabled=?, schedule_time=?
                WHERE id=?
            ''', (
                data['title'], 
                data['content'], 
                data.get('media_type', 'text'),
                data.get('media_url', ''), 
                data.get('is_active', 1),
                data.get('image_url', ''),
                data.get('video_url', ''),
                data.get('buttons', '[]'),
                data.get('buttons_per_row', 2),
                data.get('schedule_enabled', 0),
                data.get('schedule_time', ''),
                msg_id
            ))
            conn.commit()
            conn.close()
            return jsonify({'success': True, 'message': '更新成功'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
    
    @app.route('/api/broadcast/message/<int:msg_id>', methods=['DELETE'])
    @login_required
    def api_delete_broadcast_message(msg_id):
        """删除群发内容"""
        try:
            conn = DB.get_conn()
            c = conn.cursor()
            c.execute('DELETE FROM broadcast_messages WHERE id=?', (msg_id,))
            conn.commit()
            conn.close()
            return jsonify({'success': True, 'message': '删除成功'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
    
    @app.route('/api/broadcast/send', methods=['POST'])
    @login_required
    def api_send_broadcast():
        """执行群发"""
        try:
            data = request.get_json()
            message_id = data['message_id']
            group_ids = data.get('group_ids', [])  # 空列表表示全部群
            
            conn = DB.get_conn()
            c = conn.cursor()
            
            # 获取消息内容
            c.execute('SELECT content FROM broadcast_messages WHERE id = ?', (message_id,))
            message_row = c.fetchone()
            if not message_row:
                conn.close()
                return jsonify({'success': False, 'message': '消息不存在'}), 404
            
            message_content = message_row[0]
            
            # 获取所有已绑定的会员群（有群链接的会员）
            c.execute('SELECT group_link FROM members WHERE group_link IS NOT NULL AND group_link != ""')
            groups = c.fetchall()
            
            # 记录群发日志
            c.execute('''
                INSERT INTO broadcast_logs (message_id, group_ids, status)
                VALUES (?, ?, 'pending')
            ''', (message_id, ','.join(map(str, group_ids)) if group_ids else 'all'))
            log_id = c.lastrowid
            conn.commit()
            conn.close()
            
            # 添加任务到队列
            pending_broadcasts_queue.append({
                'log_id': log_id,
                'message_content': message_content,
                'group_links': [g[0] for g in groups]
            })
            
            return jsonify({'success': True, 'message': f'群发任务已提交，预计发送到{len(groups)}个群组', 'log_id': log_id})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
    
    # ==================== 机器人设置 ====================
    
    @app.route('/bot-settings')
    @login_required
    def bot_settings_page():
        """机器人设置页面"""
        return render_template('bot_settings.html', active_page='bot_settings')
    
    @app.route('/api/bot-configs')
    @login_required
    def api_get_bot_configs():
        """获取机器人配置列表"""
        try:
            conn = DB.get_conn()
            c = conn.cursor()
            c.execute('SELECT * FROM bot_configs ORDER BY id DESC')
            rows = c.fetchall()
            configs = []
            for row in rows:
                configs.append({
                    'id': row[0],
                    'bot_token': row[1],
                    'bot_username': row[2],
                    'is_active': row[3],
                    'api_id': row[4],
                    'api_hash': row[5],
                    'create_time': row[6]
                })
            conn.close()
            return jsonify({'configs': configs})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/bot-config', methods=['POST'])
    @login_required
    def api_create_bot_config():
        """添加机器人配置"""
        try:
            data = request.get_json()
            conn = DB.get_conn()
            c = conn.cursor()
            c.execute('''
                INSERT INTO bot_configs (bot_token, bot_username, api_id, api_hash)
                VALUES (?, ?, ?, ?)
            ''', (data['bot_token'], data.get('bot_username', ''), 
                  data.get('api_id', 0), data.get('api_hash', '')))
            conn.commit()
            conn.close()
            return jsonify({'success': True, 'message': '机器人配置添加成功'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
    
    @app.route('/api/advertisements')
    @login_required
    def api_get_advertisements():
        """获取广告列表"""
        try:
            conn = DB.get_conn()
            c = conn.cursor()
            c.execute('SELECT * FROM advertisements ORDER BY id DESC')
            rows = c.fetchall()
            ads = []
            for row in rows:
                ads.append({
                    'id': row[0],
                    'title': row[1],
                    'content': row[2],
                    'position': row[3],
                    'is_active': row[4],
                    'create_time': row[5]
                })
            conn.close()
            return jsonify({'ads': ads})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/advertisement', methods=['POST'])
    @login_required
    def api_create_advertisement():
        """创建广告"""
        try:
            data = request.get_json()
            conn = DB.get_conn()
            c = conn.cursor()
            c.execute('''
                INSERT INTO advertisements (title, content, position)
                VALUES (?, ?, ?)
            ''', (data['title'], data['content'], data.get('position', 'top')))
            conn.commit()
            conn.close()
            return jsonify({'success': True, 'message': '广告创建成功'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
    
    @app.route('/api/advertisement/<int:ad_id>', methods=['PUT'])
    @login_required
    def api_update_advertisement(ad_id):
        """更新广告"""
        try:
            data = request.get_json()
            conn = DB.get_conn()
            c = conn.cursor()
            c.execute('''
                UPDATE advertisements 
                SET title=?, content=?, position=?, is_active=?
                WHERE id=?
            ''', (data['title'], data['content'], data.get('position', 'top'),
                  data.get('is_active', 1), ad_id))
            conn.commit()
            conn.close()
            return jsonify({'success': True, 'message': '更新成功'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
    
    @app.route('/api/advertisement/<int:ad_id>', methods=['DELETE'])
    @login_required
    def api_delete_advertisement(ad_id):
        """删除广告"""
        try:
            conn = DB.get_conn()
            c = conn.cursor()
            c.execute('DELETE FROM advertisements WHERE id=?', (ad_id,))
            conn.commit()
            conn.close()
            return jsonify({'success': True, 'message': '删除成功'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
    
    @app.route('/api/publish-ad/<int:ad_id>', methods=['POST'])
    @login_required
    def api_publish_ad(ad_id):
        """发布指定广告到所有会员群并置顶"""
        try:
            conn = DB.get_conn()
            c = conn.cursor()
            
            # 获取广告内容
            c.execute('SELECT title, content FROM advertisements WHERE id=?', (ad_id,))
            ad = c.fetchone()
            if not ad:
                conn.close()
                return jsonify({'success': False, 'message': '广告不存在'}), 404
            
            title, content = ad
            ad_text = f'📢 {title}\n\n{content}'
            
            # 获取所有有群链接的会员
            c.execute('SELECT telegram_id, group_link FROM members WHERE group_link IS NOT NULL AND group_link != ""')
            members_with_groups = c.fetchall()
            conn.close()
            
            if not members_with_groups:
                return jsonify({'success': False, 'message': '没有找到任何会员群'})
            
            # 添加发布任务到队列
            task = {
                'type': 'pinned_ad',
                'content': ad_text,
                'groups': members_with_groups,
                'status': 'pending'
            }
            pending_broadcasts_queue.append(task)
            
            return jsonify({
                'success': True, 
                'message': f'广告已加入发布队列，将发送到 {len(members_with_groups)} 个群'
            })
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
    
    @app.route('/api/welcome-messages')
    @login_required
    def api_get_welcome_messages():
        """获取欢迎语列表"""
        try:
            conn = DB.get_conn()
            c = conn.cursor()
            c.execute('SELECT * FROM welcome_messages ORDER BY id DESC')
            rows = c.fetchall()
            messages = []
            for row in rows:
                messages.append({
                    'id': row[0],
                    'group_id': row[1],
                    'message': row[2],
                    'is_active': row[3],
                    'create_time': row[4]
                })
            conn.close()
            return jsonify({'messages': messages})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/welcome-message', methods=['POST'])
    @login_required
    def api_create_welcome_message():
        """创建欢迎语"""
        try:
            data = request.get_json()
            content = data.get('content') or data.get('message', '')
            if not content:
                return jsonify({'success': False, 'message': '欢迎语内容不能为空'}), 400
            conn = DB.get_conn()
            c = conn.cursor()
            c.execute('''
                INSERT INTO welcome_messages (group_id, message)
                VALUES (?, ?)
            ''', (data.get('group_id', ''), content))
            conn.commit()
            conn.close()
            return jsonify({'success': True, 'message': '欢迎语创建成功'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
    
    @app.route('/api/welcome-message/<int:msg_id>', methods=['DELETE'])
    @login_required
    def api_delete_welcome_message(msg_id):
        """删除欢迎语"""
        try:
            conn = DB.get_conn()
            c = conn.cursor()
            c.execute('DELETE FROM welcome_messages WHERE id=?', (msg_id,))
            conn.commit()
            conn.close()
            return jsonify({'success': True, 'message': '删除成功'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
    
    @app.route('/api/statistics/enhanced-v2')
    @login_required
    def api_get_enhanced_statistics_v2():
        """增强统计 - 包含今日昨日月度对比"""
        try:
            from datetime import datetime, timedelta
            conn = DB.get_conn()
            c = conn.cursor()
            
            today = datetime.now().date()
            yesterday = today - timedelta(days=1)
            month_start = today.replace(day=1)
            
            # 今日注册
            c.execute('''
                SELECT COUNT(*) FROM members 
                WHERE DATE(register_time) = ?
            ''', (str(today),))
            today_register = c.fetchone()[0]
            
            # 昨日注册
            c.execute('''
                SELECT COUNT(*) FROM members 
                WHERE DATE(register_time) = ?
            ''', (str(yesterday),))
            yesterday_register = c.fetchone()[0]
            
            # 本月注册
            c.execute('''
                SELECT COUNT(*) FROM members 
                WHERE DATE(register_time) >= ?
            ''', (str(month_start),))
            month_register = c.fetchone()[0]
            
            # 今日VIP
            c.execute('''
                SELECT COUNT(*) FROM members 
                WHERE is_vip=1 AND DATE(vip_time) = ?
            ''', (str(today),))
            today_vip = c.fetchone()[0]
            
            # 昨日VIP
            c.execute('''
                SELECT COUNT(*) FROM members 
                WHERE is_vip=1 AND DATE(vip_time) = ?
            ''', (str(yesterday),))
            yesterday_vip = c.fetchone()[0]
            
            # 本月VIP
            c.execute('''
                SELECT COUNT(*) FROM members 
                WHERE is_vip=1 AND DATE(vip_time) >= ?
            ''', (str(month_start),))
            month_vip = c.fetchone()[0]
            
            # 捡漏账号收益统计
            c.execute('''
                SELECT 
                    SUM(total_earned) as total,
                    COUNT(*) as count
                FROM fallback_accounts
            ''')
            fallback_stats = c.fetchone()
            
            conn.close()
            
            return jsonify({
                'today_register': today_register,
                'yesterday_register': yesterday_register,
                'month_register': month_register,
                'today_vip': today_vip,
                'yesterday_vip': yesterday_vip,
                'month_vip': month_vip,
                'fallback_total_earned': fallback_stats[0] or 0,
                'fallback_account_count': fallback_stats[1] or 0
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500


    # ==================== 层级设置 ====================
    
    @app.route('/level-settings')
    @login_required
    def level_settings_page():
        """层级设置页面"""
        return render_template('level_settings.html', active_page='level_settings')
    
    @app.route('/api/level-settings', methods=['GET'])
    @login_required
    def api_get_level_settings():
        """获取层级设置"""
        try:
            conn = DB.get_conn()
            c = conn.cursor()
            
            # 获取层级数量
            c.execute("SELECT value FROM system_config WHERE key = 'level_count'")
            row = c.fetchone()
            level_count = int(row[0]) if row else 10
            
            # 获取每层金额
            level_amounts = {}
            for i in range(1, level_count + 1):
                c.execute("SELECT value FROM system_config WHERE key = ?", (f'level_{i}_amount',))
                row = c.fetchone()
                level_amounts[i] = float(row[0]) if row else 0
            
            conn.close()
            return jsonify({
                'success': True,
                'level_count': level_count,
                'level_amounts': level_amounts
            })
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    @app.route('/api/level-settings', methods=['POST'])
    @login_required
    def api_save_level_settings():
        """保存层级设置"""
        try:
            data = request.get_json()
            level_count = data.get('level_count', 10)
            level_amounts = data.get('level_amounts', {})
            
            conn = DB.get_conn()
            c = conn.cursor()
            
            # 保存层级数量
            c.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)", 
                     ('level_count', str(level_count)))
            
            # 保存每层金额
            for level, amount in level_amounts.items():
                c.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)",
                         (f'level_{level}_amount', str(amount)))
            
            # 计算VIP升级总金额
            total = sum(float(v) for v in level_amounts.values())
            c.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES (?, ?)",
                     ('vip_upgrade_amount', str(total)))
            
            conn.commit()
            conn.close()
            
            return jsonify({'success': True, 'message': '保存成功', 'vip_total': total})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})

    print("✅ 所有缺失路由已添加")
