# 💰 分红触发测试指南

## 🎯 分红触发机制

### 自动触发时机
分红在**用户开通VIP**时自动触发，系统会：
1. 检查上级10层
2. 验证每层上级的条件
3. 自动分配分红（满足条件）或转入捡漏账号（不满足）

---

## 🧪 测试方法

### 方法1：模拟充值触发（推荐）

#### 步骤1：准备测试账号
```
需要至少2个Telegram账号：
- 账号A：推荐人（上级）
- 账号B：新用户（下级）
```

#### 步骤2：建立推荐关系
```
1. 账号A先在机器人注册（/start）
2. 获取账号A的推荐链接
3. 账号B通过推荐链接注册
```

#### 步骤3：账号A完成所有条件
```
1. 账号A开通VIP
2. 账号A绑定群组（/bind_group）
3. 将机器人拉入群并设为管理员
4. 发送群链接给机器人完成绑定
5. 检查状态（/check_status）确保全部完成
```

#### 步骤4：账号B开通VIP（触发分红）
```
方式1 - 通过充值：
  在机器人中点击"开通VIP"按钮
  按提示充值（实际充值或后台手动到账）

方式2 - 后台手动开通：
  访问 http://localhost:5051
  找到账号B的记录
  手动修改余额和VIP状态
```

#### 步骤5：观察分红结果
```
✅ 如果账号A满足所有条件：
   - 账号A收到分红通知消息
   - 账号A余额增加10U（默认）
   - 账号A的total_earned增加10U

❌ 如果账号A未满足条件：
   - 账号A收到"错过分红"通知
   - 分红转入捡漏账号
   - 账号A的missed_balance增加10U
```

---

### 方法2：后台数据库直接操作（快速测试）

#### 使用SQLite管理工具
```bash
# 安装DB Browser for SQLite 或使用命令行
sqlite3 bot.db
```

#### 快速测试脚本
```sql
-- 1. 查看现有用户
SELECT telegram_id, username, is_vip, balance FROM members;

-- 2. 给测试用户充值（假设telegram_id是123456）
UPDATE members SET balance = 150 WHERE telegram_id = 123456;

-- 3. 手动触发VIP开通（需要在机器人中操作）
-- 或者直接设置VIP状态（但不会触发分红，不推荐）
-- UPDATE members SET is_vip = 1, vip_time = datetime('now') WHERE telegram_id = 123456;
```

**注意：直接修改数据库不会触发分红逻辑，必须通过充值流程！**

---

### 方法3：修改代码添加测试命令（开发测试）

创建测试命令快速触发分红：

```python
# 在a.py中添加测试命令（仅用于开发测试）

@bot.on(events.NewMessage(pattern='/test_bonus'))
async def test_bonus_handler(event):
    """测试分红功能（仅测试用）"""
    telegram_id = event.sender_id
    
    # 检查是否已是VIP
    member = DB.get_member(telegram_id)
    if not member:
        await event.respond('请先 /start 注册')
        return
    
    if member['is_vip']:
        await event.respond('您已是VIP，无法重复触发')
        return
    
    # 确认测试
    await event.respond(
        '⚠️ 测试模式：将开通VIP并触发分红\n\n'
        '确认执行？发送 "确认" 继续',
        buttons=[[Button.text('确认', resize=True)]]
    )

@bot.on(events.NewMessage(pattern='确认'))
async def confirm_test_bonus(event):
    """确认测试分红"""
    telegram_id = event.sender_id
    
    # 调用充值处理函数（模拟VIP充值）
    config = get_system_config()
    await process_recharge(telegram_id, config['vip_price'], is_vip_order=True)
    
    await event.respond('✅ 测试完成！请检查上级是否收到分红')
```

**使用方法：**
1. 添加上述代码到a.py
2. 重启机器人
3. 发送 `/test_bonus`
4. 发送 `确认`
5. 观察分红结果

---

## 📊 验证分红是否成功

### 方法1：查看Telegram消息
上级会收到以下消息之一：

**成功获得分红：**
```
🎉 恭喜！您获得了 10 U 分红！

来自第 1 层下级开通VIP
下级用户: @username
当前余额: 110 U
累计获得: 10 U
```

**错过分红：**
```
⚠️ 您错过了 10 U 分红！

原因：未完成以下条件
❌ 未绑定群组
❌ 机器人不是管理员

来自第 1 层下级开通VIP
累计错过: 10 U

💡 完成所有条件后即可获得分红
```

### 方法2：查看后台数据
访问 http://localhost:5051

**会员管理页面：**
- 查看`累计获得`字段（total_earned）
- 查看`错过余额`字段（missed_balance）

**捡漏账号页面：**
访问 http://localhost:5051/fallback-accounts
- 查看捡漏账号的累计收益

### 方法3：查询数据库
```sql
-- 查看用户余额和收益
SELECT 
    telegram_id, 
    username, 
    balance, 
    total_earned, 
    missed_balance 
FROM members 
WHERE telegram_id = 你的上级ID;

-- 查看捡漏账号收益
SELECT 
    telegram_id, 
    username, 
    total_earned 
FROM fallback_accounts;
```

---

## 🔧 常见问题

### Q1: 分红没有触发？
**检查清单：**
- ✅ 下级是否真的开通了VIP？
- ✅ 是否通过充值流程开通？（直接改数据库不会触发）
- ✅ 上级是否也是VIP？（非VIP不会获得分红）
- ✅ 检查系统配置中的`level_count`和`level_reward`

### Q2: 分红金额不对？
**检查系统配置：**
```sql
SELECT * FROM system_config WHERE key IN ('level_count', 'level_reward');
```
默认值：
- `level_count`: 10（分红层数）
- `level_reward`: 10（每层分红金额）

### Q3: 分红全部进入捡漏账号？
**说明上级未满足条件，需要：**
1. 上级必须是VIP
2. 上级必须绑定群组
3. 机器人必须在群里且是管理员
4. 上级必须加入所有上层群

使用 `/check_status` 检查状态

### Q4: 如何查看分红记录？
**暂无专门的分红记录表，可以通过：**
1. 查看用户的`total_earned`字段
2. 查看Telegram消息历史
3. 后台日志（如果启用了日志记录）

**建议：** 可以添加一个`bonus_records`表记录所有分红历史

---

## 💡 测试建议

### 完整测试流程
```
1. 创建3个测试账号（A → B → C）
2. A推荐B，B推荐C
3. A和B都开通VIP并完成所有条件
4. C开通VIP
5. 观察：
   - B应该获得第1层分红（10U）
   - A应该获得第2层分红（10U）
   - 其余8层进入捡漏账号
```

### 边界情况测试
```
场景1：上级未开通VIP
  结果：分红进入捡漏账号

场景2：上级是VIP但未绑群
  结果：分红进入捡漏账号，上级收到"错过分红"通知

场景3：10层都是真实用户且都满足条件
  结果：每层各得10U，无捡漏账号收益

场景4：没有上级（第1个用户）
  结果：10层全部进入捡漏账号
```

---

## 🚀 快速开始

**最简单的测试方法：**

1. **准备两个Telegram账号**

2. **账号A（上级）完成设置：**
   ```
   /start
   开通VIP
   /bind_group
   （绑定群组并设置机器人为管理员）
   /check_status （确认全部✅）
   ```

3. **账号B（下级）通过A的推荐链接注册：**
   ```
   （点击A的推荐链接）
   /start
   开通VIP
   ```

4. **观察结果：**
   - 账号A应该立即收到分红通知
   - 后台查看A的余额增加

**就这么简单！**

---

## 📞 需要帮助？

如果分红仍未触发，请提供：
1. 下级的telegram_id
2. 上级的telegram_id
3. `/check_status` 的截图
4. 后台会员管理页面的截图

我会帮您诊断问题！
