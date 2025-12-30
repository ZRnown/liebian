# 裂变推广机器人系统

## 🚀 启动方式

### 方法1：使用PM2（推荐）
```bash
# 使用PM2配置文件启动
pm2 start ecosystem.config.js

# 查看状态
pm2 status

# 查看日志
pm2 logs liebian-bot

# 停止服务
pm2 stop liebian-bot
```

### 方法2：直接运行
```bash
# 从项目根目录运行
python3 main.py

# 或者从app目录运行（兼容旧方式）
cd app
python3 run.py
```

### 方法3：使用启动脚本
```bash
# 使用提供的启动脚本
bash scripts/start.sh
```

## 📁 项目结构

```
/www/wwwroot/liebian/
├── main.py              # 主启动文件（推荐）
├── app/
│   ├── run.py          # 兼容性启动文件
│   ├── database.py     # 数据库操作
│   ├── bot_logic.py    # 机器人逻辑
│   ├── web_app.py      # Web管理后台
│   └── ...
├── scripts/
│   └── start.sh        # 启动脚本
├── data/               # 数据目录
└── ecosystem.config.js # PM2配置文件
```

## 🔧 故障排除

如果遇到 `ModuleNotFoundError: No module named 'app'` 错误：

1. **使用推荐的启动方式**：从项目根目录运行 `python3 main.py`
2. **或者使用PM2**：`pm2 start ecosystem.config.js`
3. **避免直接运行** `app/run.py`，因为它的导入路径不正确

## 📊 访问地址

- **Web管理后台**: http://你的服务器IP:5051
- **默认账号**: admin / admin

## ⚠️ 注意事项

- 首次运行前请确保已创建 `data/` 目录
- 记得及时修改默认管理员密码
- 生产环境建议使用PM2管理进程
