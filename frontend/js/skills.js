const Skills = {
    activeSkillId: null,

    init() {
        this.loadSkills();
        this.populateAgentSelect();
    },

    async populateAgentSelect() {
        const sel = document.getElementById('skill-agent-ids');
        if (!sel) return;
        try {
            const agents = await API.fetch('/api/external-agents');
            // Keep static options, then append dynamic github-type agents
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

    async submitForm() {
        const editId = document.getElementById('skill-edit-id').value;
        const userSel = document.getElementById('skill-user-id');
        const selectedIds = Array.from(userSel.selectedOptions).map(o => o.value);
        const agentSel = document.getElementById('skill-agent-ids');
        const selectedAgents = Array.from(agentSel.selectedOptions).map(o => o.value);
        const payload = {
            name: document.getElementById('skill-name').value.trim(),
            description: document.getElementById('skill-description').value.trim() || null,
            tags: document.getElementById('skill-tags').value.trim() || null,
            usage: document.getElementById('skill-usage').value.trim() || null,
            user_id: selectedIds.length ? selectedIds.join(',') : '__global__',
            agent_ids: selectedAgents.length ? selectedAgents.join(',') : '__all__',
        };

        if (!payload.name) {
            alert('Skill Name is required.');
            return;
        }

        try {
            let res;
            if (editId) {
                res = await API.fetch(`/api/skills/${editId}`, {
                    method: 'PUT',
                    body: JSON.stringify(payload)
                });
            } else {
                res = await API.fetch('/api/skills', {
                    method: 'POST',
                    body: JSON.stringify(payload)
                });
            }
            if (res.status === 'success') {
                this.activeSkillId = res.id || editId || null;
                await this.loadSkills();
                if (res.id) {
                    const skills = await API.fetch('/api/skills');
                    const newSkill = skills.find(s => s.id === res.id);
                    if (newSkill) this.selectItem(newSkill);
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

    async loadSkills() {
        try {
            const skills = await API.fetch('/api/skills');
            const list = Array.isArray(skills) ? skills : [];
            document.getElementById('skill-count').innerText = list.length;
            this.renderList(list);
        } catch (err) {
            console.error('Failed to load skills:', err);
        }
    },

    renderList(skills) {
        const container = document.getElementById('skill-list');
        if (!container) return;

        if (!skills.length) {
            container.innerHTML = `
                <div class="text-center py-20 text-slate-300">
                    <i class="fas fa-bolt text-4xl mb-4 block"></i>
                    <p class="font-bold text-sm">No skills registered yet</p>
                </div>`;
            return;
        }

        container.innerHTML = skills.map(skill => `
            <div onclick="Skills.selectItem(${JSON.stringify(skill).replace(/"/g, '&quot;')})"
                 class="p-6 border-b border-slate-100 cursor-pointer hover:bg-slate-50 transition-all group ${this.activeSkillId === skill.id ? 'bg-blue-50 border-l-4 border-l-blue-600' : ''}">
                <div class="flex items-center justify-between mb-2">
                    <div class="flex items-center gap-3">
                        <div class="w-8 h-8 rounded-lg bg-blue-50 text-blue-600 flex items-center justify-center shrink-0 group-hover:bg-blue-600 group-hover:text-white transition-colors">
                            <i class="fas fa-bolt text-xs"></i>
                        </div>
                        <span class="font-bold text-slate-700 group-hover:text-slate-900">${escapeHtml(skill.name)}</span>
                    </div>
                    ${!skill.is_active ? '<span class="text-[8px] font-black bg-slate-100 text-slate-400 px-1.5 py-0.5 rounded uppercase">Disabled</span>' : ''}
                </div>
                <p class="text-[11px] text-slate-400 line-clamp-1 ml-11">${escapeHtml(skill.description || 'No description')}</p>
            </div>
        `).join('');
    },

    async selectItem(skill = null) {
        this.activeSkillId = skill?.id || null;
        this.loadSkills(); // Refresh list to update active state

        const placeholder = document.getElementById('skill-placeholder');
        const content = document.getElementById('skill-content');
        const header = document.getElementById('skill-header');
        const actions = document.getElementById('skill-detail-actions');

        if (!skill) {
            // New Skill Mode
            placeholder.classList.add('hidden');
            content.classList.remove('hidden');
            header.innerText = "New Skill";
            actions.innerHTML = "";

            document.getElementById('skill-form').reset();
            document.getElementById('skill-edit-id').value = "";
            document.getElementById('skill-field-id').value = "";

            await this.loadUserDropdown(['__global__']);
            this.setAgentDropdown(['__all__']);
            return;
        }

        placeholder.classList.add('hidden');
        content.classList.remove('hidden');
        header.innerText = skill.name.toUpperCase();

        actions.innerHTML = `
            <div class="flex items-center gap-3">
                <button onclick="Skills.toggleActive('${escapeHtml(skill.id)}', ${!skill.is_active})"
                        class="p-2.5 rounded-xl text-slate-400 hover:text-blue-600 hover:bg-blue-50 transition-all border border-slate-100"
                        title="${skill.is_active ? 'Disable' : 'Enable'}">
                    <i class="fas ${skill.is_active ? 'fa-toggle-on' : 'fa-toggle-off'} text-xs"></i>
                </button>
                <button onclick="Skills.deleteSkill('${escapeHtml(skill.id)}')"
                        class="p-2.5 rounded-xl text-slate-400 hover:text-rose-500 hover:bg-rose-50 transition-all border border-slate-100">
                    <i class="fas fa-trash-alt text-xs"></i>
                </button>
            </div>
        `;

        document.getElementById('skill-edit-id').value = skill.id;
        document.getElementById('skill-field-id').value = skill.id;
        document.getElementById('skill-name').value = skill.name;
        document.getElementById('skill-description').value = skill.description || '';
        document.getElementById('skill-tags').value = skill.tags || '';
        document.getElementById('skill-usage').value = skill.usage || '';

        const selectedIds = (skill.user_id || '__global__').split(',').map(s => s.trim());
        await this.loadUserDropdown(selectedIds);

        const selectedAgents = (skill.agent_ids || '__all__').split(',').map(s => s.trim());
        this.setAgentDropdown(selectedAgents);
    },

    async loadUserDropdown(selectedIds = ['__global__']) {
        const sel = document.getElementById('skill-user-id');
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
        const sel = document.getElementById('skill-agent-ids');
        if (!sel) return;
        const agents = Array.isArray(selectedAgents) ? selectedAgents : [selectedAgents];
        Array.from(sel.options).forEach(opt => {
            opt.selected = agents.includes(opt.value);
        });
    },

    async toggleActive(id, isActive) {
        try {
            await API.fetch(`/api/skills/${id}`, {
                method: 'PUT',
                body: JSON.stringify({ is_active: isActive })
            });
            const skills = await API.fetch('/api/skills');
            const skill = skills.find(s => s.id === id);
            if (skill) this.selectItem(skill);
            else this.loadSkills();
        } catch (err) {
            console.error('Toggle failed:', err);
        }
    },

    async deleteSkill(id) {
        if (!confirm('Delete this skill?')) return;
        try {
            await API.fetch(`/api/skills/${id}`, { method: 'DELETE' });
            this.activeSkillId = null;
            document.getElementById('skill-placeholder').classList.remove('hidden');
            document.getElementById('skill-content').classList.add('hidden');
            this.loadSkills();
        } catch (err) {
            console.error('Delete failed:', err);
        }
    }
};
