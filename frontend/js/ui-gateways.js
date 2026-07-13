Object.assign(UI, {
    renderGateways(svcs, conf) {
        const platforms = [{ id: 'tg', name: 'Telegram', icon: 'telegram' }, { id: 'dc', name: 'Discord', icon: 'discord' }, { id: 'line', name: 'Line', icon: 'line' }, { id: 'web', name: 'WebChat', icon: 'globe', fas: true }];
        const svcName = { tg: 'channel-telegram', dc: 'channel-discord', line: 'channel-line', web: 'channel-webchat' };
        const list = document.getElementById('gateways-list'); if (!list) return;
        list.innerHTML = platforms.map(p => {
            const svc = svcName[p.id];
            const up = svcs.find(s=>s.name.includes(svc))?.status.includes('Up');
            return `<div onclick="UI.loadGatewayDetail('${p.id}', ${JSON.stringify(svcs).replace(/"/g, '&quot;')})"
                 class="p-6 border-b border-slate-100 cursor-pointer hover:bg-slate-50 transition-all group ${App.state.activeGateway===p.id?'bg-blue-50 border-l-4 border-l-blue-600':''}">
                <div class="flex items-center gap-5">
                    <div class="w-12 h-12 rounded-xl bg-slate-50 border border-slate-100 flex items-center justify-center text-blue-600 group-hover:scale-110 transition-transform">
                        <i class="${p.fas ? 'fas' : 'fab'} fa-${p.icon} text-xl"></i>
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
        const platforms = { 'tg': 'Telegram', 'dc': 'Discord', 'line': 'Line', 'web': 'WebChat' };
        const fullName = platforms[platform] || platform.toUpperCase();
        App.state.activeGateway = platform; this.renderGateways(svcs, {});
        const config = await API.fetch('/api/config'); const gConf = config.gateways_config?.[platform] || {};
        const content = document.getElementById('gateway-content');
        if (content) {
            content.classList.remove('hidden'); document.getElementById('gateway-placeholder').classList.add('hidden');
            document.getElementById('gateway-detail-name').innerText = fullName;
            const iconMap = { tg: 'fab fa-telegram', dc: 'fab fa-discord', line: 'fab fa-line', web: 'fas fa-globe' };
            document.getElementById('gateway-icon-large').innerHTML = `<i class="${iconMap[platform] || 'fas fa-globe'}"></i>`;
            this.updateGatewayStatus(platform, svcs);
            if (platform === 'web') {
                document.getElementById('gateway-config-form').innerHTML = `<div class="p-4 rounded-xl bg-slate-50 border border-slate-100 text-sm text-slate-500">WebChat is a standalone web application.<br>Configure it via its own <code>.env</code> file.</div>`;
            } else {
                let fields = platform === 'line' ? [ { label: 'ACCESS TOKEN', key: 'token', type: 'password' }, { label: 'SECRET KEY', key: 'secret', type: 'password' } ] : [{ label: 'TOKEN', key: 'token', type: 'password' }];
                // The API no longer returns the secret itself (only token_set).
                // Render an empty field with a "configured" hint; leaving it
                // blank on save preserves the existing token.
                const ph = gConf.token_set ? 'configured — leave blank to keep' : 'not set';
                document.getElementById('gateway-config-form').innerHTML = fields.map(f => `<div class="space-y-3"><label class="label-mono text-[10px] text-blue-600 font-black uppercase tracking-[0.2em]">${f.label}</label><input type="${f.type}" id="gw-field-${f.key}" value="" placeholder="${ph}" class="w-full bg-slate-50 border border-slate-100 rounded-xl px-5 py-4 outline-none focus:ring-2 focus:ring-blue-500/20 font-mono text-sm text-slate-900"></div>`).join('');
            }
        }
    },

    updateGatewayStatus(platform, svcs) {
        const el = document.getElementById('gateway-detail-actions'); if (!el) return;
        const svcName = { tg: 'channel-telegram', dc: 'channel-discord', line: 'channel-line', web: 'channel-webchat' };
        const svc = svcName[platform] || platform;
        const up = (svcs.find(s=>s.name.includes(svc))?.status || '').includes('Up');
        el.innerHTML = `<button onclick="UI.serviceAction('${svc}', '${up?'stop':'start'}')" class="px-6 py-2 rounded-xl text-xs font-black uppercase tracking-widest transition-all ${up?'bg-slate-100 text-rose-500':'bg-blue-600 text-white hover:bg-blue-700'}">${up?'STOP':'START'}</button>`;
    },

    async saveGatewayConfig() {
        const platform = App.state.activeGateway; if (!platform) return;
        if (platform === 'web') return;
        const config = platform === 'line' ? { token: document.getElementById('gw-field-token').value, secret: document.getElementById('gw-field-secret').value } : { token: document.getElementById('gw-field-token').value };
        try { await API.fetch('/api/gateways', { method: 'POST', body: JSON.stringify({ platform, config }) }); alert('Bridge established.'); App.refresh(); } catch(e) { alert('Sync Failed.'); }
    },
});
