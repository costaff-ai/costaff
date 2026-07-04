// Shell / Cockpit: dark IA. Tier 0 System(core) switcher + context bar,
// Tier 1 Manager (pinned) + External Agents as an expandable tree, Tier 2
// System Library. Selecting an agent (or a component leaf) renders a
// breadcrumb + agent header + tabbed component view (MCPs / APIs / Skills /
// Logs) into #view-agents. MCP tab is editable (assign + Apply & Restart);
// agent controls (restart/stop, enable/disable, remove) live in the header.
const Shell = {
    state: {
        sel: null,          // { type:'agent', key, managerName?, ext?, tab }
        expanded: {},       // agentKey -> bool
    },
    data: { cores: [], svcs: [], exts: [], mcp: { available_mcps: [], agent_mcps: {} }, skills: [], apis: [], prefix: 'costaff', managerName: null },

    async init() {
        const va = document.getElementById('view-agents');
        if (va) va.classList.add('ck');
        await this.loadCores();
        await this.loadData();
        this.renderCtx();
        this.renderTree();
        this.renderLibrary();
    },

    async loadCores() {
        let cores = [];
        try { cores = await API.fetch('/api/cores'); } catch (e) {}
        this.data.cores = cores || [];
        const active = this.data.cores.find(c => c.active) || this.data.cores[0];
        if (active) { App.state.activeCorePrefix = active.prefix; this.data.prefix = active.prefix; }
        this.renderSwitcher(active);
    },

    async loadData() {
        const [svcs, exts, mcp, skills, apis] = await Promise.all([
            API.fetch('/api/status').catch(() => []),
            API.fetch('/api/external-agents').catch(() => []),
            API.fetch('/api/agent-mcp-config').catch(() => ({ available_mcps: [], agent_mcps: {} })),
            API.fetch('/api/skills').catch(() => []),
            API.fetch('/api/apis').catch(() => []),
        ]);
        this.data.svcs = svcs || [];
        this.data.exts = exts || [];
        this.data.mcp = mcp || { available_mcps: [], agent_mcps: {} };
        this.data.skills = skills || [];
        this.data.apis = apis || [];
        App.state.cachedSvcs = this.data.svcs;
        const mgr = this.data.svcs.find(s => s.name.includes(this.data.prefix + '-agent-costaff'));
        this.data.managerName = mgr ? mgr.name : null;
    },

    async reload() { await this.loadData(); this.renderCtx(); this.renderTree(); this.renderLibrary(); if (this.state.sel) this.renderAgentView(); },

    // ---------- Tier 0 ----------
    renderSwitcher(active) {
        const wrap = document.getElementById('system-switcher');
        if (!wrap) return;
        const cores = this.data.cores;
        const multi = cores.length > 1;
        const label = active ? active.label : 'Default';
        wrap.innerHTML = `
            <div class="ck-sw" id="ck-sw">
                <button class="ck-sw-btn" ${multi ? 'onclick="Shell.toggleSys(event)"' : 'disabled'}>
                    <span class="ck-sw-logo"><i class="fas fa-layer-group text-sm"></i></span>
                    <span class="ck-sw-txt"><span class="ck-sw-k">CoStaff System</span><span class="ck-sw-v">${escapeHtml(label)}</span></span>
                    ${multi ? '<i class="fas fa-chevron-down text-xs ck-sw-caret"></i>' : ''}
                </button>
                <div class="ck-sw-menu">
                    ${cores.map(c => `<button class="ck-sw-mi ${c.active ? 'on' : ''}" onclick="Shell.switchCore('${escapeHtml(c.name)}')">
                        <span class="ck-ck">${c.active ? '<i class="fas fa-check text-xs"></i>' : ''}</span>
                        <span style="flex:1">${escapeHtml(c.label)}</span>
                        <span class="ck-meta">${escapeHtml(c.prefix || '')}</span>
                    </button>`).join('')}
                </div>
            </div>`;
    },
    toggleSys(e) { e.stopPropagation(); document.getElementById('ck-sw')?.classList.toggle('open'); },
    async switchCore(name) { try { await API.post('/api/cores/active', { name }); location.reload(); } catch (e) { alert('Switch failed: ' + e.message); } },

    renderCtx() {
        const el = document.getElementById('ck-ctx'); if (!el) return;
        const active = this.data.cores.find(c => c.active) || this.data.cores[0] || {};
        const port = active.manager_port || active.port || '';
        const db = active.db || (active.prefix ? active.prefix + '_db' : '');
        const n = 1 + this.data.exts.length;
        el.innerHTML = `<span class="ck-dot"></span>${escapeHtml(this.data.prefix)}-*<span class="ck-sep">·</span>${port ? ':' + port : ''}${port ? '<span class="ck-sep">·</span>' : ''}${db ? escapeHtml(db) : ''}<span class="ck-sep">·</span>${n} agents`;
    },

    // ---------- Tier 1: tree ----------
    _mgrKey() { return 'costaff_agent'; },
    _extKey(name) { return name.replace(/-/g, '_'); },

    _mcpCount(key) { return (this.data.mcp.agent_mcps && this.data.mcp.agent_mcps[key]) ? this.data.mcp.agent_mcps[key].length : 0; },
    _itemsFor(list, key) {
        return (list || []).filter(it => {
            const ids = (it.agent_ids || '__all__').split(',').map(s => s.trim());
            return ids.includes('__all__') || ids.includes(key);
        });
    },
    _counts(key) {
        return {
            mcps: this._mcpCount(key),
            apis: this._itemsFor(this.data.apis, key).length,
            skills: this._itemsFor(this.data.skills, key).length,
        };
    },

    _leaves(key, isSel, curTab, kind, ident) {
        const c = this._counts(key);
        // manager leaves re-select the manager; external leaves re-select the
        // external agent by key (so the component view gets the ext object).
        const call = kind === 'manager' ? `Shell.pick('manager','${ident}',` : `Shell.pickExtByKey('${ident}',`;
        const row = (id, label, icon) => `<button class="ck-leaf ${isSel && curTab === id ? 'sel' : ''}" onclick="${call}'${id}')"><span class="ck-li"><i class="fas ${icon}"></i></span>${label}<span class="ck-cnt">${c[id]}</span></button>`;
        return `<div class="ck-kids">${row('mcps', 'MCPs', 'fa-cube')}${row('apis', 'APIs', 'fa-code')}${row('skills', 'Skills', 'fa-bolt')}</div>`;
    },
    async pickExtByKey(key, tab) {
        const agent = this.data.exts.find(a => this._extKey(a.name) === key);
        if (agent) return this.pickExt(agent, tab);
    },

    renderTree() {
        // Manager
        const mgrWrap = document.getElementById('nav-manager');
        if (mgrWrap) {
            if (this.data.managerName) {
                const up = this.data.svcs.find(s => s.name === this.data.managerName)?.status.includes('Up');
                const key = this._mgrKey();
                const sel = this.state.sel && this.state.sel.type === 'manager';
                const open = this.state.expanded[key];
                mgrWrap.innerHTML = `
                    <button class="ck-agent mgr ${sel ? 'sel' : ''} ${open ? 'open' : ''}" onclick="Shell.pick('manager','${key}','${sel ? this.state.sel.tab : 'mcps'}')">
                        <span class="ck-chev" onclick="Shell.toggle(event,'${key}')"><i class="fas fa-chevron-right text-[10px]"></i></span>
                        <span class="ck-ai"><i class="fas fa-robot text-xs"></i></span>
                        <span class="ck-nm">Costaff Agent</span>
                        <span class="ck-hub">Hub</span>
                        <span class="ck-stat ${up ? 'up' : 'off'}"></span>
                    </button>${this._leaves(key, sel, sel ? this.state.sel.tab : '', 'manager', key)}`;
            } else {
                mgrWrap.innerHTML = '<div class="px-3 py-2 text-[11px]" style="color:var(--ck-faint)">Manager offline</div>';
            }
        }
        // External
        const extWrap = document.getElementById('nav-external');
        if (extWrap) {
            const exts = this.data.exts;
            const rows = exts.map(a => {
                const key = this._extKey(a.name);
                const sel = this.state.sel && this.state.sel.type === 'ext' && this.state.sel.key === key;
                const open = this.state.expanded[key];
                const dot = a.health ? 'up' : (a.enabled ? 'off' : 'off');
                const payload = JSON.stringify(a).replace(/"/g, '&quot;');
                return `<button class="ck-agent ${sel ? 'sel' : ''} ${open ? 'open' : ''}" onclick="Shell.pickExt(${payload}, '${sel ? this.state.sel.tab : 'mcps'}')">
                        <span class="ck-chev" onclick="Shell.toggle(event,'${key}')"><i class="fas fa-chevron-right text-[10px]"></i></span>
                        <span class="ck-ai"><i class="fas fa-satellite-dish text-[10px]"></i></span>
                        <span class="ck-nm">${escapeHtml(a.name)}</span>
                        <span class="ck-stat ${a.health ? 'up' : (a.enabled ? 'off' : 'off')}"></span>
                    </button>${this._leaves(key, sel, sel ? this.state.sel.tab : '', 'extkey', key)}`;
            }).join('');
            extWrap.innerHTML = `<div class="ck-grp">External Agents · ${exts.length}<button class="ck-add" onclick="UI.openAddExternalAgentModal()" title="Add external agent"><i class="fas fa-plus"></i></button></div>${exts.length ? rows : '<div class="ck-empt"><i class="fas fa-satellite-dish"></i><span>No external agent yet.<br><code>costaff agent add …</code></span></div>'}`;
        }
    },

    renderLibrary() {
        const el = document.getElementById('nav-library'); if (!el) return;
        const rows = [
            { id: 'mcps', label: 'MCPs', icon: 'fa-cube', n: (this.data.mcp.available_mcps || []).length },
            { id: 'apis', label: 'APIs', icon: 'fa-code', n: this.data.apis.length },
            { id: 'skills', label: 'Skills', icon: 'fa-bolt', n: this.data.skills.length },
        ];
        el.innerHTML = rows.map(r => `<button class="ck-lib" onclick="App.switchMainTab('${r.id}')"><span class="ck-li"><i class="fas ${r.icon} text-xs"></i></span>${r.label}<span class="ck-cnt">${r.n}</span></button>`).join('');
    },

    toggle(e, key) { e.stopPropagation(); this.state.expanded[key] = !this.state.expanded[key]; this.renderTree(); },

    // ---------- selection ----------
    async pick(type, key, tab) {
        this.state.sel = { type, key, tab: tab || 'mcps', managerName: this.data.managerName };
        this.state.expanded[key] = true;
        await App.switchMainTab('agents');
        this.renderTree();
        this.renderAgentView();
    },
    async pickExt(agent, tab) {
        const key = this._extKey(agent.name);
        this.state.sel = { type: 'ext', key, tab: tab || 'mcps', ext: agent };
        this.state.expanded[key] = true;
        await App.switchMainTab('agents');
        this.renderTree();
        this.renderAgentView();
    },
    setTab(tab) { if (this.state.sel) { this.state.sel.tab = tab; this.renderTree(); this.renderAgentView(); } },

    // ---------- component view ----------
    _sysLabel() { const a = this.data.cores.find(c => c.active) || this.data.cores[0]; return a ? a.label : 'System'; },

    renderAgentView() {
        const host = document.getElementById('ck-agentview');
        if (!host || !this.state.sel) return;
        const s = this.state.sel;
        const isExt = s.type === 'ext';
        const key = s.key;
        const name = isExt ? s.ext.name : 'Costaff Agent';
        const running = isExt ? !!s.ext.health : (this.data.svcs.find(v => v.name === this.data.managerName)?.status.includes('Up'));
        const typeLabel = isExt ? (s.ext.type === 'github' ? 'GitHub' : 'Remote URL') : '內建';
        const c = this._counts(key);

        // header actions
        let acts = '';
        if (!isExt && this.data.managerName) {
            const svc = UI._dockerServiceName ? UI._dockerServiceName(this.data.managerName) : this.data.managerName;
            acts = `<button class="ck-btn" onclick="UI.serviceAction('${escapeHtml(svc)}','restart'); Shell._later()">Restart</button>
                    <button class="ck-btn ${running ? 'danger' : 'primary'}" onclick="UI.serviceAction('${escapeHtml(svc)}','${running ? 'stop' : 'start'}'); Shell._later()">${running ? 'Stop' : 'Start'}</button>`;
        } else if (isExt) {
            acts = `<button class="ck-btn" onclick="UI.toggleExtAgent('${escapeHtml(s.ext.name)}', ${!s.ext.enabled}); Shell._later()">${s.ext.enabled ? 'Disable' : 'Enable'}</button>`;
            if (s.ext.type === 'url') acts += `<button class="ck-btn danger" onclick="Shell.removeExt('${escapeHtml(s.ext.name)}')">Remove</button>`;
        }

        const badges = `
            <span class="ck-chip ${running ? 'run' : ''}"><span class="d"></span>${running ? 'Running' : (isExt ? 'Offline' : 'Stopped')}</span>
            <span class="ck-chip b">${typeLabel}</span>
            ${!isExt ? '<span class="ck-chip">Orchestrator</span>' : (s.ext.version ? `<span class="ck-chip mono">v${escapeHtml(s.ext.version)}</span>` : '')}`;

        const keyLine = isExt ? `${this.data.prefix}-agent-${key.replace(/_/g, '-')}` : `${this.data.prefix}-agent-costaff`;
        const tab = (id, label, n, icon) => `<button class="ck-tab ${s.tab === id ? 'sel' : ''}" onclick="Shell.setTab('${id}')"><i class="fas ${icon}"></i>${label}<span class="n">${n}</span></button>`;

        host.innerHTML = `
            <div class="ck-crumbs"><span class="sys">${escapeHtml(this._sysLabel())}</span><i class="fas fa-chevron-right text-[9px] sepi"></i><b>Agents</b><i class="fas fa-chevron-right text-[9px] sepi"></i><b>${escapeHtml(name)}</b><i class="fas fa-chevron-right text-[9px] sepi"></i><span class="cur">${s.tab.toUpperCase()}</span></div>
            <div class="ck-ahead">
                <div class="ck-big"><i class="fas ${isExt ? 'fa-satellite-dish' : 'fa-robot'} text-lg"></i></div>
                <div class="ck-who"><h2>${escapeHtml(name)}</h2><div class="key">${escapeHtml(keyLine)}</div><div class="row">${badges}</div></div>
                <div class="ck-acts">${acts}</div>
            </div>
            <div class="ck-tabs">${tab('mcps', 'MCPs', c.mcps, 'fa-cube')}${tab('apis', 'APIs', c.apis, 'fa-code')}${tab('skills', 'Skills', c.skills, 'fa-bolt')}${tab('logs', 'Logs', '', 'fa-terminal')}</div>
            <div id="ck-body"></div>`;

        if (s.tab === 'mcps') this._renderMcpTab(key, isExt, s.ext);
        else if (s.tab === 'logs') this._renderLogsTab(isExt, s.ext);
        else this._renderItemTab(s.tab, key);
    },

    _renderMcpTab(key, isExt, ext) {
        const body = document.getElementById('ck-body'); if (!body) return;
        // url-type external agents self-manage MCP
        if (isExt && ext.type === 'url') {
            body.innerHTML = `<div class="ck-empty"><i class="fas fa-ban text-2xl"></i><p>Remote URL agent self-manages MCP</p><p class="s">CoStaff only handles routing & health</p></div>`;
            return;
        }
        if (isExt && !ext.mcp_configurable) {
            body.innerHTML = `<div class="ck-empty"><i class="fas fa-cube text-2xl"></i><p>This agent does not expose configurable MCP</p></div>`;
            return;
        }
        const available = this.data.mcp.available_mcps || [];
        const assigned = (this.data.mcp.agent_mcps && this.data.mcp.agent_mcps[key]) || [];
        if (!available.length) { body.innerHTML = `<div class="ck-empty"><i class="fas fa-cube text-2xl"></i><p>No MCP available in this System</p></div>`; return; }
        const coreName = isExt ? null : 'costaff';
        const cards = available.map(m => {
            const on = assigned.includes(m);
            const isCore = m === coreName;
            const badge = isCore ? '<span class="ck-chip b"><span class="d"></span>Core</span>' : '';
            return `<div class="ck-card click ${on ? 'on' : ''}" ${isCore ? '' : `onclick="Shell._toggleMcp(this)"`} data-mcp="${escapeHtml(m)}">
                <div class="ck-ci"><i class="fas fa-cube text-xs"></i></div>
                <div class="ck-cinfo"><div class="t"><code>${escapeHtml(m)}</code></div></div>
                <div class="ck-cbadges">${badge}</div>
                <span class="ck-check"><i class="fas fa-check text-[10px]"></i></span>
            </div>`;
        }).join('');
        body.innerHTML = `<div class="ck-list">${cards}</div><div class="ck-applybar"><button class="ck-btn primary" onclick="Shell._applyMcp('${key}')">Apply & Restart</button></div>`;
    },
    _toggleMcp(card) { card.classList.toggle('on'); },
    async _applyMcp(key) {
        const body = document.getElementById('ck-body'); if (!body) return;
        const mcps = Array.from(body.querySelectorAll('.ck-card.on')).map(c => c.dataset.mcp);
        const btn = body.querySelector('.ck-applybar button');
        if (btn) { btn.textContent = 'Applying…'; btn.disabled = true; }
        try {
            await API.fetch('/api/agent-mcp-config', { method: 'POST', body: JSON.stringify({ agent_id: key, mcps }) });
            if (btn) btn.textContent = 'Restarting…';
            setTimeout(() => this.reload(), 5000);
        } catch (e) { alert('Failed: ' + e.message); if (btn) { btn.textContent = 'Apply & Restart'; btn.disabled = false; } }
    },

    _renderItemTab(kind, key) {
        const body = document.getElementById('ck-body'); if (!body) return;
        const list = kind === 'apis' ? this.data.apis : this.data.skills;
        const items = this._itemsFor(list, key);
        if (!items.length) {
            body.innerHTML = `<div class="ck-empty"><i class="fas ${kind === 'apis' ? 'fa-code' : 'fa-bolt'} text-2xl"></i><p>None scoped to this agent</p><p class="s">Add & assign in System Library</p></div>`;
            return;
        }
        const cards = items.map(it => {
            const ids = (it.agent_ids || '__all__').split(',').map(x => x.trim());
            const glob = ids.includes('__all__');
            const badge = glob ? '<span class="ck-chip v"><span class="d"></span>Global</span>' : '<span class="ck-chip g"><span class="d"></span>Agent</span>';
            const off = it.is_active === false ? '<span class="ck-chip"><span class="d" style="background:var(--ck-faint)"></span>Off</span>' : '';
            const meta = kind === 'apis' ? `${escapeHtml((it.method || 'GET').toUpperCase())} · ${escapeHtml(it.url || '')}` : escapeHtml(it.description || '');
            return `<div class="ck-card"><div class="ck-ci"><i class="fas ${kind === 'apis' ? 'fa-code' : 'fa-bolt'} text-xs"></i></div>
                <div class="ck-cinfo"><div class="t">${escapeHtml(it.name)}</div>${meta ? `<div class="m">${meta}</div>` : ''}</div>
                <div class="ck-cbadges">${off}${badge}</div></div>`;
        }).join('');
        body.innerHTML = `<div class="ck-list">${cards}</div><div class="ck-applybar"><button class="ck-btn" onclick="App.switchMainTab('${kind === 'apis' ? 'apis' : 'skills'}')">Manage in Library</button></div>`;
    },

    _renderLogsTab(isExt, ext) {
        const body = document.getElementById('ck-body'); if (!body) return;
        const name = isExt ? ext.name : this.data.managerName;
        if (!name) { body.innerHTML = `<div class="ck-empty"><i class="fas fa-terminal text-2xl"></i><p>No container to read logs from</p></div>`; return; }
        body.innerHTML = `<div class="ck-applybar" style="margin-bottom:12px;justify-content:space-between"><span style="font-family:var(--ck-mono);font-size:11px;color:var(--ck-faint)">docker logs · ${escapeHtml(name)}</span><button class="ck-btn" onclick="Shell._renderLogsTab(${isExt}, ${isExt ? JSON.stringify(ext).replace(/"/g, '&quot;') : 'null'})">Refresh</button></div><div class="ck-logs" id="ck-logbox">Loading…</div>`;
        API.fetch(`/api/logs/${name}?tail=80`).then(res => {
            const box = document.getElementById('ck-logbox');
            if (box) box.textContent = (res.logs || '(no logs)').replace(/\[\d+m/g, '').trim() || '(no logs)';
        }).catch(e => { const box = document.getElementById('ck-logbox'); if (box) box.textContent = '(error: ' + e.message + ')'; });
    },

    async removeExt(name) {
        if (!confirm(`Remove agent '${name}'? This cannot be undone.`)) return;
        try { await API.fetch(`/api/external-agents/${name}`, { method: 'DELETE' }); this.state.sel = null; const h = document.getElementById('ck-agentview'); if (h) h.innerHTML = this._placeholder(); this.reload(); }
        catch (e) { alert('Failed: ' + e.message); }
    },
    _later() { setTimeout(() => this.reload(), 4000); },
    _placeholder() { return `<div class="ck-ph"><i class="fas fa-diagram-project"></i><p>Select an agent from the sidebar</p></div>`; },
};

window.Shell = Shell;
document.addEventListener('click', () => document.getElementById('ck-sw')?.classList.remove('open'));
