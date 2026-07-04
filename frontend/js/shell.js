// Shell: sidebar information architecture — System switcher (Tier 0),
// Manager Agent (pinned) + External Agents (grouped) (Tier 1). The per-agent
// components (Tier 2) live in the Agents detail panel (ui-agents.js).
//
// Replaces the old header-only core switcher: Shell owns core discovery and
// sets App.state.activeCorePrefix so other tabs stay scoped to the active core.
const Shell = {
    async init() {
        await this.loadCores();
        await this.renderAgentsNav();
    },

    // ---- Tier 0: System (core) switcher ----
    async loadCores() {
        const wrap = document.getElementById('system-switcher');
        if (!wrap) return;
        let cores = [];
        try { cores = await API.fetch('/api/cores'); } catch (e) { cores = []; }
        cores = cores || [];
        const active = cores.find(c => c.active) || cores[0];
        if (active) App.state.activeCorePrefix = active.prefix;
        const activeLabel = active ? active.label : 'Default';
        const multi = cores.length > 1;

        wrap.innerHTML = `
            <div class="relative">
                <button ${multi ? 'onclick="Shell.toggleSysMenu(event)"' : 'disabled'}
                    class="w-full flex items-center gap-3 bg-white border border-slate-200 rounded-xl px-3 py-2.5 ${multi ? 'hover:border-blue-300 cursor-pointer' : 'cursor-default'} transition-all shadow-sm text-left">
                    <span class="w-8 h-8 rounded-lg bg-blue-600 text-white flex items-center justify-center shrink-0"><i class="fas fa-layer-group text-sm"></i></span>
                    <span class="flex-1 min-w-0">
                        <span class="block text-[8px] font-black uppercase tracking-[0.15em] text-slate-400">CoStaff System</span>
                        <span class="block text-sm font-bold text-slate-900 truncate">${escapeHtml(activeLabel)}</span>
                    </span>
                    ${multi ? '<i class="fas fa-chevron-down text-slate-300 text-xs shrink-0 transition-transform" id="sys-caret"></i>' : ''}
                </button>
                <div id="sys-menu" class="hidden absolute left-0 right-0 mt-1.5 bg-white border border-slate-200 rounded-xl shadow-xl z-50 p-1.5">
                    ${cores.map(c => `
                        <button onclick="Shell.switchCore('${escapeHtml(c.name)}')" class="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg hover:bg-blue-50 transition-all text-left ${c.active ? 'bg-blue-50/60' : ''}">
                            <span class="w-4 text-blue-600 shrink-0">${c.active ? '<i class="fas fa-check text-xs"></i>' : ''}</span>
                            <span class="flex-1 text-sm font-semibold text-slate-700 truncate">${escapeHtml(c.label)}</span>
                            <span class="text-[9px] font-mono text-slate-300 shrink-0">${escapeHtml(c.prefix || '')}</span>
                        </button>`).join('')}
                </div>
            </div>`;
    },

    toggleSysMenu(e) {
        e.stopPropagation();
        const m = document.getElementById('sys-menu');
        const c = document.getElementById('sys-caret');
        if (m) m.classList.toggle('hidden');
        if (c) c.classList.toggle('rotate-180');
    },

    async switchCore(name) {
        try { await API.post('/api/cores/active', { name }); window.location.reload(); }
        catch (e) { alert('Switch failed: ' + e.message); }
    },

    // ---- Tier 1: Manager (pinned) + External Agents (grouped) ----
    async renderAgentsNav() {
        const mgrWrap = document.getElementById('nav-manager');
        const extWrap = document.getElementById('nav-external');
        let svcs = [], exts = [];
        try { svcs = await API.fetch('/api/status'); } catch (e) { svcs = []; }
        try { exts = await API.fetch('/api/external-agents'); } catch (e) { exts = []; }
        App.state.cachedSvcs = svcs;

        const prefix = App.state.activeCorePrefix || 'costaff';
        const mgr = (svcs || []).find(s => s.name.includes(prefix + '-agent-costaff'));
        const mgrUp = mgr && mgr.status.includes('Up');
        if (mgrWrap) {
            mgrWrap.innerHTML = mgr ? `
                <button onclick="Shell.openManager()" class="sidebar-item w-full flex items-center gap-3 px-6 py-2.5 font-bold text-sm">
                    <span class="w-7 h-7 rounded-lg bg-blue-600 text-white flex items-center justify-center shrink-0"><i class="fas fa-robot text-xs"></i></span>
                    <span class="flex-1 text-left truncate">Costaff Agent</span>
                    <span class="text-[8px] font-black uppercase tracking-wider text-blue-600 border border-blue-200 rounded px-1.5 py-0.5 shrink-0">Hub</span>
                    <span class="w-2 h-2 rounded-full shrink-0 ${mgrUp ? 'bg-green-500' : 'bg-slate-300'}"></span>
                </button>` : '<div class="px-6 py-2 text-[11px] text-slate-400 italic">Manager offline</div>';
        }

        if (extWrap) {
            const count = (exts || []).length;
            const rows = (exts || []).map(a => {
                const dot = a.health ? 'bg-green-500' : (a.enabled ? 'bg-red-400' : 'bg-slate-300');
                const payload = JSON.stringify(a).replace(/"/g, '&quot;');
                return `<button onclick="Shell.openExt(${payload})" class="sidebar-item w-full flex items-center gap-3 px-6 py-2 font-semibold text-[13px]">
                    <span class="w-7 h-7 rounded-lg bg-slate-100 text-slate-500 flex items-center justify-center shrink-0"><i class="fas fa-satellite-dish text-[10px]"></i></span>
                    <span class="flex-1 text-left truncate">${escapeHtml(a.name)}</span>
                    <span class="w-2 h-2 rounded-full shrink-0 ${dot}"></span>
                </button>`;
            }).join('');
            extWrap.innerHTML = `
                <div class="sidebar-group-label flex items-center justify-between pr-6">
                    <span>External Agents · ${count}</span>
                    <button onclick="UI.openAddExternalAgentModal()" class="text-slate-300 hover:text-blue-600 transition-colors" title="Add external agent"><i class="fas fa-plus text-[10px]"></i></button>
                </div>
                ${count ? rows : '<div class="mx-6 my-1 px-3 py-2.5 border border-dashed border-slate-200 rounded-lg text-[11px] text-slate-400 leading-snug">No external agent yet.<br><span class="font-mono text-[10px] text-slate-400">costaff agent add …</span></div>'}`;
        }
    },

    async openManager() {
        await App.switchMainTab('agents');
        let svcs = (App.state.cachedSvcs && App.state.cachedSvcs.length) ? App.state.cachedSvcs : [];
        if (!svcs.length) { try { svcs = await API.fetch('/api/status'); } catch (e) { svcs = []; } }
        const prefix = App.state.activeCorePrefix || 'costaff';
        const mgr = svcs.find(s => s.name.includes(prefix + '-agent-costaff'));
        if (mgr) UI.loadAgentDetail(mgr.name, svcs);
    },

    async openExt(agent) {
        await App.switchMainTab('agents');
        UI.loadExtAgentDetail(agent);
    },
};

window.Shell = Shell;
// Close the system menu on any outside click.
document.addEventListener('click', () => {
    const m = document.getElementById('sys-menu');
    if (m && !m.classList.contains('hidden')) {
        m.classList.add('hidden');
        const c = document.getElementById('sys-caret');
        if (c) c.classList.remove('rotate-180');
    }
});
