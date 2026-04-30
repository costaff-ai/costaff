# CoStaff Core 開發規範

適用於 `costaff/`（CLI、Manager Agent、MCP Core、API Server、前端）的開發準則。

## 1. 目錄結構與職責

```
costaff/
├── costaff.py               # CLI 入口（Click group）
├── cli/commands/            # CLI 子命令
│   ├── services.py          # costaff start/stop/restart/ps
│   ├── agent.py             # costaff agent add/list/remove/restart/rebuild
│   ├── channel.py           # costaff channel add/list/remove/rebuild
│   ├── database.py          # costaff database backup
│   ├── onboard.py           # costaff onboard（首次設定）
│   ├── doctor.py            # costaff doctor（健康診斷）
│   ├── dashboard.py         # costaff dashboard
│   ├── license_cmd.py       # costaff license
│   └── update.py            # costaff update
├── managers/                # 核心邏輯層
│   ├── config.py            # config.json 讀寫（external_agents, dynamic_channels）
│   ├── docker.py            # Docker Compose 操作
│   ├── auth.py              # 使用者驗證
│   ├── database.py          # Postgres 連線與操作
│   └── audit.py             # 審計日誌
├── agents/costaff_agent/    # Manager Agent（ADK LlmAgent）
│   ├── agent.py
│   └── instructions/agent_instruction.md
├── mcp_servers/             # Core MCP Server（供 Manager Agent 使用）
│   ├── server.py
│   ├── tools/               # MCP 工具（messaging, projects, tasks, diary...）
│   └── executors/           # 背景執行器（reminder, regular_work, project_task）
├── server/                  # FastAPI API Server
│   ├── app.py
│   └── routers/             # agents, auth, config, diary, system, tasks, users
├── src/core/                # 共用底層
│   ├── adk_client.py        # ADK 連線
│   ├── database.py          # DB models / session
│   ├── license.py           # 授權驗證
│   └── notifiers/           # discord, telegram, line, email 通知器
├── frontend/                # Web Dashboard（純靜態 + fetch API）
│   ├── index.html
│   ├── views/               # agents, chat, tasks, diary, mcps, skills...
│   ├── js/                  # app.js, api.js, ui.js...
│   └── css/
└── docker-compose.yaml      # 核心 compose（不含 agent/channel 插件）
```

## 2. 核心架構約定

- **CLI → Managers**：CLI 命令只負責參數解析與輸出，業務邏輯在 `managers/` 層。
- **config.json**：由 `managers/config.py` 讀寫，結構見頂層 `CLAUDE.md` Section 3.4。修改後需重新產生 `EXTERNAL_AGENTS_CONFIG`。
- **MCP Tools 命名**：`mcp_servers/tools/` 下的工具命名規範同 `skill/costaff-agent/MCP_TOOLS_SKILL.md`（工具檔名不得與 Python 標準庫衝突）。
- **通知器**：`src/core/notifiers/` 各平台通知器，供 executors 和 Manager Agent 使用。

## 3. 常用除錯

```bash
# Core MCP server 日誌
docker logs costaff-mcp-costaff 2>&1 | tail -30

# Manager Agent 日誌
docker logs costaff-agent 2>&1 | tail -30

# API server 日誌（含 FastAPI）
docker logs costaff-agent 2>&1 | grep -E "ERROR|WARNING"
```

## 4. 修改後部署

```bash
# 本地改完 push 後，Mac Mini 拉新版並重建
ssh Simon-Mac-Mini-Remote "cd ~/.costaff/costaff && git fetch origin && git reset --hard origin/main"
ssh Simon-Mac-Mini-Remote "pip install -e ~/.costaff/costaff -q"

# 若 mcp_servers/ 有改動，重建 MCP 容器
ssh Simon-Mac-Mini-Remote "docker compose -f ~/.costaff/costaff/docker-compose.yaml up -d --build --force-recreate costaff-mcp-costaff"
```
