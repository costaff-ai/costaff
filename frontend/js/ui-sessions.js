Object.assign(UI, {
    drawTable(hId, bId, schemaType, data) {
        const head = document.getElementById(hId);
        const body = document.getElementById(bId);
        if (!data || data.length === 0) {
            if (body) body.innerHTML = '<tr><td colspan="6" class="text-center py-20 text-slate-500 font-headline uppercase tracking-widest opacity-30 italic">No records found</td></tr>';
            return;
        }
        const s = Config.TABLE_SCHEMAS[schemaType];
        const deletableTables = ['reminders', 'identities', 'user_states'];
        if (head) head.innerHTML = `<tr class="bg-slate-50 uppercase tracking-widest text-[9px] font-bold text-primary/60">${s.cols.map(c => `<th class="px-6 py-4 text-left font-headline">${c}</th>`).join('')}${deletableTables.includes(schemaType)?'<th class="px-6 py-4"></th>':''}</tr>`;

        if (body) body.innerHTML = data.map(r => {
            let isToolOnlyRow = false;
            if (schemaType === 'events' && r.content) {
                try {
                    const parts = JSON.parse(r.content);
                    isToolOnlyRow = parts.length > 0 && parts.every(p => p.type === 'call' || p.type === 'result');
                } catch {}
            }
            const toolClass = isToolOnlyRow ? ' event-tool-row' : '';
            const toolStyle = (isToolOnlyRow && !this._showToolEvents) ? 'display:none;' : '';
            return `
            <tr class="group hover:bg-slate-50 transition-all border-b border-slate-100 last:border-none${toolClass}" style="${toolStyle}">
                ${s.keys.map(k => {
                    let val = r[k] || '-';
                    let valIsHtml = false; // set true when we intentionally build trusted markup for `val`
                    if (schemaType === 'reminders' && k === 'run_at' && r.cron) {
                        val = `<span class="font-mono text-blue-600 font-bold">${escapeHtml(r.cron)}</span>`;
                        valIsHtml = true;
                    }
                    if (schemaType === 'reminders' && k === 'channel' && r.channel === 'command') {
                        val = `<span class="bg-slate-900 text-white px-2 py-0.5 rounded text-[9px] font-black tracking-tighter uppercase">Shell_Exec</span>`;
                        valIsHtml = true;
                    }

                    if (k === 'status' || k === 'state') {
                        let displayVal = escapeHtml(val.toString().toUpperCase());
                        const isCron = schemaType === 'reminders' && r.cron;

                        if (k === 'state' && typeof val === 'object' && val !== null) {
                            const keys = Object.keys(val);
                            const preview = keys.slice(0, 3).join(', ') + (keys.length > 3 ? ` … +${keys.length - 3}` : '');
                            const escaped = JSON.stringify(val).replace(/'/g, '&#39;').replace(/"/g, '&quot;');
                            displayVal = `<span class="text-[10px] font-mono text-slate-500 mr-1">{${escapeHtml(preview)}}</span><button onclick="UI.showStateModal('${escaped}')" class="text-[9px] font-bold text-blue-500 hover:text-blue-700 border border-blue-200 rounded px-1.5 py-0.5 hover:bg-blue-50 transition-colors">View</button>`;
                        } else if (k === 'state' && typeof val === 'string' && val.startsWith('{')) {
                            try {
                                const parsed = JSON.parse(val);
                                const keys = Object.keys(parsed);
                                const preview = keys.slice(0, 3).join(', ') + (keys.length > 3 ? ` … +${keys.length - 3}` : '');
                                const escaped = val.replace(/'/g, '&#39;').replace(/"/g, '&quot;');
                                displayVal = `<span class="text-[10px] font-mono text-slate-500 mr-1">{${escapeHtml(preview)}}</span><button onclick="UI.showStateModal('${escaped}')" class="text-[9px] font-bold text-blue-500 hover:text-blue-700 border border-blue-200 rounded px-1.5 py-0.5 hover:bg-blue-50 transition-colors">View</button>`;
                            } catch {
                                const escaped = val.replace(/'/g, '&#39;').replace(/"/g, '&quot;');
                                displayVal = `<button onclick="UI.showStateModal('${escaped}')" class="text-[9px] font-bold text-blue-500 hover:text-blue-700 border border-blue-200 rounded px-1.5 py-0.5 hover:bg-blue-50 transition-colors">View</button>`;
                            }
                        }

                        if (isCron) {
                            if (val === 'pending' || val === 'scheduled') displayVal = 'SCHEDULED';
                            if (val === 'active') displayVal = 'RUNNING';
                        }

                        const valLower = val.toString().toLowerCase();
                        const active = valLower.includes('up') || valLower.includes('success') || valLower.includes('online') || ['pending', 'scheduled', 'active'].includes(valLower);
                        const isError = valLower.includes('exit') || valLower.includes('error') || valLower.includes('fail');
                        const badgeClass = isError ? 'badge-error' : active ? 'badge-active' : 'badge-idle';

                        return `<td class="px-6 py-5">
                            <span class="status-badge ${badgeClass}">
                                <span class="badge-dot"></span>
                                ${displayVal}
                            </span>
                        </td>`;
                    }
                    if (schemaType === 'events' && k === 'content') {
                        try {
                            const parts = JSON.parse(val);
                            // Escape everything, then re-allow ONLY bare whitelist tags
                            // (no attributes) — so `<span onmouseover=...>` stays escaped.
                            const _safe = (s) => s
                                .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
                                .replace(/&lt;(\/?(?:b|i|u|s|code|br|span))&gt;/gi, '<$1>');
                            const _truncate = (text, limit=400) => {
                                if (text.length <= limit) return `<span>${_safe(text)}</span>`;
                                const uid = 'ev' + Math.random().toString(36).slice(2,8);
                                return `<span id="${uid}-short">${_safe(text.slice(0, limit))}<span class="text-slate-400">…</span>
                                    <button onclick="document.getElementById('${uid}-short').style.display='none';document.getElementById('${uid}-full').style.display=''" class="ml-1 text-[9px] font-bold text-blue-500 hover:text-blue-700">more</button></span>
                                    <span id="${uid}-full" style="display:none">${_safe(text)}
                                    <button onclick="document.getElementById('${uid}-full').style.display='none';document.getElementById('${uid}-short').style.display=''" class="ml-1 text-[9px] font-bold text-slate-400 hover:text-slate-600">less</button></span>`;
                            };
                            const html = parts.map(p => {
                                if (p.type === 'text') {
                                    return `<div class="text-sm text-slate-700 whitespace-pre-wrap leading-relaxed">${_truncate(p.text)}</div>`;
                                }
                                if (p.type === 'call') {
                                    const args = JSON.stringify(p.args, null, 2);
                                    return `<div class="text-xs mt-1 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2">
                                        <span class="font-black text-amber-600 text-[10px] uppercase tracking-wide">🔧 ${escapeHtml(p.name)}</span>
                                        <pre class="text-slate-500 text-[10px] mt-1 whitespace-pre-wrap leading-relaxed">${_truncate(args, 300)}</pre>
                                    </div>`;
                                }
                                if (p.type === 'result') {
                                    const data = typeof p.data === 'string' ? p.data : JSON.stringify(p.data, null, 2);
                                    return `<div class="text-xs mt-1 bg-emerald-50 border border-emerald-100 rounded-lg px-3 py-2">
                                        <span class="font-black text-emerald-600 text-[10px] uppercase tracking-wide">✅ ${escapeHtml(p.name)}</span>
                                        <pre class="text-slate-500 text-[10px] mt-1 whitespace-pre-wrap leading-relaxed">${_truncate(data, 300)}</pre>
                                    </div>`;
                                }
                                return '';
                            }).join('<div class="border-t border-slate-100 my-2"></div>');
                            return `<td class="px-6 py-5 max-w-sm">${html || '<span class="text-slate-300 text-xs italic">—</span>'}</td>`;
                        } catch(e) {}
                    }
                    return `<td class="px-6 py-5 text-sm font-medium text-slate-900">${valIsHtml ? val : escapeHtml(val)}</td>`;
                }).join('')}
                ${schemaType==='reminders' ? `<td class="px-6 py-5 text-right flex justify-end gap-2">
                    <button data-cron-id="${escapeHtml(r.id)}" data-cron-channel="${escapeHtml(r.channel)}" data-cron-recipient="${escapeHtml(r.recipient)}" data-cron-full="${escapeHtml(((r.cron || '') + ' ' + (r.prompt || '')).trim())}" onclick="UI.openEditCronModal(this.dataset.cronId, this.dataset.cronChannel, this.dataset.cronRecipient, this.dataset.cronFull)" class="p-2 text-slate-400 hover:text-blue-600 transition-all"><i class="fas fa-edit text-xs"></i></button>
                    <button onclick="UI.deleteReminder('${escapeHtml(r.id)}')" class="p-2 text-slate-400 hover:text-rose-500 transition-all"><i class="fas fa-trash-alt text-xs"></i></button>
                </td>` : ''}
                ${schemaType==='identities' ? `<td class="px-6 py-5"><button onclick="UI.deleteIdentity('${escapeHtml(r.session_id)}')" class="p-2 text-slate-400 hover:text-rose-500 transition-all"><i class="fas fa-trash-alt text-xs"></i></button></td>` : ''}
                ${schemaType==='user_states' ? `<td class="px-6 py-5"><button onclick="UI.deleteUserState('${escapeHtml(r.app_name)}','${escapeHtml(r.user_id)}')" class="p-2 text-slate-400 hover:text-rose-500 transition-all"><i class="fas fa-trash-alt text-xs"></i></button></td>` : ''}
            </tr>`;
        }).join('');
    },

    toggleToolEvents() {
        this._showToolEvents = !this._showToolEvents;
        const btn = document.getElementById('btn-toggle-tools');
        const label = document.getElementById('btn-toggle-tools-label');
        if (this._showToolEvents) {
            if (btn) btn.className = btn.className.replace('border-slate-200 bg-white text-slate-400 hover:border-amber-300 hover:text-amber-600', 'border-amber-400 bg-amber-50 text-amber-600');
            if (label) label.textContent = 'Tool Calls: ON';
        } else {
            if (btn) btn.className = btn.className.replace('border-amber-400 bg-amber-50 text-amber-600', 'border-slate-200 bg-white text-slate-400 hover:border-amber-300 hover:text-amber-600');
            if (label) label.textContent = 'Tool Calls: OFF';
        }
        this._applyEventFilters();
    },

    filterDBTable() {
        this._applyEventFilters();
    },

    _applyEventFilters() {
        const query = (document.getElementById('db-filter-input')?.value || '').toLowerCase();
        const rows = document.querySelectorAll('#sessions-tbody tr');
        rows.forEach(row => {
            const isToolRow = row.classList.contains('event-tool-row');
            const textMatch = !query || row.innerText.toLowerCase().includes(query);
            const toolVisible = !isToolRow || this._showToolEvents;
            row.style.display = (textMatch && toolVisible) ? '' : 'none';
        });
    },
});
