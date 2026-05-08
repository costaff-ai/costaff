# CoStaff Core 開發規範

適用於 `costaff/`（CLI、Manager Agent、MCP Core、API Server、前端）的開發準則。

## 1. 目錄結構與職責

```
costaff/
├── costaff.py               # CLI 入口（Typer group）
├── cli/commands/            # CLI 子命令
│   ├── services.py          # costaff start/stop/restart/ps
│   ├── agent.py             # `costaff agent ...` 群組 registry（純 23 行 typer.Typer 殼）
│   ├── agent_lifecycle.py   #   add / remove / enable / disable
│   ├── agent_container.py   #   list / restart / rebuild
│   ├── agent_model.py       #   model + .env 讀寫 helpers
│   ├── channel.py           # costaff channel add/list/remove/rebuild
│   ├── database.py          # costaff database backup
│   ├── onboard.py           # costaff onboard（首次設定）
│   ├── doctor.py            # costaff doctor（健康診斷）
│   ├── dashboard.py         # costaff dashboard（host-side FastAPI）
│   ├── licensing.py         # costaff license
│   └── update.py            # costaff update
├── services/                # 核心邏輯層（CLI 之下、容器之上）
│   ├── config.py            # config.json 讀寫；包含 MCP env var 自動產生 + agent_mcp_filters 白名單
│   ├── auth.py              # AuthManager — bearer session token + auth.json
│   ├── database.py          # Postgres 連線
│   ├── audit.py             # 審計日誌
│   ├── docker.py            # Docker compose 操作（legacy 介面）
│   └── runtime/             # Runtime 抽象層
│       ├── base.py          # Runtime ABC（up/stop/build/down/ps/logs/...）
│       └── docker.py        # DockerRuntime 實作；CLI 不該直接 docker subprocess
├── agents/costaff_agent/    # Manager Agent（ADK LlmAgent）— pure orchestrator pattern
│   ├── agent.py             # ~30 行：tools = mcp_toolsets + skills + remote agent tools
│   ├── instruction/
│   │   ├── __init__.py      # build_instruction(has_agent_tools)
│   │   └── system.md
│   ├── mcp_toolsets/        # load_all_mcp_toolsets()
│   ├── models/              # selected_model（gemini / litellm）
│   ├── skills/              # load_all_skills() → SkillToolset
│   └── sub_agents/          # ⚠️ 內容是 RemoteA2aAgent 包成 AgentTool（不是 sub_agents=[...]！）
│                            #    function: load_all_remote_agent_tools()，加進 tools list
├── mcp_servers/             # Core MCP Server（manager 用 + plugin agent 共用 4 個 tool）
│   ├── server.py            # FastMCP server，自動 discover tools/
│   ├── setup.py             # `mcp = FastMCP(...)` instance（重命名以避免與 core/ 套件衝突）
│   ├── task_helpers.py      # build_task_spec / get_user_channel_info（executor 用）
│   ├── background.py        # APScheduler 啟動、預設 4 個 RegularWork
│   ├── tools/               # MCP 工具（epics, stories, project_tasks, task_comments, ...）
│   │   └── _shared.py       # require_approved 守門
│   └── executors/           # 背景 job：reminder, regular_work, project_task
├── server/                  # FastAPI Dashboard 後端（host-side，由 `costaff dashboard` 啟動）
│   ├── app.py
│   └── routers/             # 每個 router 一個 domain
│       ├── auth.py / system.py / config.py / agents.py / diary.py
│       ├── identity.py        # /api/users, /api/identities/*, /api/memory/user_states, /api/reminders/{id}
│       ├── chat_inspect.py    # /api/chat/sessions, /api/chat/history/{id}, /api/db/{table}
│       ├── integrations.py    # /api/apis, /api/skills CRUD（API + Skill configs）
│       ├── proxies.py         # /api/logs/{service}, /api/proxy/run_sse, /api/proxy/sessions/...
│       ├── regular_works.py   # /api/regular-works[/{id}/...]（cron 排程任務）
│       └── project.py         # /api/epics, /api/epics/{eid}/stories, /api/project-tasks
├── core/                    # 跨層基礎（DB、license、ADK client、notifiers）
│   ├── adk_client.py
│   ├── database.py / models.py
│   ├── license.py           # Ed25519-signed license + plan limits
│   └── notifiers/           # discord, telegram, line, email + dispatcher.py
├── utils/                   # 純 utility，按 domain 分檔
│   ├── paths.py             # VERSION, PATHS, _project_root, _base_dir, _runtime_root, _workspace_root
│   ├── serialization.py     # _dt_to_z, _serialize_row
│   ├── validators.py        # _validate_cron, _validate_a2a_url
│   ├── ports.py             # _next_available_port, _next_available_channel_port
│   ├── plugin_env.py        # _prompt_model_config, _prompt_and_write_plugin_env
│   ├── compose.py           # _write_channel_fragment
│   ├── deploy.py            # _deploy_local_channel, _deploy_local_agent
│   ├── crypto.py            # encrypt_headers / decrypt_headers (Fernet)
│   └── network.py           # is_safe_url (SSRF guard)
├── tests/                   # pytest 測試（host-side，**不需 deploy 任何容器**）
│   ├── conftest.py          # in-memory SQLite db_session fixture；ADK_SESSION_SERVICE_URI 預設
│   └── test_*.py            # 88 tests covering crypto/network/_shared/license/auth/task_helpers/...
├── frontend/                # Web Dashboard（純靜態 + fetch API）
│   ├── index.html
│   ├── views/ / js/ / css/
└── docker-compose.yaml      # 核心 compose（不含 agent/channel 插件）
```

## 2. 核心架構約定

### 2.1 通用層次
- **CLI → services/**：CLI 命令只負責參數解析與輸出，業務邏輯在 `services/` 層；`services/runtime/` 是 docker 抽象，CLI 不該直接 `subprocess.run(["docker", ...])`。
- **`config.json` 由 `services/config.py` 讀寫**，gitignored、Mac Mini 上的 `.env` 與 `config.json` 不會被 `git reset` 覆蓋。
- **MCP 工具命名**：`mcp_servers/tools/` 下的工具命名規範同 `skill/costaff-agent/MCP_TOOLS_SKILL.md`（檔名不得與 Python 標準庫或 sub-agent 自己的 MCP tool 衝突；之前踩過 `list_workspace`，已改名 `list_data_files`）。
- **通知器**：`core/notifiers/` 各平台通知器；`core/notifiers/dispatcher.py` 統一 dispatch 介面，executor 與 manager agent 都從這個 dispatcher 出。

### 2.2 Manager Agent 特有
- **AgentTool 不是 sub_agents**：`agents/costaff_agent/agent.py` 的 manager 用 `tools=[*mcp_toolsets, skills, *AgentTool(remote)]`、`sub_agents=[]`。`sub_agents/__init__.py` 的 `load_all_remote_agent_tools()` 包 `AgentTool(agent=RemoteA2aAgent(...))`。**禁止**改回 `sub_agents=[RemoteA2aAgent(...)]` + `transfer_to_agent` — 那會把 session history 含 user 「OK」 一起送給 sub-agent，造成 sub-agent 進入對話模式不執行。詳見 `skill/costaff-agent/A2A_SERVER_SKILL.md` Section 3 + `tests/test_remote_agent_tools.py`（10 個 regression test 鎖住此契約）。
- **MCP whitelist**：plugin agent 連 manager core MCP 時透過 `config.json` 的 `agent_mcp_filters` 限制可見 tool（見 Section 2.3）。
- **Sub-agent 控制權自動回**：透過 A2A `RemoteA2aAgent` wrapper 自動把 sub-agent 的 return value 帶回 manager turn，hub-and-spoke flow 是「manager → A → manager → B → manager → user」。

### 2.3a Agent Protocol v1.0

**The authoritative contract for any external agent (first-party or third-party) is `docs/AGENT_PROTOCOL_v1.0.md`.** Anything that touches manifest schema, A2A endpoint behaviour, the four core MCP tools, the workspace conventions, or `agent_mcp_filters` semantics MUST stay consistent with that spec.

- Spec: `costaff/docs/AGENT_PROTOCOL_v1.0.md`
- Manifest JSON Schema: `costaff/docs/schemas/costaff.agent.json.schema.json`
- Tool JSON Schemas: `costaff/docs/schemas/tools/*.schema.json`
- Validator: `services/agent_protocol.py` (`validate_manifest`)
- CLI hook: `costaff agent add --strict` runs full schema validation; lenient mode warns on missing `protocol_version`.

When changing the four core tools' signatures or adding a new core tool, **bump `protocol_version` in `services/agent_protocol.py`**'s `LATEST_PROTOCOL_MINOR` and document the change in the spec's §13 changelog. Breaking changes need a MAJOR bump.

### 2.3 MCP Whitelist (`agent_mcp_filters`)

`config.json` schema（gitignored，Mac Mini 上手動維護）：

```json
{
  "agent_mcp_filters": {
    "coding": {
      "costaff": ["send_message_now", "add_task_comment", "move_to_shared", "list_data_files"]
    },
    "business_analysis": {
      "costaff": ["send_message_now", "add_task_comment", "move_to_shared", "list_data_files"]
    }
  }
}
```

**為什麼要這樣**：manager core MCP 暴露 ~42 個 tool，每個 plugin agent 只需要 4 個（progress 通知 + 寫 task comment + 檔案管理）。沒有 filter 的話 sub-agent 看到 80+ tool spec → token bloat、tool 選錯、可能撞名。

**注意 key 命名**：`agent_mcp_filters` 的 key 用底線（`business_analysis`），對齊 `services/config.py` 的 `agent_key = ext_name.replace("-", "_")` 慣例；config.json 的 `external_agents` key 仍用連字號（`business-analysis`）。

修 `agent_mcp_filters` 後執行：
```bash
ssh Simon-Mac-Mini-Remote 'cd ~/.costaff/costaff && python3 -c "from services.config import ConfigManager; ConfigManager.update_mcp_urls()"'
ssh Simon-Mac-Mini-Remote 'costaff agent rebuild coding && costaff agent rebuild business-analysis'
```
（agent restart 不夠，需要 rebuild 才會讓 plugin 重讀新的 `<NAME>_AGENT_MCP_URLS` 環境變數）

### 2.4 測試與部署
- **`utils/` 已完全 domain-split**：直接 import `utils.paths` / `utils.serialization` / `utils.validators` / `utils.ports` / `utils.plugin_env` / `utils.compose` / `utils.deploy`，不要再寫 `from utils.helpers import …`（殼已刪）。
- **`tests/` 純 host-side**：pytest 跑完不影響任何 container；改完 `git push` 就好，不用 deploy 容器。
- **`server/app.py` 的 FastAPI 跑在 host**（由 `costaff dashboard` 啟動），不在 manager 容器內。所以改 `server/` 或 `utils/` 後 **只需** `pip install -e ~/.costaff/costaff`，**不用** rebuild 任何容器。

## 3. 常用除錯

```bash
# Core MCP server 日誌
docker logs costaff-mcp-costaff 2>&1 | tail -30

# Manager Agent 日誌
docker logs costaff-agent-costaff 2>&1 | tail -30

# Sub-agent 是否被 manager 真的呼叫過 A2A
docker logs costaff-agent-costaff 2>&1 | grep "POST http://costaff-agent-"
docker logs costaff-agent-coding 2>&1 | grep "POST / HTTP"

# Sub-agent 是否實際執行 tool（不只 ListToolsRequest）
docker logs costaff-mcp-coding 2>&1 | grep "CallToolRequest"

# 確認 MCP whitelist 套上了（log 有 "filtered to N tools"）
docker logs costaff-agent-coding 2>&1 | grep "Added extra MCP"

# 跑全套單元測試
python3 -m pytest tests/ -q
```

## 4. 修改後部署

| 改動位置 | 部署方式 |
|---|---|
| `cli/`、`server/`、`utils/`、`services/`、`tests/`（host-side） | `git push` → Mac Mini `git reset --hard origin/main` + `pip install -e .` |
| `mcp_servers/`、`agents/costaff_agent/` | 同上 + `docker compose up -d --build --force-recreate costaff-agent-costaff costaff-mcp-costaff` |
| `config.json`（`agent_mcp_filters` 等） | 直接編輯 Mac Mini `~/.costaff/costaff/config.json` + `ConfigManager.update_mcp_urls()` |
| Plugin agent (coding/BA) 的程式碼 | 各自的 git repo `git push` → Mac Mini reset 對應的 src/ → `costaff agent rebuild <name>` |

**`restart` vs `rebuild`**：
- `costaff agent restart <name>` — 只重啟容器，**不**重 build image，跑的是舊 code。
- `costaff agent rebuild <name>` — 重 build image + 重啟，才能套用新 code 或新 env var。
- 改了 plugin agent 程式碼或 `<NAME>_AGENT_MCP_URLS`：**用 rebuild**。
- 只想清掉 stuck container 狀態：用 restart。

## 5. 已消滅的 god modules（重構記錄）

下列檔曾是巨型 god module，已拆成 domain modules（URL/CLI 介面完全沒變）：

| 原檔（已不存在或變殼） | 拆成 |
|---|---|
| `utils/helpers.py` (528 行 → 已刪除) | `paths.py` / `serialization.py` / `validators.py` / `ports.py` / `plugin_env.py` / `compose.py` / `deploy.py` |
| `server/routers/users.py` (500 行, 22 endpoints) | `identity.py` / `chat_inspect.py` / `integrations.py` / `proxies.py` |
| `server/routers/tasks.py` (405 行, 18 endpoints) | `regular_works.py` / `project.py` |
| `cli/commands/agent.py` (441 行) | 自己變 23 行 registry + `agent_lifecycle.py` / `agent_container.py` / `agent_model.py` |

未來若有 PR 試圖把新 endpoint 塞進舊大檔（特別是 `users.py` 的舊位置），請拒絕並指向對應 domain router。
