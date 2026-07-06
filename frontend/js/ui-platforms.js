// Platforms — read-only ops view for business platforms (ERP/CRM/HRM/…).
// Lists registered platforms with frontend health, allows start / restart /
// stop, and supports search + status filtering and a card / list view toggle.
// Deploy/rebuild/remove stay CLI-only.
const Platforms = {
    HEALTH: {
        healthy:   { dot: 'bg-emerald-500', label: 'Healthy' },
        unhealthy: { dot: 'bg-amber-500',   label: 'Starting' },
        down:      { dot: 'bg-rose-500',    label: 'Down' },
        'n/a':     { dot: 'bg-slate-300',   label: 'Disabled' },
    },

    _all: [],
    _search: '',
    _status: '__all__',
    _view: 'cards',
    _page: 1,
    _pageSize: 8,   // rows per page in the table (list) view

    async init() { await this.load(); },

    async load() {
        const el = document.getElementById('platforms-list');
        if (!el) return;
        el.className = '';
        el.innerHTML = `<div class="text-center text-slate-400 py-12 text-sm font-mono">Loading platforms…</div>`;
        try {
            this._all = (await API.fetch('/api/platforms')) || [];
            this.render();
        } catch (e) {
            el.innerHTML = `<div class="text-center text-rose-500 py-12 text-sm font-mono">Failed to load: ${escapeHtml(e.message)}</div>`;
        }
    },

    // filter / view changes reset to the first page (the visible set changed)
    setSearch(v) { this._search = (v || '').toLowerCase().trim(); this._page = 1; this.render(); },
    setStatus(v) { this._status = v; this._page = 1; this.render(); },
    setView(v) { this._view = v; this._page = 1; this.render(); },
    setPage(n) { this._page = n; this.render(); },

    _syncToggle() {
        const on = 'px-3 py-2 text-xs bg-blue-600 text-white';
        const c = document.getElementById('plat-view-cards');
        const l = document.getElementById('plat-view-list');
        if (c) c.className = this._view === 'cards' ? on : 'px-3 py-2 text-xs text-slate-500';
        if (l) l.className = (this._view === 'list' ? on : 'px-3 py-2 text-xs text-slate-500') + ' border-l border-slate-200';
    },

    _filtered() {
        return this._all.filter(p => {
            if (this._status !== '__all__' && (p.health || 'n/a') !== this._status) return false;
            if (this._search) {
                const hay = `${p.name || ''} ${p.port || ''} ${p.url || ''}`.toLowerCase();
                if (!hay.includes(this._search)) return false;
            }
            return true;
        });
    },

    _btn(label, onclick, cls, icon) {
        return `<button onclick="${onclick}" class="px-4 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-widest transition-all ${cls}">${icon ? `<i class="fas ${icon} mr-1"></i>` : ''}${label}</button>`;
    },

    _actions(p) {
        const up = p.health === 'healthy' || p.health === 'unhealthy';
        return up
            ? `${p.url ? `<a href="${escapeHtml(p.url)}" target="_blank" rel="noopener" class="px-4 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-widest bg-slate-100 text-slate-600 hover:bg-slate-200 transition-all no-underline"><i class="fas fa-arrow-up-right-from-square mr-1"></i>Open</a>` : ''}
               ${this._btn('Restart', `Platforms.action('${escapeHtml(p.name)}','restart')`, 'bg-slate-100 text-slate-600 hover:bg-slate-200', 'fa-rotate')}
               ${this._btn('Stop', `Platforms.action('${escapeHtml(p.name)}','stop')`, 'bg-slate-100 text-rose-500 hover:bg-rose-50', 'fa-stop')}`
            : this._btn('Start', `Platforms.action('${escapeHtml(p.name)}','start')`, 'bg-blue-600 text-white hover:bg-blue-700', 'fa-play');
    },

    _endpoint(p) {
        return `${p.port ? 'localhost:' + escapeHtml(p.port) : 'no public port'}${p.ref ? ' · ' + escapeHtml(p.ref) : ''}`;
    },

    render() {
        const el = document.getElementById('platforms-list');
        if (!el) return;
        this._syncToggle();
        const countEl = document.getElementById('platforms-count');

        if (!this._all.length) {
            el.className = '';
            el.innerHTML = `<div class="text-center text-slate-400 py-12 text-sm font-mono">No platforms registered. Add one with <code>costaff platform add &lt;name&gt;</code>.</div>`;
            if (countEl) countEl.textContent = '';
            return;
        }
        const list = this._filtered();
        if (countEl) countEl.textContent = `${list.length} of ${this._all.length} platform${this._all.length > 1 ? 's' : ''}`;
        if (!list.length) {
            el.className = '';
            el.innerHTML = `<div class="text-center text-slate-400 py-12 text-sm font-mono">No platforms match the current filter.</div>`;
            return;
        }
        if (this._view === 'list') this._renderList(el, list);
        else this._renderCards(el, list);
    },

    _renderCards(el, list) {
        el.className = 'grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4';
        el.innerHTML = list.map(p => {
            const h = this.HEALTH[p.health] || this.HEALTH['n/a'];
            return `<div class="rounded-2xl border border-slate-100 bg-white p-5 hover:shadow-md transition-all">
                <div class="flex items-start justify-between mb-4">
                    <div class="flex items-center gap-3 min-w-0">
                        <div class="w-11 h-11 rounded-xl bg-slate-50 border border-slate-100 flex items-center justify-center text-blue-600 shrink-0">
                            <i class="fas ${p.is_shared_db ? 'fa-database' : 'fa-cube'} text-lg"></i>
                        </div>
                        <div class="min-w-0">
                            <div class="text-sm font-black text-slate-900 uppercase tracking-wide truncate">${escapeHtml(p.name)}${p.is_shared_db ? ' <span class="text-[9px] text-slate-400 normal-case tracking-normal">(shared DB)</span>' : ''}</div>
                            <div class="text-[10px] font-mono text-slate-400 mt-0.5 truncate">${this._endpoint(p)}</div>
                        </div>
                    </div>
                    <span class="flex items-center gap-1.5 text-[10px] font-black uppercase tracking-widest text-slate-500 shrink-0"><span class="w-2 h-2 rounded-full ${h.dot}"></span>${h.label}</span>
                </div>
                <div class="flex items-center gap-2 flex-wrap">${this._actions(p)}</div>
            </div>`;
        }).join('');
    },

    _renderList(el, list) {
        el.className = '';
        // paginate so a long platform list stays manageable
        const total = list.length;
        const pageSize = this._pageSize;
        const pages = Math.max(1, Math.ceil(total / pageSize));
        this._page = Math.min(Math.max(1, this._page), pages);
        const start = (this._page - 1) * pageSize;
        const pageItems = list.slice(start, start + pageSize);
        const rows = pageItems.map(p => {
            const h = this.HEALTH[p.health] || this.HEALTH['n/a'];
            return `<tr class="border-t border-slate-50 hover:bg-slate-50/60 transition-all">
                <td class="py-3 px-4">
                    <div class="flex items-center gap-3 min-w-0">
                        <div class="w-8 h-8 rounded-lg bg-slate-50 border border-slate-100 flex items-center justify-center text-blue-600 shrink-0"><i class="fas ${p.is_shared_db ? 'fa-database' : 'fa-cube'} text-xs"></i></div>
                        <span class="text-xs font-black text-slate-900 uppercase tracking-wide truncate">${escapeHtml(p.name)}${p.is_shared_db ? ' <span class="text-[9px] text-slate-400 normal-case tracking-normal">(shared DB)</span>' : ''}</span>
                    </div>
                </td>
                <td class="py-3 px-4 text-[11px] font-mono text-slate-400 whitespace-nowrap">${this._endpoint(p)}</td>
                <td class="py-3 px-4"><span class="flex items-center gap-1.5 text-[10px] font-black uppercase tracking-widest text-slate-500 whitespace-nowrap"><span class="w-2 h-2 rounded-full ${h.dot}"></span>${h.label}</span></td>
                <td class="py-3 px-4"><div class="flex items-center gap-2 flex-wrap justify-end">${this._actions(p)}</div></td>
            </tr>`;
        }).join('');
        const table = `<div class="rounded-2xl border border-slate-100 bg-white overflow-hidden"><div class="overflow-x-auto"><table class="w-full text-left">
            <thead><tr class="text-[10px] uppercase tracking-widest text-slate-400 bg-slate-50/50">
                <th class="py-2.5 px-4 font-black">Platform</th><th class="py-2.5 px-4 font-black">Endpoint</th><th class="py-2.5 px-4 font-black">Status</th><th class="py-2.5 px-4 font-black text-right">Actions</th>
            </tr></thead>
            <tbody>${rows}</tbody></table></div></div>`;
        el.innerHTML = table + this._pager(this._page, pages, start, pageItems.length, total);
    },

    _pager(page, pages, start, shown, total) {
        if (pages <= 1) return '';
        const btn = (label, target, disabled) => `<button ${disabled ? 'disabled' : `onclick="Platforms.setPage(${target})"`} class="px-3 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-widest transition-all ${disabled ? 'bg-slate-50 text-slate-300 cursor-default' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}">${label}</button>`;
        return `<div class="flex items-center justify-between mt-4 flex-wrap gap-3">
            <span class="text-[11px] font-mono text-slate-400">Showing ${start + 1}–${start + shown} of ${total}</span>
            <div class="flex items-center gap-2">
                ${btn('<i class="fas fa-chevron-left mr-1"></i>Prev', page - 1, page <= 1)}
                <span class="text-[11px] font-black uppercase tracking-widest text-slate-500 px-1">Page ${page} / ${pages}</span>
                ${btn('Next<i class="fas fa-chevron-right ml-1"></i>', page + 1, page >= pages)}
            </div>
        </div>`;
    },

    async action(name, act) {
        try {
            await API.post(`/api/platforms/${name}/action`, { action: act });
            setTimeout(() => this.load(), 800);
        } catch (e) {
            alert(`Platform ${act} failed:\n${e.message}`);
        }
    },
};
