#!/usr/bin/env python3
"""
测试团队图谱总览API
"""

import sys
import os
import json

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_team_graph_all_api():
    """测试团队图谱总览API"""
    try:
        from app.web_app import api_team_graph_all
        from flask import Flask

        # 创建测试应用上下文
        app = Flask(__name__)

        with app.app_context():
            print("测试团队图谱总览API...")

            try:
                # 调用API
                result = api_team_graph_all()
                print("API调用成功")

                # 解析响应
                response_data = json.loads(result.get_data(as_text=True))
                print("API响应数据结构:")
                print(f"- success: {response_data.get('success')}")
                print(f"- members数量: {len(response_data.get('members', []))}")
                print(f"- stats: {response_data.get('stats')}")

                # 验证数据结构
                if not response_data.get('success'):
                    print("❌ API返回失败")
                    return False

                members = response_data.get('members', [])
                if not isinstance(members, list):
                    print("❌ members不是数组")
                    return False

                if len(members) == 0:
                    print("⚠️ 没有成员数据")
                else:
                    # 检查第一个成员的数据结构
                    first_member = members[0]
                    required_fields = ['telegram_id', 'username', 'referrer_id', 'is_vip']
                    for field in required_fields:
                        if field not in first_member:
                            print(f"❌ 成员缺少字段: {field}")
                            return False
                    print("✅ 成员数据结构正确")

                stats = response_data.get('stats', {})
                required_stats = ['total', 'vip_count', 'max_depth', 'top_level']
                for field in required_stats:
                    if field not in stats:
                        print(f"❌ 统计信息缺少字段: {field}")
                        return False
                print("✅ 统计信息结构正确")

                print("✅ 团队图谱总览API测试通过")
                return True

            except Exception as e:
                print(f"❌ API调用失败: {e}")
                import traceback
                traceback.print_exc()
                return False

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = test_team_graph_all_api()
    if success:
        print("\n🎉 团队图谱总览API工作正常！")
    else:
        print("\n❌ 团队图谱总览API测试失败")
