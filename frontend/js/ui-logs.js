Object.assign(UI, {
    updateLogServices(svcs) {
        const sel = document.getElementById('log-service-select'); if (!sel) return;
        const cur = sel.value;
        // Match Runtime Monitor (renderDashboard): only show CoStaff-managed
        // containers, sorted alphabetically. The /api/status endpoint also
        // returns unrelated containers (e.g. ai-rap-*, gpt-vis), which the
        // log monitor doesn't need to drop down.
        const filtered = [...svcs]
            .filter(s => s.name.toLowerCase().startsWith('costaff-'))
            .sort((a, b) => a.name.localeCompare(b.name));
        sel.innerHTML = `<option value="">-- SELECT NODE --</option>`
            + filtered.map(s => `<option value="${escapeHtml(s.name)}" ${s.name===cur?'selected':''}>${escapeHtml(s.name.toUpperCase())}</option>`).join('');
    },

    async renderLogs() {
        const select = document.getElementById('log-service-select'); if (!select || !select.value) return;
        const res = await API.fetch(`/api/logs/${select.value}`); const output = res.logs || 'NO_DATA_STREAM';
        if (output === this.lastLogs) return; this.lastLogs = output;
        const box = document.getElementById('log-output'); const filter = document.getElementById('log-filter').value.toLowerCase();
        box.innerHTML = output.split('\n').map(line => {
            if (filter && !line.toLowerCase().includes(filter)) return '';
            if (!line.trim()) return '';
            let color = 'text-slate-400';
            if (line.includes('ERROR') || line.includes('FAIL') || line.includes('CRITICAL')) color = 'text-rose-400 font-bold';
            else if (line.includes('INFO')) color = 'text-cyan-400';
            else if (line.includes('WARN')) color = 'text-amber-400';
            else if (line.includes('SUCCESS')) color = 'text-emerald-400 font-bold';
            const lineContent = line.replace(/\[\d+m/g, '');
            return `<div class="${color} mb-1 flex gap-4"><span class="text-slate-600 shrink-0 select-none">[${new Date().toLocaleTimeString([], {hour12:false})}]</span><span class="break-all">${escapeHtml(lineContent)}</span></div>`;
        }).join('');
        if (document.getElementById('log-autoscroll').checked) box.scrollTop = box.scrollHeight;
    },

    filterLogs() { this.renderLogs(); },

    downloadLogs() {
        const box = document.getElementById('log-output'); if (!box) return;
        const text = box.innerText; if (!text || text.includes('Initialize neural')) return alert('NO_DATA');
        const blob = new Blob([text], { type: 'text/plain' });
        const url = URL.createObjectURL(blob); const a = document.createElement('a');
        const source = document.getElementById('log-service-select').value || 'system';
        a.href = url; a.download = `costaff_logs_${source}_${new Date().toISOString().slice(0,19).replace(/:/g,'-')}.log`;
        document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url);
    },
});
