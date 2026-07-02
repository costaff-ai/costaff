// Platforms — read-only ops view for business platforms (ERP/CRM/HRM/…).
// Lists registered platforms in dependency order with frontend health, and
// allows start / restart / stop per platform. Deploy/rebuild/remove stay CLI-only.
const Platforms = {
    HEALTH: {
        healthy:   { dot: 'bg-emerald-500', label: 'Healthy' },
        unhealthy: { dot: 'bg-amber-500',   label: 'Starting' },
        down:      { dot: 'bg-rose-500',    label: 'Down' },
        'n/a':     { dot: 'bg-slate-300',   label: 'Disabled' },
    },

    async init() { await this.load(); },

    async load() {
        const el = document.getElementById('platforms-list');
        if (!el) return;
        el.innerHTML = `<div class="col-span-full text-center text-slate-400 py-12 text-sm font-mono">Loading platforms…</div>`;
        try {
            const list = await API.fetch('/api/platforms');
            this.render(list);
        } catch (e) {
            el.innerHTML = `<div class="col-span-full text-center text-rose-500 py-12 text-sm font-mono">Failed to load: ${escapeHtml(e.message)}</div>`;
        }
    },

    _btn(label, onclick, cls, icon) {
        return `<button onclick="${onclick}" class="px-4 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-widest transition-all ${cls}">${icon ? `<i class="fas ${icon} mr-1"></i>` : ''}${label}</button>`;
    },

    render(list) {
        const el = document.getElementById('platforms-list');
        if (!el) return;
        if (!list || !list.length) {
            el.innerHTML = `<div class="col-span-full text-center text-slate-400 py-12 text-sm font-mono">No platforms registered. Add one with <code>costaff platform add &lt;name&gt;</code>.</div>`;
            return;
        }
        el.innerHTML = list.map(p => {
            const h = this.HEALTH[p.health] || this.HEALTH['n/a'];
            const up = p.health === 'healthy' || p.health === 'unhealthy';
            const actions = up
                ? `${p.url ? `<a href="${escapeHtml(p.url)}" target="_blank" rel="noopener" class="px-4 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-widest bg-slate-100 text-slate-600 hover:bg-slate-200 transition-all no-underline"><i class="fas fa-arrow-up-right-from-square mr-1"></i>Open</a>` : ''}
                   ${this._btn('Restart', `Platforms.action('${escapeHtml(p.name)}','restart')`, 'bg-slate-100 text-slate-600 hover:bg-slate-200', 'fa-rotate')}
                   ${this._btn('Stop', `Platforms.action('${escapeHtml(p.name)}','stop')`, 'bg-slate-100 text-rose-500 hover:bg-rose-50', 'fa-stop')}`
                : this._btn('Start', `Platforms.action('${escapeHtml(p.name)}','start')`, 'bg-blue-600 text-white hover:bg-blue-700', 'fa-play');
            return `<div class="rounded-2xl border border-slate-100 bg-white p-5 hover:shadow-md transition-all">
                <div class="flex items-start justify-between mb-4">
                    <div class="flex items-center gap-3 min-w-0">
                        <div class="w-11 h-11 rounded-xl bg-slate-50 border border-slate-100 flex items-center justify-center text-blue-600 shrink-0">
                            <i class="fas ${p.is_shared_db ? 'fa-database' : 'fa-cube'} text-lg"></i>
                        </div>
                        <div class="min-w-0">
                            <div class="text-sm font-black text-slate-900 uppercase tracking-wide truncate">${escapeHtml(p.name)}${p.is_shared_db ? ' <span class="text-[9px] text-slate-400 normal-case tracking-normal">(shared DB)</span>' : ''}</div>
                            <div class="text-[10px] font-mono text-slate-400 mt-0.5 truncate">${p.port ? 'localhost:' + escapeHtml(p.port) : 'no public port'}${p.ref ? ' · ' + escapeHtml(p.ref) : ''}</div>
                        </div>
                    </div>
                    <span class="flex items-center gap-1.5 text-[10px] font-black uppercase tracking-widest text-slate-500 shrink-0"><span class="w-2 h-2 rounded-full ${h.dot}"></span>${h.label}</span>
                </div>
                <div class="flex items-center gap-2 flex-wrap">${actions}</div>
            </div>`;
        }).join('');
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
