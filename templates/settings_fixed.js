// 加载捡漏账号列表
async function loadFallbackAccounts() {
    try {
        const response = await fetch('/api/settings/fallback-accounts');
        const data = await response.json();
        
        if (data.success && data.accounts) {
            const tbody = document.getElementById('fallback-accounts-list');
            tbody.innerHTML = data.accounts.map((acc, idx) => `
                <tr class="hover:bg-slate-50">
                    <td class="px-4 py-3 text-slate-700">#${idx + 1}</td>
                    <td class="px-4 py-3 font-medium text-slate-800">@${acc.username || '未设置'}</td>
                    <td class="px-4 py-3 text-slate-600">${acc.telegram_id || '-'}</td>
                    <td class="px-4 py-3 font-semibold text-green-600">${acc.balance || 0} U</td>
                    <td class="px-4 py-3">
                        <span class="px-2 py-1 bg-green-100 text-green-700 rounded text-xs">
                            ${acc.is_vip ? 'VIP' : '普通'}
                        </span>
                    </td>
                </tr>
            `).join('');
        }
    } catch (error) {
        console.error('加载捡漏账号失败:', error);
    }
}

// 加载Bot Token列表
async function loadBotTokens() {
    try {
        const response = await fetch('/api/settings/bot-tokens');
        const data = await response.json();
        
        if (data.success && data.tokens) {
            const container = document.getElementById('bot-tokens-list');
            if (data.tokens.length === 0) {
                container.innerHTML = '<p class="text-slate-400 text-sm text-center py-4">暂无Token</p>';
            } else {
                container.innerHTML = data.tokens.map((token, idx) => `
                    <div class="flex items-center gap-3 p-3 bg-slate-50 rounded-lg">
                        <span class="text-sm font-medium text-slate-600">#${idx + 1}</span>
                        <input type="text" value="${token.substring(0, 20)}..." disabled class="flex-1 bg-white border-0 ring-1 ring-slate-200 rounded-lg px-3 py-2 text-sm">
                        <button onclick="deleteBotToken(${idx})" class="px-3 py-2 bg-red-100 hover:bg-red-200 text-red-600 rounded-lg text-sm transition-all">
                            <i class="ti ti-trash"></i>
                        </button>
                    </div>
                `).join('');
            }
        }
    } catch (error) {
        console.error('加载Bot Token失败:', error);
    }
}

// 添加Bot Token
async function addBotToken() {
    const token = document.getElementById('new-bot-token').value.trim();
    if (!token) {
        showToast('输入错误', '请输入Bot Token', 'error');
        return;
    }
    
    try {
        const response = await fetch('/api/settings/bot-tokens', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token })
        });
        const data = await response.json();
        
        if (data.success) {
            showToast('添加成功', 'Bot Token已添加', 'success');
            document.getElementById('new-bot-token').value = '';
            loadBotTokens();
        } else {
            showToast('添加失败', data.message, 'error');
        }
    } catch (error) {
        showToast('添加失败', '网络错误', 'error');
    }
}

// 删除Bot Token
async function deleteBotToken(index) {
    if (!confirm('确定要删除这个Token吗？')) return;
    
    try {
        const response = await fetch(`/api/settings/bot-tokens/${index}`, {
            method: 'DELETE'
        });
        const data = await response.json();
        
        if (data.success) {
            showToast('删除成功', 'Token已删除', 'success');
            loadBotTokens();
        } else {
            showToast('删除失败', data.message, 'error');
        }
    } catch (error) {
        showToast('删除失败', '网络错误', 'error');
    }
}

// 更新置顶广告
async function updatePinnedAd() {
    const content = document.getElementById('pinned-ad-content').value.trim();
    if (!content) {
        showToast('输入错误', '请输入广告内容', 'error');
        return;
    }
    updateSetting('pinned_ad', content, '置顶广告已更新');
}

// 更新群欢迎语
async function updateWelcomeMessage() {
    const content = document.getElementById('welcome-message-content').value.trim();
    if (!content) {
        showToast('输入错误', '请输入欢迎语内容', 'error');
        return;
    }
    updateSetting('welcome_message', content, '群欢迎语已更新');
}

window.addEventListener('DOMContentLoaded', function() {
    loadSettings();
    loadFallbackAccounts();
    loadBotTokens();
    
    // 加载置顶广告和欢迎语
    fetch('/api/settings').then(r => r.json()).then(data => {
        if (data.success && data.settings) {
            document.getElementById('pinned-ad-content').value = data.settings.pinned_ad || '';
            document.getElementById('welcome-message-content').value = data.settings.welcome_message || '';
        }
    }).catch(err => console.error('加载配置失败:', err));
    
    // 自动高亮当前页面导航栏
    const currentPath = window.location.pathname;
    const navLinks = document.querySelectorAll('aside nav a[href]');
    navLinks.forEach(link => {
        const href = link.getAttribute('href');
        link.classList.remove('bg-indigo-50', 'text-indigo-600', 'border', 'border-indigo-100/50', 'shadow-sm');
        link.classList.add('hover:bg-slate-50', 'text-slate-500', 'hover:text-slate-900');
        
        if ((currentPath === '/' && href === '/') || (currentPath === href && href !== '/')) {
            link.classList.remove('hover:bg-slate-50', 'text-slate-500', 'hover:text-slate-900');
            link.classList.add('bg-indigo-50', 'text-indigo-600', 'border', 'border-indigo-100/50', 'shadow-sm');
        }
    });
});
