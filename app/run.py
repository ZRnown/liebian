"""
启动入口 - 统一启动Bot和Web后台
"""
import threading
from database import init_db, sync_member_groups_from_members
from bot_logic import run_bot

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
    try:
        sync_member_groups_from_members()
        print("✅ 会员群组数据同步完成")
    except Exception as e:
        print(f"⚠️ 会员群组数据同步失败: {e}")
    print()
    
    # 2. 启动 Web 后台 (在独立线程中)
    print("🌐 启动Web管理后台...")
    try:
        from web_app import run_web
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
    print("=" * 60)
    print()
    print("💡 提示：")
    print("   - 所有服务正在运行中...")
    print("   - 按 Ctrl+C 停止所有服务")
    print("=" * 60)
    print()
    
    try:
        run_bot()
    except KeyboardInterrupt:
        print("\n停止服务...")
    except Exception as e:
        print(f"❌ 启动失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()

