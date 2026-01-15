"""
启动入口 - 统一启动Bot和Web后台
"""
import threading
import time
# 【注意】这里必须加点 . 表示从当前包导入
from .database import init_db, sync_member_groups_from_members
from .bot_logic import run_bot

def main():
    print("=" * 60)
    print("🤖 裂变推广机器人系统启动中...")
    print("=" * 60)
    print()
    
    # 1. 初始化数据库
    print("📊 初始化数据库...")
    init_db()
    print("✅ 数据库初始化完成")
    
    # 同步已有会员群链接到 member_groups
    print("🔄 同步会员群组数据...")
    print("ℹ️ 跳过启动时的群组数据同步，将在机器人启动后进行")
    print()
    
    # 2. 启动 Web 后台 (在独立线程中)
    print("🌐 启动Web管理后台...")
    web_thread = None
    try:
        # 【注意】这里的导入也建议检查一下 web_app.py 内部是否使用了相对导入
        from .web_app import run_web
        web_thread = threading.Thread(target=run_web, daemon=True)
        web_thread.start()
        print("✅ Web管理后台已启动 (端口: 5051)")
    except Exception as e:
        print(f"⚠️ Web后台启动失败: {e}")
        print("继续启动Bot...")
    print()
    
    # 3. 启动 Bot (主线程)
    print("🚀 Telegram机器人启动中...")
    print()
    print("=" * 60)
    print("📱 访问地址：")
    print("   Web后台: http://localhost:5051")
    print("   公网地址: http://154.201.68.178:5051")
    print("=" * 60)
    print()
    
    try:
        run_bot()

        # 保活逻辑
        print("ℹ️ Bot服务未启动或已结束，主进程进入保活模式以维持Web后台运行...")
        while True:
            time.sleep(10)

    except KeyboardInterrupt:
        print("\n🛑 收到停止信号，正在关闭服务...")
        if web_thread and web_thread.is_alive():
            print("正在停止Web服务器...")
        print("✅ 服务已停止")
    except Exception as e:
        print(f"❌ 机器人启动失败: {e}")
        import traceback
        traceback.print_exc()

        if web_thread and web_thread.is_alive():
            print("💡 Web服务可能仍在运行，可以单独访问管理后台")
            print("ℹ️ 主进程进入保活模式以维持Web后台运行...")
            while True:
                time.sleep(10)
        else:
            print("❌ 所有服务启动失败，请检查配置和网络连接")

if __name__ == '__main__':
    main()