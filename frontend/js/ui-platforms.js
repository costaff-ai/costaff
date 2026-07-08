// Platforms — business platforms (ERP/CRM/HRM/…) in two flavours:
// - local: installed on this host via `costaff platform add`; health probes
//   localhost, lifecycle = start/restart/stop. Deploy/rebuild stay CLI-only.
// - remote: registered here App-Store-style (pick an app → set its URL);
//   health probes the stored URL, full CRUD from the dashboard.
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

    async init() { this.bindStoreForm(); await this.load(); },

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
        const open = p.url ? `<a href="${escapeHtml(p.url)}" target="_blank" rel="noopener" class="px-4 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-widest bg-slate-100 text-slate-600 hover:bg-slate-200 transition-all no-underline"><i class="fas fa-arrow-up-right-from-square mr-1"></i>Open</a>` : '';
        if (p.type === 'remote') {
            // remote instances live on their own host — no compose lifecycle here
            return `${open}
               ${this._btn('Edit', `Platforms.openEdit('${escapeHtml(p.name)}')`, 'bg-slate-100 text-slate-600 hover:bg-slate-200', 'fa-pen')}
               ${this._btn('Remove', `Platforms.remove('${escapeHtml(p.name)}')`, 'bg-slate-100 text-rose-500 hover:bg-rose-50', 'fa-trash-alt')}`;
        }
        const up = p.health === 'healthy' || p.health === 'unhealthy';
        return up
            ? `${open}
               ${this._btn('Restart', `Platforms.action('${escapeHtml(p.name)}','restart')`, 'bg-slate-100 text-slate-600 hover:bg-slate-200', 'fa-rotate')}
               ${this._btn('Stop', `Platforms.action('${escapeHtml(p.name)}','stop')`, 'bg-slate-100 text-rose-500 hover:bg-rose-50', 'fa-stop')}`
            : this._btn('Start', `Platforms.action('${escapeHtml(p.name)}','start')`, 'bg-blue-600 text-white hover:bg-blue-700', 'fa-play');
    },

    _endpoint(p) {
        if (p.type === 'remote') return p.url ? escapeHtml(p.url.replace(/^https?:\/\//, '')) : 'no URL';
        return `${p.port ? 'localhost:' + escapeHtml(p.port) : 'no public port'}${p.ref ? ' · ' + escapeHtml(p.ref) : ''}`;
    },

    _icon(p) {
        if (p.is_shared_db) return 'fa-database';
        return p.icon || (p.type === 'remote' ? 'fa-cloud' : 'fa-cube');
    },

    _typeTag(p) {
        return p.type === 'remote'
            ? ' <span class="text-[9px] text-sky-500 normal-case tracking-normal font-bold">(remote)</span>'
            : (p.is_shared_db ? ' <span class="text-[9px] text-slate-400 normal-case tracking-normal">(shared DB)</span>' : '');
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
                            <i class="fas ${this._icon(p)} text-lg"></i>
                        </div>
                        <div class="min-w-0">
                            <div class="text-sm font-black text-slate-900 uppercase tracking-wide truncate">${escapeHtml(p.name)}${this._typeTag(p)}</div>
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
                        <div class="w-8 h-8 rounded-lg bg-slate-50 border border-slate-100 flex items-center justify-center text-blue-600 shrink-0"><i class="fas ${this._icon(p)} text-xs"></i></div>
                        <span class="text-xs font-black text-slate-900 uppercase tracking-wide truncate">${escapeHtml(p.name)}${this._typeTag(p)}</span>
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

    // --- App-Store flow: pick an app → set its URL --------------------
    _editing: null,     // platform name when editing, null when adding
    _pickedApp: null,   // catalog app the new instance belongs to (icon identity)
    _catalog: [],

    async openStore() {
        this._editing = null;
        this._pickedApp = null;
        document.getElementById('plat-store-title').textContent = 'Add Platform';
        document.getElementById('plat-store-subtitle').textContent = 'Pick an app, then point it at your instance';
        this._showStep('shelf');
        document.getElementById('plat-store-modal').classList.remove('hidden');
        const grid = document.getElementById('plat-catalog-grid');
        grid.innerHTML = `<div class="col-span-full text-center text-slate-400 py-8 text-sm font-mono">Loading catalog…</div>`;
        try {
            this._catalog = (await API.fetch('/api/platforms/catalog')) || [];
        } catch (e) {
            grid.innerHTML = `<div class="col-span-full text-center text-rose-500 py-8 text-sm font-mono">Failed to load catalog: ${escapeHtml(e.message)}</div>`;
            return;
        }
        // Registered apps stay clickable — picking one registers ANOTHER
        // instance under a new name (e.g. a remote erp next to the local one).
        const card = (app) => `
            <button type="button" onclick="Platforms.pickApp('${escapeHtml(app.name)}')"
                class="text-left p-4 rounded-2xl border border-slate-100 bg-white hover:border-blue-300 hover:shadow-md transition-all">
                <div class="w-9 h-9 rounded-lg bg-blue-50 text-blue-600 flex items-center justify-center mb-3"><i class="fas ${escapeHtml(app.icon || 'fa-cube')}"></i></div>
                <div class="text-xs font-black text-slate-900 uppercase tracking-wide">${escapeHtml(app.name)}${app.registered ? ' <span class="text-[9px] text-emerald-500 normal-case tracking-normal">✓ installed</span>' : ''}</div>
                <div class="text-[10px] text-slate-400 mt-1 leading-snug">${escapeHtml(app.description || '')}</div>
            </button>`;
        grid.innerHTML = this._catalog.map(card).join('') + `
            <button type="button" onclick="Platforms.pickApp(null)"
                class="text-left p-4 rounded-2xl border border-dashed border-slate-200 bg-white/50 hover:border-blue-300 hover:shadow-md transition-all">
                <div class="w-9 h-9 rounded-lg bg-slate-100 text-slate-500 flex items-center justify-center mb-3"><i class="fas fa-plus"></i></div>
                <div class="text-xs font-black text-slate-900 uppercase tracking-wide">Custom</div>
                <div class="text-[10px] text-slate-400 mt-1 leading-snug">Any other platform — set your own name and URL.</div>
            </button>`;
    },

    // next free instance name for an app: "erp" → "erp-2" → "erp-3" …
    _suggestName(app) {
        const taken = new Set(this._all.map(p => p.name));
        if (!taken.has(app)) return app;
        let i = 2;
        while (taken.has(`${app}-${i}`)) i++;
        return `${app}-${i}`;
    },

    pickApp(name) {
        const app = name ? this._catalog.find(a => a.name === name) : null;
        this._pickedApp = app ? app.name : null;
        const extraInstance = !!(app && app.registered);
        this._fillForm({
            name: app ? this._suggestName(app.name) : '',
            nameEditable: !app || extraInstance,
            icon: app ? app.icon : 'fa-cube',
            description: app ? app.description : '',
            url: '', mcp_url: '',
        });
        if (extraInstance) {
            document.getElementById('plat-f-desc-label').textContent =
                `'${app.name}' already exists here — this registers another instance under a new name.`;
        }
        this._showStep('form');
    },

    openEdit(name) {
        const p = this._all.find(x => x.name === name);
        if (!p) return;
        this._editing = name;
        document.getElementById('plat-store-title').textContent = 'Edit Platform';
        document.getElementById('plat-store-subtitle').textContent = 'Update where this platform lives';
        this._fillForm({
            name: p.name, nameEditable: false, icon: this._icon(p),
            description: p.description || '', url: p.url || '', mcp_url: p.mcp_url || '',
        });
        this._showStep('form');
        document.getElementById('plat-store-back').textContent = 'CANCEL';
        document.getElementById('plat-store-modal').classList.remove('hidden');
    },

    _fillForm(f) {
        document.getElementById('plat-f-icon').className = `fas ${f.icon || 'fa-cube'} text-xl`;
        document.getElementById('plat-f-name-label').textContent = f.name || 'Custom platform';
        document.getElementById('plat-f-desc-label').textContent = f.description || '';
        document.getElementById('plat-f-name-row').classList.toggle('hidden', !f.nameEditable);
        document.getElementById('plat-f-name').value = f.name;
        document.getElementById('plat-f-url').value = f.url;
        document.getElementById('plat-f-mcp').value = f.mcp_url;
        document.getElementById('plat-f-desc').value = f.description;
    },

    _showStep(step) {
        document.getElementById('plat-store-shelf').classList.toggle('hidden', step !== 'shelf');
        document.getElementById('plat-store-form').classList.toggle('hidden', step !== 'form');
        document.getElementById('plat-store-back').textContent = 'BACK';
    },

    storeBack() {
        if (this._editing) return this.closeStore();
        this._showStep('shelf');
    },

    closeStore() {
        document.getElementById('plat-store-modal').classList.add('hidden');
        this._editing = null;
        this._pickedApp = null;
    },

    bindStoreForm() {
        const form = document.getElementById('plat-store-form');
        if (!form) return;
        form.onsubmit = async (e) => {
            e.preventDefault();
            const nameRowHidden = document.getElementById('plat-f-name-row').classList.contains('hidden');
            const name = this._editing
                || (nameRowHidden ? document.getElementById('plat-f-name-label').textContent
                                  : document.getElementById('plat-f-name').value).trim().toLowerCase();
            const body = {
                url: document.getElementById('plat-f-url').value.trim(),
                mcp_url: document.getElementById('plat-f-mcp').value.trim() || null,
                description: document.getElementById('plat-f-desc').value.trim() || null,
            };
            if (!body.url) return alert('Frontend URL is required.');
            try {
                if (this._editing) {
                    await API.fetch(`/api/platforms/${this._editing}`, { method: 'PUT', body: JSON.stringify(body) });
                } else {
                    if (!name) return alert('Name is required.');
                    await API.fetch('/api/platforms', { method: 'POST', body: JSON.stringify({ name, app: this._pickedApp, ...body }) });
                }
                this.closeStore();
                await this.load();
            } catch (err) { alert('Save failed: ' + err.message); }
        };
    },

    async remove(name) {
        if (!confirm(`Unregister platform '${name}'?\n(The remote instance itself is not touched.)`)) return;
        try {
            await API.fetch(`/api/platforms/${name}`, { method: 'DELETE' });
            await this.load();
        } catch (e) { alert('Remove failed: ' + e.message); }
    },
};
