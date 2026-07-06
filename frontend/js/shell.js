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
    data: { cores: [], svcs: [], exts: [], mcp: { available_mcps: [], agent_mcps: {} }, skills: [], apis: [], cards: {}, prefix: 'costaff', managerName: null },

    async init() {
        const va = document.getElementById('view-agents');
        if (va) va.classList.add('ck');
        await this.loadCores();
        await this.loadData();
        this.renderTree();
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
        this._loadCards();  // lazy, non-blocking: fetch each external agent's A2A card for its real skills
    },

    async reload() { await this.loadData(); this.renderTree(); if (this.state.sel) this.renderAgentView(); },

    // Fetch external agents' live A2A agent cards (real declared skills). Cached
    // per key; only fetches healthy agents not already cached. Re-renders when done.
    async _fetchCard(ext) {
        const key = this._extKey(ext.name);
        try { this.data.cards[key] = await API.fetch(`/api/external-agents/${encodeURIComponent(ext.name)}/card`); }
        catch (e) { this.data.cards[key] = { error: (e && e.message) || 'fetch failed', skills: [] }; }
    },
    async _loadCards() {
        const pending = this.data.exts.filter(a => a.health && this.data.cards[this._extKey(a.name)] === undefined);
        if (!pending.length) return;
        await Promise.all(pending.map(a => this._fetchCard(a)));
        this.renderTree();
        if (this.state.sel && this.state.sel.type === 'ext') this.renderAgentView();
    },

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
    // The tab set differs by agent kind. Manager: its own registry (MCPs it
    // wires + global/agent-scoped APIs & Skills), MCPs editable. Every external
    // (Option-C) agent gets the SAME two read-only pages — Skills (from its live
    // A2A card) + MCPs (shared MCP wiring, view-only) — plus Logs. External
    // agents are never editable here (no toggle / Apply & Restart).
    _tabsFor(isExt, ext) {
        if (!isExt) return [
            { id: 'mcps', label: 'MCPs', icon: 'fa-cube' },
            { id: 'apis', label: 'APIs', icon: 'fa-code' },
            { id: 'skills', label: 'Skills', icon: 'fa-bolt' },
            { id: 'logs', label: 'Logs', icon: 'fa-terminal' },
        ];
        return [
            { id: 'skills', label: 'Skills', icon: 'fa-bolt' },
            { id: 'mcps', label: 'MCPs', icon: 'fa-cube' },
            { id: 'logs', label: 'Logs', icon: 'fa-terminal' },
        ];
    },
    // count shown on a tab / tree leaf. External 'skills' = live A2A card count.
    _tabCount(id, key, isExt) {
        if (id === 'skills') return isExt ? ((this.data.cards[key] || {}).skills || []).length : this._itemsFor(this.data.skills, key).length;
        if (id === 'apis') return this._itemsFor(this.data.apis, key).length;
        if (id === 'mcps') return this._mcpCount(key);
        return '';
    },

    _leaves(key, isSel, curTab, kind, ident, isExt, ext) {
        // manager leaves re-select the manager; external leaves re-select the
        // external agent by key (so the component view gets the ext object).
        const call = kind === 'manager' ? `Shell.pick('manager','${ident}',` : `Shell.pickExtByKey('${ident}',`;
        const leaves = this._tabsFor(isExt, ext).filter(t => t.id !== 'logs');  // logs is a tab, not a tree leaf
        const row = (t) => `<button class="ck-leaf ${isSel && curTab === t.id ? 'sel' : ''}" onclick="${call}'${t.id}')"><span class="ck-li"><i class="fas ${t.icon}"></i></span>${t.label}<span class="ck-cnt">${this._tabCount(t.id, key, isExt)}</span></button>`;
        return `<div class="ck-kids">${leaves.map(row).join('')}</div>`;
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
                    </button>${this._leaves(key, sel, sel ? this.state.sel.tab : '', 'manager', key, false, null)}`;
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
                return `<button class="ck-agent ${sel ? 'sel' : ''} ${open ? 'open' : ''}" onclick="Shell.pickExt(${payload}, '${sel ? this.state.sel.tab : 'skills'}')">
                        <span class="ck-chev" onclick="Shell.toggle(event,'${key}')"><i class="fas fa-chevron-right text-[10px]"></i></span>
                        <span class="ck-ai"><i class="fas fa-satellite-dish text-[10px]"></i></span>
                        <span class="ck-nm">${escapeHtml(a.name)}</span>
                        <span class="ck-stat ${a.health ? 'up' : (a.enabled ? 'off' : 'off')}"></span>
                    </button>${this._leaves(key, sel, sel ? this.state.sel.tab : '', 'extkey', key, true, a)}`;
            }).join('');
            extWrap.innerHTML = `<div class="ck-grp">External Agents · ${exts.length}<button class="ck-add" onclick="UI.openAddExternalAgentModal()" title="Add external agent"><i class="fas fa-plus"></i></button></div>${exts.length ? rows : '<div class="ck-empt"><i class="fas fa-satellite-dish"></i><span>No external agent yet.<br><code>costaff agent add …</code></span></div>'}`;
        }
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
        this.state.sel = { type: 'ext', key, tab: tab || 'skills', ext: agent };
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
        const tabsList = this._tabsFor(isExt, isExt ? s.ext : null);
        if (!tabsList.find(t => t.id === s.tab)) s.tab = tabsList[0].id;  // keep tab valid across agent kinds

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
        const tab = (t) => `<button class="ck-tab ${s.tab === t.id ? 'sel' : ''}" onclick="Shell.setTab('${t.id}')"><i class="fas ${t.icon}"></i>${t.label}<span class="n">${this._tabCount(t.id, key, isExt)}</span></button>`;

        host.innerHTML = `
            <div class="ck-crumbs"><span class="sys">${escapeHtml(this._sysLabel())}</span><i class="fas fa-chevron-right text-[9px] sepi"></i><b>Agents</b><i class="fas fa-chevron-right text-[9px] sepi"></i><b>${escapeHtml(name)}</b><i class="fas fa-chevron-right text-[9px] sepi"></i><span class="cur">${s.tab.toUpperCase()}</span></div>
            <div class="ck-ahead">
                <div class="ck-big"><i class="fas ${isExt ? 'fa-satellite-dish' : 'fa-robot'} text-lg"></i></div>
                <div class="ck-who"><h2>${escapeHtml(name)}</h2><div class="key">${escapeHtml(keyLine)}</div><div class="row">${badges}</div></div>
                <div class="ck-acts">${acts}</div>
            </div>
            <div class="ck-tabs">${tabsList.map(tab).join('')}</div>
            <div id="ck-body"></div>`;

        if (s.tab === 'mcps') this._renderMcpTab(key, isExt, s.ext);
        else if (s.tab === 'logs') this._renderLogsTab(isExt, s.ext);
        else if (s.tab === 'skills' && isExt) this._renderCardSkillsTab(key, s.ext);
        else this._renderItemTab(s.tab, key);
    },

    // External agent Skills tab — rendered from the live A2A card (its REAL
    // declared skills), fetched lazily via /api/external-agents/{name}/card.
    _renderCardSkillsTab(key, ext) {
        const body = document.getElementById('ck-body'); if (!body) return;
        const card = this.data.cards[key];
        if (card === undefined) {  // not fetched yet
            body.innerHTML = `<div class="ck-empty"><i class="fas fa-bolt text-2xl"></i><p>Loading capabilities…</p></div>`;
            this._fetchCard(ext).then(() => {
                if (this.state.sel && this.state.sel.type === 'ext' && this.state.sel.key === key && this.state.sel.tab === 'skills') this._renderCardSkillsTab(key, ext);
            });
            return;
        }
        if (card.error) {
            body.innerHTML = `<div class="ck-empty"><i class="fas fa-triangle-exclamation text-2xl"></i><p>Could not read this agent's A2A card</p><p class="s">${escapeHtml(String(card.error))}</p></div>`;
            return;
        }
        const sk = card.skills || [];
        if (!sk.length) { body.innerHTML = `<div class="ck-empty"><i class="fas fa-bolt text-2xl"></i><p>Agent card declares no skills</p></div>`; return; }
        const banner = `<div class="ck-banner"><i class="fas fa-satellite-dish"></i>From the agent's live <b>A2A card</b> · ${sk.length} skill${sk.length > 1 ? 's' : ''}</div>`;
        const cards = sk.map(sm => {
            const desc = (sm.description || '').split('\n')[0].trim().slice(0, 160);
            const tags = (sm.tags || []).slice(0, 6).map(t => `<span class="ck-chip mono">${escapeHtml(t)}</span>`).join('');
            return `<div class="ck-card"><div class="ck-ci"><i class="fas fa-bolt text-xs"></i></div>
                <div class="ck-cinfo"><div class="t">${escapeHtml(sm.name || sm.id || '(unnamed)')}</div>${desc ? `<div class="m" style="font-family:inherit">${escapeHtml(desc)}</div>` : ''}${tags ? `<div class="row" style="display:flex;flex-wrap:wrap;gap:6px;margin-top:6px">${tags}</div>` : ''}</div></div>`;
        }).join('');
        body.innerHTML = banner + `<div class="ck-list">${cards}</div>`;
    },

    _renderMcpTab(key, isExt, ext) {
        const body = document.getElementById('ck-body'); if (!body) return;
        const assigned = (this.data.mcp.agent_mcps && this.data.mcp.agent_mcps[key]) || [];

        // External agents: MCP wiring is READ-ONLY in the UI. Their tools live in
        // their own container (see the Skills tab / A2A card); shared core-MCP
        // wiring is managed via CLI (agent_mcp_filters + rebuild), not edited here.
        if (isExt) {
            if (!assigned.length) {
                const why = ext && ext.type === 'url'
                    ? 'Remote URL agent self-manages its MCP'
                    : 'This agent runs its own tools; shared core-MCP wiring is set via CLI';
                body.innerHTML = `<div class="ck-empty"><i class="fas fa-cube text-2xl"></i><p>No shared MCP servers wired to this agent</p><p class="s">${why}</p></div>`;
                return;
            }
            const roCards = assigned.map(m => `<div class="ck-card"><div class="ck-ci"><i class="fas fa-cube text-xs"></i></div><div class="ck-cinfo"><div class="t"><code>${escapeHtml(m)}</code></div></div><div class="ck-cbadges"><span class="ck-chip g"><span class="d"></span>wired</span></div></div>`).join('');
            body.innerHTML = `<div class="ck-banner"><i class="fas fa-lock"></i>Read-only · shared MCP servers wired to this agent (managed via CLI)</div><div class="ck-list">${roCards}</div>`;
            return;
        }

        // Manager: editable core-MCP assignment.
        const available = this.data.mcp.available_mcps || [];
        if (!available.length) { body.innerHTML = `<div class="ck-empty"><i class="fas fa-cube text-2xl"></i><p>No MCP available in this System</p></div>`; return; }
        const coreName = 'costaff';
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
            body.innerHTML = `<div class="ck-empty"><i class="fas ${kind === 'apis' ? 'fa-code' : 'fa-bolt'} text-2xl"></i><p>None scoped to this agent</p><div class="ck-applybar" style="justify-content:center;margin-top:12px"><button class="ck-btn" onclick="App.switchMainTab('${kind === 'apis' ? 'apis' : 'skills'}')">Manage registry</button></div></div>`;
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
        body.innerHTML = `<div class="ck-list">${cards}</div><div class="ck-applybar"><button class="ck-btn" onclick="App.switchMainTab('${kind === 'apis' ? 'apis' : 'skills'}')">Manage registry</button></div>`;
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
