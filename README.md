# 🤖 裂变推广机器人系统

基于 Telegram Bot 和 Flask Web 后台的裂变推广系统。

## 📁 项目结构

```
liebian.mifzla.top/
├── app/                    # 应用核心代码
│   ├── __init__.py        # 包初始化文件
│   ├── main.py            # 主程序（原 a.py）
│   ├── config.py          # 配置文件（路径管理）
│   ├── core_functions.py  # 核心功能模块
│   ├── bot_commands_addon.py  # Bot命令扩展
│   ├── complete_all_features.py  # 完整功能路由
│   └── missing_routes.py  # 缺失路由补充
│
├── templates/             # HTML模板文件
│   ├── base.html
│   ├── index.html
│   ├── login.html
│   └── ...
│
├── static/                # 静态文件
│   ├── favicon.jpg
│   └── uploads/           # 上传文件目录
│
├── scripts/               # 工具脚本
│   ├── start.sh          # 启动脚本
│   ├── stop.sh           # 停止脚本
│   └── deploy_check.py   # 部署检查脚本
│
├── docs/                  # 文档目录
│   ├── 部署指南.md       # 详细部署文档
│   ├── 快速部署.md       # 快速参考
│   └── README.txt        # 原始说明
│
├── data/                  # 数据文件（运行时生成）
│   ├── bot.db            # SQLite数据库
│   ├── bot.log           # 运行日志
│   ├── bot.pid           # 进程ID文件
│   └── bot.session       # Telegram会话文件
│
├── requirements.txt       # Python依赖列表
├── .gitignore            # Git忽略文件
└── README.md             # 本文件
```

## 🚀 快速开始

### 1. 安装依赖

```bash
pip3 install -r requirements.txt
```

### 2. 配置

编辑 `app/main.py`，修改以下配置：

```python
# Telegram API 配置
API_ID = 你的API_ID
API_HASH = '你的API_HASH'
BOT_TOKEN = '你的BOT_TOKEN'

# 管理员ID
ADMIN_IDS = [你的Telegram用户ID]
```

### 3. 启动服务

```bash
# 使用脚本启动
./scripts/start.sh

# 或直接运行
python3 -m app.main
```

### 4. 访问后台

- 地址：`http://localhost:5051`
- 默认账号：`admin` / `admin`
- ⚠️ 首次登录后请立即修改密码！

## 📚 详细文档

- [完整部署指南](docs/部署指南.md)
- [快速部署参考](docs/快速部署.md)

## 🔧 主要功能

- ✅ 10层裂变推广系统
- ✅ VIP会员自动激活
- ✅ USDT充值提现
- ✅ 行业资源分类管理
- ✅ 多客服系统
- ✅ 群验证功能
- ✅ Web管理后台
- ✅ 数据统计报表
- ✅ 定时群发功能

## 🛠️ 技术栈

- Python 3.7+
- Telethon (Telegram Bot框架)
- Flask (Web框架)
- SQLite3 (数据库)
- Tailwind CSS (前端样式)

## 📝 注意事项

1. 首次运行会自动创建数据库
2. 数据文件存储在 `data/` 目录
3. 定期备份 `data/bot.db` 数据库
4. 生产环境建议使用 systemd 管理服务
5. 不要泄露 BOT_TOKEN 和 API 密钥

## 📞 支持

如有问题，请查看文档或检查日志文件 `data/bot.log`。

# liebian
