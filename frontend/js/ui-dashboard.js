Object.assign(UI, {
    renderLicense(data) {
        const card = document.getElementById('license-card');
        if (!card) return;

        if (data.plan === 'invalid') {
            card.innerHTML = `
                <div class="flex items-center gap-3 text-red-500">
                    <i class="fas fa-exclamation-triangle text-xl"></i>
                    <div>
                        <p class="text-xs font-black uppercase tracking-widest">License Invalid</p>
                        <p class="text-xs text-slate-400 mt-1">${escapeHtml(data.error || 'Unknown error')}</p>
                    </div>
                </div>`;
            return;
        }

        const isPaid    = data.plan !== 'oss';
        const isExpired = data.is_expired;
        const planLabel = data.plan.toUpperCase();
        const planColor = isExpired ? 'red' : isPaid ? 'blue' : 'slate';
        const limits    = data.limits || {};

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
                    <span class="text-xs font-bold text-slate-500">${escapeHtml(used)} / ${escapeHtml(fmtLimit(limit))}</span>
                </div>
                <div class="w-full h-2 bg-slate-100 rounded-full overflow-hidden">
                    <div class="h-full rounded-full transition-all ${barColor(p)}" style="width: ${p}%"></div>
                </div>
            </div>`;
        };

        const metrics = [
            { label: 'Agents',  used: usage.agents ?? 0, limit: limits.max_agents ?? 1 },
            { label: 'Users',   used: usage.users  ?? 0, limit: limits.max_users  ?? 1 },
            { label: 'Skills',  used: usage.skills ?? 0, limit: limits.max_skills ?? 10 },
        ];

        card.innerHTML = `
            <div class="flex flex-col gap-5">
                <div class="flex items-center justify-between">
                    <div class="flex items-center gap-4">
                        <div class="w-12 h-12 rounded-2xl bg-${planColor}-50 flex items-center justify-center">
                            <i class="fas fa-${isPaid ? 'shield-alt' : 'code-branch'} text-${planColor}-500 text-xl"></i>
                        </div>
                        <div>
                            <div class="flex items-center gap-2">
                                <span class="text-lg font-headline font-bold text-slate-900">${escapeHtml(planLabel)} PLAN</span>
                                ${isExpired ? '<span class="text-[10px] font-black uppercase bg-red-50 text-red-500 px-2 py-0.5 rounded-full">EXPIRED</span>' : ''}
                            </div>
                            ${data.issued_to ? `<p class="text-xs text-slate-400 mt-0.5">${escapeHtml(data.issued_to)}${data.contact_phone ? ` · ${escapeHtml(data.contact_phone)}` : ''}</p>` : ''}
                            <p class="text-xs ${expiryColor} mt-0.5">${escapeHtml(expiryText)}</p>
                        </div>
                    </div>
                    ${!isPaid ? `
                    <a href="mailto:simonliuyuwei@gmail.com?subject=CoStaff License Inquiry"
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
                    <div class="text-4xl font-headline font-bold mb-3 text-slate-900">${m.isRaw ? escapeHtml(m.value) : escapeHtml(m.value) + '%'}</div>
                    ${!m.isRaw ? `<div class="progress-bar bg-slate-100"><div class="progress-fill" style="width: ${escapeHtml(m.value)}%"></div></div>` : ''}
                </div>
            </div>`).join('');
    },

    renderDashboard(svcs) {
        const lastUpdateEl = document.getElementById('dashboard-last-update');
        if (lastUpdateEl) lastUpdateEl.innerText = `SYNC: ${new Date().toLocaleTimeString()}`;

        const table = document.getElementById('status-table');
        if (table) table.innerHTML = [...svcs].filter(s => s.name.toLowerCase().startsWith('costaff-')).sort((a, b) => a.name.localeCompare(b.name)).map(s => {
            const isActive = s.status.includes('Up');
            return `
            <tr class="group hover:bg-slate-50 transition-all">
                <td class="font-headline font-bold tracking-tight text-base uppercase text-slate-900">${escapeHtml(s.name)}</td>
                <td>
                    <span class="status-badge ${isActive ? 'badge-active' : 'badge-idle'}">
                        <span class="badge-dot"></span>
                        ${isActive ? 'ACTIVE' : 'IDLE'}
                    </span>
                </td>
                <td class="text-[11px] font-mono text-slate-400 italic uppercase">${escapeHtml(s.status)}</td>
                <td class="text-right">
                    <button onclick="UI.serviceAction('${escapeHtml(s.name)}', 'restart')" class="text-[9px] font-black text-blue-600 hover:text-white transition-all uppercase tracking-widest px-4 py-2 border border-blue-200 rounded-lg hover:bg-blue-600">RESTART</button>
                </td>
            </tr>`;
        }).join('');

        // Restrict every metric to CoStaff-managed containers. The
        // backend `/api/status` is permissive (returns anything matching
        // costaff/mcp/bot/postgres/gpt-vis), so unrelated containers from
        // other projects (ai-rap-*, gpt-vis, the host postgres) would
        // otherwise inflate the counts here.
        const costaff = svcs.filter(s => s.name.toLowerCase().startsWith('costaff-'));
        const statsGrid = document.getElementById('stats-grid');
        if (statsGrid) statsGrid.innerHTML = `
            <div class="card-linear bg-white border border-slate-100 shadow-xl rounded-3xl p-8 hover:bg-slate-50 transition-all duration-300 cursor-default group">
                <div class="label-mono text-[9px] mb-4 text-slate-400 tracking-[0.2em] uppercase">TOTAL SERVICES</div>
                <div class="text-5xl font-headline font-bold text-slate-900">${costaff.length}</div>
            </div>
            <div class="card-linear bg-white border border-slate-100 shadow-xl rounded-3xl p-8 hover:bg-slate-50 transition-all duration-300 cursor-default group">
                <div class="label-mono text-[9px] mb-4 text-slate-400 tracking-[0.2em] uppercase">HEALTHY NODES</div>
                <div class="text-5xl font-headline font-bold text-slate-900">${costaff.filter(s=>s.status.includes('Up')).length}</div>
            </div>
            <div class="card-linear bg-white border border-slate-100 shadow-xl rounded-3xl p-8 hover:bg-slate-50 transition-all duration-300 cursor-default group">
                <div class="label-mono text-[9px] mb-4 text-slate-400 tracking-[0.2em] uppercase">GATEWAYS</div>
                <div class="text-5xl font-headline font-bold text-slate-900">${costaff.filter(s=>s.name.startsWith('costaff-channel-')).length}</div>
            </div>
            <div class="card-linear bg-white border border-slate-100 shadow-xl rounded-3xl p-8 hover:bg-slate-50 transition-all duration-300 cursor-default group">
                <div class="label-mono text-[9px] mb-4 text-slate-400 tracking-[0.2em] uppercase">MCP CORES</div>
                <div class="text-5xl font-headline font-bold text-slate-900">${costaff.filter(s=>s.name.startsWith('costaff-mcp-')).length}</div>
            </div>`;
    },

    renderAITeam({ works, diary }) {
        // --- Scheduled Jobs ---
        const rwList = document.getElementById('dash-rw-list');
        const rwBadge = document.getElementById('dash-rw-badge');
        if (rwList) {
            const active = (works || []).filter(w => w.status === 'active');
            if (rwBadge) rwBadge.textContent = `${active.length} JOBS`;
            if (active.length === 0) {
                rwList.innerHTML = `<div class="flex items-center justify-center h-20 text-slate-300 text-[10px] font-bold uppercase tracking-widest">No active schedules</div>`;
            } else {
                rwList.innerHTML = active.map(w => {
                    const ch = w.channel ? `<span class="bg-green-50 text-green-600 px-1.5 py-0.5 rounded text-[9px] font-bold uppercase">${escapeHtml(w.channel)}</span>` : '';
                    const lastRan = w.last_ran_at ? `<span class="text-[9px] text-slate-300">${new Date(w.last_ran_at).toLocaleString()}</span>` : '';
                    return `<div class="px-5 py-3 flex flex-col gap-1 hover:bg-slate-50 transition-all">
                        <div class="flex items-center justify-between gap-2">
                            <span class="font-bold text-slate-800 text-sm truncate">${escapeHtml(w.title)}</span>
                            <div class="flex items-center gap-1 shrink-0">${ch}</div>
                        </div>
                        <div class="flex items-center gap-2 flex-wrap">
                            <span class="font-mono text-[10px] text-blue-600 bg-blue-50 px-1.5 py-0.5 rounded font-bold">${escapeHtml(w.cron)}</span>
                            <span class="text-[9px] text-purple-600 bg-purple-50 px-1.5 py-0.5 rounded font-bold">${escapeHtml(w.agent_id || 'costaff_agent')}</span>
                            ${lastRan}
                        </div>
                        ${w.last_output ? `<p class="text-[10px] text-slate-400 line-clamp-2 leading-relaxed mt-1">${escapeHtml(w.last_output)}</p>` : ''}
                    </div>`;
                }).join('');
            }
        }

        // --- Diary Feed ---
        const diaryList = document.getElementById('dash-diary-list');
        const diaryDate = document.getElementById('dash-diary-date');
        if (diaryList) {
            const entries = diary || [];
            if (diaryDate && entries.length > 0) diaryDate.textContent = entries[0].date || '';
            if (entries.length === 0) {
                diaryList.innerHTML = `<div class="flex items-center justify-center h-20 text-slate-300 text-[10px] font-bold uppercase tracking-widest">No diary entries yet</div>`;
            } else {
                const byDate = {};
                entries.forEach(e => {
                    const d = e.date || e.created_at?.split('T')[0] || '—';
                    if (!byDate[d]) byDate[d] = [];
                    byDate[d].push(e);
                });
                diaryList.innerHTML = Object.entries(byDate).map(([date, items]) => {
                    const cards = items.map(e => {
                        const typeColor = { daily: 'text-blue-600 bg-blue-50', weekly: 'text-purple-600 bg-purple-50', monthly: 'text-green-600 bg-green-50' };
                        const tc = typeColor[e.type] || 'text-slate-500 bg-slate-50';
                        return `<div class="px-5 py-4 hover:bg-slate-50 transition-all">
                            <div class="flex items-center gap-2 mb-2">
                                <span class="text-[9px] font-black uppercase tracking-widest px-2 py-0.5 rounded ${tc}">${escapeHtml(e.type || 'note')}</span>
                                <span class="text-[10px] font-bold text-slate-500">${escapeHtml(e.agent_name || '—')}</span>
                            </div>
                            ${e.done ? `<div class="mb-1"><span class="text-[9px] font-black text-slate-400 uppercase tracking-widest">Done</span><p class="text-xs text-slate-700 mt-0.5 leading-relaxed">${escapeHtml(e.done)}</p></div>` : ''}
                            ${e.next ? `<div class="mb-1"><span class="text-[9px] font-black text-slate-400 uppercase tracking-widest">Next</span><p class="text-xs text-slate-500 mt-0.5 leading-relaxed">${escapeHtml(e.next)}</p></div>` : ''}
                            ${e.blocker ? `<div><span class="text-[9px] font-black text-red-400 uppercase tracking-widest">Blocker</span><p class="text-xs text-red-600 mt-0.5 leading-relaxed">${escapeHtml(e.blocker)}</p></div>` : ''}
                        </div>`;
                    }).join('');
                    return `<div>
                        <div class="px-5 py-2 bg-slate-50 border-b border-slate-100 sticky top-0">
                            <span class="text-[10px] font-black text-slate-400 uppercase tracking-widest">${escapeHtml(date)}</span>
                        </div>
                        ${cards}
                    </div>`;
                }).join('');
            }
        }
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

            let attempts = 0;
            const maxAttempts = 30;
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
});
