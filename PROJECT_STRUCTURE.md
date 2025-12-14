# 📁 项目结构说明

## 目录结构

```
liebian.mifzla.top/
│
├── app/                          # 应用核心代码目录
│   ├── __init__.py              # Python包初始化文件
│   ├── main.py                  # 主程序（原 a.py，已重命名）
│   ├── config.py                # 配置文件（统一管理路径）
│   ├── core_functions.py        # 核心功能模块
│   ├── bot_commands_addon.py    # Bot命令扩展模块
│   ├── complete_all_features.py # 完整功能路由
│   └── missing_routes.py        # 缺失路由补充
│
├── templates/                    # HTML模板目录
│   ├── base.html                # 基础模板
│   ├── index.html               # 首页/会员管理
│   ├── login.html               # 登录页面
│   ├── dashboard.html           # 仪表盘
│   ├── members.html             # 会员列表
│   ├── statistics.html          # 统计报表
│   ├── withdrawals.html         # 提现审核
│   ├── resources.html           # 资源管理
│   ├── customer_service.html    # 客服管理
│   ├── settings.html             # 系统设置
│   ├── broadcast.html           # 群发管理
│   └── ...                      # 其他模板文件
│
├── static/                       # 静态文件目录
│   ├── favicon.jpg              # 网站图标
│   └── uploads/                 # 上传文件目录
│       └── .gitkeep            # Git保持目录
│
├── scripts/                      # 工具脚本目录
│   ├── start.sh                 # 启动脚本
│   ├── stop.sh                  # 停止脚本
│   └── deploy_check.py          # 部署环境检查脚本
│
├── docs/                         # 文档目录
│   ├── 部署指南.md              # 详细部署文档
│   ├── 快速部署.md              # 快速参考
│   ├── README.txt               # 原始说明文档
│   └── ...                      # 其他文档
│
├── data/                         # 数据文件目录（运行时生成）
│   ├── bot.db                   # SQLite数据库
│   ├── bot.log                  # 运行日志
│   ├── bot.pid                  # 进程ID文件
│   └── bot.session              # Telegram会话文件
│
├── requirements.txt             # Python依赖列表
├── .gitignore                   # Git忽略文件配置
├── README.md                    # 项目说明文档
└── PROJECT_STRUCTURE.md         # 本文件
```

## 文件说明

### 核心应用文件 (app/)

- **main.py**: 主程序入口，包含 Telegram Bot 和 Flask Web 服务器
- **config.py**: 统一管理项目路径和配置
- **core_functions.py**: 核心业务逻辑（群组检测、层级计算等）
- **bot_commands_addon.py**: Bot 命令处理扩展
- **complete_all_features.py**: 完整的 API 路由定义
- **missing_routes.py**: 补充的 API 路由

### 模板文件 (templates/)

所有 HTML 模板文件，使用 Flask 的 Jinja2 模板引擎。

### 静态文件 (static/)

CSS、JavaScript、图片等静态资源文件。

### 脚本文件 (scripts/)

- **start.sh**: 启动应用的 Shell 脚本
- **stop.sh**: 停止应用的 Shell 脚本
- **deploy_check.py**: 检查部署环境的 Python 脚本

### 数据文件 (data/)

运行时生成的文件，包括：
- 数据库文件
- 日志文件
- 进程ID文件
- Telegram会话文件

**注意**: 此目录已在 `.gitignore` 中排除，不会被提交到版本控制。

## 路径配置

所有路径配置统一在 `app/config.py` 中管理：

- `BASE_DIR`: 项目根目录
- `DATA_DIR`: 数据文件目录
- `DB_PATH`: 数据库文件路径
- `LOG_PATH`: 日志文件路径
- `UPLOAD_DIR`: 上传文件目录

## 启动方式

### 方式1：使用脚本（推荐）

```bash
# 启动
./scripts/start.sh

# 停止
./scripts/stop.sh
```

### 方式2：直接运行

```bash
python3 -m app.main
```

### 方式3：使用 systemd（生产环境）

参考 `docs/部署指南.md` 中的 systemd 配置。

## 清理说明

已删除的文件类型：

- ✅ 所有 `.bak`, `.backup`, `.broken` 备份文件
- ✅ 所有临时修复脚本（`fix_*.py`, `add_*.py`, `check_*.py` 等）
- ✅ 所有测试文件（`test_*.py`）
- ✅ 所有临时工具脚本
- ✅ 重复的模板备份文件
- ✅ 测试报告 JSON 文件
- ✅ 旧的文档文件（已移动到 docs/）

## 迁移说明

如果你之前使用的是旧的文件结构：

1. **主程序**: `a.py` → `app/main.py`
2. **启动脚本**: 路径已更新，使用 `./scripts/start.sh`
3. **数据库路径**: 已统一使用 `app/config.py` 中的配置
4. **导入路径**: 已更新为相对导入

## 注意事项

1. 首次运行前，确保 `data/` 目录有写入权限
2. 数据库文件会自动创建在 `data/bot.db`
3. 日志文件会写入 `data/bot.log`
4. 所有路径配置都在 `app/config.py` 中，修改路径只需修改该文件

