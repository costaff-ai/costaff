"""Official CoStaff Platform Registry — the single catalog shared by the
`costaff platform` CLI and the dashboard's App-Store-style platform picker.

Entry fields:
  github      : clone URL used by `costaff platform add <name>`
  prefix      : env-var prefix used by the platform's compose (<P>_DB_PASSWORD …)
  oidc        : the Account Manager seeds an `AM_<oidc>_CLIENT_SECRET` client
                for this platform (None → platform doesn't use OIDC)
  port        : default frontend (public) port (None → no web frontend)
  description : one-line blurb shown on the store card
  icon        : font-awesome class for the store / platform card
"""

_GH = "https://github.com/costaff-ai"

OFFICIAL_PLATFORMS = {
    "db": {
        "github": f"{_GH}/costaff-platform-db.git", "prefix": None, "oidc": None, "port": None,
        "description": "Shared PostgreSQL every platform depends on.", "icon": "fa-database",
    },
    "account-manager": {
        "github": f"{_GH}/costaff-platform-account-manager.git", "prefix": "AM", "oidc": None, "port": 18320,
        "description": "OIDC identity provider — single sign-on for all platforms.", "icon": "fa-user-shield",
    },
    "erp": {
        "github": f"{_GH}/costaff-platform-erp.git", "prefix": "ERP", "oidc": "ERP", "port": 18210,
        "description": "Enterprise resource planning — orders, inventory, BOM, approvals.", "icon": "fa-industry",
    },
    "crm": {
        "github": f"{_GH}/costaff-platform-crm.git", "prefix": "CRM", "oidc": "CRM", "port": 18250,
        "description": "Customer relationship management — leads, deals, pipelines.", "icon": "fa-handshake",
    },
    "scm": {
        "github": f"{_GH}/costaff-platform-scm.git", "prefix": "SCM", "oidc": "SCM", "port": 18310,
        "description": "Supply chain management — suppliers, purchasing, logistics.", "icon": "fa-truck-fast",
    },
    "hrm": {
        "github": f"{_GH}/costaff-platform-hrm.git", "prefix": "HRM", "oidc": "HRM", "port": 18410,
        "description": "Human resources — employees, leave, payroll, reviews.", "icon": "fa-id-badge",
    },
    "plm": {
        "github": f"{_GH}/costaff-platform-plm.git", "prefix": "PLM", "oidc": "PLM", "port": 18510,
        "description": "Product lifecycle management — designs, revisions, ECO flow.", "icon": "fa-diagram-project",
    },
    "accounting": {
        "github": f"{_GH}/costaff-platform-accounting.git", "prefix": "ACC", "oidc": None, "port": 18610,
        "description": "Double-entry accounting — vouchers, ledgers, financial reports.", "icon": "fa-file-invoice-dollar",
    },
    "knowledge": {
        "github": f"{_GH}/costaff-platform-knowledge.git", "prefix": "KMS", "oidc": "KMS", "port": 18710,
        "description": "Knowledge base — spaces, versioned articles, tags, comments.", "icon": "fa-book-open",
    },
    "project": {
        "github": f"{_GH}/costaff-platform-project.git", "prefix": "PROJECT", "oidc": "PROJECT", "port": 18730,
        "description": "Project management — tasks, boards, milestones, approvals.", "icon": "fa-list-check",
    },
    "expense": {
        "github": f"{_GH}/costaff-platform-expense.git", "prefix": "EXPENSE", "oidc": "EXPENSE", "port": 18750,
        "description": "Expense claims — submissions, multi-step approval, budgets.", "icon": "fa-receipt",
    },
    "helpdesk": {
        "github": f"{_GH}/costaff-platform-helpdesk.git", "prefix": "HELPDESK", "oidc": "HELPDESK", "port": 18770,
        "description": "Ticketing & support — queues, SLA tracking, escalations.", "icon": "fa-headset",
    },
}
