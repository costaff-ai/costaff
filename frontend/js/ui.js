const UI = {
    lastLogs: "",
    chatState: { app: null, session: null, user: 'web-user' },
    _requireApproval: true,

    // --- Approval Toggle ---
    _approvalIsOss: false,
    async initApprovalToggle() {
        try {
            const [conf, lic] = await Promise.all([
                API.fetch('/api/config'),
                API.fetch('/api/license'),
            ]);
            this._approvalIsOss = !lic || lic.plan === 'oss' || lic.plan === 'invalid';
            this._requireApproval = !this._approvalIsOss && conf.require_approval !== false;
        } catch(e) {
            this._approvalIsOss = true;
            this._requireApproval = false;
        }
        this._renderApprovalToggle();
    },
    _renderApprovalToggle() {
        const btn = document.getElementById('approval-toggle-btn');
        const knob = document.getElementById('approval-toggle-knob');
        const text = document.getElementById('approval-status-text');
        if (!btn) return;
        if (this._approvalIsOss) {
            btn.className = "relative inline-flex h-7 w-14 items-center rounded-full transition-colors focus:outline-none bg-slate-200 cursor-not-allowed";
            knob.className = "inline-block h-5 w-5 transform rounded-full bg-white shadow-md transition-transform translate-x-1";
            text.innerHTML = `All users chat without approval &nbsp;<span class="px-1.5 py-0.5 rounded text-[10px] font-black bg-blue-100 text-blue-600 uppercase">Enterprise</span>`;
            btn.onclick = null;
        } else if (this._requireApproval) {
            btn.className = "relative inline-flex h-7 w-14 items-center rounded-full transition-colors focus:outline-none bg-amber-500 cursor-pointer";
            knob.className = "inline-block h-5 w-5 transform rounded-full bg-white shadow-md transition-transform translate-x-8";
            text.textContent = "New users must be approved by admin before chatting";
            btn.onclick = () => UI.toggleRequireApproval();
        } else {
            btn.className = "relative inline-flex h-7 w-14 items-center rounded-full transition-colors focus:outline-none bg-slate-300 cursor-pointer";
            knob.className = "inline-block h-5 w-5 transform rounded-full bg-white shadow-md transition-transform translate-x-1";
            text.textContent = "All users can chat without approval";
            btn.onclick = () => UI.toggleRequireApproval();
        }
    },
    async toggleRequireApproval() {
        if (this._approvalIsOss) return;
        this._requireApproval = !this._requireApproval;
        this._renderApprovalToggle();
        try {
            await API.fetch('/api/config/require-approval', {
                method: 'POST',
                body: JSON.stringify({ enabled: this._requireApproval })
            });
        } catch(e) {
            this._requireApproval = !this._requireApproval;
            this._renderApprovalToggle();
        }
    },

    // --- Theme Management ---
    loadTheme() {
        const theme = localStorage.getItem('mate_theme') || 'light';
        this.toggleTheme(theme);
    },
    toggleTheme(mode) {
        if (mode === 'light') {
            document.body.classList.add('light-mode');
            localStorage.setItem('mate_theme', 'light');
        } else {
            document.body.classList.remove('light-mode');
            localStorage.setItem('mate_theme', 'dark');
        }
        this.updateThemeUI(mode);
    },
    updateThemeUI(mode) {
        const darkBtn = document.getElementById('theme-btn-dark');
        const lightBtn = document.getElementById('theme-btn-light');
        if (!darkBtn || !lightBtn) return;

        if (mode === 'light') {
            lightBtn.className = "flex-1 flex flex-col items-center gap-3 p-6 rounded-3xl border-2 border-blue-600 bg-blue-50 shadow-xl shadow-blue-600/10 transition-all";
            lightBtn.innerHTML = `<i class="fas fa-sun text-2xl text-blue-600"></i><span class="text-xs font-black uppercase tracking-widest text-blue-600">Light Mode</span>`;
            
            darkBtn.className = "flex-1 flex flex-col items-center gap-3 p-6 rounded-3xl border-2 border-slate-200 bg-white hover:border-slate-300 transition-all";
            darkBtn.innerHTML = `<i class="fas fa-moon text-2xl text-slate-400"></i><span class="text-xs font-black uppercase tracking-widest text-slate-400">Dark Mode</span>`;
        } else {
            darkBtn.className = "flex-1 flex flex-col items-center gap-3 p-6 rounded-3xl border-2 border-blue-600 bg-blue-600/10 shadow-xl shadow-blue-600/20 transition-all";
            darkBtn.innerHTML = `<i class="fas fa-moon text-2xl text-blue-400"></i><span class="text-xs font-black uppercase tracking-widest text-blue-400">Dark Mode</span>`;
            
            lightBtn.className = "flex-1 flex flex-col items-center gap-3 p-6 rounded-3xl border-2 transition-all" + " border-white/10 hover:border-white/20" + " " + "bg-white/5";
            lightBtn.innerHTML = `<i class="fas fa-sun text-2xl" style="color:#475569"></i><span class="text-xs font-black uppercase tracking-widest" style="color:#475569">Light Mode</span>`;
        }
    },

    parseMarkdown(text) {
        if (!text) return "";
        if (typeof marked !== 'undefined') {
            try { return marked.parse(text); } catch(e) { return text; }
        }
        return text.replace(/\n/g, '<br>');
    },

    formatUptime(seconds) {
        const d = Math.floor(seconds / (3600*24));
        const h = Math.floor(seconds % (3600*24) / 3600);
        const m = Math.floor(seconds % 3600 / 60);
        if (d > 0) return `${d}d ${h}h`;
        if (h > 0) return `${h}h ${m}m`;
        return `${m}m`;
    },

    renderLicense(data) {
        const card = document.getElementById('license-card');
        if (!card) return;

        if (data.plan === 'invalid') {
            card.innerHTML = `
                <div class="flex items-center gap-3 text-red-500">
                    <i class="fas fa-exclamation-triangle text-xl"></i>
                    <div>
                        <p class="text-xs font-black uppercase tracking-widest">License Invalid</p>
                        <p class="text-xs text-slate-400 mt-1">${data.error || 'Unknown error'}</p>
                    </div>
                </div>`;
            return;
        }

        const isEnterprise = data.plan !== 'oss';
        const isExpired    = data.is_expired;
        const planLabel    = data.plan.toUpperCase();
        const planColor    = isExpired ? 'red' : isEnterprise ? 'blue' : 'slate';
        const limits       = data.limits || {};

        const expiryText = data.expires_at
            ? (isExpired ? `Expired on ${data.expires_at}` : `Valid until ${data.expires_at}`)
            : 'No expiry';
        const expiryColor = isExpired ? 'text-red-500' : 'text-slate-400';

        const usage = data.usage || {};

        const fmtLimit = (v) => (v === 999 || v === 999999) ? '∞' : v;
        const barColor = (pct) => pct >= 100 ? 'bg-red-500' : pct >= 80 ? 'bg-yellow-400' : 'bg-blue-500';
        const pct = (used, limit) => limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0;

        const progressItem = (label, used, limit) => {
            const p = pct(used, limit);
            return `
            <div class="flex flex-col gap-2">
                <div class="flex justify-between items-center">
                    <span class="text-xs font-black uppercase tracking-widest text-slate-400">${label}</span>
                    <span class="text-xs font-bold text-slate-500">${used} / ${fmtLimit(limit)}</span>
                </div>
                <div class="w-full h-2 bg-slate-100 rounded-full overflow-hidden">
                    <div class="h-full rounded-full transition-all ${barColor(p)}" style="width: ${p}%"></div>
                </div>
            </div>`;
        };

        const metrics = [
            { label: 'Monthly Executions', used: usage.monthly_executions ?? 0, limit: limits.monthly_executions ?? 30 },
            { label: 'Extra MCP',          used: usage.extra_mcp ?? 0,           limit: limits.extra_mcp ?? 1 },
            { label: 'Users',              used: usage.users ?? 0,               limit: limits.max_users ?? 1 },
            { label: 'Channels',           used: usage.enabled_channels ?? 0,    limit: limits.enabled_channels ?? 1 },
            { label: 'APIs',               used: usage.apis ?? 0,                limit: limits.max_apis ?? 5 },
            { label: 'Skills',             used: usage.skills ?? 0,              limit: limits.max_skills ?? 5 },
        ];

        card.innerHTML = `
            <div class="flex flex-col gap-5">
                <div class="flex items-center justify-between">
                    <div class="flex items-center gap-4">
                        <div class="w-12 h-12 rounded-2xl bg-${planColor}-50 flex items-center justify-center">
                            <i class="fas fa-${isEnterprise ? 'shield-alt' : 'code-branch'} text-${planColor}-500 text-xl"></i>
                        </div>
                        <div>
                            <div class="flex items-center gap-2">
                                <span class="text-lg font-headline font-bold text-slate-900">${planLabel} PLAN</span>
                                ${isExpired ? '<span class="text-[10px] font-black uppercase bg-red-50 text-red-500 px-2 py-0.5 rounded-full">EXPIRED</span>' : ''}
                            </div>
                            ${data.issued_to ? `<p class="text-xs text-slate-400 mt-0.5">${data.issued_to}</p>` : ''}
                            <p class="text-xs ${expiryColor} mt-0.5">${expiryText}</p>
                        </div>
                    </div>
                    ${!isEnterprise ? `
                    <a href="mailto:simonliuyuwei@gmail.com?subject=Mateclaw Enterprise License Inquiry"
                       class="text-[10px] font-black uppercase tracking-widest text-blue-600 hover:text-blue-700 transition-all whitespace-nowrap">
                        Upgrade →
                    </a>` : ''}
                </div>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                    ${metrics.map(m => progressItem(m.label, m.used, m.limit)).join('')}
                </div>
            </div>`;
    },

    renderOSStats(data) {
        const grid = document.getElementById('os-stats-grid');
        if (!grid) return;
        const metrics = [
            { label: 'CPU LOAD', value: data.cpu, color: 'primary', icon: 'bolt' },
            { label: 'MEMORY', value: data.memory, color: 'accent', icon: 'memory' },
            { label: 'DISK IO', value: data.disk, color: 'primary', icon: 'hdd' },
            { label: 'UPTIME', value: this.formatUptime(data.uptime), color: 'primary', icon: 'schedule', isRaw: true }
        ];
        grid.innerHTML = metrics.map(m => `
            <div class="card-linear min-h-[160px] bg-white border border-slate-100 shadow-xl rounded-3xl p-6 hover:bg-slate-50 transition-all cursor-default group">
                <div class="flex justify-between items-start mb-4">
                    <span class="label-mono text-[10px] font-bold text-slate-400 tracking-[0.2em] uppercase">${m.label}</span>
                    <i class="fas fa-${m.icon} text-primary opacity-30 transition-all group-hover:scale-110"></i>
                </div>
                <div class="mt-auto">
                    <div class="text-4xl font-headline font-bold mb-3 text-slate-900">${m.isRaw ? m.value : m.value + '%'}</div>
                    ${!m.isRaw ? `<div class="progress-bar bg-slate-100"><div class="progress-fill" style="width: ${m.value}%"></div></div>` : ''}
                </div>
            </div>`).join('');
    },

    _usersProfiles: [],
    _activeIdentityId: null,

    _channelIcon(sid) {
        if (sid.startsWith('tg_'))   return { icon: 'fab fa-telegram', color: 'bg-sky-500', label: 'Telegram' };
        if (sid.startsWith('dc_'))   return { icon: 'fab fa-discord',  color: 'bg-indigo-500', label: 'Discord' };
        if (sid.startsWith('line_')) return { icon: 'fab fa-line',     color: 'bg-green-500', label: 'LINE' };
        return { icon: 'fas fa-globe', color: 'bg-slate-400', label: 'Unknown' };
    },

    renderUsersPage(identities, profiles) {
        this._usersProfiles = profiles || [];
        const list = document.getElementById('identity-list');
        const countEl = document.getElementById('users-count-label');
        if (!list) return;

        if (countEl) countEl.textContent = `${identities.length} ident${identities.length !== 1 ? 'ities' : 'ity'}`;

        if (!identities || !identities.length) {
            list.innerHTML = `<div class="text-center py-20 text-slate-300"><i class="fas fa-id-card text-4xl mb-4 block"></i><p class="font-bold text-sm">No identities yet</p></div>`;
            return;
        }

        list.innerHTML = identities.map(id => {
            const ch = this._channelIcon(id.session_id);
            const name = id.name || 'Unknown';
            const isActive = this._activeIdentityId === id.session_id;
            const statusDot = id.is_approved
                ? '<span class="w-2 h-2 rounded-full bg-emerald-500 shrink-0"></span>'
                : '<span class="w-2 h-2 rounded-full bg-amber-400 shrink-0"></span>';
            return `<div onclick="UI.selectIdentity(${JSON.stringify(id).replace(/"/g, '&quot;')})"
                 class="p-5 border-b border-slate-100 cursor-pointer hover:bg-slate-50 transition-all group ${isActive ? 'bg-blue-50 border-l-4 border-l-blue-600' : ''}">
                <div class="flex items-center gap-3 mb-1">
                    <div class="w-8 h-8 rounded-lg ${ch.color} text-white flex items-center justify-center shrink-0">
                        <i class="${ch.icon} text-xs"></i>
                    </div>
                    <span class="font-bold text-sm text-slate-800 group-hover:text-slate-900 flex-1 truncate">${name}</span>
                    ${statusDot}
                </div>
                <p class="font-mono text-[10px] text-slate-400 truncate ml-11">${id.session_id}</p>
            </div>`;
        }).join('');

        // Re-select active if still in list
        if (this._activeIdentityId) {
            const active = identities.find(i => i.session_id === this._activeIdentityId);
            if (active) this.selectIdentity(active, true);
        }
    },

    selectIdentity(id, silent = false) {
        this._activeIdentityId = id.session_id;
        if (!silent) {
            // Re-render list to update active state without re-fetching
            const items = document.querySelectorAll('#identity-list > div');
            items.forEach(el => {
                const isActive = el.querySelector('.font-mono')?.textContent?.trim() === id.session_id;
                el.classList.toggle('bg-blue-50', isActive);
                el.classList.toggle('border-l-4', isActive);
                el.classList.toggle('border-l-blue-600', isActive);
            });
        }

        const placeholder = document.getElementById('user-placeholder');
        const content = document.getElementById('user-content');
        placeholder.classList.add('hidden');
        content.classList.remove('hidden');
        content.classList.add('flex');

        const ch = this._channelIcon(id.session_id);
        document.getElementById('user-channel-icon').className = `w-16 h-16 rounded-2xl ${ch.color} text-white flex items-center justify-center text-2xl shadow-xl`;
        document.getElementById('user-channel-icon').innerHTML = `<i class="${ch.icon}"></i>`;
        document.getElementById('user-detail-name').textContent = id.name || 'Unknown';

        const statusBadge = id.is_approved
            ? '<span class="px-3 py-1 rounded-full text-[10px] font-black bg-emerald-50 text-emerald-600">APPROVED</span>'
            : '<span class="px-3 py-1 rounded-full text-[10px] font-black bg-amber-50 text-amber-500">PENDING</span>';
        document.getElementById('user-status-badge').innerHTML = statusBadge;

        const approveBtn = id.is_approved
            ? `<button onclick="UI.setIdentityApproval('${id.session_id}', false)" class="px-5 py-2 rounded-xl text-[10px] font-black uppercase bg-rose-50 text-rose-500 hover:bg-rose-500 hover:text-white transition-all border border-rose-100">Revoke</button>`
            : `<button onclick="UI.setIdentityApproval('${id.session_id}', true)" class="px-5 py-2 rounded-xl text-[10px] font-black uppercase bg-emerald-600 text-white hover:bg-emerald-700 transition-all">Approve</button>`;
        const deleteBtn = `<button onclick="UI.deleteIdentity('${id.session_id}')" class="p-2.5 rounded-xl text-slate-400 hover:text-rose-500 hover:bg-rose-50 transition-all border border-slate-100"><i class="fas fa-trash-alt text-xs"></i></button>`;
        document.getElementById('user-detail-actions').innerHTML = approveBtn + deleteBtn;

        document.getElementById('user-session-id').textContent = id.session_id;
        document.getElementById('user-hashed-id').textContent = id.hashed_id || '—';
        document.getElementById('user-channel-label').textContent = ch.label;
        document.getElementById('user-created-at').textContent = id.created_at ? new Date(id.created_at).toLocaleString() : '—';

        // Profile panel
        const profile = this._usersProfiles.find(p => p.user_id === id.hashed_id);
        const profileBody = document.getElementById('user-profile-body');
        if (profile) {
            const rows = [
                ['Chinese Name', profile.chinese_name],
                ['English Name', profile.english_name],
                ['Job Title',    profile.job_title],
                ['Company',      profile.company_name],
                ['Email',        profile.personal_email],
                ['Phone',        profile.mobile_phone],
            ].filter(([, v]) => v);
            profileBody.innerHTML = rows.length
                ? rows.map(([label, val]) => `
                    <div class="flex items-center gap-4">
                        <span class="text-[10px] font-black text-slate-400 uppercase tracking-widest w-28 shrink-0">${label}</span>
                        <span class="text-sm text-slate-700">${val}</span>
                    </div>`).join('')
                + `<div class="pt-4 border-t border-slate-100 mt-2">
                    <button onclick="UI.deleteUser('${profile.user_id}')" class="text-[10px] font-black text-rose-400 hover:text-rose-600 uppercase tracking-widest transition-colors">Delete Profile</button>
                </div>`
                : `<p class="text-[11px] text-slate-400 italic">Profile exists but has no fields filled in.</p>`;
        } else {
            profileBody.innerHTML = `<p class="text-[11px] text-slate-400 italic">No profile linked to this identity yet.</p>`;
        }
    },

    async setIdentityApproval(sessionId, approve) {
        try {
            await API.fetch(`/api/identities/${encodeURIComponent(sessionId)}/${approve ? 'approve' : 'revoke'}`, { method: 'POST' });
            App.refresh();
        } catch(e) { alert('Failed to update approval status.'); }
    },

    async deleteIdentity(sessionId) {
        if (!confirm(`Delete identity ${sessionId}?`)) return;
        try {
            await API.fetch(`/api/identities/${encodeURIComponent(sessionId)}`, { method: 'DELETE' });
            App.refresh();
        } catch(e) { alert('Failed to delete identity.'); }
    },

    async deleteUser(userId) {
        if (!confirm('Delete this user profile? This cannot be undone.')) return;
        try {
            await API.fetch(`/api/users/${userId}`, { method: 'DELETE' });
            App.refresh();
        } catch(e) { alert('Failed to delete user.'); }
    },

    async deleteUserState(appName, userId) {
        if (!confirm(`Delete memory state for ${userId}?`)) return;
        try {
            await API.fetch(`/api/memory/user_states?app_name=${encodeURIComponent(appName)}&user_id=${encodeURIComponent(userId)}`, { method: 'DELETE' });
            App.refresh();
        } catch(e) { alert('Failed to delete memory state.'); }
    },

    drawTable(hId, bId, schemaType, data) {
        const head = document.getElementById(hId); 
        const body = document.getElementById(bId); 
        if (!data || data.length === 0) { 
            if (body) body.innerHTML = '<tr><td colspan="6" class="text-center py-20 text-slate-500 font-headline uppercase tracking-widest opacity-30 italic">No records found</td></tr>'; 
            return; 
        }
        const s = Config.TABLE_SCHEMAS[schemaType]; 
        const deletableTables = ['reminders', 'identities', 'user_states'];
        if (head) head.innerHTML = `<tr class="bg-slate-50 uppercase tracking-widest text-[9px] font-bold text-primary/60">${s.cols.map(c => `<th class="px-6 py-4 text-left font-headline">${c}</th>`).join('')}${deletableTables.includes(schemaType)?'<th class="px-6 py-4"></th>':''}</tr>`;
        
        if (body) body.innerHTML = data.map(r => `
            <tr class="group hover:bg-slate-50 transition-all border-b border-slate-100 last:border-none">
                ${s.keys.map(k => { 
                    let val = r[k] || '-'; 
                    if (schemaType === 'reminders' && k === 'run_at' && r.cron) {
                        val = `<span class="font-mono text-blue-600 font-bold">${r.cron}</span>`;
                    }
                    if (schemaType === 'reminders' && k === 'channel' && r.channel === 'command') {
                        val = `<span class="bg-slate-900 text-white px-2 py-0.5 rounded text-[9px] font-black tracking-tighter uppercase">Shell_Exec</span>`;
                    }
                    
                    if (k === 'status' || k === 'state') {
                        let displayVal = val.toString().toUpperCase();
                        const isCron = schemaType === 'reminders' && r.cron;

                        // Handle JSON states for Memory
                        if (k === 'state' && typeof val === 'object' && val !== null) {
                            displayVal = `<span class="text-[10px] font-mono text-blue-500 opacity-80" title='${JSON.stringify(val)}'>{ DATA_OBJ }</span>`;
                        } else if (k === 'state' && typeof val === 'string' && val.startsWith('{')) {
                            displayVal = `<span class="text-[10px] font-mono text-blue-500 opacity-80" title='${val}'>{ MEMORY_BLOCK }</span>`;
                        }

                        // Map internal statuses to user-friendly labels
                        if (isCron) {
                            if (val === 'pending' || val === 'scheduled') displayVal = 'SCHEDULED';
                            if (val === 'active') displayVal = 'RUNNING';
                        }

                        const valLower = val.toString().toLowerCase();
                        const active = valLower.includes('up') || valLower.includes('success') || valLower.includes('online') || ['pending', 'scheduled', 'active'].includes(valLower);
                        const isError = valLower.includes('exit') || valLower.includes('error') || valLower.includes('fail');
                        const badgeClass = isError ? 'badge-error' : active ? 'badge-active' : 'badge-idle';

                        return `<td class="px-6 py-5">
                            <span class="status-badge ${badgeClass}">
                                <span class="badge-dot"></span>
                                ${displayVal}
                            </span>
                        </td>`;
                    }
                    if (schemaType === 'events' && k === 'content') {
                        try {
                            const parts = JSON.parse(val);
                            const html = parts.map(p => {
                                if (p.type === 'text') {
                                    return `<div class="text-sm text-slate-700 whitespace-pre-wrap leading-relaxed">${p.text.replace(/</g,'&lt;')}</div>`;
                                }
                                if (p.type === 'call') {
                                    const args = JSON.stringify(p.args, null, 2);
                                    return `<div class="text-xs mt-1"><span class="font-black text-amber-600">🔧 ${p.name}</span><pre class="text-slate-400 text-[10px] mt-1 whitespace-pre-wrap leading-relaxed">${args.substring(0, 400).replace(/</g,'&lt;')}</pre></div>`;
                                }
                                if (p.type === 'result') {
                                    const data = typeof p.data === 'string' ? p.data : JSON.stringify(p.data, null, 2);
                                    return `<div class="text-xs mt-1"><span class="font-black text-emerald-600">✅ ${p.name}</span><pre class="text-slate-400 text-[10px] mt-1 whitespace-pre-wrap leading-relaxed">${data.substring(0, 400).replace(/</g,'&lt;')}</pre></div>`;
                                }
                                return '';
                            }).join('<div class="border-t border-slate-50 my-2"></div>');
                            return `<td class="px-6 py-5 max-w-xs">${html}</td>`;
                        } catch(e) {}
                    }
                    return `<td class="px-6 py-5 text-sm font-medium text-slate-900">${val}</td>`;
                }).join('')}
                ${schemaType==='reminders' ? `<td class="px-6 py-5 text-right flex justify-end gap-2">
                    <button onclick="UI.openEditCronModal('${r.id}', '${r.channel}', '${r.recipient}', \`${(r.cron || '') + ' ' + (r.prompt || '')}\`.trim())" class="p-2 text-slate-400 hover:text-blue-600 transition-all"><i class="fas fa-edit text-xs"></i></button>
                    <button onclick="UI.deleteReminder('${r.id}')" class="p-2 text-slate-400 hover:text-rose-500 transition-all"><i class="fas fa-trash-alt text-xs"></i></button>
                </td>` : ''}
                ${schemaType==='identities' ? `<td class="px-6 py-5"><button onclick="UI.deleteIdentity('${r.session_id}')" class="p-2 text-slate-400 hover:text-rose-500 transition-all"><i class="fas fa-trash-alt text-xs"></i></button></td>` : ''}
                ${schemaType==='user_states' ? `<td class="px-6 py-5"><button onclick="UI.deleteUserState('${r.app_name}','${r.user_id}')" class="p-2 text-slate-400 hover:text-rose-500 transition-all"><i class="fas fa-trash-alt text-xs"></i></button></td>` : ''}
            </tr>`).join('');
    },

    renderDashboard(svcs) {
        const lastUpdateEl = document.getElementById('dashboard-last-update');
        if (lastUpdateEl) lastUpdateEl.innerText = `SYNC: ${new Date().toLocaleTimeString()}`;

        const table = document.getElementById('status-table');
        if (table) table.innerHTML = svcs.map(s => {
            const isActive = s.status.includes('Up');
            return `
            <tr class="group hover:bg-slate-50 transition-all">
                <td class="font-headline font-bold tracking-tight text-base uppercase text-slate-900">${s.name}</td>
                <td>
                    <span class="status-badge ${isActive ? 'badge-active' : 'badge-idle'}">
                        <span class="badge-dot"></span>
                        ${isActive ? 'ACTIVE' : 'IDLE'}
                    </span>
                </td>
                <td class="text-[11px] font-mono text-slate-400 italic uppercase">${s.status}</td>
                <td class="text-right">
                    <button onclick="UI.serviceAction('${s.name}', 'restart')" class="text-[9px] font-black text-blue-600 hover:text-white transition-all uppercase tracking-widest px-4 py-2 border border-blue-200 rounded-lg hover:bg-blue-600">RESTART</button>
                </td>
            </tr>`;
        }).join('');
            
        const statsGrid = document.getElementById('stats-grid');
        if (statsGrid) statsGrid.innerHTML = `
            <div class="card-linear bg-white border border-slate-100 shadow-xl rounded-3xl p-8 hover:bg-slate-50 transition-all duration-300 cursor-default group">
                <div class="label-mono text-[9px] mb-4 text-slate-400 tracking-[0.2em] uppercase">TOTAL SERVICES</div>
                <div class="text-5xl font-headline font-bold text-slate-900">${svcs.length}</div>
            </div>
            <div class="card-linear bg-white border border-slate-100 shadow-xl rounded-3xl p-8 hover:bg-slate-50 transition-all duration-300 cursor-default group">
                <div class="label-mono text-[9px] mb-4 text-slate-400 tracking-[0.2em] uppercase">HEALTHY NODES</div>
                <div class="text-5xl font-headline font-bold text-slate-900">${svcs.filter(s=>s.status.includes('Up')).length}</div>
            </div>
            <div class="card-linear bg-white border border-slate-100 shadow-xl rounded-3xl p-8 hover:bg-slate-50 transition-all duration-300 cursor-default group">
                <div class="label-mono text-[9px] mb-4 text-slate-400 tracking-[0.2em] uppercase">GATEWAYS</div>
                <div class="text-5xl font-headline font-bold text-slate-900">${svcs.filter(s=>s.name.includes('bot')).length}</div>
            </div>
            <div class="card-linear bg-white border border-slate-100 shadow-xl rounded-3xl p-8 hover:bg-slate-50 transition-all duration-300 cursor-default group">
                <div class="label-mono text-[9px] mb-4 text-slate-400 tracking-[0.2em] uppercase">MATE CORES</div>
                <div class="text-5xl font-headline font-bold text-slate-900">${svcs.filter(s=>s.name.includes('mcp')).length}</div>
            </div>`;
    },

    renderChatSessions(sessions) {
        const list = document.getElementById('chat-session-list');
        if (!list) return;
        // Show only web sessions (channels have their own history)
        const webSessions = sessions.filter(s => s.user_id === 'web-user' || s.id.startsWith('web-'));
        if (webSessions.length === 0) {
            list.innerHTML = `<div class="p-10 text-center text-slate-400 text-xs italic opacity-60">No conversations yet</div>`;
            return;
        }
        list.innerHTML = webSessions.map(s => `
            <div onclick="UI.loadChatHistory('${s.id}')"
                 class="p-5 border-b border-slate-100 cursor-pointer hover:bg-slate-50 transition-all group ${App.state.activeSession===s.id?'bg-blue-50 border-l-4 border-l-blue-600':''}">
                <div class="flex items-center justify-between mb-1">
                    <div class="text-[10px] text-slate-400 font-mono tracking-tighter">${new Date(s.update_time).toLocaleDateString()}</div>
                    ${App.state.activeSession===s.id ? '<span class="status-badge badge-live" style="font-size:8px;padding:2px 6px"><span class="badge-dot"></span>Active</span>' : ''}
                </div>
                <div class="text-xs font-mono truncate text-slate-500 group-hover:text-blue-600 transition-colors">${s.id}</div>
            </div>`).join('');
    },

    async initChat() {
        // Always connect to the mateclaw agent — same as channels (Telegram/Discord/Line)
        const agents = await API.fetch('/api/agents');
        this.chatState.app = agents.find(a => a.includes('mateclaw')) || agents[0] || 'mateclaw_agent';

        const form = document.getElementById('chat-form');
        if (form) form.onsubmit = (e) => { e.preventDefault(); this.sendChatMessage(); };
        const input = document.getElementById('chat-input');
        if (input) {
            input.addEventListener('input', (e) => this.handleChatInput(e));
            input.addEventListener('keydown', (e) => this.handleChatKeydown(e));
        }

        // Load history list; do NOT auto-start a session (session is created lazily on first send)
        const sessions = await API.fetch('/api/chat/sessions');
        this.renderChatSessions(sessions);

        // Auto-load the most recent web session that has messages
        const webSessions = sessions.filter(s => s.user_id === 'web-user' || s.id.startsWith('web-'));
        if (webSessions.length > 0) {
            await this.loadChatHistory(webSessions[0].id);
        }
    },

    handleChatInput(e) {
        const val = e.target.value;
        const panel = document.getElementById('slash-commands');
        if (val.startsWith('/')) { this.renderSlashCommands(val.substring(1)); panel.classList.remove('hidden'); }
        else { panel.classList.add('hidden'); }
    },

    handleChatKeydown(e) {
        const panel = document.getElementById('slash-commands');
        if (panel.classList.contains('hidden')) return;
        const items = panel.querySelectorAll('.slash-item');
        let activeIdx = Array.from(items).findIndex(i => i.classList.contains('bg-blue-50'));
        if (e.key === 'ArrowDown') { e.preventDefault(); if (activeIdx < items.length - 1) { items[activeIdx]?.classList.remove('bg-blue-50'); items[activeIdx + 1].classList.add('bg-blue-50'); items[activeIdx + 1].scrollIntoView({ block: 'nearest' }); } }
        else if (e.key === 'ArrowUp') { e.preventDefault(); if (activeIdx > 0) { items[activeIdx].classList.remove('bg-blue-50'); items[activeIdx - 1].classList.add('bg-blue-50'); items[activeIdx - 1].scrollIntoView({ block: 'nearest' }); } }
        else if (e.key === 'Enter' && activeIdx >= 0) { e.preventDefault(); items[activeIdx].click(); }
        else if (e.key === 'Escape') { panel.classList.add('hidden'); }
    },

    renderSlashCommands(filter = "") {
        const commands = [
            { cmd: 'start', desc: 'Initialize session' }, { cmd: 'reset', desc: 'Reset context' }, { cmd: 'profile', desc: 'View profile' },
            { cmd: 'list', desc: 'List reminders' }, { cmd: 'files', desc: 'View files' }, { cmd: 'help', desc: 'Commands' }
        ];
        const filtered = commands.filter(c => c.cmd.startsWith(filter.toLowerCase()));
        const list = document.getElementById('slash-list');
        if (filtered.length === 0) { document.getElementById('slash-commands').classList.add('hidden'); return; }
        list.innerHTML = filtered.map((c, idx) => `
            <div onclick="UI.applySlashCommand('${c.cmd}')" class="slash-item px-4 py-2.5 cursor-pointer hover:bg-slate-50 transition-all flex items-center justify-between group ${idx===0?'bg-blue-50':''}">
                <div class="flex items-center gap-3"><span class="text-blue-600 font-bold text-sm">/${c.cmd}</span><span class="text-xs text-slate-400 font-headline uppercase">${c.desc}</span></div>
            </div>`).join('');
    },

    applySlashCommand(cmd) {
        const input = document.getElementById('chat-input');
        input.value = `/${cmd} `; input.focus(); document.getElementById('slash-commands').classList.add('hidden');
    },

    async startNewChat() {
        this.chatState.session = 'web-' + Math.random().toString(36).substring(2, 10);
        App.state.activeSession = null;
        const label = document.getElementById('chat-session-label');
        if (label) label.innerText = `Session: ${this.chatState.session}`;
        document.getElementById('chat-messages').innerHTML = `<div class="flex flex-col items-center justify-center h-full text-slate-300 uppercase tracking-[0.3em] font-headline"><i class="fas fa-robot text-6xl mb-6"></i><p>Intelligence Synchronized</p></div>`;
        await API.fetch(`/api/proxy/sessions/${this.chatState.app}/${this.chatState.user}/${this.chatState.session}`, { method: 'POST' });
        this.renderChatSessions(await API.fetch('/api/chat/sessions'));
    },

    async sendChatMessage() {
        const input = document.getElementById('chat-input');
        const text = input.value.trim();
        if (!text || !this.chatState.app) return;
        if (!this.chatState.session) await this.startNewChat();
        input.value = ''; this.appendMessage('user', text);
        const thinkingId = 'thinking-' + Date.now();
        this.appendMessage('agent', '<div class="typing-dots"><span></span><span></span><span></span></div>', thinkingId);
        try {
            const res = await fetch('/api/proxy/run_sse', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${API.token()}` },
                body: JSON.stringify({ app_name: this.chatState.app, user_id: this.chatState.user, session_id: this.chatState.session, new_message: { role: 'user', parts: [{ text }] }, streaming: true })
            });
            const reader = res.body.getReader(); const decoder = new TextDecoder();
            let currentAgentMsgId = null; let currentText = "";
            const removeT = () => { const el = document.getElementById(thinkingId); if (el) el.remove(); };
            while (true) {
                const { done, value } = await reader.read(); if (done) break;
                const lines = decoder.decode(value).split('\n');
                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    try {
                        const data = JSON.parse(line.substring(6));
                        const parts = data.content?.parts || [];
                        for (const p of parts) {
                            if (p.functionCall) {
                                removeT();
                                currentAgentMsgId = null; currentText = "";
                                this.appendMessage('agent', `🔧 **Tool Call:** \`${p.functionCall.name}\``, null, 'tool-call');
                            } else if (p.functionResponse) {
                                currentAgentMsgId = null; currentText = "";
                                this.appendMessage('agent', `✅ **Tool Result:** \n\`\`\`json\n${JSON.stringify(p.functionResponse.response.structuredContent||p.functionResponse.response.content, null, 2)}\n\`\`\``, null, 'tool-res');
                            } else if (p.text) {
                                removeT();
                                if (!currentAgentMsgId || data.partial === false) {
                                    if (data.partial === false && currentAgentMsgId) { document.getElementById(currentAgentMsgId).querySelector('.chat-content').innerHTML = this.parseMarkdown(p.text); currentAgentMsgId = null; currentText = ""; }
                                    else { currentAgentMsgId = 'msg-' + Date.now(); this.appendMessage('agent', p.text, currentAgentMsgId); currentText = p.text; }
                                } else { currentText += p.text; document.getElementById(currentAgentMsgId).querySelector('.chat-content').innerHTML = this.parseMarkdown(currentText); }
                            }
                        }
                    } catch(e){}
                }
            }
            removeT();
        } catch(e){ this.appendMessage('agent', '❌ **Error:** Connection lost.'); }
    },

    // Directly appends a message bubble to a given container (used for history batch render)
    _appendHistoryMessage(container, author, text, extraClass = "", customTime = null) {
        const isToolCall = extraClass === 'tool-call';
        const isToolRes  = extraClass === 'tool-res';
        const bubbleClass = author === 'user'
            ? 'bg-blue-600 text-white rounded-2xl rounded-tr-none shadow-lg'
            : isToolCall ? 'bg-amber-50 border border-amber-200 text-amber-900 rounded-2xl shadow-sm'
            : isToolRes  ? 'bg-emerald-50 border border-emerald-200 text-emerald-900 rounded-2xl shadow-sm'
            : 'bg-white text-slate-900 border border-slate-200 shadow-sm rounded-2xl rounded-tl-none';
        const content = this.parseMarkdown(text);
        const div = document.createElement('div');
        div.className = `flex flex-col ${author === 'user' ? 'items-end' : 'items-start'} mb-4 w-full`;
        div.innerHTML = `
            <div class="px-5 py-3 max-w-[85%] ${bubbleClass} break-words">
                <div class="chat-content text-[14px] leading-relaxed">${content}</div>
            </div>
            <div class="text-[9px] text-slate-400 mt-1 uppercase font-bold tracking-widest px-1">
                ${author} • ${customTime || ''}
            </div>`;
        container.appendChild(div);
    },

    appendMessage(author, text, id = null, extraClass = "", customTime = null) {
        const container = document.getElementById('chat-messages'); if (!container) return;
        const placeholder = container.querySelector('.label-mono');
        if (placeholder && !extraClass.includes('tool')) container.innerHTML = '';
        const div = document.createElement('div'); 
        div.className = `flex flex-col ${author==='user'?'items-end':'items-start'} ${extraClass} mb-8 w-full`;
        if (id) div.id = id;
        const bubbleClass = author === 'user' 
            ? 'bg-blue-600 text-white rounded-2xl rounded-tr-none shadow-lg' 
            : 'bg-white text-black border border-slate-200 shadow-sm';
        const content = (author === 'agent' && !text.includes('typing-dots')) ? this.parseMarkdown(text) : text;
        div.innerHTML = `
            <div class="px-6 py-4 max-w-[85%] ${bubbleClass} break-words">
                <div class="chat-content text-[15px] leading-relaxed">${content}</div>
            </div>
            <div class="text-[9px] text-slate-500 mt-2 uppercase font-bold tracking-widest px-1">
                ${author} • ${customTime || new Date().toLocaleTimeString()}
            </div>`;
        container.appendChild(div); 
        setTimeout(() => { container.scrollTop = container.scrollHeight; }, 50);
    },

    async loadChatHistory(sid) {
        App.state.activeSession = sid; this.chatState.session = sid;
        const label = document.getElementById('chat-session-label');
        if (label) label.innerText = `Session: ${sid}`;
        this.renderChatSessions(await API.fetch('/api/chat/sessions'));
        const history = await API.fetch(`/api/chat/history/${sid}`); 
        const container = document.getElementById('chat-messages'); if (!container) return;
        container.innerHTML = '';
        if (!history || history.length === 0) {
            container.innerHTML = `<div class="h-full flex flex-col items-center justify-center text-slate-300 uppercase tracking-[0.3em] font-headline"><i class="fas fa-inbox text-5xl mb-4"></i><p class="text-xs">No messages in this session</p></div>`;
            return;
        }
        history.forEach(item => {
            let event = item.event_data;
            if (typeof event === 'string') { try { event = JSON.parse(event); } catch(e) { return; } }
            if (!event || !event.content) return;
            const isUser = event.content.role === 'user' || event.author === 'web-user' || event.author === 'user';
            const author = isUser ? 'user' : 'agent';
            const timestamp = new Date(item.timestamp * 1000).toLocaleTimeString();
            (event.content.parts || []).forEach(p => {
                // ADK DB stores snake_case; SSE stream uses camelCase — handle both
                const funcCall = p.function_call || p.functionCall;
                const funcResp = p.function_response || p.functionResponse;
                if (p.text && p.text.trim()) {
                    this._appendHistoryMessage(container, author, p.text, '', timestamp);
                } else if (funcCall) {
                    const argsStr = Object.keys(funcCall.args || {}).length
                        ? '\n```json\n' + JSON.stringify(funcCall.args, null, 2) + '\n```'
                        : '';
                    this._appendHistoryMessage(container, 'agent', `🔧 **${funcCall.name}**${argsStr}`, 'tool-call', timestamp);
                } else if (funcResp) {
                    const resp = funcResp.response || {};
                    const content = resp.structuredContent || resp.content || resp;
                    this._appendHistoryMessage(container, 'agent',
                        `✅ **${funcResp.name}**\n\`\`\`json\n${JSON.stringify(content, null, 2)}\n\`\`\``,
                        'tool-res', timestamp);
                }
            });
        });
        setTimeout(() => { container.scrollTop = container.scrollHeight; }, 50);
    },

    _coreMCPs: ['mateclaw', 'coding'],

    renderMCP(svcs, conf) {
        const coreMCPs = (conf.mcp || []).map(m => ({name: m, isExternal: false, isCore: true}));
        if (conf.coding_agent_enabled && !coreMCPs.find(m => m.name === 'coding')) {
            coreMCPs.push({name: 'coding', isExternal: false, isCore: true});
        }
        const extMCPs = Object.keys(conf.external_mcp || {}).map(m => ({name: m, isExternal: true, isCore: false}));
        const allList = [...coreMCPs, ...extMCPs];

        const list = document.getElementById('mcp-list'); if (!list) return;
        document.getElementById('mcp-count').innerText = allList.length;

        list.innerHTML = allList.map(m => {
            const up = m.isExternal ? true : svcs.find(s => s.name.includes('mcp-' + m.name))?.status.includes('Up');
            const labelText = m.isCore ? 'System Core' : (m.isExternal ? 'Remote Extension' : 'Local Runtime');
            const labelColor = m.isCore ? 'text-blue-500' : (m.isExternal ? 'text-blue-400' : 'text-slate-400');
            const icon = m.isCore ? 'fa-shield-alt' : (m.isExternal ? 'fa-cloud' : 'fa-terminal');
            return `<div onclick="UI.loadMCPDetail('${m.name}', ${JSON.stringify(svcs).replace(/"/g, '&quot;')})"
                 class="p-6 border-b border-slate-100 cursor-pointer hover:bg-slate-50 transition-all group ${App.state.activeMCP === m.name ? 'bg-blue-50 border-l-4 border-l-blue-600' : ''}">
                <div class="flex items-center gap-5">
                    <div class="w-12 h-12 rounded-xl ${m.isCore ? 'bg-blue-600 text-white shadow-lg shadow-blue-200' : 'bg-slate-50 border border-slate-100 text-blue-600 group-hover:scale-110'} flex items-center justify-center transition-transform">
                        <i class="fas ${icon} text-lg"></i>
                    </div>
                    <div class="flex-1 min-w-0">
                        <div class="flex justify-between items-center mb-1">
                            <div class="text-base font-headline font-bold text-slate-900 truncate tracking-tight uppercase">${m.name}</div>
                            <div class="w-2 h-2 rounded-full ${up ? 'bg-blue-600 shadow-[0_0_8px_rgba(37,99,235,0.5)] animate-pulse' : 'bg-slate-200'}"></div>
                        </div>
                        <span class="text-[9px] font-mono font-bold ${labelColor} uppercase tracking-widest">${labelText}</span>
                    </div>
                </div>
            </div>`;
        }).join('');
    },

    async loadMCPDetail(name, svcs) {
        App.state.activeMCP = name; this.renderMCP(svcs, await API.fetch('/api/config'));
        const detail = await API.fetch(`/api/mcp/${name}/config`);
        const config = await API.fetch('/api/config');
        const isExt = config.external_mcp && config.external_mcp[name];
        document.getElementById('mcp-placeholder').classList.add('hidden'); document.getElementById('mcp-content').classList.remove('hidden');
        document.getElementById('mcp-header').innerText = name.toUpperCase();
        document.getElementById('mcp-input-name').value = name; 
        document.getElementById('mcp-input-desc').value = detail.description || '';
        document.getElementById('mcp-json-editor').value = JSON.stringify(detail, null, 2);
        document.getElementById('mcp-field-id').value = detail.name || name;
        const isCore = this._coreMCPs.includes(name);
        // Show/hide source+url+headers+save for core vs external MCPs
        document.getElementById('field-group-source').classList.toggle('hidden', isCore);
        document.getElementById('field-group-url').classList.toggle('hidden', isCore);
        document.getElementById('field-group-headers').classList.toggle('hidden', isCore);
        document.getElementById('mcp-save-row').classList.toggle('hidden', isCore);
        if (isExt) {
            // detail is now a Dive-format object { url, transport, enabled, headers }
            const url = detail.url || '';
            const transport = detail.transport || (url.includes('/sse') ? 'sse' : 'streamable');
            document.getElementById('mcp-field-url').value = url;
            document.getElementById('mcp-transport-select').value = transport;
            this.renderHeaders(detail.headers || {});
        } else {
            this.renderHeaders({});
        }
        document.getElementById('mcp-type-badge').innerText = isCore ? 'System Core' : 'Remote Extension';
        this.updateMCPActionButtons(name, isExt ? true : svcs.find(s=>s.name.includes('mcp-'+name))?.status.includes('Up'), isExt);
    },

    setMCPMode(mode) {
        // All external MCPs are remote; this method is kept for compatibility but no-ops.
        App.state.mcpMode = 'remote';
    },

    async saveMCPConfig() {
        try {
            const editorValue = document.getElementById('mcp-json-editor').value;
            const config = JSON.parse(editorValue);
            const name = document.getElementById('mcp-input-name').value.trim();
            const description = document.getElementById('mcp-input-desc').value.trim();

            // All external MCPs use Dive-format remote object
            const url = document.getElementById('mcp-field-url').value.trim() || config.url || '';
            const transport = document.getElementById('mcp-transport-select').value || config.transport || 'streamable';
            const diveObj = {
                url,
                transport,
                enabled: config.enabled !== undefined ? config.enabled : true,
                headers: this.getHeaders(),
                ...(description && { description }),
            };
            if (!diveObj.url) { alert('API Endpoint URL is required.'); return; }

            if (App.state.activeMCP) {
                await API.fetch(`/api/mcp/${App.state.activeMCP}/config`, { method: 'POST', body: JSON.stringify(diveObj) });
            } else {
                await API.fetch(`/api/mcp`, { method: 'POST', body: JSON.stringify({ name, config: diveObj, is_external: true, url: diveObj.url }) });
            }
            alert('Settings saved.'); App.refresh();
        } catch(e) { alert('Save error: ' + e.message); }
    },

    renderHeaders(headers) {
        const el = document.getElementById('headers-editor'); if (!el) return;
        el.innerHTML = '';
        const entries = Object.entries(headers || {});
        if (entries.length === 0) { el.innerHTML = '<p class="text-[11px] text-slate-300 ml-1">No headers. Click Add to add one.</p>'; return; }
        entries.forEach(([k, v]) => this._appendHeaderRow(el, k, v));
    },
    addHeaderRow() {
        const el = document.getElementById('headers-editor'); if (!el) return;
        const placeholder = el.querySelector('p');
        if (placeholder) el.innerHTML = '';
        this._appendHeaderRow(el, '', '');
        el.lastElementChild.querySelector('input').focus();
    },
    _appendHeaderRow(container, key, value) {
        const row = document.createElement('div');
        row.className = 'flex items-center gap-2';
        row.innerHTML = `
            <input type="text" placeholder="Key" value="${key}" class="flex-1 bg-white border border-slate-100 rounded-xl px-4 py-2.5 text-sm font-mono text-slate-700 outline-none focus:ring-2 focus:ring-blue-500/20">
            <input type="text" placeholder="Value" value="${value}" class="flex-1 bg-white border border-slate-100 rounded-xl px-4 py-2.5 text-sm font-mono text-slate-700 outline-none focus:ring-2 focus:ring-blue-500/20">
            <button onclick="this.parentElement.remove()" class="w-8 h-8 flex items-center justify-center text-slate-300 hover:text-rose-400 transition-colors shrink-0"><i class="fas fa-times text-xs"></i></button>`;
        container.appendChild(row);
    },
    getHeaders() {
        const el = document.getElementById('headers-editor'); if (!el) return {};
        const result = {};
        el.querySelectorAll('div').forEach(row => {
            const inputs = row.querySelectorAll('input');
            const k = inputs[0]?.value.trim(); const v = inputs[1]?.value.trim();
            if (k) result[k] = v || '';
        });
        return result;
    },

    updateMCPActionButtons(name, up, isExt) {
        const el = document.getElementById('mcp-detail-actions'); if (!el) return;
        const svc = 'mcp-'+name; const isUp = up === true || (typeof up === 'string' && up.includes('Up'));
        if (this._coreMCPs.includes(name)) {
            el.innerHTML = `<span class="bg-blue-600 text-white px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest shadow-lg shadow-blue-200">System Core</span>`;
            return;
        }
        if (isExt) el.innerHTML = `<button onclick="UI.deleteItem('mcp', '${name}')" class="px-6 py-2 rounded-xl text-xs font-black bg-rose-50 text-rose-500 hover:bg-rose-500 hover:text-white transition-all uppercase tracking-widest border border-rose-100">Remove Link</button>`;
        else el.innerHTML = `<div class="flex items-center gap-3"><button onclick="UI.deleteItem('mcp', '${name}')" class="p-2.5 rounded-xl text-slate-400 hover:text-rose-500 hover:bg-rose-50 transition-all border border-slate-100"><i class="fas fa-trash-alt text-xs"></i></button><button onclick="UI.serviceAction('${svc}', '${isUp?'stop':'start'}')" class="px-6 py-2 rounded-xl text-xs font-black transition-all ${isUp?'bg-slate-100 text-rose-500 hover:bg-rose-500 hover:text-white':'bg-blue-600 text-white hover:bg-blue-700'} uppercase tracking-widest">${isUp?'STOP':'START'}</button></div>`;
    },

    renderGateways(svcs, conf) { 
        const platforms = [{ id: 'tg', name: 'Telegram', icon: 'telegram' }, { id: 'dc', name: 'Discord', icon: 'discord' }, { id: 'line', name: 'Line', icon: 'line' }];
        const list = document.getElementById('gateways-list'); if (!list) return;
        list.innerHTML = platforms.map(p => {
            const svc = 'bot-'+(p.id==='tg'?'telegram':p.id==='dc'?'discord':'line');
            const up = svcs.find(s=>s.name.includes(svc))?.status.includes('Up');
            return `<div onclick="UI.loadGatewayDetail('${p.id}', ${JSON.stringify(svcs).replace(/"/g, '&quot;')})" 
                 class="p-6 border-b border-slate-100 cursor-pointer hover:bg-slate-50 transition-all group ${App.state.activeGateway===p.id?'bg-blue-50 border-l-4 border-l-blue-600':''}">
                <div class="flex items-center gap-5">
                    <div class="w-12 h-12 rounded-xl bg-slate-50 border border-slate-100 flex items-center justify-center text-blue-600 group-hover:scale-110 transition-transform">
                        <i class="fab fa-${p.icon} text-xl"></i>
                    </div>
                    <div class="flex-1 min-w-0">
                        <div class="flex justify-between items-center mb-1">
                            <div class="text-base font-headline font-bold text-slate-900 uppercase">${p.name}</div>
                            <span class="status-badge ${up ? 'badge-active' : 'badge-idle'}"><span class="badge-dot"></span>${up ? 'LIVE' : 'OFFLINE'}</span>
                        </div>
                        <span class="text-[9px] font-mono text-slate-400 uppercase tracking-widest">Connection</span>
                    </div>
                </div>
            </div>`;
        }).join('');
    },

    async loadGatewayDetail(platform, svcs) {
        const platforms = { 'tg': 'Telegram', 'dc': 'Discord', 'line': 'Line' };
        const fullName = platforms[platform] || platform.toUpperCase();
        App.state.activeGateway = platform; this.renderGateways(svcs, {});
        const config = await API.fetch('/api/config'); const gConf = config.gateways_config?.[platform] || {};
        const content = document.getElementById('gateway-content');
        if (content) {
            content.classList.remove('hidden'); document.getElementById('gateway-placeholder').classList.add('hidden');
            document.getElementById('gateway-detail-name').innerText = fullName;
            document.getElementById('gateway-icon-large').innerHTML = `<i class="fab fa-${platform==='tg'?'telegram':platform==='dc'?'discord':'line'}"></i>`;
            this.updateGatewayStatus(platform, svcs);
            let fields = platform === 'line' ? [ { label: 'ACCESS TOKEN', key: 'token', type: 'password' }, { label: 'SECRET KEY', key: 'secret', type: 'password' } ] : [{ label: 'TOKEN', key: 'token', type: 'password' }];
            document.getElementById('gateway-config-form').innerHTML = fields.map(f => `<div class="space-y-3"><label class="label-mono text-[10px] text-blue-600 font-black uppercase tracking-[0.2em]">${f.label}</label><input type="${f.type}" id="gw-field-${f.key}" value="${gConf[f.key] || ''}" class="w-full bg-slate-50 border border-slate-100 rounded-xl px-5 py-4 outline-none focus:ring-2 focus:ring-blue-500/20 font-mono text-sm text-slate-900"></div>`).join('');
        }
    },

    updateGatewayStatus(platform, svcs) {
        const el = document.getElementById('gateway-detail-actions'); if (!el) return;
        const svc = 'bot-'+(platform==='tg'?'telegram':platform==='dc'?'discord':'line');
        const up = (svcs.find(s=>s.name.includes(svc))?.status || '').includes('Up');
        el.innerHTML = `<button onclick="UI.serviceAction('${svc}', '${up?'stop':'start'}')" class="px-6 py-2 rounded-xl text-xs font-black uppercase tracking-widest transition-all ${up?'bg-slate-100 text-rose-500':'bg-blue-600 text-white hover:bg-blue-700'}">${up?'STOP':'START'}</button>`;
    },

    async saveGatewayConfig() {
        const platform = App.state.activeGateway; if (!platform) return;
        const config = platform === 'line' ? { token: document.getElementById('gw-field-token').value, secret: document.getElementById('gw-field-secret').value } : { token: document.getElementById('gw-field-token').value };
        try { await API.fetch('/api/gateways', { method: 'POST', body: JSON.stringify({ platform, config }) }); alert('Bridge established.'); App.refresh(); } catch(e) { alert('Sync Failed.'); }
    },

    renderAgents(svcs) {
        // Cache svcs so onclick handlers can retrieve by name without embedding JSON in HTML
        App.state.cachedSvcs = svcs;
        // Only show root mateclaw-agent as Internal Agent
        const agents = svcs.filter(s => s.name.includes('mateclaw-agent'));
        const list = document.getElementById('agents-list'); if (!list) return;
        list.innerHTML = agents.map(a => {
            const up = a.status.includes('Up');
            return `<div onclick="UI.loadAgentDetail('${a.name}')"
                 class="p-5 cursor-pointer hover:bg-slate-50 transition-all ${App.state.activeAgent===a.name?'bg-blue-50 border-l-4 border-l-blue-600':''}">
                <div class="flex justify-between items-center mb-1"><div class="text-sm font-headline font-bold text-slate-900 uppercase tracking-tight">mateclaw agent</div><div class="w-2 h-2 rounded-full ${up?'bg-blue-600 shadow-[0_0_8px_rgba(37,99,235,0.5)] animate-pulse':'bg-slate-200'}"></div></div>
                <div class="text-[10px] text-slate-400 font-mono uppercase tracking-tighter italic">${a.status}</div></div>`;
        }).join('');
    },

    async loadExternalAgents() {
        const list = document.getElementById('external-agents-list');
        if (!list) return;
        try {
            const agents = await API.fetch('/api/external-agents');
            if (!agents.length) {
                list.innerHTML = '<div class="p-5 text-[11px] text-slate-400 text-center">No external agents yet.<br>Click + to add one.</div>';
                return;
            }
            list.innerHTML = agents.map(a => {
                const isActive = App.state.activeExtAgent === a.name;
                const healthDot = a.health
                    ? 'bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.5)] animate-pulse'
                    : (a.enabled ? 'bg-red-400' : 'bg-slate-200');
                const typeColor = a.type === 'github' ? 'text-violet-500 bg-violet-50' : 'text-blue-500 bg-blue-50';
                return `<div onclick="UI.loadExtAgentDetail(${JSON.stringify(a).replace(/"/g, '&quot;')})"
                    class="p-5 cursor-pointer hover:bg-slate-50 transition-all ${isActive ? 'bg-violet-50 border-l-4 border-l-violet-500' : ''}">
                    <div class="flex justify-between items-center mb-1">
                        <div class="text-sm font-headline font-bold text-slate-900 uppercase tracking-tight">${a.name}</div>
                        <div class="w-2 h-2 rounded-full ${healthDot}"></div>
                    </div>
                    <div class="flex items-center gap-2 mt-1">
                        <span class="text-[9px] font-black uppercase px-1.5 py-0.5 rounded ${typeColor}">${a.type}</span>
                        ${!a.enabled ? '<span class="text-[9px] font-black uppercase px-1.5 py-0.5 rounded bg-slate-100 text-slate-400">disabled</span>' : ''}
                    </div>
                </div>`;
            }).join('');
        } catch(e) {
            list.innerHTML = '<div class="p-5 text-[11px] text-rose-400">Failed to load agents.</div>';
        }
    },

    async loadExtAgentDetail(agent) {
        App.state.activeExtAgent = agent.name;
        App.state.activeAgent = null;
        // Re-render internal agents list to clear its highlight
        if (App.state.cachedSvcs) this.renderAgents(App.state.cachedSvcs);
        // Switch panel
        document.getElementById('agent-placeholder').classList.add('hidden');
        document.getElementById('agent-content').classList.add('hidden');
        document.getElementById('ext-agent-content').classList.remove('hidden');

        document.getElementById('ext-agent-name').innerText = agent.name.toUpperCase();
        document.getElementById('ext-agent-url').innerText = agent.a2a_url || '—';
        document.getElementById('ext-agent-description').innerText = agent.description || '—';

        const versionRow = document.getElementById('ext-agent-version-row');
        if (agent.version) {
            versionRow.classList.remove('hidden');
            document.getElementById('ext-agent-version').innerText = agent.version;
        } else { versionRow.classList.add('hidden'); }

        // Type badge
        const badge = document.getElementById('ext-agent-type-badge');
        const health = agent.health
            ? '<span class="inline-flex items-center gap-1 text-[10px] font-black text-green-600 bg-green-50 px-2 py-0.5 rounded-full"><span class="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse inline-block"></span>ONLINE</span>'
            : '<span class="inline-flex items-center gap-1 text-[10px] font-black text-red-500 bg-red-50 px-2 py-0.5 rounded-full"><span class="w-1.5 h-1.5 rounded-full bg-red-400 inline-block"></span>OFFLINE</span>';
        const typeLabel = agent.type === 'github'
            ? '<span class="text-[10px] font-black text-violet-600 bg-violet-50 px-2 py-0.5 rounded-full uppercase">GitHub Deploy</span>'
            : '<span class="text-[10px] font-black text-blue-600 bg-blue-50 px-2 py-0.5 rounded-full uppercase">Remote URL</span>';
        badge.innerHTML = `<div class="flex items-center gap-2 mt-1">${typeLabel}${health}</div>`;

        // Icon color by type
        document.getElementById('ext-agent-icon').className = agent.type === 'github'
            ? 'w-16 h-16 rounded-2xl bg-violet-600 text-white flex items-center justify-center text-3xl shadow-xl shadow-violet-200'
            : 'w-16 h-16 rounded-2xl bg-blue-600 text-white flex items-center justify-center text-3xl shadow-xl shadow-blue-200';

        // Actions
        const actions = document.getElementById('ext-agent-actions');
        const toggleLabel = agent.enabled ? 'DISABLE' : 'ENABLE';
        const toggleClass = agent.enabled ? 'bg-slate-100 text-rose-500' : 'bg-blue-600 text-white hover:bg-blue-700';
        actions.innerHTML = `
            <button onclick="UI.toggleExtAgent('${agent.name}', ${!agent.enabled})" class="px-4 py-2 rounded-xl text-xs font-black uppercase tracking-widest transition-all ${toggleClass}">${toggleLabel}</button>
            ${agent.type === 'url' ? `<button onclick="UI.removeExtAgent('${agent.name}')" class="px-4 py-2 rounded-xl text-xs font-black uppercase tracking-widest border border-rose-200 text-rose-500 hover:bg-rose-50 transition-all">REMOVE</button>` : ''}
        `;

        // Show/hide type-specific sections
        const mcpSection = document.getElementById('ext-agent-mcp-section');
        const logsSection = document.getElementById('ext-agent-logs-section');
        const urlNotice = document.getElementById('ext-agent-url-notice');
        if (agent.type === 'github') {
            // MCP section only for agents that declare mcp_configurable in mateclaw.agent.json
            if (agent.mcp_configurable) {
                mcpSection.classList.remove('hidden'); mcpSection.classList.add('flex');
                this._loadExtAgentMCPConfig(agent.name);
            } else {
                mcpSection.classList.add('hidden'); mcpSection.classList.remove('flex');
            }
            logsSection.classList.remove('hidden'); logsSection.classList.add('flex');
            urlNotice.classList.add('hidden');
            this.loadExtAgentLogs(agent.name);
        } else {
            mcpSection.classList.add('hidden'); mcpSection.classList.remove('flex');
            logsSection.classList.add('hidden'); logsSection.classList.remove('flex');
            urlNotice.classList.remove('hidden');
        }

        this.loadExternalAgents();
    },

    async _loadExtAgentMCPConfig(agentName) {
        const box = document.getElementById('ext-agent-mcp-checkboxes');
        if (!box) return;
        box.innerHTML = '<p class="text-[11px] text-slate-300 col-span-2">Loading...</p>';
        try {
            const data = await API.fetch('/api/agent-mcp-config');
            const agentKey = agentName.replace(/-/g, '_');
            const available = data.available_mcps || [];
            const assigned = data.agent_mcps?.[agentKey] || [];
            box.innerHTML = available.map(mcp => {
                const checked = assigned.includes(mcp);
                return `<label class="flex items-center gap-3 p-3 rounded-xl border ${checked ? 'border-blue-200 bg-blue-50' : 'border-slate-100 bg-white'} cursor-pointer hover:border-blue-200 transition-all">
                    <input type="checkbox" value="${mcp}" ${checked ? 'checked' : ''} data-agent="${agentKey}"
                        class="w-4 h-4 accent-blue-600 rounded" onchange="UI._updateMCPCheckStyle(this)">
                    <span class="text-xs font-bold text-slate-700">${mcp}</span>
                </label>`;
            }).join('') || '<p class="text-[11px] text-slate-400 col-span-2">No MCP extensions configured yet.</p>';
        } catch(e) {
            box.innerHTML = '<p class="text-[11px] text-rose-400 col-span-2">Failed to load MCP config.</p>';
        }
    },

    async loadExtAgentLogs(agentName) {
        const name = agentName || App.state.activeExtAgent;
        if (!name) return;
        const box = document.getElementById('ext-agent-logs-preview');
        try {
            const res = await API.fetch(`/api/logs/${name}?tail=50`);
            if (box) { box.innerText = (res.logs || '(no logs)').replace(/\u001b\[\d+m/g, '').trim() || '(no logs)'; box.scrollTop = box.scrollHeight; }
        } catch(e) {
            if (box) box.innerText = `(error fetching logs: ${e.message})`;
        }
    },

    async toggleExtAgent(name, enabled) {
        try {
            await API.fetch(`/api/external-agents/${name}`, {
                method: 'PATCH',
                body: JSON.stringify({ enabled })
            });
            App.refresh();
        } catch(e) { alert('Failed: ' + e.message); }
    },

    async removeExtAgent(name) {
        if (!confirm(`Remove agent '${name}'? This cannot be undone.`)) return;
        try {
            await API.fetch(`/api/external-agents/${name}`, { method: 'DELETE' });
            document.getElementById('agent-placeholder').classList.remove('hidden');
            document.getElementById('ext-agent-content').classList.add('hidden');
            App.state.activeExtAgent = null;
            App.refresh();
        } catch(e) { alert('Failed: ' + e.message); }
    },

    openAddExternalAgentModal() {
        document.getElementById('ext-agent-input-name').value = '';
        document.getElementById('ext-agent-input-url').value = '';
        document.getElementById('ext-agent-input-desc').value = '';
        document.getElementById('add-ext-agent-modal').classList.remove('hidden');
    },

    closeAddExternalAgentModal() {
        document.getElementById('add-ext-agent-modal').classList.add('hidden');
    },

    async submitAddExternalAgent() {
        const name = document.getElementById('ext-agent-input-name').value.trim();
        const url = document.getElementById('ext-agent-input-url').value.trim();
        const desc = document.getElementById('ext-agent-input-desc').value.trim();
        if (!name || !url) { alert('Name and URL are required.'); return; }
        try {
            await API.fetch('/api/external-agents', {
                method: 'POST',
                body: JSON.stringify({ name, a2a_url: url, description: desc })
            });
            this.closeAddExternalAgentModal();
            App.refresh();
        } catch(e) { alert('Failed: ' + e.message); }
    },

    async loadAgentDetail(name, svcs) {
        const svcList = svcs || App.state.cachedSvcs || [];
        App.state.activeAgent = name; App.state.activeExtAgent = null;
        this.renderAgents(svcList);
        this.loadExternalAgents(); // re-render external list to clear its highlight
        const agent = svcList.find(s => s.name === name); if (!agent) return;
        document.getElementById('agent-placeholder').classList.add('hidden');
        document.getElementById('ext-agent-content').classList.add('hidden');
        document.getElementById('agent-content').classList.remove('hidden');
        document.getElementById('agent-detail-name').innerText = 'MATECLAW AGENT';
        this.loadAgentLogs();
        this.updateAgentStatus(name, svcs);
        this.loadAgentMCPConfig(name);
    },

    // Map Docker container name (may include project prefix) to config agent_id
    _agentConfigId(dockerName) {
        if (dockerName.includes('mateclaw-agent') || dockerName.includes('mateclaw_agent')) return 'mateclaw_agent';
        if (dockerName.includes('coding-agent') || dockerName.includes('coding_agent')) return 'coding_agent';
        return dockerName.replace(/-/g, '_');
    },

    // Extract bare service name for docker logs (strip compose project prefix)
    _dockerServiceName(containerName) {
        // e.g. "mateclaw-mateclaw-agent-1" → "mateclaw-agent"
        return containerName.replace(/^[^-]+-/, '').replace(/-\d+$/, '');
    },

    async loadAgentMCPConfig(dockerName) {
        const box = document.getElementById('agent-mcp-checkboxes');
        if (!box) return;
        box.innerHTML = '<p class="text-[11px] text-slate-300 col-span-2">Loading...</p>';
        try {
            const data = await API.fetch('/api/agent-mcp-config');
            const agentId = this._agentConfigId(dockerName);
            const available = data.available_mcps || [];
            const assigned = data.agent_mcps?.[agentId] || [];

            if (!available.length) {
                box.innerHTML = '<p class="text-[11px] text-slate-400 col-span-2">No MCP extensions configured yet.</p>';
                return;
            }

            box.innerHTML = available.map(mcp => {
                const checked = assigned.includes(mcp);
                const isCore = (agentId === 'mateclaw_agent' && mcp === 'mateclaw') || (agentId === 'coding_agent' && mcp === 'coding');
                return `<label class="flex items-center gap-3 p-3 rounded-xl border ${checked ? 'border-blue-200 bg-blue-50' : 'border-slate-100 bg-white'} cursor-pointer hover:border-blue-200 transition-all">
                    <input type="checkbox" value="${mcp}" ${checked ? 'checked' : ''} ${isCore ? 'disabled' : ''}
                        class="w-4 h-4 accent-blue-600 rounded" onchange="UI._updateMCPCheckStyle(this)">
                    <div>
                        <span class="text-xs font-bold text-slate-700">${mcp}</span>
                        ${isCore ? '<span class="ml-2 text-[9px] font-black bg-blue-100 text-blue-600 px-1.5 py-0.5 rounded uppercase">Core</span>' : ''}
                    </div>
                </label>`;
            }).join('');
        } catch(e) {
            box.innerHTML = '<p class="text-[11px] text-rose-400 col-span-2">Failed to load MCP config.</p>';
        }
    },

    _updateMCPCheckStyle(checkbox) {
        const label = checkbox.closest('label');
        if (checkbox.checked) {
            label.className = label.className.replace('border-slate-100 bg-white', 'border-blue-200 bg-blue-50');
        } else {
            label.className = label.className.replace('border-blue-200 bg-blue-50', 'border-slate-100 bg-white');
        }
    },

    async saveExtAgentMCPConfig() {
        const agentName = App.state.activeExtAgent;
        if (!agentName) return;
        const agentId = agentName.replace(/-/g, '_');
        const box = document.getElementById('ext-agent-mcp-checkboxes');
        if (!box) return;
        const checked = Array.from(box.querySelectorAll('input[type=checkbox]'))
            .filter(cb => cb.checked).map(cb => cb.value);
        const btn = document.querySelector('#ext-agent-mcp-section button[onclick="UI.saveExtAgentMCPConfig()"]');
        const orig = btn ? btn.innerText : '';
        if (btn) { btn.innerText = 'APPLYING...'; btn.disabled = true; btn.style.opacity = '0.5'; }
        try {
            await API.fetch('/api/agent-mcp-config', {
                method: 'POST',
                body: JSON.stringify({ agent_id: agentId, mcps: checked })
            });
            if (btn) btn.innerText = 'RESTARTING...';
            setTimeout(() => {
                if (btn) { btn.disabled = false; btn.style.opacity = '1'; btn.innerText = orig; }
                this.loadExtAgentLogs(agentName);
                App.refresh();
            }, 5000);
        } catch(e) {
            if (btn) { btn.disabled = false; btn.style.opacity = '1'; btn.innerText = orig; }
            alert('Failed: ' + e.message);
        }
    },

    async saveAgentMCPConfig() {
        const agentId = this._agentConfigId(App.state.activeAgent);
        const box = document.getElementById('agent-mcp-checkboxes');
        if (!box || !agentId) return;

        const checked = Array.from(box.querySelectorAll('input[type=checkbox]'))
            .filter(cb => cb.checked)
            .map(cb => cb.value);

        const btn = document.querySelector('#agent-content button[onclick="UI.saveAgentMCPConfig()"]');
        const originalText = btn ? btn.innerText : '';
        if (btn) { btn.innerText = 'APPLYING...'; btn.disabled = true; btn.style.opacity = '0.5'; }

        try {
            await API.fetch('/api/agent-mcp-config', {
                method: 'POST',
                body: JSON.stringify({ agent_id: agentId, mcps: checked })
            });
            if (btn) { btn.innerText = 'RESTARTING...'; }
            // Backend triggers restart in background; poll logs after a short delay
            setTimeout(() => {
                if (btn) { btn.disabled = false; btn.style.opacity = '1'; btn.innerText = originalText; }
                this.loadAgentLogs();
                App.refresh();
            }, 5000);
        } catch(e) {
            if (btn) { btn.disabled = false; btn.style.opacity = '1'; btn.innerText = originalText; }
            alert('Failed to save MCP config: ' + e.message);
        }
    },

    updateAgentStatus(name, svcs) {
        const el = document.getElementById('agent-detail-actions'); if (!el) return;
        const agent = svcs.find(s => s.name === name); if (!agent) return;
        const up = agent.status.includes('Up');
        const svc = this._dockerServiceName(agent.name);
        el.innerHTML = `<button onclick="UI.serviceAction('${svc}', 'restart')" class="px-4 py-2 rounded-xl text-xs font-black uppercase tracking-widest border border-slate-100 text-slate-500 hover:bg-slate-900 hover:text-white transition-all">REBOOT</button><button onclick="UI.serviceAction('${svc}', '${up?'stop':'start'}')" class="px-6 py-2 rounded-xl text-xs font-black uppercase tracking-widest ${up?'bg-slate-100 text-rose-500':'bg-blue-600 text-white hover:bg-blue-700'} transition-all">${up?'STOP':'START'}</button>`;
    },

    async loadAgentLogs() {
        if (!App.state.activeAgent) return;
        // docker logs needs the full container name, not the bare service name
        const res = await API.fetch(`/api/logs/${App.state.activeAgent}?tail=50`);
        const box = document.getElementById('agent-logs-preview'); if (box) { box.innerText = (res.logs || '').replace(/\[\d+m/g, ''); box.scrollTop = box.scrollHeight; }
    },

    async serviceAction(svc, action) { 
        const btn = window.event?.currentTarget;
        let originalText = "";
        if (btn && btn.tagName === 'BUTTON') { 
            originalText = btn.innerText;
            btn.innerText = action === 'stop' ? 'STOPPING...' : 'STARTING...'; 
            btn.disabled = true; 
            btn.style.opacity = '0.5'; 
        }
        
        try { 
            await API.fetch(`/api/services/${svc}/action`, { method: 'POST', body: JSON.stringify({ action }) }); 
            
            // Poll for status change
            let attempts = 0;
            const maxAttempts = 30; // 30 seconds timeout
            const targetStatus = action === 'stop' ? 'offline' : 'up';
            
            const poll = async () => {
                if (attempts >= maxAttempts) {
                    if (btn) { btn.disabled = false; btn.style.opacity = '1'; btn.innerText = originalText; }
                    App.refresh();
                    return;
                }
                
                attempts++;
                const svcs = await API.fetch('/api/status');
                const s = svcs.find(item => item.name === svc || item.name.includes(svc));
                const currentIsUp = s && s.status.includes('Up');
                
                const reached = (targetStatus === 'offline' && !currentIsUp) || (targetStatus === 'up' && currentIsUp);
                
                if (reached) {
                    if (btn) { btn.disabled = false; btn.style.opacity = '1'; }
                    App.refresh();
                } else {
                    setTimeout(poll, 1000);
                }
            };
            
            setTimeout(poll, 1000);
            
        } catch(e){ 
            alert('Action failed: ' + e.message); 
            if (btn) { btn.disabled = false; btn.style.opacity = '1'; btn.innerText = originalText; }
            App.refresh(); 
        } 
    },
    
    openAddModal(type) { 
        if (type === 'mcp') {
            const tempName = `new-extension-${Math.random().toString(36).substring(2, 7)}`;
            App.state.activeMCP = null;
            document.getElementById('mcp-placeholder').classList.add('hidden'); document.getElementById('mcp-content').classList.remove('hidden');
            document.getElementById('mcp-header').innerText = "New Extension";
            document.getElementById('mcp-input-name').value = tempName; document.getElementById('mcp-input-desc').value = "";
            const diveTemplate = JSON.stringify({ url: "", transport: "streamable", enabled: true, headers: {} }, null, 2);
            document.getElementById('mcp-json-editor').value = diveTemplate;
            document.getElementById('mcp-field-id').value = tempName;
            document.getElementById('mcp-field-url').value = "";
            document.getElementById('mcp-transport-select').value = 'streamable';
            document.getElementById('field-group-source').classList.remove('hidden');
            document.getElementById('field-group-url').classList.remove('hidden');
            document.getElementById('field-group-headers').classList.remove('hidden');
            document.getElementById('mcp-save-row').classList.remove('hidden');
            document.getElementById('mcp-type-badge').innerText = 'Remote Extension';
            this.renderHeaders({});
            return;
        }
        document.getElementById('modal-title').innerText = `PROVISION: ${type.toUpperCase()}`; 
        document.getElementById('modal-container').classList.remove('hidden'); 
        document.getElementById('modal-confirm').onclick = async () => { 
            const name = document.getElementById('modal-input').value; if (!name) return; 
            await API.fetch(`/api/${type}`, { method: 'POST', body: JSON.stringify({ name }) }); 
            this.closeModal(); App.refresh(); 
        }; 
    },
    closeModal() { document.getElementById('modal-container').classList.add('hidden'); document.getElementById('modal-input').value = ''; },
    async deleteItem(type, name) { if (confirm(`DE-INDEX ${name}?`)) { await API.fetch(`/api/${type}/${name}`, { method: 'DELETE' }); App.refresh(); } },
    
    updateLogServices(svcs) { 
        const sel = document.getElementById('log-service-select'); if (!sel) return;
        const cur = sel.value; sel.innerHTML = `<option value="">-- SELECT NODE --</option>` + svcs.map(s => `<option value="${s.name}" ${s.name===cur?'selected':''}>${s.name.toUpperCase()}</option>`).join(''); 
    },

    async renderLogs() { 
        const select = document.getElementById('log-service-select'); if (!select || !select.value) return;
        const res = await API.fetch(`/api/logs/${select.value}`); const output = res.logs || 'NO_DATA_STREAM';
        if (output === this.lastLogs) return; this.lastLogs = output;
        const box = document.getElementById('log-output'); const filter = document.getElementById('log-filter').value.toLowerCase();
        box.innerHTML = output.split('\n').map(line => {
            if (filter && !line.toLowerCase().includes(filter)) return '';
            if (!line.trim()) return '';
            let color = 'text-slate-400';
            if (line.includes('ERROR') || line.includes('FAIL') || line.includes('CRITICAL')) color = 'text-rose-400 font-bold';
            else if (line.includes('INFO')) color = 'text-cyan-400';
            else if (line.includes('WARN')) color = 'text-amber-400';
            else if (line.includes('SUCCESS')) color = 'text-emerald-400 font-bold';
            const lineContent = line.replace(/\[\d+m/g, '');
            return `<div class="${color} mb-1 flex gap-4"><span class="text-slate-600 shrink-0 select-none">[${new Date().toLocaleTimeString([], {hour12:false})}]</span><span class="break-all">${lineContent}</span></div>`;
        }).join('');
        if (document.getElementById('log-autoscroll').checked) box.scrollTop = box.scrollHeight;
    },

    async renderCronjobs() {
        const data = await API.fetch('/api/db/reminders');
        this.drawTable('cron-thead', 'cron-tbody', 'reminders', data);
        const nextEl = document.getElementById('next-cron-time'); const nextMsgEl = document.getElementById('next-cron-msg');
        if (nextEl && nextMsgEl) {
            if (data.length > 0) {
                const upcoming = data.find(r => ['pending', 'scheduled', 'active'].includes(r.status)) || data[0];
                const timeStr = upcoming.cron ? upcoming.cron : upcoming.run_at ? new Date(upcoming.run_at).toLocaleString() : 'STANDBY';
                nextEl.innerText = timeStr; nextMsgEl.innerText = upcoming.prompt || 'No message content';
                nextMsgEl.classList.remove('italic');
            } else { nextEl.innerText = 'NO TASKS'; nextMsgEl.innerText = 'No active schedules detected.'; nextMsgEl.classList.add('italic'); }
        }
    },
    openCronModal() {
        this.editingCronId = null; document.getElementById('cron-modal').classList.remove('hidden');
        document.getElementById('cron-full-input').value = ''; document.getElementById('cron-recipient').value = '';
    },
    openEditCronModal(id, channel, recipient, fullCommand) {
        this.editingCronId = id; document.getElementById('cron-modal').classList.remove('hidden');
        document.getElementById('cron-channel').value = channel; document.getElementById('cron-recipient').value = recipient;
        document.getElementById('cron-full-input').value = fullCommand;
    },
    closeCronModal() { document.getElementById('cron-modal').classList.add('hidden'); this.editingCronId = null; },
    async saveCronjobLine() {
        const input = document.getElementById('cron-full-input').value.trim(); const chan = document.getElementById('cron-channel').value;
        const target = document.getElementById('cron-recipient').value.trim(); if (!input || !target) return alert('FIELDS_REQUIRED');
        const parts = input.split(/\s+/); if (parts.length < 6) return alert('INVALID_FORMAT');
        const cronExpr = parts.slice(0, 5).join(' '); const messageContent = parts.slice(5).join(' ');
        const data = { channel: chan, recipient: target, prompt: messageContent, cron: cronExpr, run_at: null };
        try { 
            const url = this.editingCronId ? `/api/reminders/${this.editingCronId}` : '/api/reminders';
            const method = this.editingCronId ? 'PUT' : 'POST';
            await API.fetch(url, { method, body: JSON.stringify(data) }); 
            this.closeCronModal(); this.renderCronjobs(); 
        } catch (e) { alert('SYNC_ERROR'); }
    },
    async deleteReminder(id) { if (confirm('PURGE_TASK?')) { try { await API.fetch(`/api/reminders/${id}`, { method: 'DELETE' }); this.renderCronjobs(); } catch (e) { alert('PURGE_FAILED'); } } },
    filterLogs() { this.renderLogs(); },
    filterDBTable() {
        const query = document.getElementById('db-filter-input').value.toLowerCase();
        const rows = document.querySelectorAll('#sessions-tbody tr');
        rows.forEach(row => {
            const text = row.innerText.toLowerCase();
            row.style.display = text.includes(query) ? '' : 'none';
        });
    },
    downloadLogs() {
        const box = document.getElementById('log-output'); if (!box) return;
        const text = box.innerText; if (!text || text.includes('Initialize neural')) return alert('NO_DATA');
        const blob = new Blob([text], { type: 'text/plain' });
        const url = URL.createObjectURL(blob); const a = document.createElement('a');
        const source = document.getElementById('log-service-select').value || 'system';
        a.href = url; a.download = `mate_logs_${source}_${new Date().toISOString().slice(0,19).replace(/:/g,'-')}.log`;
        document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url);
    }
};

window.UI = UI;
