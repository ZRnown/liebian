"""
配置文件
统一管理项目路径和配置
"""
import os

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

# 确保数据目录存在
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

