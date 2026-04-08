# Mateclaw

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Docker Support](https://img.shields.io/badge/docker-supported-blue.svg)](https://www.docker.com/)
[![Google ADK](https://img.shields.io/badge/Google%20ADK-latest-orange.svg)](https://github.com/google/adk-python)
[![MCP](https://img.shields.io/badge/MCP-enabled-green.svg)](https://modelcontextprotocol.io/)
[![A2A Protocol](https://img.shields.io/badge/A2A-protocol-violet.svg)](https://github.com/google/A2A)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)

[繁體中文](./README_zhtw.md) | **English**

**Mateclaw** is a self-hosted, privacy-first AI agent platform built on **Google ADK (Agent Development Kit)** and **Model Context Protocol (MCP)**. It connects your preferred chat platforms — **Telegram, Discord, and Line** — while exposing a full-featured web dashboard for operators to manage agents, tools, users, and sessions.

External agents (such as [`mateclaw-coding-agent`](https://github.com/MateClawAI/mateclaw-coding-agent) and [`mateclaw-viz-report-agent`](https://github.com/MateClawAI/mateclaw-viz-report-agent)) integrate via the **A2A protocol**, extending the platform's capabilities without modifying the core.

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Web Dashboard](#web-dashboard)
- [External Agents](#external-agents)
- [Tech Stack](#tech-stack)
- [Getting Started](#getting-started)
- [CLI Reference](#cli-reference)
- [Bot Commands](#bot-commands)
- [License](#license)

---

## Features

- **Multi-Agent Orchestration** — The primary Mateclaw Agent delegates tasks to external agents via A2A protocol; add any `mateclaw.agent.json`-compatible agent with a single CLI command
- **Per-Agent Tool Assignment** — Assign which MCPs, APIs, and Skills each agent can access; changes apply with a targeted restart, no full redeploy needed
- **Dynamic MCP Layer** — Core MCPs are always present; add external MCPs (streamable HTTP or SSE) from the dashboard at runtime
- **API & Skill Registry** — Register external REST APIs and reusable prompt templates in the database, assigned per-agent and per-user
- **Multi-Channel Support** — Telegram, Discord, and Line bots out of the box
- **Multi-Model Support** — Google Gemini natively, or any LiteLLM-compatible provider
- **Secure Identity Hashing** — Platform IDs are mapped to 16-character SHA-256 hashes; real IDs never stored
- **Identity Approval Workflow** — New users held pending until operator approves from the dashboard
- **User Profile Memory** — Agent remembers name, role, company, contact info, and preferences across sessions
- **Proactive Reminders** — Schedule cron-based notifications delivered to any connected chat platform
- **Kanban Task Automation** — Recurring agent tasks (web search, DB queries, report generation) that push results back to users
- **Web Dashboard** — Dark/light mode operator console for full lifecycle management

---

## Architecture

```mermaid
graph TD
    User_TG((Telegram)) <--> Bot_TG[Telegram Bot]
    User_DC((Discord)) <--> Bot_DC[Discord Bot]
    User_LN((Line)) <--> Bot_LN[Line Bot]

    Bot_TG & Bot_DC & Bot_LN <--> MateclawAgent[Mateclaw Agent\nGoogle ADK]

    MateclawAgent <--> MCP_Core[Core MCP]
    MateclawAgent <--> MCP_Ext[External MCPs\nStreamable HTTP / SSE]

    MCP_Core <--> DB[(PostgreSQL / SQLite)]
    MCP_Core <--> Scheduler[APScheduler]
    Scheduler --> Notifier[Notifier]
    Notifier --> Bot_TG & Bot_DC & Bot_LN

    Dashboard[Web Dashboard] <--> API[FastAPI Backend]
    API <--> DB
    API -->|restart| MateclawAgent
```

---

## Web Dashboard

The dashboard (`mateclaw dashboard`) is a browser-based operator console with dark/light mode:

| Module | Description |
|--------|-------------|
| **Dashboard** | Live system stats (CPU, memory, disk) and service health overview |
| **Chat** | Talk to the Mateclaw Agent directly from the browser with full conversation history |
| **Agents** | View internal/external agent status; configure per-agent MCP assignments with Apply & Restart |
| **MCPs** | Manage MCP extensions — add/remove external MCPs at runtime |
| **APIs** | Register external REST API configs and assign them per-agent or per-user |
| **Skills** | Register reusable prompt templates and assign them per-agent or per-user |
| **Reminders** | View and manage scheduled cron reminders |
| **Tasks** | Monitor Kanban-style automation task results |
| **Users** | Identity Map with User Profile detail panel |
| **Sessions** | Browse chat sessions; Event Logs show full function call / response traces |
| **Channels** | Configure Telegram / Discord / Line bot tokens |
| **Config** | Theme, model provider, approval gate settings |
| **Logs** | Stream container logs from any service in real time |

---

## External Agents

Mateclaw supports deploying and managing external agents that communicate via the **A2A protocol**.

Any project containing a `mateclaw.agent.json` manifest can be registered and deployed:

```bash
# Deploy a local agent project
mateclaw agent deploy --local /path/to/my-agent

# Add a remote URL agent
mateclaw agent add my-agent --url http://my-agent.example.com

# List all agents
mateclaw agent list
```

**First-party agents:**

| Agent | Repository | Role |
|-------|------------|------|
| Coding Agent | [mateclaw-coding-agent](https://github.com/MateClawAI/mateclaw-coding-agent) | Sandboxed Python code execution |
| Viz Report Agent | [mateclaw-viz-report-agent](https://github.com/MateClawAI/mateclaw-viz-report-agent) | Chart generation & HTML/PDF reports |

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Agent Framework | [Google ADK](https://github.com/google/adk-python) |
| Agent-to-Agent | A2A Protocol (`RemoteA2aAgent`) |
| Tool Protocol | [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) |
| AI Models | Google Gemini, LiteLLM-compatible providers |
| Telegram Bot | [Aiogram 3.x](https://docs.aiogram.dev/) |
| Discord Bot | [discord.py](https://discordpy.readthedocs.io/) |
| Line Bot | [line-bot-sdk](https://github.com/line/line-bot-sdk-python) |
| Web Backend | [FastAPI](https://fastapi.tiangolo.com/) + [uvicorn](https://www.uvicorn.org/) |
| Database | [SQLAlchemy](https://www.sqlalchemy.org/) — PostgreSQL or SQLite |
| Scheduler | [APScheduler](https://apscheduler.readthedocs.io/) |
| Deployment | Docker + Docker Compose |
| CLI | [Typer](https://typer.tiangolo.com/) + [Rich](https://rich.readthedocs.io/) |

---

## Getting Started

### Prerequisites

- Python 3.10+
- Docker and Docker Compose
- At least one of:
  - **Gemini API Key** from [Google AI Studio](https://aistudio.google.com/)
  - **LiteLLM-compatible** provider API key

### 1. Install the CLI

```bash
pip install -e .
```

### 2. Run the Setup Wizard

```bash
mateclaw onboard
```

The wizard configures:
- AI model provider (Gemini or LiteLLM)
- Database type (SQLite or PostgreSQL)
- Bot tokens (Telegram, Discord, Line — all optional)
- Admin credentials for the web dashboard
- Identity hashing salt

All configuration is saved to `.mateclaw/` in the current directory.

### 3. Start the Platform

```bash
mateclaw start
```

### 4. Open the Dashboard

```bash
mateclaw dashboard
```

Opens the web UI at `http://localhost:8501`.

---

## CLI Reference

| Command | Description |
|---------|-------------|
| `mateclaw onboard` | Interactive setup wizard |
| `mateclaw start` | Build and start all services |
| `mateclaw start --no-build` | Start without rebuilding images |
| `mateclaw stop` | Stop all services |
| `mateclaw restart` | Restart all services |
| `mateclaw ps` | Show status of running services |
| `mateclaw dashboard` | Open the web dashboard |
| `mateclaw chat` | CLI-based chat with the agent |
| `mateclaw agent deploy --local <path>` | Deploy a local agent project |
| `mateclaw agent add <name> --url <url>` | Register a remote URL agent |
| `mateclaw agent list` | List all registered agents |
| `mateclaw agent remove <name>` | Remove a registered agent |
| `mateclaw config show` | Display current configuration |
| `mateclaw database backup` | Backup the database |
| `mateclaw database restore` | Restore from a backup |
| `mateclaw version` | Show CLI version |

---

## Bot Commands

Available on Telegram, Discord, and Line:

| Command | Description |
|---------|-------------|
| `/start` | Initialise session and check identity |
| `/profile` | View your stored profile |
| `/list` | List active reminders and tasks |
| `/reset` | Clear the current conversation context |
| `/help` | Show available commands |

**Natural language examples:**

- "Remind me to drink water at 3 PM every day."
- "Search for the latest AI news every morning at 9 AM and send me a summary."
- "Analyse this CSV and generate an HTML report with charts."
- "Save my name as Simon and my role as Software Engineer."

---

## License

This project is dual-licensed under **AGPL v3 + Commercial License**. See `LICENSE` for details.

For commercial licensing inquiries, contact: simonliuyuwei@gmail.com
