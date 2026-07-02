Object.assign(UI, {
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
            return `<div onclick="UI.loadMCPDetail('${escapeHtml(m.name)}', ${JSON.stringify(svcs).replace(/"/g, '&quot;')})"
                 class="p-6 border-b border-slate-100 cursor-pointer hover:bg-slate-50 transition-all group ${App.state.activeMCP === m.name ? 'bg-blue-50 border-l-4 border-l-blue-600' : ''}">
                <div class="flex items-center gap-5">
                    <div class="w-12 h-12 rounded-xl ${m.isCore ? 'bg-blue-600 text-white shadow-lg shadow-blue-200' : 'bg-slate-50 border border-slate-100 text-blue-600 group-hover:scale-110'} flex items-center justify-center transition-transform">
                        <i class="fas ${icon} text-lg"></i>
                    </div>
                    <div class="flex-1 min-w-0">
                        <div class="flex justify-between items-center mb-1">
                            <div class="text-base font-headline font-bold text-slate-900 truncate tracking-tight uppercase">${escapeHtml(m.name)}</div>
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
        document.getElementById('field-group-source').classList.toggle('hidden', isCore);
        document.getElementById('field-group-url').classList.toggle('hidden', isCore);
        document.getElementById('field-group-headers').classList.toggle('hidden', isCore);
        document.getElementById('mcp-save-row').classList.toggle('hidden', isCore);
        if (isExt) {
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
            <input type="text" placeholder="Key" value="${escapeHtml(key)}" class="flex-1 bg-white border border-slate-100 rounded-xl px-4 py-2.5 text-sm font-mono text-slate-700 outline-none focus:ring-2 focus:ring-blue-500/20">
            <input type="text" placeholder="Value" value="${escapeHtml(value)}" class="flex-1 bg-white border border-slate-100 rounded-xl px-4 py-2.5 text-sm font-mono text-slate-700 outline-none focus:ring-2 focus:ring-blue-500/20">
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
        if (isExt) el.innerHTML = `<button onclick="UI.deleteItem('mcp', '${escapeHtml(name)}')" class="px-6 py-2 rounded-xl text-xs font-black bg-rose-50 text-rose-500 hover:bg-rose-500 hover:text-white transition-all uppercase tracking-widest border border-rose-100">Remove Link</button>`;
        else el.innerHTML = `<div class="flex items-center gap-3"><button onclick="UI.deleteItem('mcp', '${escapeHtml(name)}')" class="p-2.5 rounded-xl text-slate-400 hover:text-rose-500 hover:bg-rose-50 transition-all border border-slate-100"><i class="fas fa-trash-alt text-xs"></i></button><button onclick="UI.serviceAction('${escapeHtml(svc)}', '${isUp?'stop':'start'}')" class="px-6 py-2 rounded-xl text-xs font-black transition-all ${isUp?'bg-slate-100 text-rose-500 hover:bg-rose-500 hover:text-white':'bg-blue-600 text-white hover:bg-blue-700'} uppercase tracking-widest">${isUp?'STOP':'START'}</button></div>`;
    },
});
