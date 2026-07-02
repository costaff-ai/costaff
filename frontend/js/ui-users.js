Object.assign(UI, {
    renderUsersPage(identities, profiles) {
        this._usersProfiles = profiles || [];
        const list = document.getElementById('identity-list');
        const countEl = document.getElementById('users-count-label');
        if (!list) return;

        if (countEl) countEl.textContent = `${identities.length} ident${identities.length !== 1 ? 'ities' : 'ity'}`;

        if (!identities || !identities.length) {
            list.innerHTML = `<div class="text-center py-20 text-slate-300"><i class="fas fa-id-card text-4xl mb-4 block"></i><p class="font-bold text-sm">No identities yet</p></div>`;
            return;
        }

        list.innerHTML = identities.map(id => {
            const ch = this._channelIcon(id.session_id);
            const name = id.name || 'Unknown';
            const isActive = this._activeIdentityId === id.session_id;
            const statusDot = id.is_approved
                ? '<span class="w-2 h-2 rounded-full bg-emerald-500 shrink-0"></span>'
                : '<span class="w-2 h-2 rounded-full bg-amber-400 shrink-0"></span>';
            return `<div onclick="UI.selectIdentity(${JSON.stringify(id).replace(/"/g, '&quot;')})"
                 class="p-5 border-b border-slate-100 cursor-pointer hover:bg-slate-50 transition-all group ${isActive ? 'bg-blue-50 border-l-4 border-l-blue-600' : ''}">
                <div class="flex items-center gap-3 mb-1">
                    <div class="w-8 h-8 rounded-lg ${ch.color} text-white flex items-center justify-center shrink-0">
                        <i class="${ch.icon} text-xs"></i>
                    </div>
                    <span class="font-bold text-sm text-slate-800 group-hover:text-slate-900 flex-1 truncate">${escapeHtml(name)}</span>
                    ${statusDot}
                </div>
                <p class="font-mono text-[10px] text-slate-400 truncate ml-11">${escapeHtml(id.session_id)}</p>
            </div>`;
        }).join('');

        if (this._activeIdentityId) {
            const active = identities.find(i => i.session_id === this._activeIdentityId);
            if (active) this.selectIdentity(active, true);
        }
    },

    selectIdentity(id, silent = false) {
        this._activeIdentityId = id.session_id;
        if (!silent) {
            const items = document.querySelectorAll('#identity-list > div');
            items.forEach(el => {
                const isActive = el.querySelector('.font-mono')?.textContent?.trim() === id.session_id;
                el.classList.toggle('bg-blue-50', isActive);
                el.classList.toggle('border-l-4', isActive);
                el.classList.toggle('border-l-blue-600', isActive);
            });
        }

        const placeholder = document.getElementById('user-placeholder');
        const content = document.getElementById('user-content');
        placeholder.classList.add('hidden');
        content.classList.remove('hidden');
        content.classList.add('flex');

        const ch = this._channelIcon(id.session_id);
        document.getElementById('user-channel-icon').className = `w-16 h-16 rounded-2xl ${ch.color} text-white flex items-center justify-center text-2xl shadow-xl`;
        document.getElementById('user-channel-icon').innerHTML = `<i class="${ch.icon}"></i>`;
        document.getElementById('user-detail-name').textContent = id.name || 'Unknown';

        const statusBadge = id.is_approved
            ? '<span class="px-3 py-1 rounded-full text-[10px] font-black bg-emerald-50 text-emerald-600">APPROVED</span>'
            : '<span class="px-3 py-1 rounded-full text-[10px] font-black bg-amber-50 text-amber-500">PENDING</span>';
        document.getElementById('user-status-badge').innerHTML = statusBadge;

        const approveBtn = id.is_approved
            ? `<button onclick="UI.setIdentityApproval('${escapeHtml(id.session_id)}', false)" class="px-5 py-2 rounded-xl text-[10px] font-black uppercase bg-rose-50 text-rose-500 hover:bg-rose-500 hover:text-white transition-all border border-rose-100">Revoke</button>`
            : `<button onclick="UI.setIdentityApproval('${escapeHtml(id.session_id)}', true)" class="px-5 py-2 rounded-xl text-[10px] font-black uppercase bg-emerald-600 text-white hover:bg-emerald-700 transition-all">Approve</button>`;
        const deleteBtn = `<button onclick="UI.deleteIdentity('${escapeHtml(id.session_id)}')" class="p-2.5 rounded-xl text-slate-400 hover:text-rose-500 hover:bg-rose-50 transition-all border border-slate-100"><i class="fas fa-trash-alt text-xs"></i></button>`;
        document.getElementById('user-detail-actions').innerHTML = approveBtn + deleteBtn;

        document.getElementById('user-session-id').textContent = id.session_id;
        document.getElementById('user-hashed-id').textContent = id.hashed_id || '—';
        document.getElementById('user-channel-label').textContent = ch.label;
        document.getElementById('user-created-at').textContent = id.created_at ? new Date(id.created_at).toLocaleString() : '—';

        const profile = this._usersProfiles.find(p => p.user_id === id.hashed_id);
        const profileBody = document.getElementById('user-profile-body');
        if (profile) {
            const rows = [
                ['Chinese Name', profile.chinese_name],
                ['English Name', profile.english_name],
                ['Job Title',    profile.job_title],
                ['Company',      profile.company_name],
                ['Email',        profile.personal_email],
                ['Phone',        profile.mobile_phone],
            ].filter(([, v]) => v);
            profileBody.innerHTML = rows.length
                ? rows.map(([label, val]) => `
                    <div class="flex items-center gap-4">
                        <span class="text-[10px] font-black text-slate-400 uppercase tracking-widest w-28 shrink-0">${label}</span>
                        <span class="text-sm text-slate-700">${escapeHtml(val)}</span>
                    </div>`).join('')
                + `<div class="pt-4 border-t border-slate-100 mt-2">
                    <button onclick="UI.deleteUser('${escapeHtml(profile.user_id)}')" class="text-[10px] font-black text-rose-400 hover:text-rose-600 uppercase tracking-widest transition-colors">Delete Profile</button>
                </div>`
                : `<p class="text-[11px] text-slate-400 italic">Profile exists but has no fields filled in.</p>`;
        } else {
            profileBody.innerHTML = `<p class="text-[11px] text-slate-400 italic">No profile linked to this identity yet.</p>`;
        }
    },

    async setIdentityApproval(sessionId, approve) {
        try {
            await API.fetch(`/api/identities/${encodeURIComponent(sessionId)}/${approve ? 'approve' : 'revoke'}`, { method: 'POST' });
            App.refresh();
        } catch(e) { alert('Failed to update approval status.'); }
    },

    async deleteIdentity(sessionId) {
        if (!confirm(`Delete identity ${sessionId}?`)) return;
        try {
            await API.fetch(`/api/identities/${encodeURIComponent(sessionId)}`, { method: 'DELETE' });
            App.refresh();
        } catch(e) { alert('Failed to delete identity.'); }
    },

    async deleteUser(userId) {
        if (!confirm('Delete this user profile? This cannot be undone.')) return;
        try {
            await API.fetch(`/api/users/${userId}`, { method: 'DELETE' });
            App.refresh();
        } catch(e) { alert('Failed to delete user.'); }
    },

    async deleteUserState(appName, userId) {
        if (!confirm(`Delete memory state for ${userId}?`)) return;
        try {
            await API.fetch(`/api/memory/user_states?app_name=${encodeURIComponent(appName)}&user_id=${encodeURIComponent(userId)}`, { method: 'DELETE' });
            App.refresh();
        } catch(e) { alert('Failed to delete memory state.'); }
    },
});
