const Diary = {
    _allEntries: [],
    _selectedDate: null,
    _byDate: {},

    _TYPE_COLOR: {
        daily:   { badge: 'bg-blue-50 text-blue-600 border-blue-100',   dot: 'bg-blue-500',   label: 'Daily' },
        weekly:  { badge: 'bg-purple-50 text-purple-600 border-purple-100', dot: 'bg-purple-500', label: 'Weekly' },
        monthly: { badge: 'bg-green-50 text-green-600 border-green-100',  dot: 'bg-green-500',  label: 'Monthly' },
    },

    async init() {
        await this.load();
    },

    async load() {
        const filter = document.getElementById('diary-days-filter');
        const days = filter ? parseInt(filter.value) : 7;
        const list = document.getElementById('diary-date-list');
        if (list) list.innerHTML = `<div class="flex items-center justify-center h-20 text-slate-300 text-[10px] font-bold uppercase tracking-widest">Loading...</div>`;
        try {
            const entries = await API.fetch(`/api/diary?days=${days}`);
            this._allEntries = Array.isArray(entries) ? entries : [];
            this._buildByDate();
            this._renderDateList();
            const dates = Object.keys(this._byDate);
            if (dates.length > 0 && !this._selectedDate) {
                this.selectDate(dates[0]);
            } else if (this._selectedDate && this._byDate[this._selectedDate]) {
                this._renderDetail(this._selectedDate);
            }
        } catch {
            if (list) list.innerHTML = `<div class="flex items-center justify-center h-20 text-red-400 text-[10px] font-bold uppercase tracking-widest">載入失敗</div>`;
        }
    },

    _buildByDate() {
        this._byDate = {};
        this._allEntries.forEach(e => {
            const d = e.date || (e.created_at ? e.created_at.split('T')[0] : '—');
            if (!this._byDate[d]) this._byDate[d] = [];
            this._byDate[d].push(e);
        });
    },

    _renderDateList() {
        const list = document.getElementById('diary-date-list');
        const countEl = document.getElementById('diary-entry-count');
        if (!list) return;

        const dates = Object.keys(this._byDate);
        if (countEl) countEl.textContent = `${this._allEntries.length} entr${this._allEntries.length !== 1 ? 'ies' : 'y'}`;

        if (dates.length === 0) {
            list.innerHTML = `<div class="flex flex-col items-center justify-center h-40 text-slate-300 gap-3">
                <i class="fas fa-book text-3xl"></i>
                <span class="text-[10px] font-bold uppercase tracking-widest">尚無日記記錄</span>
            </div>`;
            return;
        }

        list.innerHTML = dates.map(date => {
            const items = this._byDate[date];
            const types = [...new Set(items.map(e => e.type).filter(Boolean))];
            const agents = [...new Set(items.map(e => e.agent_name).filter(Boolean))];
            const isActive = this._selectedDate === date;
            return `<div onclick="Diary.selectDate('${escapeHtml(date)}')"
                class="p-5 cursor-pointer hover:bg-slate-50 transition-all ${isActive ? 'bg-blue-50 border-l-4 border-l-blue-600' : ''}">
                <div class="flex items-center justify-between mb-2">
                    <span class="text-sm font-headline font-bold tracking-tight ${isActive ? 'text-blue-700' : 'text-slate-900'}">${escapeHtml(date)}</span>
                    <span class="text-[10px] font-bold text-slate-400">${items.length} ${items.length !== 1 ? 'entries' : 'entry'}</span>
                </div>
                <div class="flex items-center gap-1.5 flex-wrap">
                    ${types.map(t => {
                        const c = this._TYPE_COLOR[t] || { badge: 'bg-slate-100 text-slate-500 border-slate-100', label: t };
                        return `<span class="text-[9px] font-black uppercase px-1.5 py-0.5 rounded border ${c.badge}">${escapeHtml(c.label)}</span>`;
                    }).join('')}
                    <span class="text-[9px] text-slate-400 truncate max-w-[120px]">${escapeHtml(agents.join(', '))}</span>
                </div>
            </div>`;
        }).join('');
    },

    selectDate(date) {
        this._selectedDate = date;
        this._renderDateList();
        this._renderDetail(date);
    },

    _renderDetail(date) {
        const placeholder = document.getElementById('diary-placeholder');
        const detail = document.getElementById('diary-detail');
        const dateEl = document.getElementById('diary-detail-date');
        const metaEl = document.getElementById('diary-detail-meta');
        const cardsEl = document.getElementById('diary-detail-cards');
        if (!detail) return;

        if (placeholder) placeholder.classList.add('hidden');
        detail.classList.remove('hidden');
        detail.classList.add('flex');

        const items = this._byDate[date] || [];
        const agents = [...new Set(items.map(e => e.agent_name).filter(Boolean))];
        if (dateEl) dateEl.textContent = date;
        if (metaEl) metaEl.textContent = `${items.length} entr${items.length !== 1 ? 'ies' : 'y'} · ${agents.join(', ')}`;
        if (!cardsEl) return;

        cardsEl.innerHTML = `<div class="grid grid-cols-1 xl:grid-cols-2 gap-5">
            ${items.map(e => {
                const c = this._TYPE_COLOR[e.type] || { badge: 'bg-slate-100 text-slate-500 border-slate-100', label: e.type || 'note' };
                return `<div class="bg-white border border-slate-100 rounded-2xl overflow-hidden shadow-sm hover:shadow-md transition-all">
                    <div class="px-5 py-4 border-b border-slate-100 bg-slate-50/50 flex items-center gap-3">
                        <div class="w-8 h-8 rounded-lg bg-purple-600/10 text-purple-500 flex items-center justify-center shrink-0">
                            <i class="fas fa-robot text-xs"></i>
                        </div>
                        <p class="text-sm font-headline font-bold text-slate-900 uppercase tracking-tight flex-1 truncate">${escapeHtml(e.agent_name || '—')}</p>
                        <span class="text-[9px] font-black uppercase px-2 py-0.5 rounded-full border shrink-0 ${c.badge}">${escapeHtml(c.label)}</span>
                    </div>
                    <div class="p-5 space-y-4">
                        ${e.done ? `<div>
                            <div class="flex items-center gap-1.5 mb-1.5">
                                <i class="fas fa-check-circle text-emerald-500 text-[10px]"></i>
                                <span class="text-[9px] font-black text-slate-400 uppercase tracking-widest">完成事項</span>
                            </div>
                            <p class="text-sm text-slate-700 leading-relaxed whitespace-pre-wrap">${escapeHtml(e.done)}</p>
                        </div>` : ''}
                        ${e.next ? `<div>
                            <div class="flex items-center gap-1.5 mb-1.5">
                                <i class="fas fa-arrow-right text-blue-500 text-[10px]"></i>
                                <span class="text-[9px] font-black text-slate-400 uppercase tracking-widest">下一步</span>
                            </div>
                            <p class="text-sm text-slate-500 leading-relaxed whitespace-pre-wrap">${escapeHtml(e.next)}</p>
                        </div>` : ''}
                        ${e.blocker ? `<div>
                            <div class="flex items-center gap-1.5 mb-1.5">
                                <i class="fas fa-exclamation-triangle text-red-400 text-[10px]"></i>
                                <span class="text-[9px] font-black text-red-400 uppercase tracking-widest">阻礙</span>
                            </div>
                            <p class="text-sm text-red-600 leading-relaxed whitespace-pre-wrap">${escapeHtml(e.blocker)}</p>
                        </div>` : ''}
                    </div>
                </div>`;
            }).join('')}
        </div>`;
    },
};
