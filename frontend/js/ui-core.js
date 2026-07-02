const UI = {
    lastLogs: "",
    chatState: { app: null, session: null, user: 'admin-user' },
    _requireApproval: true,
    _approvalIsOss: false,
    _usersProfiles: [],
    _activeIdentityId: null,
    _showToolEvents: false,
    _coreMCPs: ['costaff', 'coding'],
    editingCronId: null,

    // --- Approval Toggle ---
    async initApprovalToggle() {
        try {
            const [conf, lic] = await Promise.all([
                API.fetch('/api/config'),
                API.fetch('/api/license'),
            ]);
            this._approvalIsOss = !lic || lic.plan === 'oss' || lic.plan === 'invalid';
            this._requireApproval = !this._approvalIsOss && conf.require_approval !== false;
        } catch(e) {
            this._approvalIsOss = true;
            this._requireApproval = false;
        }
        this._renderApprovalToggle();
    },
    _renderApprovalToggle() {
        const btn = document.getElementById('approval-toggle-btn');
        const knob = document.getElementById('approval-toggle-knob');
        const text = document.getElementById('approval-status-text');
        if (!btn) return;
        if (this._approvalIsOss) {
            btn.className = "relative inline-flex h-7 w-14 items-center rounded-full transition-colors focus:outline-none bg-slate-200 cursor-not-allowed";
            knob.className = "inline-block h-5 w-5 transform rounded-full bg-white shadow-md transition-transform translate-x-1";
            text.innerHTML = `All users chat without approval &nbsp;<span class="px-1.5 py-0.5 rounded text-[10px] font-black bg-blue-100 text-blue-600 uppercase">Enterprise</span>`;
            btn.onclick = null;
        } else if (this._requireApproval) {
            btn.className = "relative inline-flex h-7 w-14 items-center rounded-full transition-colors focus:outline-none bg-amber-500 cursor-pointer";
            knob.className = "inline-block h-5 w-5 transform rounded-full bg-white shadow-md transition-transform translate-x-8";
            text.textContent = "New users must be approved by admin before chatting";
            btn.onclick = () => UI.toggleRequireApproval();
        } else {
            btn.className = "relative inline-flex h-7 w-14 items-center rounded-full transition-colors focus:outline-none bg-slate-300 cursor-pointer";
            knob.className = "inline-block h-5 w-5 transform rounded-full bg-white shadow-md transition-transform translate-x-1";
            text.textContent = "All users can chat without approval";
            btn.onclick = () => UI.toggleRequireApproval();
        }
    },
    async toggleRequireApproval() {
        if (this._approvalIsOss) return;
        this._requireApproval = !this._requireApproval;
        this._renderApprovalToggle();
        try {
            await API.fetch('/api/config/require-approval', {
                method: 'POST',
                body: JSON.stringify({ enabled: this._requireApproval })
            });
        } catch(e) {
            this._requireApproval = !this._requireApproval;
            this._renderApprovalToggle();
        }
    },

    // --- Theme Management ---
    loadTheme() {
        const theme = localStorage.getItem('costaff_theme') || 'light';
        this.toggleTheme(theme);
    },
    toggleTheme(mode) {
        if (mode === 'light') {
            document.body.classList.add('light-mode');
            localStorage.setItem('costaff_theme', 'light');
        } else {
            document.body.classList.remove('light-mode');
            localStorage.setItem('costaff_theme', 'dark');
        }
        this.updateThemeUI(mode);
    },
    updateThemeUI(mode) {
        const darkBtn = document.getElementById('theme-btn-dark');
        const lightBtn = document.getElementById('theme-btn-light');
        if (!darkBtn || !lightBtn) return;

        if (mode === 'light') {
            lightBtn.className = "flex-1 flex flex-col items-center gap-3 p-6 rounded-3xl border-2 border-blue-600 bg-blue-50 shadow-xl shadow-blue-600/10 transition-all";
            lightBtn.innerHTML = `<i class="fas fa-sun text-2xl text-blue-600"></i><span class="text-xs font-black uppercase tracking-widest text-blue-600">Light Mode</span>`;

            darkBtn.className = "flex-1 flex flex-col items-center gap-3 p-6 rounded-3xl border-2 border-slate-200 bg-white hover:border-slate-300 transition-all";
            darkBtn.innerHTML = `<i class="fas fa-moon text-2xl text-slate-400"></i><span class="text-xs font-black uppercase tracking-widest text-slate-400">Dark Mode</span>`;
        } else {
            darkBtn.className = "flex-1 flex flex-col items-center gap-3 p-6 rounded-3xl border-2 border-blue-600 bg-blue-600/10 shadow-xl shadow-blue-600/20 transition-all";
            darkBtn.innerHTML = `<i class="fas fa-moon text-2xl text-blue-400"></i><span class="text-xs font-black uppercase tracking-widest text-blue-400">Dark Mode</span>`;

            lightBtn.className = "flex-1 flex flex-col items-center gap-3 p-6 rounded-3xl border-2 transition-all" + " border-white/10 hover:border-white/20" + " " + "bg-white/5";
            lightBtn.innerHTML = `<i class="fas fa-sun text-2xl" style="color:#475569"></i><span class="text-xs font-black uppercase tracking-widest" style="color:#475569">Light Mode</span>`;
        }
    },

    // --- Common helpers ---

    // Escape a value for safe interpolation into innerHTML (text OR attribute
    // context). Use this for ANY backend / agent / cross-channel-user derived
    // string before putting it in a template literal. Also exposed as the
    // global `escapeHtml` for the other UI modules.
    escapeHtml(v) {
        if (v === null || v === undefined) return '';
        return String(v)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    },

    parseMarkdown(text) {
        if (!text) return "";
        let html = null;
        if (typeof marked !== 'undefined') {
            try { html = marked.parse(text); } catch(e) { html = null; }
        }
        if (html === null) {
            // marked unavailable/failed — escape first, never emit raw HTML.
            return this.escapeHtml(text).replace(/\n/g, '<br>');
        }
        // marked emits raw HTML for `<img onerror=...>`, `<script>` etc. in the
        // source, and chat/project/comment text is untrusted (LLM output or
        // cross-channel end-user input). Sanitize before it hits innerHTML.
        if (typeof DOMPurify !== 'undefined') {
            return DOMPurify.sanitize(html);
        }
        return html;
    },

    formatUptime(seconds) {
        const d = Math.floor(seconds / (3600*24));
        const h = Math.floor(seconds % (3600*24) / 3600);
        const m = Math.floor(seconds % 3600 / 60);
        if (d > 0) return `${d}d ${h}h`;
        if (h > 0) return `${h}h ${m}m`;
        return `${m}m`;
    },

    _channelIcon(sid) {
        if (sid.startsWith('tg_'))   return { icon: 'fab fa-telegram', color: 'bg-sky-500',    label: 'Telegram' };
        if (sid.startsWith('dc_'))   return { icon: 'fab fa-discord',  color: 'bg-indigo-500', label: 'Discord' };
        if (sid.startsWith('line_')) return { icon: 'fab fa-line',     color: 'bg-green-500',  label: 'LINE' };
        if (sid.startsWith('web_'))  return { icon: 'fas fa-globe',    color: 'bg-blue-600',   label: 'WebChat' };
        return { icon: 'fas fa-globe', color: 'bg-slate-400', label: 'Unknown' };
    },

    // --- Generic add/remove modal (used by MCPs etc.) ---
    openAddModal(type) {
        if (type === 'mcp') {
            const tempName = `new-extension-${Math.random().toString(36).substring(2, 7)}`;
            App.state.activeMCP = null;
            document.getElementById('mcp-placeholder').classList.add('hidden'); document.getElementById('mcp-content').classList.remove('hidden');
            document.getElementById('mcp-header').innerText = "New Extension";
            document.getElementById('mcp-input-name').value = tempName; document.getElementById('mcp-input-desc').value = "";
            const diveTemplate = JSON.stringify({ url: "", transport: "streamable", enabled: true, headers: {} }, null, 2);
            document.getElementById('mcp-json-editor').value = diveTemplate;
            document.getElementById('mcp-field-id').value = tempName;
            document.getElementById('mcp-field-url').value = "";
            document.getElementById('mcp-transport-select').value = 'streamable';
            document.getElementById('field-group-source').classList.remove('hidden');
            document.getElementById('field-group-url').classList.remove('hidden');
            document.getElementById('field-group-headers').classList.remove('hidden');
            document.getElementById('mcp-save-row').classList.remove('hidden');
            document.getElementById('mcp-type-badge').innerText = 'Remote Extension';
            this.renderHeaders({});
            return;
        }
        document.getElementById('modal-title').innerText = `PROVISION: ${type.toUpperCase()}`;
        document.getElementById('modal-container').classList.remove('hidden');
        document.getElementById('modal-confirm').onclick = async () => {
            const name = document.getElementById('modal-input').value; if (!name) return;
            await API.fetch(`/api/${type}`, { method: 'POST', body: JSON.stringify({ name }) });
            this.closeModal(); App.refresh();
        };
    },
    closeModal() { document.getElementById('modal-container').classList.add('hidden'); document.getElementById('modal-input').value = ''; },
    async deleteItem(type, name) { if (confirm(`DE-INDEX ${name}?`)) { await API.fetch(`/api/${type}/${name}`, { method: 'DELETE' }); App.refresh(); } },

    showStateModal(escapedJson) {
        const raw = escapedJson.replace(/&quot;/g, '"').replace(/&#39;/g, "'");
        let pretty = raw;
        try { pretty = JSON.stringify(JSON.parse(raw), null, 2); } catch {}

        let modal = document.getElementById('state-json-modal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'state-json-modal';
            modal.className = 'fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm';
            modal.onclick = (e) => { if (e.target === modal) modal.remove(); };
            document.body.appendChild(modal);
        }
        modal.innerHTML = `
            <div class="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[80vh] flex flex-col overflow-hidden mx-4">
                <div class="flex items-center justify-between px-6 py-4 border-b border-slate-100 bg-slate-50/50 shrink-0">
                    <span class="text-xs font-black uppercase tracking-widest text-slate-700">Memory State</span>
                    <button onclick="document.getElementById('state-json-modal').remove()" class="text-slate-400 hover:text-slate-700 transition-colors"><i class="fas fa-times"></i></button>
                </div>
                <div class="overflow-y-auto flex-1 p-6">
                    <pre class="text-[11px] font-mono text-slate-700 leading-relaxed whitespace-pre-wrap break-all bg-slate-50 rounded-xl p-4">${pretty.replace(/</g,'&lt;').replace(/>/g,'&gt;')}</pre>
                </div>
            </div>`;
    },
};

window.UI = UI;
// Global escaping helper for all UI modules. `escapeHtml` uses no `this`, so a
// bare reference is safe to share.
window.escapeHtml = UI.escapeHtml;
