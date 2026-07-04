const App = {
    state: {
        activeTab: 'dashboard',
        subTabs: { sessions: 'explorer', information: 'identities', users: 'profiles' },
        activeSession: null,
        activeMCP: null,
        activeGateway: null,
        activeAgent: null,
        activeExtAgent: null,
        mcpMode: 'local',
        loadedViews: new Set(),
    },

    async init() {
        UI.loadTheme();
        let isSetup = true;
        try {
            const authStatus = await API.fetch('/api/check-setup');
            isSetup = authStatus.is_setup !== false;
        } catch(e) {
            console.error("Initialization error:", e);
        }

        if (!API.token()) {
            this.showLogin(isSetup);
        } else {
            this.start();
        }

        // Bind sidebar events
        document.querySelectorAll('.sidebar-item').forEach(btn => {
            btn.onclick = () => this.switchMainTab(btn.dataset.tab);
        });
    },

    showLogin(isSetup = true) {
        const overlay = document.getElementById('auth-overlay');
        const form = document.getElementById('auth-form');
        if (overlay) overlay.classList.remove('hidden');

        if (!isSetup) {
            const hintEl = document.getElementById('auth-hint');
            const btnEl = document.getElementById('auth-submit-btn');
            if (hintEl) hintEl.classList.remove('hidden');
            if (btnEl) btnEl.textContent = 'CREATE ACCOUNT & CONNECT';
        }

        if (form) {
            form.onsubmit = async (e) => {
                e.preventDefault();
                const u = document.getElementById('username').value;
                const p = document.getElementById('password').value;
                const errorEl = document.getElementById('auth-error');

                try {
                    if (errorEl) errorEl.classList.add('hidden');
                    // If no account exists yet, create it first with the entered credentials
                    if (!isSetup) {
                        await API.post('/api/setup', { username: u, password: p });
                        isSetup = true;
                    }
                    const res = await API.fetch('/api/login', {
                        method: 'POST',
                        body: JSON.stringify({ username: u, password: p })
                    });

                    if (res && res.token) {
                        localStorage.setItem('costaff_token', res.token);
                        window.location.reload();
                    } else {
                        throw new Error("Invalid response structure");
                    }
                } catch (err) {
                    console.error("Login failed:", err);
                    if (errorEl) {
                        errorEl.innerText = "ACCESS_DENIED: INVALID_CREDENTIALS";
                        errorEl.classList.remove('hidden');
                    }
                }
            };
        }
    },

    async start() {
        const overlay = document.getElementById('auth-overlay');
        const sidebar = document.getElementById('sidebar');
        const main = document.getElementById('main-view');

        if (overlay) overlay.classList.add('hidden');
        if (sidebar) sidebar.classList.remove('hidden');
        if (main) main.classList.remove('hidden');

        // Shell: system switcher + Manager/External agent nav (sets activeCorePrefix)
        if (typeof Shell !== 'undefined') await Shell.init();
        await this.switchMainTab('dashboard');

        // Polling sync — skip sessions tab (user-driven, not auto-refreshed)
        setInterval(() => { if (this.state.activeTab !== 'sessions') this.refresh(); }, 5000);
    },

    async switchMainTab(tabId) {
        if (!tabId) return;
        this.state.activeTab = tabId;

        // UI: Sidebar active state
        document.querySelectorAll('.sidebar-item').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.tab === tabId);
        });

        const container = document.getElementById(`view-${tabId}`);
        if (!container) {
            console.error(`Container view-${tabId} not found`);
            return;
        }

        // Load content if first time
        if (!this.state.loadedViews.has(tabId)) {
            try {
                const html = await fetch(`views/${tabId}.html?v=7`).then(r => {
                    if (!r.ok) throw new Error(`View ${tabId} not found`);
                    return r.text();
                });
                container.innerHTML = html;
                this.state.loadedViews.add(tabId);

                // One-time initialization for specific tabs
                if (tabId === 'chat') await UI.initChat();
                if (tabId === 'tasks') await Projects.init();
                if (tabId === 'cronjobs' && typeof RegularWork !== 'undefined') await RegularWork.init();
                if (tabId === 'apis') Apis.init();
                if (tabId === 'platforms') Platforms.init();
                if (tabId === 'skills') Skills.init();
                if (tabId === 'diary') Diary.init();
                if (tabId === 'config') { UI.updateThemeUI(localStorage.getItem('costaff_theme') || 'light'); await UI.initApprovalToggle(); }
                if (tabId === 'logs') {
                    const svcs = await API.fetch('/api/status');
                    UI.updateLogServices(svcs);
                }
            } catch(e) {
                console.error("View render failed:", tabId, e);
                container.innerHTML = `<div class="p-20 text-center uppercase font-headline text-red-400 text-sm">
                    <div class="text-xl font-bold mb-2">Failed to load module: ${tabId}</div>
                    <div class="font-mono text-xs bg-red-50 border border-red-100 rounded p-4 mt-2 text-left max-w-lg mx-auto">${e && e.message ? e.message : String(e)}</div>
                    <button onclick="App.state.loadedViews.delete('${tabId}'); App.switchMainTab('${tabId}')" class="mt-4 px-4 py-2 bg-blue-600 text-white text-xs rounded-xl font-bold hover:bg-blue-700">Retry</button>
                </div>`;
            }
        }

        // Ensure theme buttons are updated if switching back to config tab
        if (tabId === 'config') { UI.updateThemeUI(localStorage.getItem('costaff_theme') || 'light'); UI.initApprovalToggle(); }

        // DOM: Visibility switch - ensure we only target actual main-tab-view elements
        document.querySelectorAll('.main-tab-view').forEach(el => el.classList.add('hidden'));
        container.classList.remove('hidden');

        // Layout fix: Toggle overflow on parent based on tab needs
        const contentArea = document.getElementById('content-area');
        if (contentArea) {
            const internalScrollTabs = ['chat', 'agents', 'mcps', 'gateways', 'users', 'diary', 'tasks'];
            if (internalScrollTabs.includes(tabId)) {
                contentArea.classList.add('overflow-hidden');
                contentArea.classList.remove('overflow-y-auto');
            } else {
                contentArea.classList.remove('overflow-hidden');
                contentArea.classList.add('overflow-y-auto');
            }
        }

        // Header Title: Sync with sidebar display name
        const titleEl = document.getElementById('view-title');
        if (titleEl) {
            const activeBtn = document.querySelector(`.sidebar-item[data-tab="${tabId}"]`);
            titleEl.innerText = activeBtn ? activeBtn.innerText.trim() : tabId.toUpperCase();
        }

        // Immediate sync
        this.refresh();
    },

    async switchSubTab(parent, subId) {
        this.state.subTabs[parent] = subId;

        // UI: Tab Buttons - Use correct light theme active classes
        document.querySelectorAll(`#view-${parent} .tab-btn`).forEach(b => {
            const isActive = b.dataset.subtab === subId;
            if (isActive) {
                b.className = "tab-btn active px-6 py-2 rounded-xl text-xs font-bold transition-all bg-blue-600 text-white shadow-lg shadow-blue-200";
            } else {
                b.className = "tab-btn px-6 py-2 rounded-xl text-xs font-bold transition-all text-slate-400 hover:text-slate-600";
            }
        });

        if (parent === 'sessions') {
            const isExp  = subId === 'explorer';
            const isHist = subId === 'history';

            const expEl    = document.getElementById('sessions-explorer');
            const tblEl    = document.getElementById('sessions-table-view');
            const filterEl = document.getElementById('session-table-filter');
            const toolsBtn = document.getElementById('btn-toggle-tools');

            if (expEl) expEl.classList.toggle('hidden', !isExp);
            if (tblEl) tblEl.classList.toggle('hidden', isExp);

            if (filterEl) {
                if (isExp) { filterEl.classList.add('hidden'); filterEl.classList.remove('flex'); }
                else       { filterEl.classList.remove('hidden'); filterEl.classList.add('flex'); }
            }
            // Tool calls toggle — only for history tab
            if (toolsBtn) toolsBtn.style.display = isHist ? '' : 'none';
        }
        this.refresh();
    },

    async refresh() {
        const tab = this.state.activeTab;
        if (!API.token() || !this.state.loadedViews.has(tab)) return;

        try {
            if (tab === 'dashboard') {
                const [stats, status, license, aiTeam] = await Promise.all([
                    API.fetch('/api/os-stats'),
                    API.fetch('/api/status'),
                    API.fetch('/api/license'),
                    API.fetch('/api/dashboard/ai-team'),
                ]);
                UI.renderOSStats(stats);
                UI.renderDashboard(status);
                UI.renderLicense(license);
                UI.renderAITeam(aiTeam);
            }

            if (tab === 'sessions') {
                if (this.state.subTabs.sessions === 'explorer') {
                    const sessions = await API.fetch('/api/chat/sessions');
                    UI.renderChatSessions(sessions, false);
                } else if (this.state.subTabs.sessions === 'history') {
                    const data = await API.fetch('/api/db/events');
                    UI.drawTable('sessions-thead', 'sessions-tbody', 'events', data);
                } else {
                    const data = await API.fetch('/api/db/user_states');
                    UI.drawTable('sessions-thead', 'sessions-tbody', 'user_states', data);
                }
            }

            if (tab === 'mcps' || tab === 'gateways' || tab === 'agents') {
                const svcs = await API.fetch('/api/status');
                const conf = await API.fetch('/api/config');
                if (tab === 'mcps') {
                    UI.renderMCP(svcs, conf);
                    if (this.state.activeMCP) UI.updateMCPActionButtons(this.state.activeMCP, svcs.find(s=>s.name.includes('mcp-'+this.state.activeMCP))?.status.includes('Up'), conf.external_mcp && conf.external_mcp[this.state.activeMCP]);
                }
                if (tab === 'gateways') {
                    UI.renderGateways(svcs, conf);
                    if (this.state.activeGateway) UI.updateGatewayStatus(this.state.activeGateway, svcs);
                }
                if (tab === 'agents') {
                    UI.renderAgents(svcs);
                    if (this.state.activeAgent) UI.updateAgentStatus(this.state.activeAgent, svcs);
                    UI.loadExternalAgents();
                }
            }

            if (tab === 'cronjobs' && typeof RegularWork !== 'undefined') RegularWork.load();
            if (tab === 'logs') UI.renderLogs();
            if (tab === 'information') {
                const sub = this.state.subTabs.information;
                const data = await API.fetch(`/api/db/${sub}`);
                UI.drawTable('info-thead', 'info-tbody', sub, data);
            }
            if (tab === 'users') {
                const [identities, profiles] = await Promise.all([
                    API.fetch('/api/identities'),
                    API.fetch('/api/users'),
                ]);
                UI.renderUsersPage(identities, profiles);
            }
        } catch (e) {
            console.warn("Telemetry sync interrupted:", e.message);
        }
    },

    logout() {
        localStorage.removeItem('costaff_token');
        window.location.reload();
    }
};

window.App = App;
document.addEventListener('DOMContentLoaded', () => App.init());
