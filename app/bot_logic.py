"""
机器人逻辑层 - 统一管理所有Telegram机器人交互
【核心修复】所有VIP开通路径都调用 distribute_vip_rewards，删除冗余的手写分红逻辑
"""
import asyncio
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from telethon import TelegramClient, events, Button
from telethon.sessions import MemorySession
from telethon.tl.types import ChannelParticipantsAdmins
from telethon.tl.functions.channels import GetParticipantRequest
import socks

from config import (
    API_ID, API_HASH, BOT_TOKEN, ADMIN_IDS, USE_PROXY, 
    PROXY_TYPE, PROXY_HOST, PROXY_PORT
)
from database import DB, get_cn_time, get_system_config, get_db_conn
from core_functions import (
    get_upline_chain, check_user_conditions, update_level_path,
    distribute_vip_rewards, check_user_in_group, check_bot_is_admin,
    verify_group_link
)
from bot_commands_addon import (
    handle_bind_group, handle_join_upline, handle_group_link_message,
    handle_check_status, handle_my_team
)

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

# 初始化机器人
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

# 全局队列
pending_broadcasts = []
notify_queue = []
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
            print(f"✅ [账号劫持成功] 备用号 {target_id_str} 正在登录 -> 切换为主账号 {row[0]}")
            return row[0]
        
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
                return False, "❌ 该账号已注册，不能设置为备用号"
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
            c.execute("SELECT group_link FROM fallback_accounts WHERE is_active = 1 AND group_link IS NOT NULL AND group_link != ''")
            results = c.fetchall()
            conn.close()
            if results:
                links = []
                seen = set()
                for r in results:
                    g_links = r[0].split('\n')
                    for l in g_links:
                        l = l.strip()
                        if l and l not in seen:
                            links.append(l)
                            seen.add(l)
                return '\n'.join(links) if links else None
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
    if deduct_balance:
        if member['balance'] < vip_price:
            return False, "余额不足"
        new_balance = member['balance'] - vip_price
        DB.update_member(telegram_id, balance=new_balance, is_vip=1, vip_time=get_cn_time())
    else:
        # 管理员赠送，不扣除余额
        new_balance = member['balance']
        DB.update_member(telegram_id, is_vip=1, vip_time=get_cn_time())
    
    # 3. 更新层级路径
    update_level_path(telegram_id)
    
    # 4. 【核心】调用统一分红函数（替代所有手写循环）
    stats = await distribute_vip_rewards(bot, telegram_id, vip_price, config)
    
    return True, {
        'new_balance': new_balance,
        'stats': stats
    }

# ==================== 事件处理器 ====================

@bot.on(events.NewMessage(pattern='/start'))
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

@bot.on(events.CallbackQuery(data=b'open_vip_balance'))
async def open_vip_balance_callback(event):
    """【已修复】使用余额开通VIP - 统一调用 distribute_vip_rewards"""
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
    
    await event.answer(text, alert=True)
    try:
        await event.delete()
    except:
        pass

@bot.on(events.CallbackQuery(pattern=b'confirm_vip'))
async def confirm_vip_callback(event):
    """【已修复】确认开通VIP - 统一调用 distribute_vip_rewards"""
    config = get_system_config()
    try:
        original_sender_id = event.sender_id
        event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
    except:
        pass
    
    member = DB.get_member(event.sender_id)
    if not member:
        await event.answer('请先发送 /start 注册')
        return
    
    if member['is_vip']:
        await event.answer('您已经是VIP了!')
        return
    
    if member['balance'] < config['vip_price']:
        await event.answer(f'余额不足! 还需 {config["vip_price"] - member["balance"]} U', alert=True)
        return
    
    # 【核心修复】调用统一处理函数
    success, result = await process_vip_upgrade(event.sender_id, config['vip_price'], config)
    
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
        f'✅ 推广赚钱\n\n'
        f'已为 {stats["real"]} 位上级发放奖励\n'
        f'捡漏账号获得 {stats["fallback"]} 次奖励'
    )
    await event.answer()

# ==================== 充值处理 ====================

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

async def process_recharge(telegram_id, amount, is_vip_order=False):
    """处理充值到账"""
    try:
        config = get_system_config()
        member = DB.get_member(telegram_id)
        if member:
            new_balance = member['balance'] + amount
            DB.update_member(telegram_id, balance=new_balance)
            
            # 如果是VIP充值订单且余额足够，自动开通VIP
            if is_vip_order and new_balance >= config['vip_price'] and not member['is_vip']:
                # 【核心修复】调用统一处理函数
                success, result = await process_vip_upgrade(telegram_id, config['vip_price'], config)
                
                if success:
                    stats = result['stats']
                    new_balance = result['new_balance']
                    
                    # 获取上层群列表
                    upline_groups = []
                    chain = get_upline_chain(telegram_id, int(config['level_count']))
                    for item in chain:
                        if not item.get('is_fallback'):
                            up_member = DB.get_member(item['id'])
                            if up_member and up_member['group_link']:
                                upline_groups.append({
                                    'level': item['level'],
                                    'username': up_member['username'],
                                    'group_link': up_member['group_link']
                                })
                    
                    group_list_text = '\n'.join([f'  {g["level"]}. @{g["username"]}的群' for g in upline_groups[:5]])
                    await bot.send_message(
                        telegram_id,
                        f'🎉 充值成功！VIP已开通！\n\n'
                        f'💰 充值金额: {amount} U\n'
                        f'💳 VIP费用: {config["vip_price"]} U\n'
                        f'💵 当前余额: {new_balance} U\n\n'
                        f'✅ 已为 {stats["real"]} 位上级发放分红\n'
                        f'📊 捡漏账号获得 {stats["fallback"]} 笔分红\n\n'
                        f'⚠️ 重要：请立即完成以下操作\n\n'
                        f'1️⃣ 绑定您的群组\n'
                        f'2️⃣ 加入上层群组（共{len(upline_groups)}个）\n'
                        f'{group_list_text}\n\n'
                        f'💡 完成以上操作后，您的下级开通VIP时\n'
                        f'   您才能获得分红！',
                        parse_mode='markdown'
                    )
                    return True
            else:
                # 普通充值通知
                await bot.send_message(
                    telegram_id,
                    f'🎉 充值成功!\n\n'
                    f'充值金额: {amount} U\n'
                    f'当前余额: {new_balance} U\n\n'
                    f'💡 余额可用于开通VIP或提现'
                )
                return True
        return False
    except Exception as e:
        print(f"处理充值失败: {e}")
        import traceback
        traceback.print_exc()
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
    success, result = await process_vip_upgrade(telegram_id, config['vip_price'], config, deduct_balance=False)
    
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

@bot.on(events.NewMessage(pattern=BTN_FISSION))
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
    
    # 已开通VIP，显示上级群和推荐群组
    text = "🔗 **群裂变加入列表**\n━━━━━━━━━━━━━━━━\n\n"
    has_groups = False
    
    # 使用 get_upline_chain 获取完整的10层关系
    chain = get_upline_chain(telegram_id, 10)
    valid_upline_groups = []
    
    for item in chain:
        if item.get('is_fallback'):
            continue
            
        upline_id = item['id']
        up_member = DB.get_member(upline_id)
        if up_member and up_member.get('group_link'):
            # 检查条件
            conds = await check_user_conditions(bot, upline_id)
            if conds and conds['all_conditions_met']:
                group_links = up_member['group_link'].split('\n')
                for link in group_links:
                    if link.strip():
                        valid_upline_groups.append({
                            'level': item['level'],
                            'link': link.strip(),
                            'name': f"第{item['level']}层上级"
                        })
                        break
    
    if valid_upline_groups:
        text += "👥 **需要加入的上级群：**\n"
        for g in valid_upline_groups:
            text += f"{g['level']}. [{g['name']}]({g['link']})\n"
        text += "\n"
        has_groups = True
        
    # 获取捡漏群
    fb_groups_text = get_fallback_resource('group')
    if fb_groups_text:
        text += "🔥 **推荐加入的群组：**\n"
        fb_list = [g.strip() for g in fb_groups_text.split('\n') if g.strip()]
        for idx, link in enumerate(fb_list, 1):
            # 尝试提取群名
            group_name = link.split('/')[-1].replace('+', '')
            if 't.me' in link:
                # 从链接中提取群名（例如：https://t.me/groupname -> groupname）
                parts = link.split('/')
                if len(parts) > 0:
                    last_part = parts[-1]
                    if '+' in last_part:
                        group_name = last_part.split('+')[0]
                    else:
                        group_name = last_part
                # 如果没有提取到，使用默认名称
                if not group_name or group_name == link:
                    group_name = f"推荐群组 {idx}"
            
            text += f"{idx}. [{group_name}]({link})\n"
        has_groups = True
    
    if not has_groups:
        await event.respond("❌ 暂无可用群组，请联系管理员配置捡漏账号群链接。")
        return
        
    buttons = [[Button.inline('🔍 验证已加群', f'verify_groups_{telegram_id}'.encode())]]
    await event.respond(text, buttons=buttons, parse_mode='markdown')

# ==================== 注册其他命令处理器 ====================

@bot.on(events.NewMessage(pattern=BTN_PROFILE))
async def profile_handler(event):
    """个人中心"""
    try:
        original_id = event.sender_id
        event.sender_id = get_main_account_id(original_id, getattr(event.sender, 'username', None))
    except:
        pass
    
    member = DB.get_member(event.sender_id)
    if not member:
        await event.respond('请先发送 /start 注册')
        return
    
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
            referrer_username = referrer.get("username", "")
            referrer_info = f'👥 推荐人: @{referrer_username} ({member["referrer_id"]})' if referrer_username else f'👥 推荐人ID: {member["referrer_id"]}'
        else:
            referrer_info = f'👥 推荐人ID: {member["referrer_id"]}'
    
    # 获取状态信息
    is_group_bound = member.get("is_group_bound", 0)
    is_bot_admin = member.get("is_bot_admin", 0)
    is_joined_upline = member.get("is_joined_upline", 0)
    
    status_info = f'\n拉群: {"是" if is_group_bound else "否"}\n群管: {"是" if is_bot_admin else "否"}\n加群: {"是" if is_joined_upline else "否"}'
    
    text = f'👤 个人中心 (已同步主账号)\n\n'
    text += f'🆔 主账号ID: `{member["telegram_id"]}`\n'
    text += f'👤 主账号名: @{member["username"]}\n'
    if referrer_info:
        text += f'{referrer_info}\n'
    text += f'💎 VIP状态: {"✅ 已开通" if member["is_vip"] else "❌ 未开通"}\n'
    text += f'💰 余额: {member["balance"]} U\n'
    text += f'📉 错过余额: {member["missed_balance"]} U\n'
    text += f'🔗 群链接: {member["group_link"] or "未设置"}\n'
    text += f'📱 绑定备用号: {backup_display}\n'
    text += status_info
    text += f'\n📅 注册时间: {member["register_time"][:10] if member["register_time"] else "未知"}'
    
    await event.respond(text, buttons=buttons)

# ==================== 个人中心按钮回调处理 ====================

@bot.on(events.CallbackQuery(pattern=b'set_group'))
async def set_group_callback(event):
    """设置群链接回调"""
    # 账号关联处理（备用号->主账号）
    try:
        original_sender_id = event.sender_id
        event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
    except:
        pass
    member = DB.get_member(event.sender_id)
    if not member:
        await event.answer('请先发送 /start 注册')
        return
    
    # 切换到群链接输入时，清理备用号等待状态
    waiting_for_backup.pop(event.sender_id, None)
    waiting_for_group_link[event.sender_id] = True
    await event.respond(
        '🔗 设置群链接\n\n'
        '请发送您的群链接 (格式: http://t.me/群用户名 或 https://t.me/群用户名)\n\n'
        '发送 /cancel 取消操作'
    )
    await event.answer()

@bot.on(events.CallbackQuery(pattern=b'set_backup'))
async def set_backup_callback(event):
    """设置备用号回调"""
    # 账号关联处理（备用号->主账号）
    try:
        original_sender_id = event.sender_id
        event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
    except:
        pass
    member = DB.get_member(event.sender_id)
    if not member:
        await event.answer('请先发送 /start 注册')
        return
    
    # 切换到备用号输入时，清理群链接等待状态
    waiting_for_group_link.pop(event.sender_id, None)
    waiting_for_backup[event.sender_id] = True
    await event.respond(
        '✏️ 设置备用号\n\n'
        '请发送您的备用飞机号 (不带@的用户名或ID)\n\n'
        '发送 /cancel 取消操作'
    )
    await event.answer()

@bot.on(events.CallbackQuery(pattern=b'earnings_history'))
async def earnings_history_callback(event):
    """查看个人收益记录"""
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
    
    conn = DB.get_conn()
    c = conn.cursor()
    c.execute('''
        SELECT amount, source_type, description, create_time
        FROM earnings_records
        WHERE member_id = ?
        ORDER BY create_time DESC
        LIMIT 50
    ''', (member["telegram_id"],))
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

@bot.on(events.CallbackQuery(pattern=b'withdraw'))
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

@bot.on(events.CallbackQuery(pattern=b'do_recharge'))
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

@bot.on(events.CallbackQuery(pattern=b'open_vip'))
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
    await event.answer()

# 返回个人中心
@bot.on(events.CallbackQuery(pattern=b'back_to_profile'))
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

@bot.on(events.CallbackQuery(data=b'recharge_for_vip'))
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

@bot.on(events.NewMessage(pattern='/bind_group'))
async def bind_group_cmd(event):
    """绑定群组命令"""
    try:
        original_sender_id = event.sender_id
        event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
    except:
        pass
    await handle_bind_group(event, bot, DB)

@bot.on(events.NewMessage(pattern='/join_upline'))
async def join_upline_cmd(event):
    """加入上层群命令"""
    try:
        original_sender_id = event.sender_id
        event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
    except:
        pass
    await handle_join_upline(event, bot, DB, get_system_config)

@bot.on(events.NewMessage(pattern='/check_status'))
async def check_status_cmd(event):
    """检查状态命令"""
    try:
        original_sender_id = event.sender_id
        event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
    except:
        pass
    await handle_check_status(event, bot, DB)

@bot.on(events.NewMessage(pattern='/my_team'))
async def my_team_cmd(event):
    """我的团队命令"""
    try:
        original_sender_id = event.sender_id
        event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
    except:
        pass
    await handle_my_team(event, bot, DB)

# ==================== 其他事件处理器 ====================

@bot.on(events.NewMessage(pattern=BTN_VIEW_FISSION))
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
        text = '❌ 您还未开通VIP\n\n'
        text += f'开通VIP后可获得以下权益:\n'
        text += f'✅ 查看裂变数据\n'
        text += f'✅ 获得下级开通VIP的奖励\n'
        text += f'✅ 加入上级群组\n\n'
        text += f'💰 VIP价格: {config["vip_price"]} U'
        _fb_group = get_fallback_resource("group")
        if _fb_group:
            text += f"\n\n💡 推荐群组:\n{_fb_group}"
        await event.respond(text)
        return

    conn = get_db_conn()
    c = conn.cursor()

    text = '📊 我的裂变数据\n'
    text += '━━━━━━━━━━━━━━\n\n'

    total_members = 0
    total_vip = 0
    buttons = []

    for level in range(1, config['level_count'] + 1):
        if level == 1:
            c.execute("""
                SELECT COUNT(*), SUM(CASE WHEN is_vip = 1 THEN 1 ELSE 0 END)
                FROM members WHERE referrer_id = ?
            """, (member['telegram_id'],))
        else:
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

        btn_text = f'第{level}层: {level_total}人'
        buttons.append([Button.inline(btn_text, f'flv_{level}_1'.encode())])

    conn.close()

    text += f'━━━━━━━━━━━━━━\n'
    text += f'📈 团队总计：{total_members}人\n'
    text += f'💎 VIP会员：{total_vip}人\n'

    buttons.append([Button.inline('🏠 主菜单', b'fission_main_menu')])

    await event.respond(text, buttons=buttons)

@bot.on(events.NewMessage(pattern=BTN_PROMOTE))
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
    
    # 未开通 VIP，禁止使用推广功能
    if not member['is_vip']:
        await event.respond(
            "抱歉，您还不是 VIP\n\n"
            "不能使用此功能，请先开通 VIP\n"
            "点击下方「开通 VIP」按钮即可开通",
            buttons=[[Button.inline('💎 开通 VIP', b'open_vip')]]
        )
        return
    
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

@bot.on(events.NewMessage(pattern=BTN_RESOURCES))
async def resources_handler(event):
    """行业资源"""
    try:
        original_sender_id = event.sender_id
        event.sender_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))
    except:
        pass
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

@bot.on(events.NewMessage(pattern=BTN_SUPPORT))
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

@bot.on(events.NewMessage(pattern=BTN_VIP))
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
            buttons=[[Button.inline(f'💰 充值 {config["vip_price"]} U 开通VIP', b'recharge_vip')]]
        )

@bot.on(events.NewMessage(pattern=BTN_MY_PROMOTE))
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

@bot.on(events.NewMessage(pattern=BTN_BACK))
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

@bot.on(events.NewMessage(pattern=BTN_ADMIN))
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

@bot.on(events.ChatAction)
async def group_welcome_handler(event):
    """新成员加入群时发送欢迎语，并自动注册为邀请者下级"""
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
    except Exception as e:
        print(f'群事件处理失败: {e}')

# ==================== 完整的消息处理器 ====================

@bot.on(events.NewMessage())
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
                    f'已为 {stats["real"]} 位上级发放奖励\n'
                    f'捡漏账号获得 {stats["fallback"]} 次奖励\n'
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
            # 验证群链接
            verification_result = await verify_group_link(bot, link)
            
            if verification_result['success']:
                # 根据是否成功检测管理员来设置 is_bot_admin
                is_admin_flag = 1 if verification_result.get('admin_checked') else 0
                
                DB.update_member(sender_id, group_link=link, is_group_bound=1, is_bot_admin=is_admin_flag)
                try:
                    sender_username = getattr(event.sender, 'username', None) if hasattr(event, 'sender') else None
                    from database import upsert_member_group
                    upsert_member_group(sender_id, link, sender_username, is_bot_admin=is_admin_flag)
                except Exception as sync_err:
                    print(f'[绑定群写入member_groups失败] {sync_err}')
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
    """定时自动群发 - 根据设置的间隔时间自动发送消息"""
    import json
    last_broadcast_time = 0
    
    while True:
        try:
            await asyncio.sleep(10)  # 每10秒检查一次
            
            print("[定时群发] 正在检查...", flush=True)
            
            conn = get_db_conn()
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
                                    file_path = '/www/wwwroot/154.201.68.178:5051' + image_url
                                await bot.send_file(f'@{chat_username}', file_path, caption=msg_content, buttons=inline_buttons)
                            elif video_url:
                                # 处理本地上传的视频路径
                                file_path = video_url
                                if video_url.startswith('/static/uploads/'):
                                    file_path = '/www/wwwroot/154.201.68.178:5051' + video_url
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
    """定期检查会员状态（拉群、群管、加群）"""
    while True:
        try:
            await asyncio.sleep(60)  # 每1分钟检查一次
            print("[状态检测] 开始检查会员状态...")
            
            conn = get_db_conn()
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
                    # 先查询当前状态，如果 is_joined_upline 已经是 1，则不再重新检测
                    c.execute("SELECT is_joined_upline FROM members WHERE telegram_id = ?", (telegram_id,))
                    current_status = c.fetchone()
                    current_is_joined_upline = current_status[0] if current_status else 0
                    
                    # 如果已经完成加群任务，跳过检测（保持已完成状态）
                    if current_is_joined_upline == 1:
                        print(f"[状态检测] 会员 {telegram_id} 已完成加群任务，跳过检测")
                        continue
                    
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
                        
                        # 检查3：用户是否加入了上级的群（只在未完成时检测）
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
                    
                    # 更新数据库（is_joined_upline 保持原值如果已经是1）
                    # 如果检测到已完成，更新为1；如果检测失败但原值是1，保持1不变
                    final_is_joined_upline = max(is_joined_upline, current_is_joined_upline)
                    
                    c.execute("""
                        UPDATE members 
                        SET is_group_bound = ?, is_bot_admin = ?, is_joined_upline = ?
                        WHERE telegram_id = ?
                    """, (is_group_bound, is_bot_admin, final_is_joined_upline, telegram_id))
                    
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

def run_bot():
    """Bot 启动入口"""
    print("🚀 Telegram Bot 启动中...")
    
    # 1. 启动通知队列处理（提现/充值通知）
    bot.loop.create_task(process_notify_queue())
    print("✅ 通知队列处理器已启动")
    
    # 2. 启动定时群发（从原有 main.py 迁移）
    bot.loop.create_task(auto_broadcast_timer())
    print("✅ 定时自动群发已启动")
    
    # 3. 启动会员状态检测（从原有 main.py 迁移）
    bot.loop.create_task(check_member_status_task())
    print("✅ 会员状态检测已启动")
    
    # 4. 启动群发队列处理（数据库队列）
    bot.loop.create_task(process_broadcast_queue())
    print("✅ 群发队列处理器已启动")
    
    # 5. 启动内存群发队列处理（Web后台群发）
    bot.loop.create_task(process_broadcasts())
    print("✅ 内存群发队列处理器已启动")
    
    print("=" * 60)
    print("✅ 所有后台任务已挂载")
    print("✅ Telegram Bot 已启动，等待消息...")
    print("=" * 60)
    bot.run_until_disconnected()

# 导出bot实例供其他模块使用
__all__ = [
    'bot', 
    'process_vip_upgrade', 
    'process_recharge', 
    'admin_manual_vip_handler', 
    'get_main_account_id', 
    'run_bot', 
    'pending_broadcasts', 
    'notify_queue',
    # 后台任务（供调试使用）
    'auto_broadcast_timer',
    'process_broadcast_queue',
    'process_broadcasts',
    'check_member_status_task',
    'process_notify_queue'
]

