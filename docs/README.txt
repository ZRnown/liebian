🤖 裂变推广机器人系统
===================

✨ 快速开始
-----------

1. 安装依赖：
   pip install telethon flask flask-login requests qrcode pillow

2. 配置BOT（编辑 a.py）：
   - 第16行填入 BOT_TOKEN
   - 第19行填入管理员ID

3. 启动系统：
   python a.py

4. 访问后台：
   http://localhost:5051
   账号：ranfeng
   密码：ranfeng133

📚 详细文档
-----------
请查看：部署指南.txt

🎯 核心功能
-----------
✅ 10层裂变推广系统
✅ VIP会员自动激活
✅ 行业资源分类管理
✅ 多客服系统
✅ 群验证功能
✅ Web管理后台
✅ 数据统计报表

🌐 管理后台路由
--------------
/                - 会员管理
/statistics      - 统计报表
/withdrawals     - 提现审核
/resources       - 资源管理
/customer-service - 客服管理
/settings        - 系统设置

🔧 技术栈
--------
- Telethon (Telegram Bot)
- Flask (Web框架)
- SQLite3 (数据库)
- Tailwind CSS (前端样式)
- Tabler Icons (图标库)

📦 文件说明
----------
a.py              - 主程序
bot.db            - 数据库
templates/        - 网页模板
部署指南.txt      - 完整部署文档
README.txt        - 本文件

⚡ 注意事项
----------
1. 首次登录后请修改管理员密码
2. 不要泄露BOT_TOKEN
3. 定期备份bot.db数据库
4. 生产环境建议使用HTTPS

🎉 系统已完成所有功能开发！
