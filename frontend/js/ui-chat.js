Object.assign(UI, {
    // --- tool call / result rendering (collapsed chip + deep-parsed JSON) ---
    _escapeHtml(s) {
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    },
    _deepParse(v) {
        // Tool results are often double-encoded ({result:"[...json...]"}); unwrap them.
        if (typeof v === 'string') {
            const s = v.trim();
            if ((s.startsWith('{') && s.endsWith('}')) || (s.startsWith('[') && s.endsWith(']'))) {
                try { return this._deepParse(JSON.parse(s)); } catch (e) { return v; }
            }
            return v;
        }
        if (Array.isArray(v)) return v.map(x => this._deepParse(x));
        if (v && typeof v === 'object') { const o = {}; for (const k in v) o[k] = this._deepParse(v[k]); return o; }
        return v;
    },
    _toolHtml(kind, name, payload) {
        const icon = kind === 'call' ? '🔧' : '✅';
        const label = kind === 'call' ? 'args' : 'result';
        let body = '';
        const empty = payload == null || (typeof payload === 'object' && !Array.isArray(payload) && Object.keys(payload).length === 0);
        if (!empty) {
            let pretty;
            try { pretty = JSON.stringify(this._deepParse(payload), null, 2); } catch (e) { pretty = String(payload); }
            body = `<details class="mt-1"><summary class="cursor-pointer text-[11px] opacity-60 select-none hover:opacity-100">show ${label}</summary>`
                 + `<pre class="mt-1 text-[11px] whitespace-pre-wrap break-all max-h-72 overflow-auto bg-black/5 rounded-lg p-2 m-0">${this._escapeHtml(pretty)}</pre></details>`;
        }
        return `<div class="font-mono text-[12px]"><span class="font-bold">${icon} ${this._escapeHtml(name || (kind === 'call' ? 'tool call' : 'tool result'))}</span>${body}</div>`;
    },

    renderChatSessions(sessions, adminOnly = true) {
        const list = document.getElementById('chat-session-list');
        if (!list) return;
        const webSessions = adminOnly
            ? sessions.filter(s => s.user_id === 'admin-user' || s.id.startsWith('admin-'))
            : sessions;
        if (webSessions.length === 0) {
            list.innerHTML = `<div class="p-10 text-center text-slate-400 text-xs italic opacity-60">No conversations yet</div>`;
            return;
        }
        list.innerHTML = webSessions.map(s => `
            <div onclick="UI.loadChatHistory('${escapeHtml(s.id)}')"
                 class="p-5 border-b border-slate-100 cursor-pointer hover:bg-slate-50 transition-all group ${App.state.activeSession===s.id?'bg-blue-50 border-l-4 border-l-blue-600':''}">
                <div class="flex items-center justify-between mb-1">
                    <div class="text-[10px] text-slate-400 font-mono tracking-tighter">${new Date(s.update_time).toLocaleDateString()}</div>
                    ${App.state.activeSession===s.id ? '<span class="status-badge badge-live" style="font-size:8px;padding:2px 6px"><span class="badge-dot"></span>Active</span>' : ''}
                </div>
                <div class="text-xs font-mono truncate text-slate-500 group-hover:text-blue-600 transition-colors">${escapeHtml(s.id)}</div>
            </div>`).join('');
    },

    async initChat() {
        // Always connect to the costaff agent — same as channels (Telegram/Discord/Line)
        const agents = await API.fetch('/api/agents');
        this.chatState.app = agents.find(a => a.includes('costaff')) || agents[0] || 'costaff_agent';

        const form = document.getElementById('chat-form');
        if (form) form.onsubmit = (e) => { e.preventDefault(); this.sendChatMessage(); };
        const input = document.getElementById('chat-input');
        if (input) {
            input.addEventListener('input', (e) => this.handleChatInput(e));
            input.addEventListener('keydown', (e) => this.handleChatKeydown(e));
        }

        // Load history list; do NOT auto-start a session (session is created lazily on first send)
        const sessions = await API.fetch('/api/chat/sessions');
        this.renderChatSessions(sessions);

        const webSessions = sessions.filter(s => s.user_id === 'admin-user' || s.id.startsWith('admin-'));
        if (webSessions.length > 0) {
            await this.loadChatHistory(webSessions[0].id);
        }
    },

    handleChatInput(e) {
        const val = e.target.value;
        const panel = document.getElementById('slash-commands');
        if (val.startsWith('/')) { this.renderSlashCommands(val.substring(1)); panel.classList.remove('hidden'); }
        else { panel.classList.add('hidden'); }
    },

    handleChatKeydown(e) {
        const panel = document.getElementById('slash-commands');
        if (panel.classList.contains('hidden')) return;
        const items = panel.querySelectorAll('.slash-item');
        let activeIdx = Array.from(items).findIndex(i => i.classList.contains('bg-blue-50'));
        if (e.key === 'ArrowDown') { e.preventDefault(); if (activeIdx < items.length - 1) { items[activeIdx]?.classList.remove('bg-blue-50'); items[activeIdx + 1].classList.add('bg-blue-50'); items[activeIdx + 1].scrollIntoView({ block: 'nearest' }); } }
        else if (e.key === 'ArrowUp') { e.preventDefault(); if (activeIdx > 0) { items[activeIdx].classList.remove('bg-blue-50'); items[activeIdx - 1].classList.add('bg-blue-50'); items[activeIdx - 1].scrollIntoView({ block: 'nearest' }); } }
        else if (e.key === 'Enter' && activeIdx >= 0) { e.preventDefault(); items[activeIdx].click(); }
        else if (e.key === 'Escape') { panel.classList.add('hidden'); }
    },

    renderSlashCommands(filter = "") {
        const commands = [
            { cmd: 'start', desc: 'Initialize session' }, { cmd: 'reset', desc: 'Reset context' }, { cmd: 'profile', desc: 'View profile' },
            { cmd: 'list', desc: 'List reminders' }, { cmd: 'files', desc: 'View files' }, { cmd: 'help', desc: 'Commands' }
        ];
        const filtered = commands.filter(c => c.cmd.startsWith(filter.toLowerCase()));
        const list = document.getElementById('slash-list');
        if (filtered.length === 0) { document.getElementById('slash-commands').classList.add('hidden'); return; }
        list.innerHTML = filtered.map((c, idx) => `
            <div onclick="UI.applySlashCommand('${c.cmd}')" class="slash-item px-4 py-2.5 cursor-pointer hover:bg-slate-50 transition-all flex items-center justify-between group ${idx===0?'bg-blue-50':''}">
                <div class="flex items-center gap-3"><span class="text-blue-600 font-bold text-sm">/${c.cmd}</span><span class="text-xs text-slate-400 font-headline uppercase">${c.desc}</span></div>
            </div>`).join('');
    },

    applySlashCommand(cmd) {
        const input = document.getElementById('chat-input');
        input.value = `/${cmd} `; input.focus(); document.getElementById('slash-commands').classList.add('hidden');
    },

    async startNewChat() {
        this.chatState.session = 'admin-' + Math.random().toString(36).substring(2, 10);
        App.state.activeSession = null;
        const label = document.getElementById('chat-session-label');
        if (label) label.innerText = `Session: ${this.chatState.session}`;
        document.getElementById('chat-messages').innerHTML = `<div class="flex flex-col items-center justify-center h-full text-slate-300 uppercase tracking-[0.3em] font-headline"><i class="fas fa-robot text-6xl mb-6"></i><p>Intelligence Synchronized</p></div>`;
        await API.fetch(`/api/proxy/sessions/${this.chatState.app}/${this.chatState.user}/${this.chatState.session}`, { method: 'POST' });
        this.renderChatSessions(await API.fetch('/api/chat/sessions'));
    },

    async sendChatMessage() {
        const input = document.getElementById('chat-input');
        const text = input.value.trim();
        if (!text || !this.chatState.app) return;
        if (!this.chatState.session) await this.startNewChat();
        input.value = ''; this.appendMessage('user', text);
        const thinkingId = 'thinking-' + Date.now();
        this.appendMessage('agent', '<div class="typing-dots"><span></span><span></span><span></span></div>', thinkingId);
        try {
            const res = await fetch('/api/proxy/run_sse', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${API.token()}` },
                body: JSON.stringify({ app_name: this.chatState.app, user_id: this.chatState.user, session_id: this.chatState.session, new_message: { role: 'user', parts: [{ text }] }, streaming: true })
            });
            const reader = res.body.getReader(); const decoder = new TextDecoder();
            let currentAgentMsgId = null; let currentText = "";
            const removeT = () => { const el = document.getElementById(thinkingId); if (el) el.remove(); };
            while (true) {
                const { done, value } = await reader.read(); if (done) break;
                const lines = decoder.decode(value).split('\n');
                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    try {
                        const data = JSON.parse(line.substring(6));
                        const parts = data.content?.parts || [];
                        for (const p of parts) {
                            if (p.functionCall) {
                                removeT();
                                currentAgentMsgId = null; currentText = "";
                                this.appendMessage('agent', this._toolHtml('call', p.functionCall.name, p.functionCall.args), null, 'tool-call');
                            } else if (p.functionResponse) {
                                currentAgentMsgId = null; currentText = "";
                                const r = p.functionResponse.response || {};
                                this.appendMessage('agent', this._toolHtml('res', p.functionResponse.name, r.structuredContent ?? r.content ?? r), null, 'tool-res');
                            } else if (p.text) {
                                removeT();
                                if (!currentAgentMsgId || data.partial === false) {
                                    if (data.partial === false && currentAgentMsgId) { document.getElementById(currentAgentMsgId).querySelector('.chat-content').innerHTML = this.parseMarkdown(p.text); currentAgentMsgId = null; currentText = ""; }
                                    else { currentAgentMsgId = 'msg-' + Date.now(); this.appendMessage('agent', p.text, currentAgentMsgId); currentText = p.text; }
                                } else { currentText += p.text; document.getElementById(currentAgentMsgId).querySelector('.chat-content').innerHTML = this.parseMarkdown(currentText); }
                            }
                        }
                    } catch(e){}
                }
            }
            removeT();
        } catch(e){ this.appendMessage('agent', '❌ **Error:** Connection lost.'); }
    },

    // Directly appends a message bubble to a given container (used for history batch render)
    _appendHistoryMessage(container, author, text, extraClass = "", customTime = null) {
        const isToolCall = extraClass === 'tool-call';
        const isToolRes  = extraClass === 'tool-res';
        const bubbleClass = author === 'user'
            ? 'bg-blue-600 text-white rounded-2xl rounded-tr-none shadow-lg'
            : isToolCall ? 'bg-amber-50 border border-amber-200 text-amber-900 rounded-2xl shadow-sm'
            : isToolRes  ? 'bg-emerald-50 border border-emerald-200 text-emerald-900 rounded-2xl shadow-sm'
            : 'bg-white text-slate-900 border border-slate-200 shadow-sm rounded-2xl rounded-tl-none';
        const content = (isToolCall || isToolRes) ? text : this.parseMarkdown(text);
        const div = document.createElement('div');
        div.className = `flex flex-col ${author === 'user' ? 'items-end' : 'items-start'} mb-4 w-full`;
        div.innerHTML = `
            <div class="px-5 py-3 max-w-[85%] ${bubbleClass} break-words overflow-x-auto">
                <div class="chat-content text-[14px] leading-relaxed [&_pre]:whitespace-pre-wrap [&_pre]:break-all">${content}</div>
            </div>
            <div class="text-[9px] text-slate-400 mt-1 uppercase font-bold tracking-widest px-1">
                ${author} • ${customTime || ''}
            </div>`;
        container.appendChild(div);
    },

    appendMessage(author, text, id = null, extraClass = "", customTime = null) {
        const container = document.getElementById('chat-messages'); if (!container) return;
        const placeholder = container.querySelector('.label-mono');
        if (placeholder && !extraClass.includes('tool')) container.innerHTML = '';
        const div = document.createElement('div');
        div.className = `flex flex-col ${author==='user'?'items-end':'items-start'} ${extraClass} mb-8 w-full`;
        if (id) div.id = id;
        const isToolCall = extraClass.includes('tool-call');
        const isToolRes = extraClass.includes('tool-res');
        const bubbleClass = author === 'user'
            ? 'bg-blue-600 text-white rounded-2xl rounded-tr-none shadow-lg'
            : isToolCall ? 'bg-amber-50 border border-amber-200 text-amber-900 rounded-2xl shadow-sm'
            : isToolRes ? 'bg-emerald-50 border border-emerald-200 text-emerald-900 rounded-2xl shadow-sm'
            : 'bg-white text-black border border-slate-200 shadow-sm';
        const content = (isToolCall || isToolRes) ? text
            : (author === 'agent' && !text.includes('typing-dots')) ? this.parseMarkdown(text)
            : (author === 'user') ? escapeHtml(text) : text;
        div.innerHTML = `
            <div class="px-6 py-4 max-w-[85%] ${bubbleClass} break-words">
                <div class="chat-content text-[15px] leading-relaxed">${content}</div>
            </div>
            <div class="text-[9px] text-slate-500 mt-2 uppercase font-bold tracking-widest px-1">
                ${author} • ${customTime || new Date().toLocaleTimeString()}
            </div>`;
        container.appendChild(div);
        setTimeout(() => { container.scrollTop = container.scrollHeight; }, 50);
    },

    async loadChatHistory(sid) {
        App.state.activeSession = sid; this.chatState.session = sid;
        const label = document.getElementById('chat-session-label');
        if (label) label.innerText = `Session: ${sid}`;
        this.renderChatSessions(await API.fetch('/api/chat/sessions'), App.state.activeTab === 'chat');
        const history = await API.fetch(`/api/chat/history/${sid}`);
        const container = document.getElementById('chat-messages'); if (!container) return;
        container.innerHTML = '';
        if (!history || history.length === 0) {
            container.innerHTML = `<div class="h-full flex flex-col items-center justify-center text-slate-300 uppercase tracking-[0.3em] font-headline"><i class="fas fa-inbox text-5xl mb-4"></i><p class="text-xs">No messages in this session</p></div>`;
            return;
        }
        history.forEach(item => {
            let event = item.event_data;
            if (typeof event === 'string') { try { event = JSON.parse(event); } catch(e) { return; } }
            if (!event || !event.content) return;
            const isUser = event.content.role === 'user' || event.author === 'admin-user' || event.author === 'user';
            const author = isUser ? 'user' : 'agent';
            const timestamp = new Date(item.timestamp * 1000).toLocaleTimeString();
            (event.content.parts || []).forEach(p => {
                // ADK DB stores snake_case; SSE stream uses camelCase — handle both
                const funcCall = p.function_call || p.functionCall;
                const funcResp = p.function_response || p.functionResponse;
                if (p.text && p.text.trim()) {
                    this._appendHistoryMessage(container, author, p.text, '', timestamp);
                } else if (funcCall) {
                    this._appendHistoryMessage(container, 'agent', this._toolHtml('call', funcCall.name, funcCall.args), 'tool-call', timestamp);
                } else if (funcResp) {
                    const resp = funcResp.response || {};
                    this._appendHistoryMessage(container, 'agent', this._toolHtml('res', funcResp.name, resp.structuredContent ?? resp.content ?? resp), 'tool-res', timestamp);
                }
            });
        });
        setTimeout(() => { container.scrollTop = container.scrollHeight; }, 50);
    },
});
