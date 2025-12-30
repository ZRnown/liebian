#!/usr/bin/env python3
"""
测试启动脚本
"""
import sys
import os

def test_imports():
    """测试各种导入方式"""
    print("🔍 测试导入...")

    try:
        # 测试从app目录运行
        os.chdir('app')
        from database import init_db
        print("✅ 从app目录相对导入成功")
    except Exception as e:
        print(f"❌ 从app目录相对导入失败: {e}")
    finally:
        os.chdir('..')

    try:
        # 测试从根目录绝对导入
        from app.database import init_db
        print("✅ 从根目录绝对导入成功")
    except Exception as e:
        print(f"❌ 从根目录绝对导入失败: {e}")

    try:
        # 测试主程序导入
        import main
        print("✅ main.py 导入成功")
    except Exception as e:
        print(f"❌ main.py 导入失败: {e}")

def test_run():
    """测试运行"""
    print("\n🚀 测试运行...")

    try:
        # 测试app/run.py
        os.chdir('app')
        import run
        print("✅ app/run.py 可以导入")
    except Exception as e:
        print(f"❌ app/run.py 导入失败: {e}")
    finally:
        os.chdir('..')

if __name__ == "__main__":
    test_imports()
    test_run()
    print("\n✨ 测试完成")
