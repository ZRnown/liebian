#!/bin/bash
# 获取脚本所在目录的父目录（项目根目录）
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$( cd "$SCRIPT_DIR/.." && pwd )"

cd "$PROJECT_DIR"

# 创建数据目录（如果不存在）
mkdir -p data

# 启动应用
nohup python3 main.py > data/bot.log 2>&1 &
echo $! > data/bot.pid
echo "Bot started with PID: $(cat data/bot.pid)"
