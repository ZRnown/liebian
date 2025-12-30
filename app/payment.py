"""
支付相关功能模块
包含USDT充值、支付订单创建、支付状态检查等功能
"""
import asyncio
import time
import hashlib
import requests as req
import re
from datetime import datetime, timedelta, timezone
from telethon import Button
import os
import sys

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app.config import ADMIN_IDS
from app.database import DB, get_cn_time, get_system_config, get_db_conn
from app.core_functions import update_level_path, distribute_vip_rewards, get_upline_chain

# 支付配置
PAYMENT_CONFIG = {
    'api_url': 'https://usdt.qxzy7888.org/pay/',
    'partner_id': '15',
    'key': '5c9dd0b054b184f964',
    'notify_url': 'http://154.201.68.178:5051/api/payment/notify',
    'return_url': 'http://154.201.68.178:5051/payment/success',
    'pay_type': 'trc20',
    'version': '1.0'
}

# 支付订单相关
payment_orders = {}  # 存储充值订单
payment_tasks = {}  # 存储支付检查任务
interval_time_in_seconds = 9  # 检查支付间隔（秒）
check_duration_seconds = 1200  # 订单有效期（秒），20分钟

CN_TIMEZONE = timezone(timedelta(hours=8))

def generate_payment_sign(params, key):
    """生成支付签名"""
    sorted_params = sorted([(k, v) for k, v in params.items() if v is not None and v != ''])
    sign_str = '&'.join([f'{k}={v}' for k, v in sorted_params])
    sign_str += f'&key={key}'
    return hashlib.md5(sign_str.encode()).hexdigest().upper()

def create_payment_order(amount, out_trade_no, remark=''):
    """创建支付订单"""
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

def check_usdt_transaction(usdt_address):
    """查询USDT TRC20地址的交易记录"""
    try:
        api_url = f"https://api.trongrid.io/v1/accounts/{usdt_address}/transactions/trc20?limit=200&contract_address=TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
        response = req.get(api_url, timeout=10)
        if response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        print(f"查询USDT交易失败: {e}")
        return None

def extract_usdt_address_from_payment_url(payment_url):
    """从支付链接页面解析USDT收款地址"""
    if not payment_url:
        return None
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = req.get(payment_url, headers=headers, timeout=10, allow_redirects=True)
        
        if response.status_code == 200:
            html = response.text
            # 匹配TRC20地址格式：T开头，34个字符
            pattern = r'T[A-Za-z1-9]{33}'
            matches = re.findall(pattern, html)
            if matches:
                return matches[0]
    except Exception as e:
        print(f'[解析支付地址] 失败: {e}')
    
    return None

async def check_payment_task(bot, order):
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
                            # 延迟导入避免循环依赖
                            import importlib
                            bot_logic_module = importlib.import_module('bot_logic')
                            await bot_logic_module.process_recharge(order['telegram_id'], amount, is_vip_order)
                            
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

async def payment_timeout_handler(bot, order):
    """处理订单超时（修复版：增加状态二次检查，完美解决手动入款却提示超时的问题）

    问题根源：
    - 三方支付后台显示"等待支付"是正常的（因为管理员没真付钱）
    - 本地机器人后台显示"已完成"是管理员手动操作的结果
    - 机器人倒计时任务醒来后，没有检查数据库状态就发超时通知

    解决方案：
    - 在发送超时通知前，先去数据库检查订单状态
    - 如果数据库状态已是completed，直接拦截超时通知
    """
    # 1. 等待订单有效期（例如20分钟 = 1200秒）
    check_duration = 1200
    await asyncio.sleep(check_duration)
    
    order_number = order['order_number']
    telegram_id = order['telegram_id']
    
    # 2. 清理内存中的任务记录（停止轮询区块链）
    if order_number in payment_orders:
        del payment_orders[order_number]
    if order_number in payment_tasks:
        del payment_tasks[order_number]

    try:
        # 3. 【关键步骤】去数据库查最新的状态
        conn = get_db_conn()
        c = conn.cursor()
        c.execute("SELECT status FROM recharge_records WHERE order_id = ?", (order_number,))
        row = c.fetchone()
        conn.close()

        # 4. 如果数据库显示已完成（管理员手动点过或回调成功），直接退出，什么都不发
        if row and row[0] == 'completed':
            print(f"[超时检查] 订单 {order_number} 已由管理员手动完成或支付成功，拦截超时通知")
            return
        # 5. 只有状态确实不是 completed 时，才发超时通知
            await bot.send_message(
            telegram_id,
            f'⏰ 订单已关闭\n\n订单号: {order_number}\n金额: {order["amount"]} U\n\n提示：如果您已支付但未到账，请联系人工客服处理。'
            )
    except Exception as e:
        print(f"[超时处理错误] {e}")

async def create_recharge_order(bot, event, amount, is_vip_order=False):
    """创建充值订单"""
    telegram_id = event.sender_id
    order_number = f"RCH_{telegram_id}_{int(time.time())}"
    payment_result = create_payment_order(amount, order_number, f"TG{telegram_id}")
    if not payment_result or payment_result.get("code") != 200:
        await event.respond("创建支付订单失败，请稍后重试")
        return

    # 保存充值记录到数据库
    conn = get_db_conn()
    c = conn.cursor()
    remark = "开通" if is_vip_order else ""

    # 检查表是否有remark字段
    c.execute("PRAGMA table_info(recharge_records)")
    columns = [col[1] for col in c.fetchall()]
    if 'remark' in columns:
        c.execute('''INSERT INTO recharge_records
                     (member_id, amount, order_id, status, payment_method, remark, create_time)
                     VALUES (?, ?, ?, ?, ?, ?, ?)''',
                  (telegram_id, amount, order_number, 'pending', 'USDT', remark, get_cn_time()))
    else:
        c.execute('''INSERT INTO recharge_records
                     (member_id, amount, order_id, status, payment_method, create_time)
                     VALUES (?, ?, ?, ?, ?, ?)''',
                  (telegram_id, amount, order_number, 'pending', 'USDT', get_cn_time()))
    conn.commit()
    conn.close()
    
    # 优先使用支付平台返回的支付链接/二维码
    payment_url = None
    payment_qrcode = None
    usdt_address = None
    
    if payment_result.get("code") == 200:
        data = payment_result.get("data", {})
        if isinstance(data, dict):
            # 尝试获取支付链接
            payment_url = data.get("url") or data.get("data", {}).get("url") or data.get("data", {}).get("qrcode")
            payment_qrcode = data.get("data", {}).get("qrcode")
            
            # 尝试从支付平台返回的数据中直接获取地址（如果有的话）
            if "address" in str(data).lower() or "收款地址" in str(data):
                data_str = str(data)
                pattern = r'T[A-Za-z1-9]{33}'
                matches = re.findall(pattern, data_str)
                if matches:
                    usdt_address = matches[0]
    
    # 如果没有从返回数据中获取到地址，尝试从支付链接页面实时解析
    if not usdt_address and payment_url:
        print(f'[支付地址] 开始实时解析支付链接: {payment_url}')
        usdt_address = extract_usdt_address_from_payment_url(payment_url)
        if usdt_address:
            print(f'[支付地址] 实时解析成功: {usdt_address}')
        else:
            print(f'[支付地址] 实时解析失败，未找到USDT地址')
    
    # 只使用实时解析到的地址，不使用任何缓存或手动配置
    if usdt_address:
        msg = f'''✅ 支付订单已创建

订单号: `{order_number}`
支付金额: {amount:.2f} USDT

📝 请转账到以下地址：
`{usdt_address}`
(TRC-20网络)

⚠️ 订单10分钟内有效，过期后请重新创建
⚠️ 转账金额必须与订单金额完全一致
✅ 支付完成后，系统将自动到账（约1-2分钟）'''
    
        buttons = [[Button.inline("返回", b"back")]]
        await event.respond(msg, buttons=buttons, parse_mode='markdown')
        
        # 保存订单信息并启动支付检查任务
        order_info = {
            'order_number': order_number,
            'telegram_id': telegram_id,
            'amount': amount,
            'usdt_address': usdt_address,
            'created_at': datetime.now(CN_TIMEZONE),
            'is_vip_order': is_vip_order
        }
        payment_orders[order_number] = order_info
        
        # 启动支付检查任务
        payment_task = bot.loop.create_task(check_payment_task(bot, order_info))
        timeout_task = bot.loop.create_task(payment_timeout_handler(bot, order_info))
        payment_tasks[order_number] = (payment_task, timeout_task)
    else:
        # 如果无法解析到USDT地址，提示错误
        error_msg = "❌ 无法获取支付地址，请稍后重试"
        if payment_url:
            error_msg += f"\n\n支付链接: {payment_url}\n（系统无法解析该链接中的收款地址）"
        await event.respond(
            error_msg,
            buttons=[[Button.inline("返回", b"back")]]
        )

__all__ = [
    'create_recharge_order', 'check_payment_task', 'payment_timeout_handler',
    'check_usdt_transaction', 'create_payment_order', 'generate_payment_sign',
    'extract_usdt_address_from_payment_url', 'payment_orders', 'payment_tasks',
    'PAYMENT_CONFIG'
]

