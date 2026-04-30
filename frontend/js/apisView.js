const Apis = {
    activeApiId: null,

    init() {
        this.loadApis();
        this.populateAgentSelect();
    },

    async populateAgentSelect() {
        const sel = document.getElementById('api-agent-ids');
        if (!sel) return;
        try {
            const agents = await API.fetch('/api/external-agents');
            const existing = new Set(Array.from(sel.options).map(o => o.value));
            (agents || []).forEach(agent => {
                const agentId = agent.name.replace(/-/g, '_');
                if (!existing.has(agentId)) {
                    const opt = document.createElement('option');
                    opt.value = agentId;
                    opt.textContent = agentId;
                    sel.appendChild(opt);
                    existing.add(agentId);
                }
            });
        } catch(e) { console.warn('Could not load agent list:', e); }
    },

    async save() {
        const editId = document.getElementById('api-edit-id').value;
        const headersRaw = document.getElementById('api-headers').value.trim();

        let headers = null;
        if (headersRaw) {
            try {
                headers = JSON.parse(headersRaw);
            } catch {
                alert('Headers must be valid JSON. Example: {"Authorization": "Bearer token"}');
                return;
            }
        }

        const userSel = document.getElementById('api-user-id');
        const selectedIds = Array.from(userSel.selectedOptions).map(o => o.value);
        const agentSel = document.getElementById('api-agent-ids');
        const selectedAgents = Array.from(agentSel.selectedOptions).map(o => o.value);
        const payload = {
            name: document.getElementById('api-name').value.trim(),
            method: document.getElementById('api-method').value,
            url: document.getElementById('api-url').value.trim(),
            user_id: selectedIds.length ? selectedIds.join(',') : '__global__',
            agent_ids: selectedAgents.length ? selectedAgents.join(',') : '__all__',
            headers,
            description: document.getElementById('api-description').value.trim() || null,
        };

        if (!payload.name || !payload.url) {
            alert('API Name and URL are required.');
            return;
        }

        try {
            let res;
            if (editId) {
                res = await API.fetch(`/api/apis/${editId}`, {
                    method: 'PUT',
                    body: JSON.stringify(payload)
                });
            } else {
                res = await API.fetch('/api/apis', {
                    method: 'POST',
                    body: JSON.stringify(payload)
                });
            }
            if (res.status === 'success') {
                this.activeApiId = res.id || editId || null;
                await this.loadApis();
                if (res.id) {
                    const apis = await API.fetch('/api/apis');
                    const newApi = apis.find(a => a.id === res.id);
                    if (newApi) this.selectItem(newApi);
                } else if (!editId) {
                    this.selectItem(null);
                }
            } else {
                alert('Failed to save: ' + (res.detail || JSON.stringify(res)));
            }
        } catch (err) {
            alert('Error: ' + err.message);
        }
    },

    async loadApis() {
        try {
            const apis = await API.fetch('/api/apis');
            const list = Array.isArray(apis) ? apis : [];
            document.getElementById('api-count').innerText = list.length;
            this.renderList(list);
        } catch (err) {
            console.error('Failed to load APIs:', err);
        }
    },

    renderList(apis) {
        const container = document.getElementById('api-list');
        if (!container) return;

        if (!apis.length) {
            container.innerHTML = `
                <div class="text-center py-20 text-slate-300">
                    <i class="fas fa-plug text-4xl mb-4 block"></i>
                    <p class="font-bold text-sm">No APIs registered yet</p>
                </div>`;
            return;
        }

        const methodColors = {
            GET: 'text-green-600 bg-green-50',
            POST: 'text-blue-600 bg-blue-50',
            PUT: 'text-yellow-600 bg-yellow-50',
            PATCH: 'text-orange-600 bg-orange-50',
            DELETE: 'text-rose-600 bg-rose-50',
        };

        container.innerHTML = apis.map(api => `
            <div onclick="Apis.selectItem(${JSON.stringify(api).replace(/"/g, '&quot;')})"
                 class="p-6 border-b border-slate-100 cursor-pointer hover:bg-slate-50 transition-all group ${this.activeApiId === api.id ? 'bg-blue-50 border-l-4 border-l-blue-600' : ''}">
                <div class="flex items-center justify-between mb-2">
                    <div class="flex items-center gap-3">
                        <div class="w-12 h-6 rounded-md ${methodColors[api.method] || 'bg-slate-100 text-slate-600'} flex items-center justify-center shrink-0 text-[10px] font-black tracking-tighter transition-colors group-hover:bg-blue-600 group-hover:text-white">
                            ${api.method}
                        </div>
                        <span class="font-bold text-slate-700 group-hover:text-slate-900">${api.name}</span>
                    </div>
                    ${!api.is_active ? '<span class="text-[8px] font-black bg-slate-100 text-slate-400 px-1.5 py-0.5 rounded uppercase">Disabled</span>' : ''}
                </div>
                <p class="text-[11px] text-slate-400 font-mono truncate ml-[60px]">${api.url}</p>
            </div>
        `).join('');
    },

    async selectItem(api = null) {
        this.activeApiId = api?.id || null;
        this.loadApis();

        const placeholder = document.getElementById('api-placeholder');
        const content = document.getElementById('api-content');
        const header = document.getElementById('api-header');
        const actions = document.getElementById('api-detail-actions');

        if (!api) {
            placeholder.classList.add('hidden');
            content.classList.remove('hidden');
            header.innerText = "New API";
            actions.innerHTML = "";
            
            document.getElementById('api-form').reset();
            document.getElementById('api-edit-id').value = "";
            document.getElementById('api-field-id').value = "";
            document.getElementById('api-curl-section').classList.remove('hidden');

            await this.loadUserDropdown(['__global__']);
            this.setAgentDropdown(['__all__']);
            return;
        }

        placeholder.classList.add('hidden');
        content.classList.remove('hidden');
        header.innerText = api.name.toUpperCase();
        document.getElementById('api-curl-section').classList.add('hidden');
        
        actions.innerHTML = `
            <div class="flex items-center gap-3">
                <button onclick="Apis.toggleActive('${api.id}', ${!api.is_active})" 
                        class="p-2.5 rounded-xl text-slate-400 hover:text-blue-600 hover:bg-blue-50 transition-all border border-slate-100"
                        title="${api.is_active ? 'Disable' : 'Enable'}">
                    <i class="fas ${api.is_active ? 'fa-toggle-on' : 'fa-toggle-off'} text-xs"></i>
                </button>
                <button onclick="Apis.deleteApi('${api.id}')" 
                        class="p-2.5 rounded-xl text-slate-400 hover:text-rose-500 hover:bg-rose-50 transition-all border border-slate-100">
                    <i class="fas fa-trash-alt text-xs"></i>
                </button>
            </div>
        `;

        document.getElementById('api-edit-id').value = api.id;
        document.getElementById('api-field-id').value = api.id;
        document.getElementById('api-name').value = api.name;
        document.getElementById('api-method').value = api.method;
        document.getElementById('api-url').value = api.url;
        document.getElementById('api-headers').value = api.headers ? JSON.stringify(api.headers, null, 2) : '';
        document.getElementById('api-description').value = api.description || '';

        const selectedIds = (api.user_id || '__global__').split(',').map(s => s.trim());
        await this.loadUserDropdown(selectedIds);

        const selectedAgents = (api.agent_ids || '__all__').split(',').map(s => s.trim());
        this.setAgentDropdown(selectedAgents);
    },

    async loadUserDropdown(selectedIds = ['__global__']) {
        const sel = document.getElementById('api-user-id');
        if (!sel) return;
        sel.innerHTML = '<option value="__global__">Global — all users</option>';
        try {
            const users = await API.fetch('/api/users');
            if (Array.isArray(users)) {
                users.forEach(u => {
                    const name = u.chinese_name || u.english_name || u.user_id;
                    const opt = document.createElement('option');
                    opt.value = u.user_id;
                    opt.textContent = `${name} (${u.user_id.slice(0, 8)}…)`;
                    sel.appendChild(opt);
                });
            }
        } catch {}
        const ids = Array.isArray(selectedIds) ? selectedIds : [selectedIds];
        Array.from(sel.options).forEach(opt => {
            opt.selected = ids.includes(opt.value);
        });
    },

    setAgentDropdown(selectedAgents = ['__all__']) {
        const sel = document.getElementById('api-agent-ids');
        if (!sel) return;
        const agents = Array.isArray(selectedAgents) ? selectedAgents : [selectedAgents];
        Array.from(sel.options).forEach(opt => {
            opt.selected = agents.includes(opt.value);
        });
    },

    importCurl() {
        const raw = document.getElementById('api-curl-input').value.trim();
        if (!raw) return;
        const normalized = raw.replace(/\\\n/g, ' ').replace(/\s+/g, ' ');
        const methodMatch = normalized.match(/(?:-X|--request)\s+['"]?([A-Z]+)['"]?/i);
        const method = methodMatch ? methodMatch[1].toUpperCase() : 'GET';
        const urlMatch = normalized.match(/curl\s+.*?\s+['"]?(https?:\/\/[^\s'"]+)['"]?/) ||
                         normalized.match(/['"]?(https?:\/\/[^\s'"]+)['"]?/);
        const url = urlMatch ? urlMatch[1] : '';
        const headers = {};
        const headerRegex = /(?:-H|--header)\s+['"]([^'"]+)['"]/g;
        let m;
        while ((m = headerRegex.exec(normalized)) !== null) {
            const colonIdx = m[1].indexOf(':');
            if (colonIdx > -1) {
                const key = m[1].slice(0, colonIdx).trim();
                const val = m[1].slice(colonIdx + 1).trim();
                if (key.toLowerCase() !== 'accept') {
                    headers[key] = val;
                }
            }
        }
        if (method) document.getElementById('api-method').value = method;
        if (url) document.getElementById('api-url').value = url;
        if (Object.keys(headers).length) {
            document.getElementById('api-headers').value = JSON.stringify(headers, null, 2);
        }
        if (url && !document.getElementById('api-name').value) {
            try {
                const hostname = new URL(url).hostname.replace(/^api\./, '').split('.')[0];
                document.getElementById('api-name').value = hostname.charAt(0).toUpperCase() + hostname.slice(1);
            } catch {}
        }
        document.getElementById('api-curl-input').value = '';
    },

    async toggleActive(id, isActive) {
        try {
            await API.fetch(`/api/apis/${id}`, {
                method: 'PUT',
                body: JSON.stringify({ is_active: isActive })
            });
            const apis = await API.fetch('/api/apis');
            const api = apis.find(a => a.id === id);
            if (api) this.selectItem(api);
            else this.loadApis();
        } catch (err) {
            console.error('Toggle failed:', err);
        }
    },

    async deleteApi(id) {
        if (!confirm('Delete this API configuration?')) return;
        try {
            await API.fetch(`/api/apis/${id}`, { method: 'DELETE' });
            this.activeApiId = null;
            document.getElementById('api-placeholder').classList.remove('hidden');
            document.getElementById('api-content').classList.add('hidden');
            this.loadApis();
        } catch (err) {
            console.error('Delete failed:', err);
        }
    }
};
