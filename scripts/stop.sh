#!/bin/bash
# 获取脚本所在目录的父目录（项目根目录）
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$( cd "$SCRIPT_DIR/.." && pwd )"

if [ -f "$PROJECT_DIR/data/bot.pid" ]; then
    kill $(cat "$PROJECT_DIR/data/bot.pid")
    rm "$PROJECT_DIR/data/bot.pid"
    echo "Bot stopped"
else
    echo "No bot.pid found"
fi
