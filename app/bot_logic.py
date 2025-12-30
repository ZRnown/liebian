"""
机器人逻辑层 - 统一管理所有Telegram机器人交互
【核心修复】支持多机器人同时运行，只读取数据库配置的Bot
"""
import asyncio
import sqlite3
import time
import os
import json
import logging
from datetime import datetime, timedelta, timezone
from telethon import TelegramClient, events, Button
from telethon.sessions import MemorySession
from telethon.tl.types import ChannelParticipantsAdmins
from telethon.tl.functions.channels import GetParticipantRequest
import socks

# 导入配置和依赖模块
import os
import sys

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app.config import (
    API_ID, API_HASH, ADMIN_IDS, USE_PROXY,
    PROXY_TYPE, PROXY_HOST, PROXY_PORT
)
from app.database import DB, get_cn_time, get_system_config, get_db_conn
from app.core_functions import (
    get_upline_chain, check_user_conditions, update_level_path,
    distribute_vip_rewards, check_user_in_group, check_bot_is_admin,
    verify_group_link
)
from app.bot_commands_addon import (
    handle_bind_group, handle_join_upline, handle_group_link_message,
    handle_check_status, handle_my_team
)

# 配置日志
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# 全局变量
active_clients = [] # 存储所有运行中的客户端
bot = None # 主Bot对象（用于主动发送消息，默认取第一个）


def compute_vip_price_from_config(config):
    """Compute effective VIP price: if per-level amounts configured, sum them; else use vip_price"""
    try:
        # support config 'level_amounts' as list or JSON string
        level_count = int(config.get('level_count', 10))
        level_amounts = config.get('level_amounts')
        if level_amounts:
            import json
            if isinstance(level_amounts, str):
                try:
                    parsed = json.loads(level_amounts)
                except Exception:
                    parsed = None
            else:
                parsed = level_amounts

            if isinstance(parsed, list):
                # sum first level_count entries (pad with zeros)
                vals = [float(x) for x in parsed[:level_count]]
                if len(vals) < level_count:
                    vals += [0.0] * (level_count - len(vals))
                return sum(vals)
            elif isinstance(parsed, dict):
                total = 0.0
                for i in range(1, level_count + 1):
                    v = parsed.get(str(i)) or parsed.get(i) or 0
                    total += float(v)
                return total
    except Exception:
        pass
    # fallback to simple vip_price
    try:
        return float(config.get('vip_price', 10))
    except Exception:
        return 10.0

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

# 子菜单按钮常量
BTN_SUB_VIEW_GROUPS = '📋 查看需要加入的群'
BTN_SUB_CHECK_STATUS = '✅ 检查加入状态'


async def send_vip_required_prompt(event_or_id, reply_method='respond'):
    """给未开通VIP的用户发送统一提示文案"""
    try:
        if isinstance(event_or_id, int):
            telegram_id = event_or_id
            member = DB.get_member(telegram_id)
        else:
            original = event_or_id
            try:
                original_sender_id = original.sender_id
                original.sender_id = get_main_account_id(original_sender_id, getattr(original.sender, 'username', None))
            except Exception:
                pass
            member = DB.get_member(original.sender_id)
            telegram_id = original.sender_id

        config = get_system_config()
        vip_price = config.get('vip_price', 10)
        balance = member['balance'] if member else 0

        text = "抱歉 您还不是VIP\n\n"
        text += "不能使用此功能 请先开通VIP\n"
        text += "点击下方「开通VIP」按钮 开通在来哦\n\n"
        text += f"💰 VIP价格: {vip_price} U\n"
        text += f"💵 当前余额: {balance} U\n"

        buttons = []
        # 如果余额足够，提供余额开通按钮；否则提供充值入口
        if balance >= vip_price:
            buttons = [[Button.inline('💎 余额开通VIP', b'confirm_vip')]]
        else:
            buttons = [[Button.inline('💳 充值开通VIP', b'recharge_for_vip')]]

        if isinstance(event_or_id, int):
            try:
                await bot.send_message(telegram_id, text, buttons=buttons)
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

def get_active_bot_tokens():
    """获取所有活跃的机器人token"""
    try:
        conn = get_db_conn()
        c = conn.cursor()
        c.execute('SELECT bot_token FROM bot_configs WHERE is_active = 1 ORDER BY id ASC')
        rows = c.fetchall()
        conn.close()
        tokens = [row[0] for row in rows if row[0]]
        print(f"[机器人初始化] 找到 {len(tokens)} 个活跃机器人token")
        return tokens
    except Exception as e:
        print(f"[机器人初始化] 获取活跃token失败: {e}")
        return []

# ==================== 机器人初始化逻辑 ====================

def init_bots():
    """初始化并启动所有配置的机器人"""
    global bot, active_clients

    tokens = get_active_bot_tokens()

    if not tokens:
        logger.error("❌ 错误：数据库中没有活跃的机器人Token！请先在后台添加机器人。")
        return []

    # 代理配置
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

    active_clients = []

    for idx, token in enumerate(tokens):
        try:
            session_name = f'bot_session_{idx}'
            client = TelegramClient(session_name, API_ID, API_HASH, proxy=proxy)
            client.start(bot_token=token)

            # 注册所有事件处理器
            register_handlers(client)

            active_clients.append(client)
            logger.info(f"✅ 机器人 #{idx+1} 启动成功 (Token: {token[:10]}...)")

        except Exception as e:
            logger.error(f"❌ 机器人 #{idx+1} 启动失败: {e}")

    if active_clients:
        bot = active_clients[0]
        logger.info(f"✅ 总计启动 {len(active_clients)} 个机器人，主Bot已就绪")
    else:
        logger.error("❌ 没有机器人启动成功")

    return active_clients

# 全局队列
pending_broadcasts = []
notify_queue = []
process_recharge_queue = []
# 其他全局变量...


# 导入支付模块
from app.payment import create_recharge_order


# ==================== 账号关联逻辑 ====================

def get_main_account_id(telegram_id, username=None):
    """获取主账号ID（精准ID匹配版）"""
    try:
        target_id_str = str(telegram_id).strip()
        clean_username = (username or '').strip().lstrip('@')

        conn = get_db_conn()
        c = conn.cursor()

        query = "SELECT telegram_id FROM members WHERE backup_account = ?"
        c.execute(query, (target_id_str,))
        row = c.fetchone()

        if not row and clean_username:
            c.execute(
                'SELECT telegram_id FROM members WHERE backup_account = ? OR backup_account = ?',
                (clean_username, f"@{clean_username}")
            )
            row = c.fetchone()

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

# ==================== VIP处理逻辑 ====================

async def process_vip_upgrade(telegram_id, vip_price, config, deduct_balance=True):
    """统一的VIP开通处理函数"""
    member = DB.get_member(telegram_id)
    if not member:
        return False, "用户不存在"

    if member.get('is_vip'):
        return False, "用户已是VIP"

    if deduct_balance:
        if member['balance'] < vip_price:
            return False, "余额不足"
        new_balance = member['balance'] - vip_price
        DB.update_member(telegram_id, balance=new_balance, is_vip=1, vip_time=get_cn_time())
    else:
        new_balance = member['balance']
        DB.update_member(telegram_id, is_vip=1, vip_time=get_cn_time())

    update_level_path(telegram_id)
    stats = await distribute_vip_rewards(bot, telegram_id, vip_price, config)

    return True, {
        'new_balance': new_balance,
        'stats': stats
    }

async def process_recharge(telegram_id, amount, is_vip_order=False):
    """处理充值到账逻辑（包括VIP自动开通）"""
    try:
        conn = get_db_conn()
        c = conn.cursor()
        c.execute('SELECT balance, is_vip FROM members WHERE telegram_id = ?', (telegram_id,))
        row = c.fetchone()
        conn.close()

        if not row:
            print(f"[Recharge] 用户 {telegram_id} 不存在")
            return

        current_balance = row[0]
        is_vip = row[1]

        # 发送到账通知
        try:
            await bot.send_message(telegram_id, f"💰 充值到账: {amount} U\n当前余额: {current_balance} U")
        except: pass

        # 尝试自动开通VIP
        config = get_system_config()
        vip_price = compute_vip_price_from_config(config)

        if is_vip_order and not is_vip and current_balance >= vip_price:
            print(f"[Recharge] 自动开通VIP: {telegram_id}")
            success, result = await process_vip_upgrade(telegram_id, vip_price, config, deduct_balance=True)
            if success:
                try:
                    await bot.send_message(telegram_id, f"💎 VIP自动开通成功！\n扣除余额: {vip_price} U")
                except: pass
    except Exception as e:
        print(f"[Recharge Process Error] {e}")

async def admin_manual_vip_handler(telegram_id, config):
    """管理员手动开通VIP的后台任务"""
    vip_price = compute_vip_price_from_config(config)
    await process_vip_upgrade(telegram_id, vip_price, config, deduct_balance=False)

# ==================== 事件处理器注册 ====================

def register_handlers(client):
    """为单个客户端注册所有事件处理器"""

    @client.on(events.NewMessage(pattern='/start'))
    async def start_handler(event):
        """启动命令"""
        original_sender_id = event.sender_id
        telegram_id = get_main_account_id(original_sender_id, getattr(event.sender, 'username', None))

        referrer_id = None
        if event.message.text and len(event.message.text.split()) > 1:
            try:
                referrer_id = int(event.message.text.split()[1])
            except: pass

        member = DB.get_member(telegram_id)

        if not member:
            username = event.sender.username or f'user_{telegram_id}'
            DB.create_member(telegram_id, username, referrer_id)
            member = DB.get_member(telegram_id)

            if referrer_id:
                try:
                    await client.send_message(referrer_id, f'🎉 新成员加入! ID: {telegram_id}')
                except: pass

        sys_config = get_system_config()
        display_id = original_sender_id
        vip_status = "✅ 已开通" if member.get('is_vip') else "❌ 未开通"

        welcome_text = f'👋 欢迎使用裂变推广机器人!\n👤 当前显示身份ID: `{display_id}`\n💎 VIP状态: {vip_status}\n💰 余额: {member["balance"]} U\n\n请选择功能:'
        if sys_config.get('pinned_ad'):
            welcome_text += f'\n\n📢 {sys_config["pinned_ad"]}'

        await event.respond(welcome_text, buttons=get_main_keyboard(telegram_id))

    # VIP 开通处理
    @client.on(events.NewMessage(pattern=BTN_VIP))
    async def vip_handler(event):
        telegram_id = get_main_account_id(event.sender_id)
        member = DB.get_member(telegram_id)

        if not member: return

        if member['is_vip']:
            await event.respond(f'💎 您已经是VIP会员!\n开通时间: {member["vip_time"][:10]}')
            return

        config = get_system_config()
        vip_price = compute_vip_price_from_config(config)

        text = f'💎 开通VIP会员\nVIP价格: {vip_price} U\n当前余额: {member["balance"]} U'
        buttons = []
        if member['balance'] >= vip_price:
            text += '\n✅ 余额充足，可以直接开通'
            buttons = [[Button.inline('💎 余额开通VIP', b'confirm_vip')]]
        else:
            text += f'\n❌ 余额不足，还需 {vip_price - member["balance"]} U'
            buttons = [[Button.inline('💳 充值开通VIP', b'recharge_for_vip')]]

        await event.respond(text, buttons=buttons)

    @client.on(events.CallbackQuery(pattern=b'confirm_vip'))
    async def cb_confirm_vip(event):
        telegram_id = get_main_account_id(event.sender_id)
        config = get_system_config()
        vip_price = compute_vip_price_from_config(config)
        success, result = await process_vip_upgrade(telegram_id, vip_price, config)
        if success:
            await event.answer("🎉 VIP开通成功！", alert=True)
            await event.respond("🎉 恭喜! 您已成为VIP会员，现在可以享受所有权益！", buttons=[[Button.inline('🔙 返回', b'back_to_profile')]])
        else:
            await event.answer(f"❌ 开通失败: {result}", alert=True)

    @client.on(events.CallbackQuery(pattern=b'recharge_for_vip'))
    async def cb_recharge_for_vip(event):
        telegram_id = get_main_account_id(event.sender_id)
        config = get_system_config()
        vip_price = compute_vip_price_from_config(config)

        # 创建充值订单，金额为VIP价格
        try:
            await create_recharge_order(client, event, vip_price, is_vip_order=True)
        except Exception as e:
            await event.answer("创建充值订单失败，请稍后重试", alert=True)

    # 个人中心
    @client.on(events.NewMessage(pattern=BTN_PROFILE))
    async def profile_handler(event):
        telegram_id = get_main_account_id(event.sender_id)
        member = DB.get_member(telegram_id)
        if not member:
            await event.respond('请先发送 /start 注册')
            return

        config = get_system_config()
        vip_price = compute_vip_price_from_config(config)

        from app.core_functions import calculate_team_stats
        team_stats = calculate_team_stats(telegram_id, 10)

        text = f'👤 个人中心\n\n'
        text += f'🆔 用户ID: `{telegram_id}`\n'
        text += f'💰 当前余额: {member["balance"]} U\n'
        text += f'💎 VIP状态: {"✅ 已开通" if member["is_vip"] else "❌ 未开通"}\n'
        if member["is_vip"]:
            text += f'📅 开通时间: {member["vip_time"][:10] if member["vip_time"] else "未知"}\n'
        text += f'🎯 VIP价格: {vip_price} U\n\n'
        text += f'👥 团队统计:\n'
        text += f'   直推人数: {team_stats["direct_count"]}\n'
        text += f'   团队总人数: {team_stats["team_count"]}\n'
        text += f'   VIP人数: {team_stats["vip_count"]}\n'
        text += f'💸 累计收益: {member.get("total_earned", 0)} U\n'
        text += f'⚠️ 累计错过: {member["missed_balance"]} U\n'

        await event.respond(text, buttons=[[Button.text(BTN_BACK, resize=True)]])

    # 在线客服
    @client.on(events.NewMessage(pattern=BTN_SUPPORT))
    async def support_handler(event):
        telegram_id = get_main_account_id(event.sender_id)
        config = get_system_config()
        support_text = config.get('support_text', '👩‍💼 在线客服\n\n暂无客服信息，请联系管理员')
        customer_services = DB.get_customer_services()

        text = support_text
        if customer_services:
            text = '👩‍💼 在线客服\n\n'
            for service in customer_services:
                text += f'📞 {service["name"]}\n'
                if service["link"]:
                    text += f'🔗 {service["link"]}\n\n'

        await event.respond(text, buttons=[[Button.text(BTN_BACK, resize=True)]])

    # 管理后台
    @client.on(events.NewMessage(pattern=BTN_ADMIN))
    async def admin_handler(event):
        if event.sender_id not in ADMIN_IDS:
            await event.respond('❌ 您不是管理员，无法访问管理后台')
            return
        text = '⚙️ 管理后台\n\n'
        text += '🌐 访问地址:\nhttp://你的服务器IP:5051\n\n'
        text += '📋 默认账号:\n用户名: admin\n密码: admin\n\n'
        text += '⚠️ 请及时修改默认密码'
        await event.respond(text, buttons=[[Button.text(BTN_BACK, resize=True)]])

    # 我的推广
    @client.on(events.NewMessage(pattern=BTN_MY_PROMOTE))
    async def my_promote_handler(event):
        telegram_id = get_main_account_id(event.sender_id)
        member = DB.get_member(telegram_id)
        if not member:
            await event.respond('请先发送 /start 注册')
            return
        if not member['is_vip']:
            await send_vip_required_prompt(event, 'respond')
            return

        bot_username = None
        try:
            me = await client.get_me()
            bot_username = me.username
        except: pass

        invite_link = f'https://t.me/{bot_username}?start={telegram_id}' if bot_username else '未知'

        from app.core_functions import calculate_team_stats
        team_stats = calculate_team_stats(telegram_id, 10)

        text = f'💫 我的推广\n\n'
        text += f'🔗 推广链接:\n{invite_link}\n\n'
        text += f'📊 推广统计:\n'
        text += f'👥 直推人数: {team_stats["direct_count"]}\n'
        text += f'👨‍👩‍👧‍👦 团队总人数: {team_stats["team_count"]}\n'
        text += f'💎 VIP人数: {team_stats["vip_count"]}\n'
        text += f'💰 累计收益: {member.get("total_earned", 0)} U\n\n'
        text += '📢 邀请好友加入即可获得奖励!'

        await event.respond(text, buttons=[[Button.text(BTN_BACK, resize=True)]])

    # 群裂变加入 - 显示子菜单
    @client.on(events.NewMessage(pattern=BTN_FISSION))
    async def fission_handler(event):
        telegram_id = get_main_account_id(event.sender_id)
        member = DB.get_member(telegram_id)
        if not member:
            await event.respond('请先发送 /start 注册')
            return
        if not member['is_vip']:
            await send_vip_required_prompt(event, 'respond')
            return

        text = '🔗 群裂变加入\n\n'
        text += '📋 加入上层群组可以获得分红奖励\n\n'
        text += '请选择操作:'

        buttons = [
            [Button.text(BTN_SUB_VIEW_GROUPS, resize=True)],
            [Button.text(BTN_SUB_CHECK_STATUS, resize=True)],
            [Button.text(BTN_BACK, resize=True)]
        ]
        await event.respond(text, buttons=buttons)

    # 监听子菜单：查看需要加入的群
    @client.on(events.NewMessage(pattern=BTN_SUB_VIEW_GROUPS))
    async def sub_view_groups_handler(event):
        # 调用 addon 中的逻辑
        await handle_join_upline(event, client, DB, get_system_config)

    # 监听子菜单：检查加入状态
    @client.on(events.NewMessage(pattern=BTN_SUB_CHECK_STATUS))
    async def sub_check_status_handler(event):
        # 调用 addon 中的逻辑
        await handle_check_status(event, client, DB)

    # 我的裂变
    @client.on(events.NewMessage(pattern=BTN_VIEW_FISSION))
    async def view_fission_handler(event):
        telegram_id = get_main_account_id(event.sender_id)
        member = DB.get_member(telegram_id)
        if not member:
            await event.respond('请先发送 /start 注册')
            return
        if not member['is_vip']:
            await send_vip_required_prompt(event, 'respond')
            return

        text = '📊 我的裂变\n\n'
        text += f'👤 群组状态: {"✅ 已绑定" if member.get("is_group_bound") else "❌ 未绑定"}\n'
        if member.get('group_link'):
            text += f'🔗 群链接: {member["group_link"]}\n'

        text += f'🤖 管理员权限: {"✅ 已设置" if member.get("is_bot_admin") else "❌ 未设置"}\n'
        text += f'👥 加入上层群: {"✅ 已完成" if member.get("is_joined_upline") else "❌ 未完成"}\n\n'

        # 显示简单的层级统计
        from app.core_functions import get_downline_tree
        downline_tree = get_downline_tree(telegram_id, 5)
        if downline_tree:
            text += '📈 团队层级分布:\n'
            for level in range(1, 6):
                if level in downline_tree:
                    members_in_level = downline_tree[level]
                    vip_count = sum(1 for m in members_in_level if m['is_vip'])
                    text += f'   第{level}层: {len(members_in_level)}人 (VIP: {vip_count}人)\n'

        # 提示用户如何绑定群组
        text += '\n💡 如需绑定或更改群组，请直接发送群链接（如 https://t.me/+xxx）给我'

        await event.respond(text, buttons=[[Button.text(BTN_BACK, resize=True)]])

    # 监听群组链接消息（用于绑定群组）
    @client.on(events.NewMessage)
    async def group_link_listener(event):
        text = event.message.text
        # 忽略命令和按钮点击
        if text.startswith('/') or text in [BTN_PROFILE, BTN_FISSION, BTN_VIEW_FISSION, BTN_RESOURCES, BTN_PROMOTE, BTN_SUPPORT, BTN_BACK, BTN_ADMIN, BTN_VIP, BTN_MY_PROMOTE, BTN_SUB_VIEW_GROUPS, BTN_SUB_CHECK_STATUS]:
            return

        # 简单正则判断链接
        if 't.me/' in text or text.startswith('@'):
            await handle_group_link_message(event, client, DB)

    # 返回主菜单
    @client.on(events.NewMessage(pattern=BTN_BACK))
    async def back_handler(event):
        telegram_id = get_main_account_id(event.sender_id)
        member = DB.get_member(telegram_id)
        if member:
            config = get_system_config()
            vip_status = "✅ 已开通" if member.get('is_vip') else "❌ 未开通"
            welcome_text = f'👋 欢迎使用裂变推广机器人!\n👤 当前显示身份ID: `{event.sender_id}`\n💎 VIP状态: {vip_status}\n💰 余额: {member["balance"]} U\n\n请选择功能:'
            if config.get('pinned_ad'):
                welcome_text += f'\n\n📢 {config["pinned_ad"]}'
            await event.respond(welcome_text, buttons=get_main_keyboard(telegram_id))
        else:
            await event.respond('请先发送 /start 注册', buttons=get_main_keyboard(telegram_id))


def run_bot():
    """Bot 启动入口"""
    print("🚀 正在启动所有配置的 Telegram Bot...")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    clients = init_bots()
    if not clients:
        print("❌ 没有可用的机器人，程序退出")
        return

    # 后台任务：处理充值队列
    async def _process_recharge_queue_worker():
        while True:
            try:
                if process_recharge_queue:
                    item = process_recharge_queue.pop(0)
                    await process_recharge(item['member_id'], item['amount'], item.get('is_vip_order', False))
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"[充值队列] 错误: {e}")
                await asyncio.sleep(1)

    loop.create_task(_process_recharge_queue_worker())

    print("✅ 所有机器人已启动，开始监听消息...")

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for c in clients:
            if c.is_connected():
                c.disconnect()


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
    'process_recharge_queue'
]
