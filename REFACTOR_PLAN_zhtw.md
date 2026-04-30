# CoStaff Core 重構計畫

本文件記錄 `costaff/` repo 的結構審查結果與後續優化計畫，分為三大類：**資料夾擺放**、**命名**、**檔案刪除**。

---

## A. 資料夾擺放優化

### A.1 `src/core/` 與 root 包並列導致分層不一致

目前 root 同時存在：`cli/`、`managers/`、`server/`、`mcp_servers/`、`agents/`、`utils/`、`models/`，
而 `src/` 底下卻只裝了一個 `core/` 子套件——半套 src-layout，是歷史遺留。

**建議方案（擇一）**：
- **方案 A（推薦，改動最小）**：把 `src/core/` 上提到 root，改名 `core/`，刪掉空殼 `src/`。
  所有 `from src.core.X` 改為 `from core.X`。
- **方案 B（徹底 src-layout）**：把所有 root 套件全塞進 `src/costaff/` 下，並設定 `setup.py` 的 `package_dir`。
  改動較大，但 import 路徑會乾淨。

### A.2 `agents/costaff_agent/utils/` 結構錯置

目前：
```
agents/costaff_agent/
├── agent.py
└── utils/
    ├── instructions/   # agent_instruction.md
    ├── skills/         # 10 個 ADK skills
    └── models/         # litellm_model 設定
```

`instructions/`、`skills/`、`models/` 都不是 utils。建議攤平：
```
agents/costaff_agent/
├── agent.py
├── instructions/
├── skills/
└── models/
```

### A.3 `models/` 應屬於 `server/`

`models/requests.py` 整支只被 `server/routers/*.py` 使用，與 `src/core/models.py`（SQLAlchemy ORM）撞名混淆。

**動作**：搬到 `server/schemas.py`，刪除 root `models/`。
**狀態**：✅ 已執行（見 §C 變更紀錄）

### A.4 `mcp_servers/utils.py` 歸屬模糊

該檔同時包含：加解密、SSRF 防護、跨 channel 通知 dispatch、project task helper。
**建議拆三份**：
- 加解密 → `src/core/crypto.py`（與現有 `utils/crypto.py` 合併）
- SSRF / network → 合併進 `utils/network.py`
- 通知 dispatch → `src/core/notifiers/dispatcher.py`

### A.5 `cli/commands/license_cmd.py` 命名特例

唯一帶 `_cmd` 後綴的 CLI 命令檔（避開 Python 內建模組 `license`）。
**建議**：改名 `cli/commands/licensing.py`。

---

## B. 命名建議

| 目前 | 問題 | 建議 |
|---|---|---|
| `models/` (root) | 與 `src/core/models.py` 撞名 | 移除（已併入 `server/schemas.py`） |
| `src/core/models.py` | "models" 太籠統 | `src/core/orm.py` 或 `src/core/db_models.py` |
| `mcp_servers/` | 複數但只有一個 server | `mcp_server/` |
| `managers/` | 抽象，內容是核心商業邏輯 | `services/` 或 `core_logic/` |
| `agents/costaff_agent/utils/` | 不是 utils | 攤平成 `instructions/`、`skills/`、`models/` |
| `cli/commands/services.py` | 與 `server/`（service 層）混 | `cli/commands/lifecycle.py` |
| `cli/commands/license_cmd.py` | 唯一 `_cmd` 後綴 | `cli/commands/licensing.py` |
| `frontend/js/api.js` | 與 `apis.js` 差一字母 | `httpClient.js` ✅ 已執行 |
| `frontend/js/apis.js` | 與 `api.js` 差一字母 | `apisView.js` ✅ 已執行 |
| `utils/helpers.py` (528 行) | god module | 拆 `paths.py`、`prompts.py`、`compose_helpers.py` |
| `agents/costaff_agent/` | 暗示是「插件」，但實為內建 Manager Agent | `manager_agent/`（與 CLAUDE.md 用詞一致） |

---

## C. 檔案刪除

### C.1 立即可刪（git 未追蹤的本地殘留）

- `.DS_Store`：✅ 已執行
- 所有 `__pycache__/`：✅ 已執行
- `costaff_cli.egg-info/`：✅ 已執行

### C.2 評估後可刪

- `models/__init__.py` + `models/requests.py` → 已搬至 `server/schemas.py`，root `models/` 已刪除 ✅
- `utils/crypto.py` 與 `mcp_servers/utils.py` 中的 Fernet 加解密邏輯重複，整合至 `src/core/crypto.py` 後刪除其一（**待處理**）

### C.3 不要刪

- 所有空 `__init__.py`（15 個）：Python 套件辨識需要
- `Dockerfile` 與 `agents/costaff_agent/Dockerfile`：兩支不同用途的 image 定義
- `costaff.py` (root) 與 `cli/__init__.py`：`setup.py` entry point 依賴
- `README.md` 與 `README_zhtw.md`：雙語並存合理

---

## D. 已完成的變更紀錄

### D.1 本地清理
```bash
find . -name ".DS_Store" -delete
find . -type d -name __pycache__ -exec rm -rf {} +
rm -rf costaff_cli.egg-info/
```

### D.2 Frontend JS 重命名
- `frontend/js/api.js` → `frontend/js/httpClient.js`
- `frontend/js/apis.js` → `frontend/js/apisView.js`
- 更新 `frontend/index.html` 中的 `<script src=...>` 引用

### D.3 Pydantic Schema 搬遷
- `models/requests.py` → `server/schemas.py`
- 刪除空殼 `models/` 目錄
- 更新 6 支 router 的 import：
  - `server/routers/auth.py`
  - `server/routers/system.py`
  - `server/routers/config.py`
  - `server/routers/users.py`
  - `server/routers/agents.py`
  - `server/routers/tasks.py`

---

## E. 後續優先級

| 優先級 | 工作 | 風險 | 預估工時 |
|---|---|---|---|
| P1 | `src/core/` 上提到 root（A.1 方案 A） | 中（影響 ~20 支檔案 import） | 1h |
| P1 | `agents/costaff_agent/utils/` 攤平（A.2） | 低 | 30min |
| P2 | `mcp_servers/utils.py` 拆分（A.4） | 中（mcp_servers 內多處引用） | 1h |
| P2 | `cli/commands/license_cmd.py` 改名（A.5） | 低 | 10min |
| P3 | `managers/` → `services/` 或 `core_logic/`（B 表） | 中（影響 cli/server 兩端） | 1h |
| P3 | `utils/helpers.py` 拆分（B 表） | 中 | 2h |

> 建議在下一次大版本（v0.3.0）統一執行 P1/P2，避免 commit 史散亂。
