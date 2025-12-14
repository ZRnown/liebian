#!/usr/bin/env python3
"""
部署环境检查脚本
用于检查部署环境是否满足要求
"""

import sys
import os
import subprocess

def check_python_version():
    """检查Python版本"""
    print("=" * 60)
    print("📦 检查 Python 版本...")
    version = sys.version_info
    if version.major >= 3 and version.minor >= 7:
        print(f"✅ Python {version.major}.{version.minor}.{version.micro} - 符合要求")
        return True
    else:
        print(f"❌ Python {version.major}.{version.minor}.{version.micro} - 需要 Python 3.7+")
        return False

def check_dependencies():
    """检查依赖包"""
    print("\n" + "=" * 60)
    print("📦 检查依赖包...")
    
    required_packages = {
        'flask': 'Flask',
        'telethon': 'Telethon',
        'requests': 'requests',
        'werkzeug': 'werkzeug',
        'qrcode': 'qrcode',
        'PIL': 'Pillow',
        'flask_login': 'flask-login'
    }
    
    missing = []
    for module, package in required_packages.items():
        try:
            __import__(module)
            print(f"✅ {package} - 已安装")
        except ImportError:
            print(f"❌ {package} - 未安装")
            missing.append(package)
    
    if missing:
        print(f"\n⚠️  缺少以下依赖包: {', '.join(missing)}")
        print("   请运行: pip3 install -r requirements.txt")
        return False
    return True

def check_files():
    """检查必需文件"""
    print("\n" + "=" * 60)
    print("📁 检查项目文件...")
    
    required_files = [
        'a.py',
        'requirements.txt',
        'start.sh',
        'stop.sh',
        'core_functions.py',
        'bot_commands_addon.py'
    ]
    
    missing = []
    for file in required_files:
        if os.path.exists(file):
            print(f"✅ {file} - 存在")
        else:
            print(f"❌ {file} - 不存在")
            missing.append(file)
    
    if missing:
        print(f"\n⚠️  缺少以下文件: {', '.join(missing)}")
        return False
    return True

def check_directories():
    """检查必需目录"""
    print("\n" + "=" * 60)
    print("📂 检查项目目录...")
    
    required_dirs = [
        'templates',
        'static'
    ]
    
    missing = []
    for dir_name in required_dirs:
        if os.path.exists(dir_name) and os.path.isdir(dir_name):
            print(f"✅ {dir_name}/ - 存在")
        else:
            print(f"❌ {dir_name}/ - 不存在")
            missing.append(dir_name)
    
    if missing:
        print(f"\n⚠️  缺少以下目录: {', '.join(missing)}")
        return False
    return True

def check_config():
    """检查配置文件"""
    print("\n" + "=" * 60)
    print("⚙️  检查配置文件...")
    
    try:
        with open('a.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        checks = {
            'API_ID': 'API_ID = ' in content,
            'API_HASH': 'API_HASH = ' in content,
            'BOT_TOKEN': 'BOT_TOKEN = ' in content,
            'ADMIN_IDS': 'ADMIN_IDS = ' in content,
        }
        
        all_ok = True
        for key, exists in checks.items():
            if exists:
                # 检查是否为默认值（需要用户修改）
                if key == 'API_ID' and '21332425' in content:
                    print(f"⚠️  {key} - 存在但可能是默认值，请确认已修改")
                elif key == 'BOT_TOKEN' and '8282974213:AAEISGP5ijUbJSBMA9N5eoygWjAB266-1UE' in content:
                    print(f"⚠️  {key} - 存在但可能是默认值，请确认已修改")
                else:
                    print(f"✅ {key} - 已配置")
            else:
                print(f"❌ {key} - 未找到")
                all_ok = False
        
        return all_ok
    except Exception as e:
        print(f"❌ 无法读取配置文件: {e}")
        return False

def check_permissions():
    """检查文件权限"""
    print("\n" + "=" * 60)
    print("🔐 检查文件权限...")
    
    files_to_check = ['start.sh', 'stop.sh']
    all_ok = True
    
    for file in files_to_check:
        if os.path.exists(file):
            if os.access(file, os.X_OK):
                print(f"✅ {file} - 有执行权限")
            else:
                print(f"⚠️  {file} - 无执行权限，运行: chmod +x {file}")
                all_ok = False
        else:
            print(f"⚠️  {file} - 不存在")
    
    return all_ok

def check_database():
    """检查数据库"""
    print("\n" + "=" * 60)
    print("💾 检查数据库...")
    
    if os.path.exists('bot.db'):
        size = os.path.getsize('bot.db')
        print(f"✅ bot.db - 存在 ({size} 字节)")
        
        # 检查是否可读写
        try:
            import sqlite3
            conn = sqlite3.connect('bot.db')
            conn.execute('SELECT 1')
            conn.close()
            print("✅ 数据库可正常访问")
            return True
        except Exception as e:
            print(f"❌ 数据库无法访问: {e}")
            return False
    else:
        print("ℹ️  bot.db - 不存在（首次运行会自动创建）")
        return True

def check_port():
    """检查端口占用"""
    print("\n" + "=" * 60)
    print("🔌 检查端口 5051...")
    
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('127.0.0.1', 5051))
        sock.close()
        
        if result == 0:
            print("⚠️  端口 5051 已被占用")
            print("   如果服务正在运行，这是正常的")
            return True
        else:
            print("✅ 端口 5051 可用")
            return True
    except Exception as e:
        print(f"⚠️  无法检查端口: {e}")
        return True

def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("🔍 裂变推广机器人 - 部署环境检查")
    print("=" * 60)
    
    results = []
    
    results.append(("Python版本", check_python_version()))
    results.append(("依赖包", check_dependencies()))
    results.append(("项目文件", check_files()))
    results.append(("项目目录", check_directories()))
    results.append(("配置文件", check_config()))
    results.append(("文件权限", check_permissions()))
    results.append(("数据库", check_database()))
    results.append(("端口", check_port()))
    
    # 总结
    print("\n" + "=" * 60)
    print("📊 检查结果总结")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{name}: {status}")
    
    print("\n" + "=" * 60)
    if passed == total:
        print("🎉 所有检查通过！可以开始部署了。")
        print("\n下一步：")
        print("1. 确认 a.py 中的配置已正确修改")
        print("2. 运行: ./start.sh 启动服务")
        print("3. 访问: http://你的IP:5051 登录管理后台")
    else:
        print(f"⚠️  有 {total - passed} 项检查未通过，请先解决这些问题。")
        print("\n请参考 部署指南.md 获取详细帮助。")
    print("=" * 60 + "\n")
    
    return passed == total

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)

