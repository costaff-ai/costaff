# CoStaff

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Docker Support](https://img.shields.io/badge/docker-supported-blue.svg)](https://www.docker.com/)
[![Google ADK](https://img.shields.io/badge/Google%20ADK-2.0-orange.svg)](https://github.com/google/adk-python)
[![MCP](https://img.shields.io/badge/MCP-enabled-green.svg)](https://modelcontextprotocol.io/)
[![A2A Protocol](https://img.shields.io/badge/A2A-protocol-violet.svg)](https://github.com/google/A2A)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)

[繁體中文](./README_zhtw.md) | **English**

**CoStaff is a self-hosted AI assistant platform you run on your own machine.**
Talk to your assistant from Telegram, Discord, LINE, or a built-in web chat;
manage everything from a browser-based dashboard. No cloud account, no
data leaves your hardware.

> **Note:** CoStaff is shipped as **self-hosted software** (Path A in our
> [deployment strategy](docs/DEPLOYMENT_STRATEGY.md)). You install it on
> your laptop, on a home server, or on a VPS you own — we don't host
> anything for you.

---

## Who is this for

- **Operators** who want a personal AI assistant that lives on their own
  hardware and chats from the apps they already use.
- **Small teams** who want a single AI assistant their whole team can
  reach via a shared chat platform.
- **Builders** who want to add their own agents (coding, BA, anything
  speaking the A2A protocol) and tools (any MCP server) to the same chat.

If you want a SaaS that someone else hosts for you, CoStaff is not for
you yet — see the [deployment strategy](docs/DEPLOYMENT_STRATEGY.md) for
when that might change.

---

## What you can do once it's running

- **Chat from your existing apps.** Telegram, Discord, LINE, plus a
  built-in web chat for when you don't want to set up a bot.
- **Schedule reminders in plain language.** "Remind me to drink water at
  3 PM every day" — the assistant pushes a notification at the right time
  to whichever channel you connected.
- **Run recurring tasks.** "Search for the latest AI news every morning
  at 9 AM and send me a summary" — picks up the result, formats it,
  delivers to chat.
- **Hand work to specialist agents.** Coding tasks → the coding agent
  runs Python in a sandbox. BI questions → the business-analysis agent
  builds an HTML report with charts.
- **Manage everything from a browser.** Approve users, attach API keys,
  inspect chat history, watch live container logs.

---

## Prerequisites

| | Minimum | Notes |
|---|---|---|
| OS | macOS 12+ **or** Ubuntu 20.04 / 22.04 / 24.04 | Apple Silicon and Intel both work |
| RAM | 4 GB | 8 GB recommended for comfortable use |
| Disk | 5 GB free | Plus space for your data |
| Network | Outbound HTTPS | To download dependencies + reach AI provider |
| AI provider | A **Gemini API key** | Free tier from [Google AI Studio](https://aistudio.google.com/) is enough to get started; any LiteLLM-compatible provider also works |

> Docker and Python are installed automatically by the installer if not
> already present.

---

## Install

> **In a hurry?** [`docs/QUICKSTART.md`](./docs/QUICKSTART.md) gets you
> chatting in 5 minutes (the same install steps + a guided first chat).

One command, on macOS or Ubuntu:

```bash
curl -fsSL https://raw.githubusercontent.com/costaff-ai/costaff/main/install.sh | bash
```

The installer:
1. Detects your OS and installs missing dependencies (Homebrew /
   Xcode CLT on macOS; deadsnakes Python on Ubuntu; Docker; git; curl).
2. Clones the CoStaff repo to `~/.costaff/costaff`.
3. Creates an isolated Python virtualenv at `~/.costaff/.venv`.
4. Installs the `costaff` CLI into that venv and adds it to your `PATH`.
5. Launches the **setup wizard** — asks for your AI provider key, admin
   credentials, and which channels (if any) you want to set up.

If the installer prints **"manual steps"** at the end (e.g. "log out and
log back in for Docker group membership"), follow them, then run
`costaff onboard` yourself.

---

## First run

After the installer finishes:

```bash
# Start everything (Postgres → external agents → core → channels)
costaff start

# Open the operator dashboard
costaff dashboard
```

The dashboard opens at **http://localhost:8501**. Click **Chat** and
start talking to the assistant — no bot tokens needed.

To add a Telegram / Discord / LINE bot later, go to **Dashboard →
Channels**, paste the token, and apply. The core platform doesn't need
to restart.

---

## Where things live

CoStaff puts everything under a single directory: `~/.costaff/`. You
own this directory; nothing else on your machine is touched.

```
~/.costaff/
├── .venv/                    # Isolated Python environment for the CLI
├── costaff/                  # Source + config
│   ├── .env                  # Your secrets (gitignored, never overwritten)
│   ├── config.json           # System config (gitignored, never overwritten)
│   ├── docker-compose.yaml   # Core stack definition
│   └── ...
├── costaff-agent/<name>/     # Each external agent plugin
│   ├── .env                  # That agent's secrets
│   ├── src/                  # Agent source (git clone)
│   └── compose-fragment.yaml
├── costaff-channel/<name>/   # Each channel plugin (telegram, discord, ...)
│   ├── .env                  # That channel's bot token
│   ├── src/                  # Channel source (git clone)
│   └── compose-fragment.yaml
└── workspace/                # Shared agent data (mounted into containers)
    └── shared/               # Files agents read/write for the user
```

### Secrets

| File | What's in it |
|---|---|
| `~/.costaff/costaff/.env` | Gemini API key, admin password hash, MCP secret, identity hash salt, database URI |
| `~/.costaff/costaff-channel/telegram/.env` | `TELEGRAM_BOT_TOKEN` |
| `~/.costaff/costaff-channel/discord/.env` | `DISCORD_BOT_TOKEN` |
| `~/.costaff/costaff-channel/line/.env` | `LINE_CHANNEL_ACCESS_TOKEN`, `LINE_CHANNEL_SECRET` |
| `~/.costaff/costaff-agent/<name>/.env` | Per-agent credentials |

These files are **never** modified by `costaff update` or any git
operation. Back them up like you'd back up SSH keys.

### Data

| Path | Contains |
|---|---|
| Postgres volume `costaff_postgres_data` | Identity table, sessions, chat history, reminders, recurring tasks |
| `~/.costaff/workspace/shared/` | Files agents produced for you (CSVs, PDFs, reports) |
| `~/.costaff/workspace/agent-<name>/` | Per-agent scratch space |

To back up everything: stop CoStaff, then archive `~/.costaff/` together
with the Postgres volume — see **`costaff database backup`**.

---

## Day-to-day commands

| Command | What it does |
|---|---|
| `costaff start` | Start every CoStaff service, in the right order |
| `costaff start --no-build` | Same, but skip rebuilding Docker images |
| `costaff stop` | Stop everything cleanly |
| `costaff restart` | Stop + start |
| `costaff status` | Show which containers are running |
| `costaff logs <service>` | Tail logs for one service (or all if omitted) |
| `costaff dashboard` | Launch the web dashboard |
| `costaff chat` | Talk to the assistant in your terminal |
| `costaff invoke <message>` | Send one message and exit (handy for scripts) |
| `costaff doctor` | Diagnose common issues; writes a timestamped report |
| `costaff update` | Pull the latest CoStaff release from GitHub |

### Managing agents

```bash
costaff agent list                                  # Show registered agents
costaff agent add <name> --github <repo URL>        # Clone + deploy a GitHub agent
costaff agent add <name> --local <path>             # Deploy a local agent project
costaff agent add <name> --url <a2a URL>            # Register a remote A2A endpoint
costaff agent restart <name>                        # Restart an agent's containers
costaff agent rebuild <name>                        # Rebuild + restart (after code changes)
costaff agent remove <name>                         # Remove an agent
costaff agent model                                 # Inspect/set the per-agent model
```

### Managing channels

```bash
costaff channel list             # Show registered channels with health
costaff channel add <name>       # Add a channel (interactive, official channels auto-resolved)
costaff channel rebuild <name>   # Rebuild + restart a channel
costaff channel remove <name>    # Remove a channel
```

### Other

```bash
costaff config validate          # Validate config.json against the schema
costaff database backup          # Dump the Postgres database to a file
costaff license                  # Manage your CoStaff license
```

---

## Update

```bash
costaff update
```

Pulls the latest release from GitHub and reinstalls the CLI. Your
`.env`, `config.json`, and database are untouched.

If you want to update by version (or roll back), pin the release tag:

```bash
cd ~/.costaff/costaff
git fetch --tags
git checkout v0.2.0           # or any tagged release
pip install -e .
```

---

## Remove

```bash
# Stop everything
costaff stop

# Remove containers, images, and the docker network
docker compose -f ~/.costaff/costaff/docker-compose.yaml down --rmi local --volumes

# (Optional) wipe the Postgres data volume
docker volume rm costaff_postgres_data

# (Optional) delete the install directory and your data
rm -rf ~/.costaff
```

You're back to the state you were in before installing.

---

## Troubleshooting

### `costaff: command not found` after install

Reload your shell so the new PATH entry takes effect:

```bash
source ~/.zshrc      # macOS default
source ~/.bashrc     # Ubuntu default
```

### "Cannot connect to Docker daemon"

- **macOS**: Open Docker Desktop from Launchpad and wait for the whale
  icon in the menu bar.
- **Ubuntu**: Log out and back in (the installer added you to the
  `docker` group), or `newgrp docker` in a new terminal.

### "Port already in use" on start

The dashboard uses `8501`, the core agent `18080`, Postgres `5432`,
the webchat `18091`. Stop whatever else is bound to those ports, or
edit `~/.costaff/costaff/docker-compose.yaml`.

### Bot doesn't reply

```bash
costaff status                                  # Are all containers up?
costaff logs costaff-channel-telegram           # Recent errors?
costaff doctor                                  # Full diagnostic report
```

### Reset everything to a clean state

```bash
costaff stop
docker compose -f ~/.costaff/costaff/docker-compose.yaml down --volumes
costaff start
```

You'll lose chat history and the identity table. Bot tokens and API
keys (in `.env` files) survive.

---

## Architecture

CoStaff is a **plugin platform**. The core (agent + MCP + dashboard)
runs as one Docker stack. Each channel and each external agent runs as
its own Docker project and connects via the shared `costaff_default`
network.

```mermaid
graph TD
    subgraph Channels ["Channel plugins (separate Docker projects)"]
        CH_TG[costaff-channel-telegram]
        CH_DC[costaff-channel-discord]
        CH_LN[costaff-channel-line]
        CH_WEB[costaff-channel-webchat]
    end

    subgraph Core ["CoStaff core (~/.costaff)"]
        CoStaffAgent[costaff-agent-costaff<br/>Google ADK manager]
        MCP_Core[costaff-mcp-costaff<br/>APScheduler + notifier]
        DB[(PostgreSQL)]
        API[FastAPI dashboard backend]
        Dashboard[Web dashboard]
    end

    subgraph Agents ["External agent plugins (separate Docker projects)"]
        AG_CODE[costaff-agent-coding]
        AG_BA[costaff-agent-business-analysis]
    end

    CH_TG & CH_DC & CH_LN & CH_WEB -->|HTTP ADK API| CoStaffAgent
    CoStaffAgent <--> MCP_Core
    CoStaffAgent -->|A2A| AG_CODE & AG_BA
    MCP_Core <--> DB
    MCP_Core -->|push| CH_TG & CH_DC & CH_LN & CH_WEB
    Dashboard <--> API
    API <--> DB
    API -->|restart| CoStaffAgent
```

All chatbot-style channels share a runtime SDK
([costaff-channel-chatbot](https://github.com/costaff-ai/costaff-channel-chatbot))
so each platform repo is a thin adapter (~150 lines) on top of the same
ADK pipeline.

### First-party plugins

| Repo | Purpose |
|---|---|
| [costaff-channel-telegram](https://github.com/costaff-ai/costaff-channel-telegram) | Telegram bot |
| [costaff-channel-discord](https://github.com/costaff-ai/costaff-channel-discord) | Discord bot |
| [costaff-channel-line](https://github.com/costaff-ai/costaff-channel-line) | LINE bot |
| [costaff-channel-slack](https://github.com/costaff-ai/costaff-channel-slack) | Slack bot (Socket Mode) |
| [costaff-channel-webchat](https://github.com/costaff-ai/costaff-channel-webchat) | Browser-based web chat |
| [costaff-agent-coding](https://github.com/costaff-ai/costaff-agent-coding) | Sandboxed Python code execution |
| [costaff-agent-business-analysis](https://github.com/costaff-ai/costaff-agent-business-analysis) | BI reporting & visualization |

---

## Web dashboard reference

| Module | What it shows |
|--------|---------------|
| **Dashboard** | Live system stats and service health |
| **Chat** | Talk to the assistant directly |
| **Agents** | Status of internal/external agents; per-agent MCP / API / Skill assignment |
| **MCPs** | Add/remove external MCP servers at runtime |
| **APIs** | Register external REST APIs and assign them per agent / per user |
| **Skills** | Register reusable prompt templates and assign them per agent / per user |
| **Reminders** | Cron reminders the assistant has scheduled |
| **Tasks** | Recurring task history (web search, DB queries, report generation) |
| **Users** | Identity Map; per-user profile (name, role, company, preferences) |
| **Sessions** | Browse chat sessions; full function call / response traces |
| **Channels** | Manage Telegram / Discord / LINE bot tokens |
| **Config** | Theme, model provider, approval-gate toggle |
| **Logs** | Stream container logs from any service |

---

## Bot interaction

After you've added a bot token (in **Dashboard → Channels**), open the
bot in your chat app and send any message. The first message creates a
**pending** identity — log into the dashboard, go to **Users**, and
approve yourself. After that, the assistant responds normally.

| Slash command | Behavior |
|---|---|
| `/reset` | Start a new conversation (clears the current session) |

Other slash command names appear in the bot menu (`/start`, `/help`,
`/profile`, `/list`) but they're handled as natural language — you can
type the same thing in plain text and get the same result.

**Natural-language examples**:

- "Remind me to drink water at 3 PM every day."
- "Search for the latest AI news every morning at 9 AM and send me a summary."
- "Analyse this CSV and generate an HTML report with charts." *(attach a CSV)*
- "Save my name as Simon and my role as software engineer."

---

## Tech stack

| Layer | Technology |
|---|---|
| Agent framework | [Google ADK](https://github.com/google/adk-python) |
| Agent-to-agent | A2A protocol (`RemoteA2aAgent`) |
| Tool protocol | [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) |
| AI models | Google Gemini, any LiteLLM-compatible provider |
| Channel SDK | [costaff-channel-chatbot](https://github.com/costaff-ai/costaff-channel-chatbot) |
| Web backend | [FastAPI](https://fastapi.tiangolo.com/) + [uvicorn](https://www.uvicorn.org/) |
| Database | [SQLAlchemy](https://www.sqlalchemy.org/) — PostgreSQL (required) |
| Scheduler | [APScheduler](https://apscheduler.readthedocs.io/) |
| Deployment | Docker + Docker Compose |
| CLI | [Typer](https://typer.tiangolo.com/) + [Rich](https://rich.readthedocs.io/) |

---

## License

Dual-licensed under **AGPL v3** + **commercial license**.

- Personal use, internal company use, and modifications you keep to
  yourself: **free under AGPL v3**.
- Re-distributing the software, or running a modified version as a
  network service for others: **AGPL v3 obligations apply** (you must
  release your modifications under AGPL v3).
- If AGPL v3 doesn't work for your use case, contact us for a
  commercial license.

See [`LICENSE`](./LICENSE) for the full text.

For commercial licensing inquiries: **https://costaffs.app**

---

## Support

- **Documentation**: see the [`docs/`](./docs) folder
- **Issues**: [github.com/costaff-ai/costaff/issues](https://github.com/costaff-ai/costaff/issues)
- **Discussions**: [github.com/costaff-ai/costaff/discussions](https://github.com/costaff-ai/costaff/discussions)
- **Security**: see [`SECURITY.md`](./SECURITY.md) for private disclosure
