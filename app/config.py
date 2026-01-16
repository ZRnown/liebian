"""
配置文件
统一管理项目路径和配置
"""
import os
from pathlib import Path

# 项目根目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 数据目录
DATA_DIR = os.path.join(BASE_DIR, 'data')

# 数据库路径
DB_PATH = os.path.join(DATA_DIR, 'bot.db')

# 日志路径
LOG_PATH = os.path.join(DATA_DIR, 'bot.log')

# PID文件路径
PID_PATH = os.path.join(DATA_DIR, 'bot.pid')

# Session文件路径
SESSION_PATH = os.path.join(DATA_DIR, 'bot.session')

# 静态文件上传目录
UPLOAD_DIR = os.path.join(BASE_DIR, 'static', 'uploads')

# Session文件目录（多机器人Session隔离）
SESSION_DIR = os.path.join(DATA_DIR, 'sessions')

# 确保数据目录存在
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(SESSION_DIR, exist_ok=True)

# ... (Rest of file remains same) ...

# ==================== Telegram Bot 配置 ====================
# 从 .env 文件或环境变量读取配置

def load_env_config():
    """从 .env 文件加载配置"""
    env_file = os.path.join(BASE_DIR, '.env')
    config = {}
    
    # 如果存在 .env 文件，读取配置
    if os.path.exists(env_file):
        with open(env_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # 跳过空行和注释
                if not line or line.startswith('#'):
                    continue
                # 解析 key=value
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    config[key] = value
    
    return config

# 加载环境配置
_env_config = load_env_config()

# Telegram API 配置
# 优先从环境变量读取，其次从 .env 文件读取，最后使用默认值
API_ID = int(os.getenv('API_ID') or _env_config.get('API_ID', '21332425'))
API_HASH = os.getenv('API_HASH') or _env_config.get('API_HASH', 'f5d0cddc784e3a7a09ea9714ed01f238')
BOT_TOKEN = os.getenv('BOT_TOKEN') or _env_config.get('BOT_TOKEN', '8520376411:AAHGZMmI-oROPyrxBmDTo7_OCtpy8kHWORc')

# 管理员 ID 列表
_admin_ids_str = os.getenv('ADMIN_IDS') or _env_config.get('ADMIN_IDS', '7935612165')
ADMIN_IDS = [int(uid.strip()) for uid in _admin_ids_str.split(',') if uid.strip()]

# 代理配置
USE_PROXY = (os.getenv('USE_PROXY') or _env_config.get('USE_PROXY', 'False')).lower() == 'true'
PROXY_TYPE = os.getenv('PROXY_TYPE') or _env_config.get('PROXY_TYPE', 'socks5')
PROXY_HOST = os.getenv('PROXY_HOST') or _env_config.get('PROXY_HOST', '127.0.0.1')
PROXY_PORT = int(os.getenv('PROXY_PORT') or _env_config.get('PROXY_PORT', '7897'))

# ==================== Web / Payment 回调公共配置 ====================
# 对外可访问的站点根地址（带端口），用于拼接支付回调/跳转等URL。
# 示例:
# - http://1.2.3.4:5051
# - https://your-domain.com
PUBLIC_BASE_URL = (os.getenv('PUBLIC_BASE_URL') or _env_config.get('PUBLIC_BASE_URL', '')).rstrip('/')

