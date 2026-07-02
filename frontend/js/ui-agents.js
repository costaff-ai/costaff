Object.assign(UI, {
    renderAgents(svcs) {
        // Cache svcs so onclick handlers can retrieve by name without embedding JSON in HTML
        App.state.cachedSvcs = svcs;
        // Only THIS core's manager (host-wide /api/status also lists other cores' managers).
        const prefix = App.state.activeCorePrefix || 'costaff';
        const agents = svcs.filter(s => s.name.includes(prefix + '-agent-costaff'));
        const list = document.getElementById('agents-list'); if (!list) return;
        list.innerHTML = agents.map(a => {
            const up = a.status.includes('Up');
            return `<div onclick="UI.loadAgentDetail('${escapeHtml(a.name)}')"
                 class="p-5 cursor-pointer hover:bg-slate-50 transition-all ${App.state.activeAgent===a.name?'bg-blue-50 border-l-4 border-l-blue-600':''}">
                <div class="flex justify-between items-center mb-1"><div class="text-sm font-headline font-bold text-slate-900 uppercase tracking-tight">costaff agent</div><div class="w-2 h-2 rounded-full ${up?'bg-blue-600 shadow-[0_0_8px_rgba(37,99,235,0.5)] animate-pulse':'bg-slate-200'}"></div></div>
                <div class="text-[10px] text-slate-400 font-mono uppercase tracking-tighter italic">${escapeHtml(a.status)}</div></div>`;
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
                        <div class="text-sm font-headline font-bold text-slate-900 uppercase tracking-tight">${escapeHtml(a.name)}</div>
                        <div class="w-2 h-2 rounded-full ${healthDot}"></div>
                    </div>
                    <div class="flex items-center gap-2 mt-1">
                        <span class="text-[9px] font-black uppercase px-1.5 py-0.5 rounded ${typeColor}">${escapeHtml(a.type)}</span>
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
        if (App.state.cachedSvcs) this.renderAgents(App.state.cachedSvcs);
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

        const badge = document.getElementById('ext-agent-type-badge');
        const health = agent.health
            ? '<span class="inline-flex items-center gap-1 text-[10px] font-black text-green-600 bg-green-50 px-2 py-0.5 rounded-full"><span class="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse inline-block"></span>ONLINE</span>'
            : '<span class="inline-flex items-center gap-1 text-[10px] font-black text-red-500 bg-red-50 px-2 py-0.5 rounded-full"><span class="w-1.5 h-1.5 rounded-full bg-red-400 inline-block"></span>OFFLINE</span>';
        const typeLabel = agent.type === 'github'
            ? '<span class="text-[10px] font-black text-violet-600 bg-violet-50 px-2 py-0.5 rounded-full uppercase">GitHub Deploy</span>'
            : '<span class="text-[10px] font-black text-blue-600 bg-blue-50 px-2 py-0.5 rounded-full uppercase">Remote URL</span>';
        badge.innerHTML = `<div class="flex items-center gap-2 mt-1">${typeLabel}${health}</div>`;

        document.getElementById('ext-agent-icon').className = agent.type === 'github'
            ? 'w-16 h-16 rounded-2xl bg-violet-600 text-white flex items-center justify-center text-3xl shadow-xl shadow-violet-200'
            : 'w-16 h-16 rounded-2xl bg-blue-600 text-white flex items-center justify-center text-3xl shadow-xl shadow-blue-200';

        const actions = document.getElementById('ext-agent-actions');
        const toggleLabel = agent.enabled ? 'DISABLE' : 'ENABLE';
        const toggleClass = agent.enabled ? 'bg-slate-100 text-rose-500' : 'bg-blue-600 text-white hover:bg-blue-700';
        actions.innerHTML = `
            <button onclick="UI.toggleExtAgent('${escapeHtml(agent.name)}', ${!agent.enabled})" class="px-4 py-2 rounded-xl text-xs font-black uppercase tracking-widest transition-all ${toggleClass}">${toggleLabel}</button>
            ${agent.type === 'url' ? `<button onclick="UI.removeExtAgent('${escapeHtml(agent.name)}')" class="px-4 py-2 rounded-xl text-xs font-black uppercase tracking-widest border border-rose-200 text-rose-500 hover:bg-rose-50 transition-all">REMOVE</button>` : ''}
        `;

        const mcpSection = document.getElementById('ext-agent-mcp-section');
        const logsSection = document.getElementById('ext-agent-logs-section');
        const urlNotice = document.getElementById('ext-agent-url-notice');
        if (agent.type === 'github') {
            // MCP section only for agents that declare mcp_configurable in costaff.agent.json
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
                    <input type="checkbox" value="${escapeHtml(mcp)}" ${checked ? 'checked' : ''} data-agent="${escapeHtml(agentKey)}"
                        class="w-4 h-4 accent-blue-600 rounded" onchange="UI._updateMCPCheckStyle(this)">
                    <span class="text-xs font-bold text-slate-700">${escapeHtml(mcp)}</span>
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
            if (box) { box.innerText = (res.logs || '(no logs)').replace(/\[\d+m/g, '').trim() || '(no logs)'; box.scrollTop = box.scrollHeight; }
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
        this.loadExternalAgents();
        const agent = svcList.find(s => s.name === name); if (!agent) return;
        document.getElementById('agent-placeholder').classList.add('hidden');
        document.getElementById('ext-agent-content').classList.add('hidden');
        document.getElementById('agent-content').classList.remove('hidden');
        document.getElementById('agent-detail-name').innerText = 'COSTAFF AGENT';
        this.loadAgentLogs();
        this.updateAgentStatus(name, svcs);
        this.loadAgentMCPConfig(name);
    },

    // Map Docker container name (may include project prefix) to config agent_id
    _agentConfigId(dockerName) {
        if (dockerName.includes('costaff-agent') || dockerName.includes('costaff_agent')) return 'costaff_agent';
        if (dockerName.includes('costaff-agent-coding') || dockerName.includes('coding_agent')) return 'coding_agent';
        return dockerName.replace(/-/g, '_');
    },

    // Extract bare service name for docker logs (strip compose project prefix)
    _dockerServiceName(containerName) {
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
                const isCore = (agentId === 'costaff_agent' && mcp === 'costaff') || (agentId === 'coding_agent' && mcp === 'coding');
                return `<label class="flex items-center gap-3 p-3 rounded-xl border ${checked ? 'border-blue-200 bg-blue-50' : 'border-slate-100 bg-white'} cursor-pointer hover:border-blue-200 transition-all">
                    <input type="checkbox" value="${escapeHtml(mcp)}" ${checked ? 'checked' : ''} ${isCore ? 'disabled' : ''}
                        class="w-4 h-4 accent-blue-600 rounded" onchange="UI._updateMCPCheckStyle(this)">
                    <div>
                        <span class="text-xs font-bold text-slate-700">${escapeHtml(mcp)}</span>
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
        el.innerHTML = `<button onclick="UI.serviceAction('${escapeHtml(svc)}', 'restart')" class="px-4 py-2 rounded-xl text-xs font-black uppercase tracking-widest border border-slate-100 text-slate-500 hover:bg-slate-900 hover:text-white transition-all">REBOOT</button><button onclick="UI.serviceAction('${escapeHtml(svc)}', '${up?'stop':'start'}')" class="px-6 py-2 rounded-xl text-xs font-black uppercase tracking-widest ${up?'bg-slate-100 text-rose-500':'bg-blue-600 text-white hover:bg-blue-700'} transition-all">${up?'STOP':'START'}</button>`;
    },

    async loadAgentLogs() {
        if (!App.state.activeAgent) return;
        // docker logs needs the full container name, not the bare service name
        const res = await API.fetch(`/api/logs/${App.state.activeAgent}?tail=50`);
        const box = document.getElementById('agent-logs-preview'); if (box) { box.innerText = (res.logs || '').replace(/\[\d+m/g, ''); box.scrollTop = box.scrollHeight; }
    },
});
