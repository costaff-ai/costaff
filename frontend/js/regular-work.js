// ============================================================
// Regular Work Module
// ============================================================
const RegularWork = {
    items: [],
    editingId: null,

    async init() {
        this.bindForm();
        await this.load();
        setInterval(() => {
            const el = document.getElementById('view-cronjobs');
            if (el && !el.classList.contains('hidden')) this.load();
        }, 15000);
    },

    bindForm() {
        const form = document.getElementById('rw-form');
        if (!form) return;
        form.onsubmit = async (e) => {
            e.preventDefault();
            const data = {
                title: document.getElementById('rw-f-title').value.trim(),
                spec: document.getElementById('rw-f-spec').value.trim(),
                cron: document.getElementById('rw-f-cron').value.trim(),
                agent_id: document.getElementById('rw-f-agent').value.trim() || 'costaff_agent',
                channel: document.getElementById('rw-f-channel').value || null,
                recipient: document.getElementById('rw-f-recipient').value.trim() || null,
            };
            if (!data.title || !data.spec || !data.cron) return alert('Title, Spec, and Cron are required.');
            try {
                if (this.editingId) {
                    await API.fetch(`/api/regular-works/${this.editingId}`, { method: 'PUT', body: JSON.stringify(data) });
                } else {
                    await API.fetch('/api/regular-works', { method: 'POST', body: JSON.stringify(data) });
                }
                this.closeModal();
                await this.load();
            } catch (err) { alert('Save failed: ' + err.message); }
        };
    },

    async load() {
        try {
            const works = await API.fetch('/api/regular-works');
            this.items = Array.isArray(works) ? works : [];
            this.render();
        } catch (err) { console.error('Failed to load regular works:', err); }
    },

    render() {
        const list = document.getElementById('rw-list');
        const badge = document.getElementById('rw-count-badge');
        const nextTime = document.getElementById('rw-next-time');
        const nextTitle = document.getElementById('rw-next-title');
        if (!list) return;

        const active = this.items.filter(w => w.status === 'active');
        if (badge) badge.textContent = `${active.length} JOBS`;

        if (this.items.length === 0) {
            list.innerHTML = `<div class="flex items-center justify-center h-40 text-slate-300 text-xs font-bold uppercase tracking-widest">No regular work configured</div>`;
            if (nextTime) nextTime.textContent = 'NO JOBS';
            if (nextTitle) nextTitle.textContent = 'No active schedules.';
            return;
        }

        if (active.length > 0 && nextTime) {
            nextTime.textContent = active[0].cron;
            if (nextTitle) nextTitle.textContent = active[0].title;
        }

        list.innerHTML = this.items.map(w => {
            const isPaused = w.status === 'paused';
            const agentBadge = w.agent_id ? `<span class="bg-purple-50 text-purple-600 px-2 py-0.5 rounded-full text-[9px] font-bold">${w.agent_id}</span>` : '';
            const channelBadge = w.channel ? `<span class="bg-green-50 text-green-600 px-2 py-0.5 rounded-full text-[9px] font-bold">${w.channel.toUpperCase()}</span>` : '';
            return `<div class="px-6 py-5 flex items-center gap-4 hover:bg-slate-50/50 transition-all group cursor-pointer" onclick="RegularWork.openDetail('${w.id}')">
                <div class="w-10 h-10 rounded-xl ${isPaused ? 'bg-slate-100' : 'bg-blue-50'} flex items-center justify-center shrink-0">
                    <i class="fas fa-sync-alt text-sm ${isPaused ? 'text-slate-400' : 'text-blue-500'}"></i>
                </div>
                <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2 mb-1">
                        <span class="font-bold text-slate-900 text-sm truncate">${w.title}</span>
                        ${isPaused ? '<span class="bg-amber-100 text-amber-600 px-2 py-0.5 rounded-full text-[9px] font-black uppercase">PAUSED</span>' : ''}
                    </div>
                    <div class="flex items-center gap-2 flex-wrap">
                        <span class="font-mono text-[10px] text-blue-600 bg-blue-50 px-2 py-0.5 rounded font-bold">${w.cron}</span>
                        ${agentBadge}${channelBadge}
                        ${w.last_run ? `<span class="text-[10px] text-slate-400">Last: ${new Date(w.last_run).toLocaleString()}</span>` : ''}
                    </div>
                </div>
                <div class="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button onclick="event.stopPropagation();RegularWork.toggleWork('${w.id}')" title="${isPaused ? 'Resume' : 'Pause'}" class="w-8 h-8 rounded-full ${isPaused ? 'bg-green-100 text-green-600' : 'bg-amber-100 text-amber-600'} flex items-center justify-center hover:scale-110 transition-all">
                        <i class="fas fa-${isPaused ? 'play' : 'pause'} text-[10px]"></i>
                    </button>
                    <button onclick="event.stopPropagation();RegularWork.editWork('${w.id}')" class="w-8 h-8 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center hover:scale-110 transition-all">
                        <i class="fas fa-edit text-[10px]"></i>
                    </button>
                    <button onclick="event.stopPropagation();RegularWork.deleteWork('${w.id}')" class="w-8 h-8 rounded-full bg-red-100 text-red-600 flex items-center justify-center hover:scale-110 transition-all">
                        <i class="fas fa-trash-alt text-[10px]"></i>
                    </button>
                </div>
            </div>`;
        }).join('');
    },

    async openDetail(id) {
        const w = this.items.find(x => x.id === id);
        if (!w) return;
        document.getElementById('rw-detail-title').textContent = w.title;
        document.getElementById('rw-detail-id').textContent = `ID: ${w.id}`;
        document.getElementById('rw-detail-spec').textContent = w.spec;
        document.getElementById('rw-detail-cron').textContent = w.cron;
        document.getElementById('rw-detail-agent').textContent = w.agent_id || '—';
        document.getElementById('rw-detail-channel').textContent = w.channel ? `${w.channel.toUpperCase()} → ${w.recipient || '?'}` : 'No callback';
        document.getElementById('rw-detail-modal').classList.remove('hidden');
        document.getElementById('rw-detail-logs').innerHTML = '<div class="text-center py-8 text-slate-300 text-xs font-bold">Loading...</div>';
        try {
            const logs = await API.fetch(`/api/regular-works/${id}/logs`);
            this.renderLogs(logs);
        } catch (err) {
            document.getElementById('rw-detail-logs').innerHTML = '<p class="text-center text-red-400 text-xs py-4">Failed to load</p>';
        }
    },

    renderLogs(logs) {
        const el = document.getElementById('rw-detail-logs');
        if (!logs || logs.length === 0) {
            el.innerHTML = '<div class="text-center py-8 bg-slate-50 rounded-xl text-slate-400 text-xs font-bold">NO HISTORY</div>';
            return;
        }
        el.innerHTML = logs.map(log => `
            <div class="bg-white border border-slate-100 rounded-xl p-4 shadow-sm">
                <div class="flex justify-between items-center mb-2">
                    <span class="text-[10px] font-black ${log.status === 'success' ? 'text-green-500' : 'text-red-500'} uppercase tracking-widest">${log.status}</span>
                    <span class="text-[10px] text-slate-400 font-bold">${new Date(log.created_at).toLocaleString()}</span>
                </div>
                <div class="bg-slate-50 p-3 rounded-lg text-[11px] text-slate-600 font-mono whitespace-pre-wrap leading-relaxed max-h-32 overflow-y-auto">${log.output || '(No Output)'}</div>
            </div>`).join('');
    },

    closeDetail() { document.getElementById('rw-detail-modal').classList.add('hidden'); },

    openModal() {
        this.editingId = null;
        document.getElementById('rw-modal-title').textContent = 'Add Regular Work';
        document.getElementById('rw-edit-id').value = '';
        document.getElementById('rw-form').reset();
        document.getElementById('rw-modal').classList.remove('hidden');
    },

    editWork(id) {
        const w = this.items.find(x => x.id === id);
        if (!w) return;
        this.editingId = id;
        document.getElementById('rw-modal-title').textContent = 'Edit Regular Work';
        document.getElementById('rw-edit-id').value = id;
        document.getElementById('rw-f-title').value = w.title;
        document.getElementById('rw-f-spec').value = w.spec;
        document.getElementById('rw-f-cron').value = w.cron;
        document.getElementById('rw-f-agent').value = w.agent_id || '';
        document.getElementById('rw-f-channel').value = w.channel || '';
        document.getElementById('rw-f-recipient').value = w.recipient || '';
        document.getElementById('rw-modal').classList.remove('hidden');
    },

    closeModal() {
        document.getElementById('rw-modal').classList.add('hidden');
        document.getElementById('rw-form').reset();
        this.editingId = null;
    },

    async toggleWork(id) {
        try {
            await API.fetch(`/api/regular-works/${id}/toggle`, { method: 'POST' });
            await this.load();
        } catch (err) { alert('Failed to toggle: ' + err.message); }
    },

    async deleteWork(id) {
        if (!confirm('Delete this Regular Work?')) return;
        try {
            await API.fetch(`/api/regular-works/${id}`, { method: 'DELETE' });
            await this.load();
        } catch (err) { alert('Delete failed: ' + err.message); }
    },
};
