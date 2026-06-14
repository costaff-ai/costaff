# CoStaff

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Docker Support](https://img.shields.io/badge/docker-supported-blue.svg)](https://www.docker.com/)
[![Google ADK](https://img.shields.io/badge/Google%20ADK-2.1-orange.svg)](https://github.com/google/adk-python)
[![MCP](https://img.shields.io/badge/MCP-enabled-green.svg)](https://modelcontextprotocol.io/)
[![A2A Protocol](https://img.shields.io/badge/A2A-protocol-violet.svg)](https://github.com/google/A2A)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)

**繁體中文** | [English](./README.md)

**CoStaff** 是一個自架、隱私優先的 AI Agent 平台，基於 **Google ADK（Agent Development Kit）** 和 **Model Context Protocol（MCP）** 構建。它連接你偏好的聊天平台——**Telegram、Discord 和 Line**——並提供功能完整的 Web 儀表板，讓操作者管理 Agent、工具、使用者與對話。

外部 Agent（如 [`costaff-agent-coding`](https://github.com/costaff-ai/costaff-agent-coding) 和 [`costaff-agent-business-analysis`](https://github.com/costaff-ai/costaff-agent-business-analysis)）透過 **A2A 協議**整合，在不修改核心的情況下擴展平台能力。

---

## 目錄

- [功能特色](#功能特色)
- [系統架構](#系統架構)
- [Web 儀表板](#web-儀表板)
- [外部 Agent](#外部-agent)
- [技術棧](#技術棧)
- [快速開始](#快速開始)
- [CLI 指令參考](#cli-指令參考)
- [Bot 指令](#bot-指令)
- [授權](#授權)

---

## 功能特色

- **多 Agent 編排** — 主 CoStaff Agent 透過 A2A 協議將任務委派給外部 Agent；任何含有 `costaff.agent.json` 宣告的 Agent 都可一鍵接入
- **逐 Agent 工具指派** — 從儀表板指定每個 Agent 可存取的 MCP、API 和 Skill，套用後針對性重啟，無需全量重新部署
- **動態 MCP 層** — 核心 MCP 始終存在；可在儀表板即時新增外部 MCP（Streamable HTTP 或 SSE）
- **API 與 Skill 登記冊** — 在資料庫中登記外部 REST API 和可重用的提示詞範本，按 Agent 和使用者分別指派
- **多平台支援** — 開箱即用的 Telegram、Discord 和 Line Bot
- **多模型支援** — 原生支援 Google Gemini，或任何 LiteLLM 相容的模型提供者
- **安全身份雜湊** — 平台 ID 對應至 16 字元 SHA-256 雜湊，真實 ID 永不儲存
- **身份審核流程** — 新使用者進入待審狀態，操作者從儀表板核准後才能使用
- **使用者檔案記憶** — Agent 跨對話記住姓名、職稱、公司、聯絡資訊和偏好設定
- **主動提醒** — 排程 Cron 通知，推送至任何已連接的聊天平台
- **看板任務自動化** — 排程執行的 Agent 任務（網路搜尋、資料庫查詢、報告生成），結果主動推送給使用者
- **Web 儀表板** — 支援深色/淺色模式的操作者控制台，全生命週期管理

---

## 系統架構

CoStaff 採用**插件式架構**。核心平台（Agent + MCP + 儀表板）作為獨立 Docker Stack 運行。Channel 和外部 Agent 各自擁有獨立的 Docker 專案，透過共用的 `costaff_default` 網路連接到核心。

```mermaid
graph TD
    subgraph Channels ["Channel 插件（各自獨立的 Docker 專案）"]
        CH_TG[costaff-channel-telegram]
        CH_DC[costaff-channel-discord]
        CH_LN[costaff-channel-line]
        CH_WEB[costaff-channel-webchat]
    end

    subgraph Core ["CoStaff 核心（.costaff/）"]
        CoStaffAgent[CoStaff Agent\nGoogle ADK]
        MCP_Core[核心 MCP\nAPScheduler + 通知器]
        DB[(PostgreSQL)]
        API[FastAPI 後端]
        Dashboard[Web 儀表板]
    end

    subgraph Agents ["外部 Agent 插件（各自獨立的 Docker 專案）"]
        AG_CODE[costaff-agent-coding\nA2A]
        AG_BA[costaff-agent-business-analysis\nA2A]
    end

    CH_TG & CH_DC & CH_LN & CH_WEB -->|HTTP ADK API| CoStaffAgent
    CoStaffAgent <--> MCP_Core
    CoStaffAgent -->|A2A| AG_CODE & AG_BA
    MCP_Core <--> DB
    MCP_Core -->|推送| CH_TG & CH_DC & CH_LN & CH_WEB
    Dashboard <--> API
    API <--> DB
    API -->|重啟| CoStaffAgent
```

所有插件透過 **`costaff_default` Docker 網路**連接——服務之間不需要 port mapping 或 tunnel。

---

## Web 儀表板

儀表板（`costaff dashboard`）是支援深色/淺色模式的瀏覽器操作控制台：

| 模組 | 說明 |
|------|------|
| **Dashboard** | 即時系統狀態（CPU、記憶體、磁碟）與服務健康概覽 |
| **Chat** | 直接在瀏覽器中與 CoStaff Agent 對話，含完整對話歷史 |
| **Agents** | 查看內外部 Agent 狀態；設定逐 Agent 的 MCP 指派，Apply & Restart 即生效 |
| **MCPs** | 管理 MCP 擴充 — 即時新增/移除外部 MCP |
| **APIs** | 登記外部 REST API 設定，按 Agent 和使用者指派 |
| **Skills** | 登記可重用提示詞範本，按 Agent 和使用者指派 |
| **Reminders** | 查看和管理排程 Cron 提醒 |
| **Tasks** | 監控看板式自動化任務結果 |
| **Users** | 身份對應表與使用者檔案詳情面板 |
| **Sessions** | 瀏覽對話 Session；事件日誌顯示完整的 Function Call / Response 追蹤 |
| **Channels** | 設定 Telegram / Discord / Line Bot Token |
| **Config** | 主題、模型提供者、審核閘門設定 |
| **Logs** | 即時串流任意服務的容器日誌 |

---

## 外部 Agent

CoStaff 支援部署和管理透過 **A2A 協議**溝通的外部 Agent。

任何包含 `costaff.agent.json` 宣告的專案都可以被登記和部署：

```bash
# 部署本地 Agent 專案
costaff agent add my-agent --local /path/to/my-agent

# 從 GitHub clone 並部署（可用 --tag 釘選 release）
costaff agent add my-agent --github https://github.com/you/my-agent --tag v0.1.0-alpha-2

# 新增遠端 URL Agent
costaff agent add my-agent --url http://my-agent.example.com

# 列出所有 Agent
costaff agent list
```

**官方第一方 Agent：**

| Agent | Repository | 職責 |
|-------|------------|------|
| Coding Agent | [costaff-agent-coding](https://github.com/costaff-ai/costaff-agent-coding) | 沙盒 Python 程式碼執行 |
| Business Analysis Agent | [costaff-agent-business-analysis](https://github.com/costaff-ai/costaff-agent-business-analysis) | BI 報告生成與數據視覺化 |

---

## 插件架構說明

CoStaff 設計為**可插拔平台**。Channel 和 Agent 都是獨立的 Docker 專案，在執行期間掛接到核心——無需修改核心程式碼。

### 插件如何連接

每個插件（Channel 或 Agent）加入共用 Docker 網路：

```yaml
# 插件的 docker-compose.yaml 中
networks:
  default:
    external: true
    name: costaff_default
```

這讓插件可以直接透過容器主機名稱存取 `costaff-agent-costaff`（ADK API，port 8080）和 `costaff-mcp-costaff`（MCP，port 8000）。

### Channel 插件

Channel 是獨立的 Bot 或 HTTP 伺服器，負責：
1. 接收來自使用者的訊息（Telegram、Discord、LINE、HTTP）
2. 透過 ADK API 的 `POST /run` 轉發給 CoStaff Agent
3. 接收來自 MCP 通知器的推送訊息

內建 Channel 存放於 `.costaff/dynamic-channels/`，執行 `costaff start` 時自動啟動。

### Agent 插件

外部 Agent 公開相容 **A2A 協議**的端點，並登記 `costaff.agent.json` manifest。CoStaff Agent 會自動發現並委派任務給它們。

```bash
# 登記本地 Agent 專案
costaff agent add my-agent --local /path/to/my-agent

# 登記遠端 Agent
costaff agent add my-agent --url http://my-agent.internal
```

---

## 技術棧

| 層級 | 技術 |
|------|------|
| Agent 框架 | [Google ADK](https://github.com/google/adk-python) |
| Agent 間通訊 | A2A Protocol（`RemoteA2aAgent`） |
| 工具協議 | [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) |
| AI 模型 | Google Gemini、LiteLLM 相容提供者 |
| Telegram Bot | [Aiogram 3.x](https://docs.aiogram.dev/) |
| Discord Bot | [discord.py](https://discordpy.readthedocs.io/) |
| Line Bot | [line-bot-sdk](https://github.com/line/line-bot-sdk-python) |
| Web 後端 | [FastAPI](https://fastapi.tiangolo.com/) + [uvicorn](https://www.uvicorn.org/) |
| 資料庫 | [SQLAlchemy](https://www.sqlalchemy.org/) — PostgreSQL（必要） |
| 排程器 | [APScheduler](https://apscheduler.readthedocs.io/) |
| 部署 | Docker + Docker Compose |
| CLI | [Typer](https://typer.tiangolo.com/) + [Rich](https://rich.readthedocs.io/) |

---

## 快速開始

### 前置需求

- Python 3.10+
- Docker 與 Docker Compose
- 來自 [Google AI Studio](https://aistudio.google.com/) 的 **Gemini API Key**（或任何 LiteLLM 相容的模型提供者）

### 最快啟動方式（不需要 Bot Token）

內建的 **Webchat** Channel 可以讓你立即開始使用，無需設定任何 Telegram、Discord 或 Line Token。

```bash
# 1. 安裝 CLI
pip install -e .

# 2. 執行設定精靈（只需填入 Gemini API Key）
costaff onboard

# 3. 啟動平台
costaff start

# 4. 開啟儀表板
costaff dashboard
```

`costaff start` 會先做 **preflight 檢查**（API Key、資料庫連線、密鑰），
缺什麼會直接告訴你怎麼修，而不是讓容器無聲地 crash-loop。

開啟 **http://localhost:8501**，進入 **Chat**，即可立即開始與 Agent 對話。
若有任何異常，先跑 `costaff doctor` —— 它會逐項診斷並在結尾列出**建議修復步驟**。

之後想新增 Bot Channel，只需前往 **儀表板 → Channels** 輸入 Token——無需重啟核心平台。

### 完整設定

設定精靈（`costaff onboard`）會引導你完成：
- AI 模型提供者選擇（Gemini 或 LiteLLM）
- PostgreSQL 連線設定
- Bot Token 設定（Telegram、Discord、Line——皆為選填）
- 儀表板管理員帳號設定
- 身份雜湊鹽值設定

所有設定儲存至當前目錄的 `.costaff/`。

---

## CLI 指令參考

### 日常操作

| 指令 | 說明 |
|------|------|
| `costaff onboard` | 互動式設定精靈 |
| `costaff bootstrap` | 非互動設定（讀環境變數、自動產生密鑰，供 CI / headless 用） |
| `costaff start` | 依正確順序建置並啟動所有服務 |
| `costaff start --no-build` | 不重建映像直接啟動 |
| `costaff stop` | 停止所有服務 |
| `costaff restart` | 重啟所有服務 |
| `costaff status` | 顯示運行中服務的狀態 |
| `costaff logs <service>` | 串流單一服務（或全部）的日誌 |
| `costaff dashboard` | 開啟 Web 儀表板 |
| `costaff chat` | 在終端機與 Agent 對話 |
| `costaff invoke <message>` | 送一則訊息後結束（適合腳本） |
| `costaff doctor` | 診斷常見問題，結尾列出建議修復步驟 |
| `costaff update` | 從 GitHub 拉取最新 core 版本 |
| `costaff update --tag <ref>` | 將 core 釘選到指定 release tag（或回退） |
| `costaff core-rebuild` | 只重建並重新建立 core stack |

### 管理 Agent

```bash
costaff agent list                                  # 列出 Agent（含釘選的 Ref）
costaff agent add <name> --github <url>             # 從 GitHub clone 並部署
costaff agent add <name> --github <url> --tag <ref> # clone 時釘選到 release tag
costaff agent add <name> --local <path>             # 部署本地 Agent 專案
costaff agent add <name> --url <a2a URL>            # 登記遠端 A2A 端點
costaff agent tags <name>                           # 列出該 Agent origin 上的 release tags
costaff agent rebuild <name> [--tag <ref>]          # 重建並重啟（可重新釘選）
costaff agent enable <name> / disable <name>        # 啟用 / 停用 Agent
costaff agent remove <name>                         # 移除 Agent
costaff agent model                                 # 查看 / 設定逐 Agent 模型
```

### 管理 Channel

```bash
costaff channel list                    # 列出 Channel（含健康狀態與釘選 Ref）
costaff channel add <name> [--tag <ref>] # 新增 Channel（官方名稱自動解析 GitHub URL）
costaff channel tags <name>             # 列出該 Channel origin 上的 release tags
costaff channel rebuild <name> [--tag <ref>]  # 重建並重啟（可重新釘選）
costaff channel remove <name>           # 移除 Channel
```

### 管理商業平台

ERP / CRM / SCM / HRM / 會計等商業平台套件，各自為獨立 Docker 專案，共用同一個 PostgreSQL 與 Account Manager（OIDC SSO）：

```bash
costaff platform list             # 依相依順序列出平台與健康狀態
costaff platform add <name>       # 官方名稱自動解析 repo，並接好共用 DB + OIDC
costaff platform rebuild <name>   # 重建並重啟平台
costaff platform start | stop     # 依相依順序（db 先）啟停整套
costaff platform provision        # 重跑共用 DB 的 role/database 佈建（冪等）
costaff platform remove <name>    # 移除平台（加 --purge 連 volume 一起刪）
```

### 其他

```bash
costaff config validate           # 依 schema 驗證 config.json
costaff database info             # 顯示資料庫連線與資料表摘要
costaff database backup           # 匯出 PostgreSQL 資料庫
costaff database restore <file>   # 從 dump 還原資料庫
costaff database clean            # 刪除並重建 schema（破壞性）
costaff license                   # 管理 CoStaff 授權
```

> **版本釘選**：每個 plugin 都可釘選到 release tag，讓主機跑的是一組可重現的版本，而非各自追 `main`。釘選會寫進 `config.json`，每次 rebuild 都會沿用。可用的 tag 見 [Releases](https://github.com/costaff-ai/costaff/releases)。

---

## Bot 指令

適用於 Telegram、Discord 和 Line：

| 指令 | 說明 |
|------|------|
| `/start` | 初始化 Session 並驗證身份 |
| `/profile` | 查看已儲存的個人檔案 |
| `/list` | 列出有效的提醒和任務 |
| `/reset` | 清除當前對話上下文 |
| `/help` | 顯示可用指令 |

**自然語言範例：**

- 「每天下午三點提醒我喝水。」
- 「每天早上九點搜尋最新 AI 新聞並發摘要給我。」
- 「分析這份 CSV 並生成一份含圖表的 HTML 報告。」
- 「記住我叫 Simon，職稱是軟體工程師。」

---

## 授權

本專案採用 **AGPL v3 + 商業授權**雙授權模式。

- **個人使用**（自己跑在自己的硬體上，OSS 上限內 — 3 agents / 1 user / 10 skills）：**AGPL v3，免費**。
- **對外提供 CoStaff 服務**（轉售、做成 SaaS、讓客戶跟你架的 CoStaff 對話）：觸發 **AGPL §13**，必須公開修改後的 source code（包含私有 skills / prompts / workflow code），**或**取得免除此義務的**商業授權**。
- **散布修改版 CoStaff**（fork 出去交付給他人）：適用 AGPL v3 標準義務。

完整條款詳見 [`LICENSE`](./LICENSE)。

## 商業授權

OSS tier 是**個人使用專屬** — 3 agents / 1 user / 10 skills，定位於評估、demo、自架個人 AI 助理。2+ users 或更高 quota 請看付費方案：

- **更高 limits** — 更多 agents / users / skills（Starter / Pro / Enterprise 三檔）
- **Enterprise WebChat** — 多租戶 Org × Team × CoStaff 路由、audit logs、SSO、檔案傳遞、sub-agent progress panel
- **Premium Agents** — 針對特定 vertical 的 production-grade 專家 agent
- **Field deployment engagement** — onboarding / 客製 / 整合支援
- **AGPL §13 豁免** — 對外提供 CoStaff 服務時不需公開修改

定價方案、比較表、購買流程：**https://costaffs.app**

## 支援管道

- 文件：[`docs/`](./docs) 目錄
- Issues：https://github.com/costaff-ai/costaff/issues
- Discussions：https://github.com/costaff-ai/costaff/discussions
- 安全性回報：見 [`SECURITY.md`](./SECURITY.md)
