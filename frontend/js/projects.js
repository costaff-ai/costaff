// ============================================================
// Projects Module — Epics / Stories / ProjectTasks
// ============================================================
const Projects = {
    currentEpicId: null,
    currentEpicTitle: null,
    refreshTimer: null,
    currentTasks: {},   // taskId -> task object cache
    viewMode: 'list',   // 'list' | 'kanban'
    filters: { stories: [], agents: [], date: '' },  // kanban filter state
    _epics: [],         // cached epic list for active-state re-render

    async init() {
        this.bindForm();
        await this.loadEpics();
        this.refreshTimer = setInterval(() => {
            const el = document.getElementById('view-tasks');
            if (el && !el.classList.contains('hidden')) {
                this.loadEpics();
                if (this.currentEpicId) this.loadStories(this.currentEpicId);
            }
        }, 15000);
    },

    bindForm() {
        const form = document.getElementById('project-form');
        if (!form) return;
        form.onsubmit = async (e) => {
            e.preventDefault();
            const mode = document.getElementById('pf-mode').value;
            const title = document.getElementById('pf-title').value.trim();
            const description = document.getElementById('pf-description').value.trim();
            const priority = document.getElementById('pf-priority').value;
            const parentId = document.getElementById('pf-parent-id').value;

            if (!title) return;
            try {
                if (mode === 'epic') {
                    await API.fetch('/api/epics', { method: 'POST', body: JSON.stringify({ title, description }) });
                    this.closeModal();
                    await this.loadEpics();
                } else if (mode === 'story') {
                    await API.fetch(`/api/epics/${parentId}/stories`, { method: 'POST', body: JSON.stringify({ title, description, priority }) });
                    this.closeModal();
                    await this.loadStories(parentId);
                }
            } catch (err) {
                alert('Save failed: ' + err.message);
            }
        };
    },

    // ---- Epic Sidebar ----

    async loadEpics() {
        try {
            const epics = await API.fetch('/api/epics');
            this._epics = Array.isArray(epics) ? epics : [];
            this.renderEpics(this._epics);
        } catch (err) {
            console.error('Failed to load epics:', err);
        }
    },

    renderEpics(epics) {
        const list = document.getElementById('epic-sidebar-list');
        const countEl = document.getElementById('epic-count');
        if (!list) return;

        if (countEl) countEl.textContent = `${epics.length} epic${epics.length !== 1 ? 's' : ''}`;

        if (epics.length === 0) {
            list.innerHTML = `<div class="flex flex-col items-center justify-center h-40 text-slate-300 gap-3">
                <i class="fas fa-project-diagram text-3xl"></i>
                <span class="text-[10px] font-bold uppercase tracking-widest">No projects yet</span>
            </div>`;
            return;
        }

        list.innerHTML = epics.map(epic => {
            const counts = epic.task_counts || {};
            const total = Object.values(counts).reduce((a, b) => a + b, 0);
            const done = counts.done || 0;
            const progress = total > 0 ? Math.round((done / total) * 100) : 0;
            const isActive = this.currentEpicId === epic.id;
            const statusColor = { active: 'bg-blue-100 text-blue-600', completed: 'bg-green-100 text-green-600', archived: 'bg-slate-100 text-slate-500' };
            const sc = statusColor[epic.status] || 'bg-slate-100 text-slate-500';
            const escapedTitle = JSON.stringify(epic.title).replace(/"/g, '&quot;');
            const escapedDesc = JSON.stringify(epic.description || '').replace(/"/g, '&quot;');
            return `<div onclick="Projects.selectEpic('${escapeHtml(epic.id)}', ${escapedTitle}, ${escapedDesc})"
                class="p-4 cursor-pointer hover:bg-slate-50 transition-all border-l-4 ${isActive ? 'bg-blue-50 border-l-blue-600' : 'border-l-transparent'}">
                <div class="flex items-center justify-between mb-2">
                    <span class="text-sm font-bold truncate flex-1 mr-2 ${isActive ? 'text-blue-700' : 'text-slate-900'}">${escapeHtml(epic.title)}</span>
                    <div class="flex items-center gap-1 shrink-0">
                        <span class="text-[8px] font-black uppercase px-1.5 py-0.5 rounded-full ${sc}">${escapeHtml(epic.status)}</span>
                        <button onclick="event.stopPropagation();Projects.deleteEpic('${escapeHtml(epic.id)}')" class="text-slate-200 hover:text-red-500 p-0.5 transition-colors"><i class="fas fa-trash-alt text-[8px]"></i></button>
                    </div>
                </div>
                <div class="flex items-center gap-2 mb-1.5">
                    <div class="flex-1 bg-slate-100 rounded-full h-1">
                        <div class="bg-blue-500 h-1 rounded-full transition-all" style="width:${progress}%"></div>
                    </div>
                    <span class="text-[9px] font-bold text-slate-400 shrink-0">${progress}%</span>
                </div>
                <span class="text-[9px] text-slate-400 font-medium">${epic.story_count || 0} stories · ${total} tasks</span>
            </div>`;
        }).join('');
    },

    async selectEpic(epicId, title, desc) {
        this.currentEpicId = epicId;
        this.currentEpicTitle = title;

        const titleEl = document.getElementById('epic-panel-title');
        const descEl = document.getElementById('epic-panel-desc');
        if (titleEl) titleEl.textContent = title;
        if (descEl) descEl.textContent = desc || '—';

        const placeholder = document.getElementById('story-placeholder');
        const panel = document.getElementById('story-panel');
        if (placeholder) placeholder.classList.add('hidden');
        if (panel) { panel.classList.remove('hidden'); panel.classList.add('flex'); }

        // Re-render sidebar to reflect active state
        this.renderEpics(this._epics);

        await this.loadStories(epicId);
    },

    async loadStories(epicId) {
        try {
            const stories = await API.fetch(`/api/epics/${epicId}/stories`);
            this.renderStories(Array.isArray(stories) ? stories : [], epicId);
        } catch (err) {
            console.error('Failed to load stories:', err);
        }
    },

    renderStories(stories, epicId) {
        // Cache all tasks for detail modal lookup
        this.currentTasks = {};
        stories.forEach(s => (s.tasks || []).forEach(t => { this.currentTasks[t.id] = t; }));

        if (this.viewMode === 'kanban') {
            this._renderKanban(stories, epicId);
            return;
        }

        const list = document.getElementById('story-list');
        if (!list) return;
        // Restore defaults for list mode (kanban overrides these inline)
        list.style.overflow = '';
        list.style.display = '';
        list.style.flexDirection = '';
        list.style.padding = '';
        list.style.gap = '';
        if (stories.length === 0) {
            list.innerHTML = `<div class="flex flex-col items-center justify-center h-full text-slate-300 gap-3">
                <i class="fas fa-book-open text-3xl"></i>
                <span class="text-xs font-bold uppercase tracking-widest">No stories yet — add the first milestone</span>
            </div>`;
            return;
        }
        const storiesHtml = stories.map(story => {
            const statusDot = { open: 'bg-slate-400', in_progress: 'bg-blue-500', done: 'bg-green-500' };
            const dot = statusDot[story.status] || 'bg-slate-300';
            const tasks = story.tasks || [];
            const taskHtml = tasks.length === 0
                ? `<div class="text-slate-300 text-xs font-bold text-center py-4">No tasks — ask costaff_agent to create some</div>`
                : tasks.map(t => {
                    const stColor = { backlog: 'text-slate-400', queued: 'text-amber-500', doing: 'text-blue-500', done: 'text-green-500', failed: 'text-red-500' };
                    const sc = stColor[t.status] || 'text-slate-400';
                    const agentBadge = t.assigned_agent ? `<span class="bg-purple-50 text-purple-600 px-2 py-0.5 rounded-full text-[9px] font-bold">${escapeHtml(t.assigned_agent)}</span>` : '';
                    return `<div class="bg-white border border-slate-100 rounded-xl p-3 flex items-center justify-between gap-3 hover:shadow-sm transition-all cursor-pointer group" onclick="Projects.openTaskDetail('${escapeHtml(t.id)}')">
                        <div class="flex items-center gap-3 min-w-0">
                            <span class="w-2 h-2 rounded-full ${dot} shrink-0"></span>
                            <span class="text-sm font-medium text-slate-800 truncate">${escapeHtml(t.title)}</span>
                            ${agentBadge}
                        </div>
                        <div class="flex items-center gap-2 shrink-0">
                            <span class="text-[10px] font-bold uppercase ${sc}">${escapeHtml(t.status)}</span>
                            <button onclick="event.stopPropagation();Projects.deleteTask('${escapeHtml(t.id)}','${escapeHtml(epicId)}')" class="opacity-0 group-hover:opacity-100 text-slate-300 hover:text-red-500 transition-all p-1"><i class="fas fa-trash-alt text-xs"></i></button>
                        </div>
                    </div>`;
                }).join('');
            return `<div class="bg-slate-50/50 border border-slate-100 rounded-2xl overflow-hidden">
                <div class="p-4 flex items-center justify-between bg-white border-b border-slate-100">
                    <div class="flex items-center gap-3">
                        <span class="w-2.5 h-2.5 rounded-full ${dot}"></span>
                        <span class="font-bold text-slate-800 text-sm">${escapeHtml(story.title)}</span>
                        <span class="text-[9px] font-black uppercase tracking-widest px-2 py-0.5 rounded-full bg-slate-100 text-slate-500">${escapeHtml(story.priority)}</span>
                    </div>
                    <div class="flex items-center gap-2">
                        <span class="text-[10px] text-slate-400 font-bold">${tasks.length} tasks</span>
                        <button onclick="Projects.deleteStory('${escapeHtml(story.id)}','${escapeHtml(epicId)}')" class="text-slate-300 hover:text-red-500 p-1"><i class="fas fa-trash-alt text-[10px]"></i></button>
                    </div>
                </div>
                <div class="p-3 space-y-2">${taskHtml}</div>
            </div>`;
        }).join('');
        list.innerHTML = `<div class="p-6 space-y-4">${storiesHtml}</div>`;
    },

    _renderKanban(stories, epicId) {
        const list = document.getElementById('story-list');
        if (!list) return;

        const allTasks = stories.flatMap(s => (s.tasks || []).map(t => ({ ...t, storyTitle: s.title, storyId: s.id })));
        const columns = [
            { key: 'backlog',  label: 'Backlog',  color: 'text-slate-500',  bg: 'bg-slate-50',  dot: 'bg-slate-300' },
            { key: 'queued',   label: 'Queued',   color: 'text-amber-600',  bg: 'bg-amber-50',  dot: 'bg-amber-400' },
            { key: 'doing',    label: 'Doing',    color: 'text-blue-600',   bg: 'bg-blue-50',   dot: 'bg-blue-500'  },
            { key: 'done',     label: 'Done',     color: 'text-green-600',  bg: 'bg-green-50',  dot: 'bg-green-500' },
            { key: 'failed',   label: 'Failed',   color: 'text-red-500',    bg: 'bg-red-50',    dot: 'bg-red-400'   },
        ];

        if (allTasks.length === 0) {
            list.innerHTML = `<div class="flex flex-col items-center justify-center h-full text-slate-300 gap-3">
                <i class="fas fa-th-large text-3xl"></i>
                <span class="text-xs font-bold uppercase tracking-widest">No tasks yet</span>
            </div>`;
            return;
        }

        // Build filter options from available tasks
        const storyOptions = [...new Map(allTasks.map(t => [t.storyId, t.storyTitle])).entries()];
        const agentOptions = [...new Set(allTasks.map(t => t.assigned_agent).filter(Boolean))];

        // Apply filters (stories and agents are arrays for multi-select)
        const now = new Date();
        const dateThresholds = {
            today: new Date(now.getFullYear(), now.getMonth(), now.getDate()),
            week:  new Date(now - 7 * 86400000),
            month: new Date(now - 30 * 86400000),
        };
        const f = this.filters;
        const visibleTasks = allTasks.filter(t => {
            if (f.stories.length && !f.stories.includes(t.storyId)) return false;
            if (f.agents.length  && !f.agents.includes(t.assigned_agent)) return false;
            if (f.date && dateThresholds[f.date]) {
                const updated = new Date(t.updated_at || t.created_at);
                if (updated < dateThresholds[f.date]) return false;
            }
            return true;
        });

        const hasActiveFilter = f.stories.length || f.agents.length || f.date;

        // Helper to build a multi-select dropdown using <details>/<summary>
        const _multiSelect = (key, label, options /* [{id, label}] */, selected /* string[] */) => {
            const count = selected.length;
            const btnLabel = count === 0 ? label : `${label} (${count})`;
            const btnActive = count > 0 ? 'border-blue-400 text-blue-600' : 'border-slate-200 text-slate-500';
            const items = options.map(o => {
                const checked = selected.includes(o.id) ? 'checked' : '';
                const escapedId = o.id.replace(/'/g, "\\'");
                return `<label class="flex items-center gap-2 px-3 py-1.5 hover:bg-slate-50 rounded-lg cursor-pointer text-[10px] font-bold text-slate-700 whitespace-nowrap">
                    <input type="checkbox" ${checked} onchange="Projects.toggleFilter('${key}','${escapedId}')" class="accent-blue-500 w-3 h-3">
                    ${escapeHtml(o.label)}
                </label>`;
            }).join('');
            return `<details class="relative kanban-filter-details" onclick="event.stopPropagation()">
                <summary class="list-none flex items-center gap-1 text-[10px] font-bold border ${btnActive} rounded-lg px-2 py-1 bg-white cursor-pointer select-none hover:border-blue-300 transition-colors">
                    ${btnLabel}<i class="fas fa-chevron-down text-[8px] ml-0.5 opacity-50"></i>
                </summary>
                <div class="absolute top-full left-0 mt-1 bg-white border border-slate-200 rounded-xl shadow-lg z-20 py-1 min-w-max max-h-52 overflow-y-auto custom-scrollbar">
                    ${items}
                </div>
            </details>`;
        };

        const filterBar = `
        <div class="flex items-center gap-2 mb-3 shrink-0 flex-wrap" id="kanban-filter-bar">
            <i class="fas fa-filter text-[10px] text-slate-400"></i>
            ${_multiSelect('stories', 'Stories', storyOptions.map(([id, title]) => ({ id, label: title })), f.stories)}
            ${_multiSelect('agents',  'Agents',  agentOptions.map(a => ({ id: a, label: a })), f.agents)}
            <select class="text-[10px] font-bold border rounded-lg px-2 py-1 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400 cursor-pointer transition-colors ${f.date ? 'border-blue-400 text-blue-600' : 'border-slate-200 text-slate-500'}"
                    onchange="Projects.setFilter('date', this.value)">
                <option value="">All Time</option>
                <option value="today" ${f.date === 'today' ? 'selected' : ''}>Today</option>
                <option value="week"  ${f.date === 'week'  ? 'selected' : ''}>Last 7 Days</option>
                <option value="month" ${f.date === 'month' ? 'selected' : ''}>Last 30 Days</option>
            </select>
            ${hasActiveFilter ? `<button onclick="Projects.clearFilters()" class="text-[10px] font-bold text-slate-400 hover:text-red-500 transition-colors ml-1"><i class="fas fa-times mr-1"></i>Clear</button>` : ''}
            <span class="text-[10px] text-slate-400 font-bold ml-auto">${visibleTasks.length} / ${allTasks.length} tasks</span>
        </div>`;

        // Switch story-list to overflow-hidden so columns scroll independently
        list.style.overflow = 'hidden';
        list.style.display = 'flex';
        list.style.flexDirection = 'column';
        list.style.padding = '1.5rem';
        list.style.gap = '0.75rem';

        list.innerHTML = filterBar + `<div class="flex gap-4 overflow-x-auto flex-1 min-h-0">` +
            columns.map(col => {
                const colTasks = visibleTasks.filter(t => t.status === col.key);
                const cards = colTasks.length === 0
                    ? `<div class="text-center text-slate-300 text-[10px] font-bold py-8 uppercase tracking-widest">Empty</div>`
                    : colTasks.map(t => {
                        const agentBadge = t.assigned_agent ? `<span class="bg-purple-50 text-purple-600 px-2 py-0.5 rounded-full text-[9px] font-bold mt-1 inline-block">${escapeHtml(t.assigned_agent)}</span>` : '';
                        return `<div class="bg-white border border-slate-100 rounded-xl p-3 shadow-sm hover:shadow-md transition-all cursor-pointer" onclick="Projects.openTaskDetail('${escapeHtml(t.id)}')">
                            <div class="flex items-start gap-2 mb-1">
                                <span class="w-2 h-2 rounded-full ${col.dot} mt-1 shrink-0"></span>
                                <span class="text-xs font-semibold text-slate-800 leading-tight">${escapeHtml(t.title)}</span>
                            </div>
                            <p class="text-[10px] text-slate-400 ml-4 mb-1">${escapeHtml(t.storyTitle)}</p>
                            ${agentBadge ? `<div class="ml-4">${agentBadge}</div>` : ''}
                        </div>`;
                    }).join('');
                return `<div class="flex-1 min-w-[200px] max-w-xs flex flex-col gap-3 h-full">
                    <div class="flex items-center justify-between px-1 shrink-0">
                        <span class="text-[10px] font-black uppercase tracking-widest ${col.color}">${col.label}</span>
                        <span class="text-[10px] font-bold text-slate-400">${colTasks.length}</span>
                    </div>
                    <div class="${col.bg} rounded-2xl p-3 space-y-2 overflow-y-auto flex-1 min-h-0 custom-scrollbar">${cards}</div>
                </div>`;
            }).join('') + `</div>`;

        // Close all <details> dropdowns when clicking outside the filter bar
        const closeDetails = (e) => {
            if (!e.target.closest('#kanban-filter-bar')) {
                document.querySelectorAll('.kanban-filter-details[open]').forEach(d => d.removeAttribute('open'));
            }
        };
        document.removeEventListener('click', this._closeDetailsHandler);
        this._closeDetailsHandler = closeDetails;
        document.addEventListener('click', closeDetails);
    },

    toggleFilter(key, value) {
        const arr = this.filters[key];
        const idx = arr.indexOf(value);
        if (idx === -1) arr.push(value); else arr.splice(idx, 1);
        if (this.currentEpicId) this.loadStories(this.currentEpicId);
    },

    setFilter(key, value) {
        this.filters[key] = value;
        if (this.currentEpicId) this.loadStories(this.currentEpicId);
    },

    clearFilters() {
        this.filters = { stories: [], agents: [], date: '' };
        if (this.currentEpicId) this.loadStories(this.currentEpicId);
    },

    switchView(mode) {
        this.viewMode = mode;
        if (mode === 'list') {
            this.filters = { stories: [], agents: [], date: '' };
            // Restore sidebar if it was hidden in fullscreen kanban
            const sidebar = document.getElementById('epic-sidebar');
            if (sidebar) sidebar.classList.remove('hidden');
        }
        // Update toggle button styles
        ['list', 'kanban'].forEach(m => {
            const btn = document.getElementById(`view-toggle-${m}`);
            if (!btn) return;
            btn.className = m === mode
                ? 'px-3 py-1.5 rounded-lg text-xs font-bold bg-blue-600 text-white transition-all'
                : 'px-3 py-1.5 rounded-lg text-xs font-bold text-slate-400 hover:text-slate-600 transition-all';
        });
        // Fullscreen button: show only in kanban mode, reset icon
        const fsBtn = document.getElementById('kanban-fullscreen-btn');
        if (fsBtn) {
            fsBtn.classList.toggle('hidden', mode !== 'kanban');
            fsBtn.innerHTML = '<i class="fas fa-expand text-[10px]"></i>';
            fsBtn.title = 'Expand kanban';
        }
        if (this.currentEpicId) this.loadStories(this.currentEpicId);
    },

    toggleKanbanFullscreen() {
        const sidebar = document.getElementById('epic-sidebar');
        const btn = document.getElementById('kanban-fullscreen-btn');
        if (!sidebar || !btn) return;
        const isExpanded = sidebar.classList.contains('hidden');
        if (isExpanded) {
            sidebar.classList.remove('hidden');
            btn.innerHTML = '<i class="fas fa-expand text-[10px]"></i>';
            btn.title = 'Expand kanban';
        } else {
            sidebar.classList.add('hidden');
            btn.innerHTML = '<i class="fas fa-compress text-[10px]"></i>';
            btn.title = 'Restore sidebar';
        }
    },

    // ---- Task Detail ----

    async openTaskDetail(taskId) {
        const t = this.currentTasks[taskId] || {};
        document.getElementById('td-title').textContent = t.title || 'Task Detail';
        document.getElementById('td-id').textContent = `TASK_ID: ${taskId}`;
        const specEl = document.getElementById('td-spec');
        if (specEl) {
            const raw = t.spec || '*(No spec provided)*';
            if (typeof marked !== 'undefined') {
                marked.setOptions({ gfm: true, breaks: true });
                specEl.innerHTML = UI.parseMarkdown(raw);
            } else {
                specEl.textContent = raw;
            }
        }
        const stColor = { backlog: 'text-slate-500', queued: 'text-amber-600', doing: 'text-blue-600', done: 'text-green-600', failed: 'text-red-500' };
        const statusEl = document.getElementById('td-status');
        if (statusEl) { statusEl.textContent = t.status || '—'; statusEl.className = `text-sm font-bold ${stColor[t.status] || 'text-slate-500'}`; }
        const agentEl = document.getElementById('td-agent');
        if (agentEl) agentEl.textContent = t.assigned_agent || '—';
        const prioEl = document.getElementById('td-priority');
        if (prioEl) prioEl.textContent = t.priority || '—';

        document.getElementById('task-detail-modal').classList.remove('hidden');
        document.getElementById('td-comments').innerHTML = '<div class="text-center py-8 text-slate-300 text-xs font-bold">Loading...</div>';
        try {
            const comments = await API.fetch(`/api/project-tasks/${taskId}/comments`);
            this.renderComments(comments);
        } catch (err) {
            document.getElementById('td-comments').innerHTML = '<p class="text-center text-red-400 text-xs py-4">Failed to load</p>';
        }
    },

    renderComments(comments) {
        const el = document.getElementById('td-comments');
        if (!comments || comments.length === 0) {
            el.innerHTML = '<div class="text-center py-8 bg-slate-50 rounded-xl text-slate-400 text-xs font-bold">NO COMMENTS YET</div>';
            return;
        }
        el.innerHTML = comments.map(c => {
            const typeColor = { result: 'text-green-600', issue: 'text-red-600', decision: 'text-blue-600', note: 'text-slate-500' };
            const tc = typeColor[c.type] || 'text-slate-500';
            return `<div class="bg-white border border-slate-100 rounded-xl p-4 shadow-sm">
                <div class="flex justify-between items-center mb-2">
                    <span class="text-[10px] font-black ${tc} uppercase tracking-widest">${escapeHtml(c.type)} · ${escapeHtml(c.author)}</span>
                    <span class="text-[10px] text-slate-400 font-bold">${new Date(c.created_at).toLocaleString()}</span>
                </div>
                <div class="prose prose-xs prose-slate max-w-none text-xs leading-relaxed markdown-body">${UI.parseMarkdown(c.content || '')}</div>
            </div>`;
        }).join('');
    },

    closeTaskDetail() { document.getElementById('task-detail-modal').classList.add('hidden'); },

    // ---- Modals ----

    openAddModal() {
        document.getElementById('pf-mode').value = 'epic';
        document.getElementById('project-modal-title').textContent = 'New Epic';
        document.getElementById('pf-priority-row').classList.add('hidden');
        document.getElementById('pf-title').value = '';
        document.getElementById('pf-description').value = '';
        document.getElementById('project-modal').classList.remove('hidden');
    },

    openAddStoryModal() {
        document.getElementById('pf-mode').value = 'story';
        document.getElementById('pf-parent-id').value = this.currentEpicId;
        document.getElementById('project-modal-title').textContent = 'New Story';
        document.getElementById('pf-priority-row').classList.remove('hidden');
        document.getElementById('pf-title').value = '';
        document.getElementById('pf-description').value = '';
        document.getElementById('project-modal').classList.remove('hidden');
    },

    openAddTaskPrompt() {
        alert('Tasks are created by the AI team via costaff_agent. Use the chat to ask your agent to create a task under this project.');
    },

    closeModal() {
        document.getElementById('project-modal').classList.add('hidden');
        document.getElementById('project-form').reset();
    },

    // ---- Delete actions ----

    async deleteEpic(epicId) {
        if (!confirm('Delete this epic and all its stories and tasks?')) return;
        try {
            await API.fetch(`/api/epics/${epicId}`, { method: 'DELETE' });
            await this.loadEpics();
        } catch (err) { alert('Delete failed: ' + err.message); }
    },

    async deleteStory(storyId, epicId) {
        if (!confirm('Delete this story?')) return;
        try {
            await API.fetch(`/api/epics/${epicId}/stories/${storyId}`, { method: 'DELETE' });
            await this.loadStories(epicId);
        } catch (err) { alert('Delete failed'); }
    },

    async deleteTask(taskId, epicId) {
        if (!confirm('Delete this task?')) return;
        try {
            await API.fetch(`/api/project-tasks/${taskId}`, { method: 'DELETE' });
            await this.loadStories(epicId);
        } catch (err) { alert('Delete failed'); }
    },
};
