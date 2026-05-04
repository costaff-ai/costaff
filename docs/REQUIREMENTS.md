# System Requirements

> **Status**: Draft. Numbers below are based on observed running
> footprints on the developer's Mac Mini (the canonical reference
> deployment) plus the contents of the docker images. They have **not**
> yet been validated by fresh-install testing on clean VMs — see
> `docs/DEPLOYMENT_STRATEGY.md` §5 for the open ship-ready items.
>
> Once those validations are done, we'll fill in real numbers and
> remove this banner.

---

## Operating system

| OS | Status | Notes |
|---|---|---|
| **macOS 14 (Sonoma) or later** | Supported | Apple Silicon and Intel both work. Docker Desktop required. |
| **macOS 12 / 13** | Best-effort | Should work; not actively tested. |
| **Ubuntu 24.04** | Supported | Native docker engine. |
| **Ubuntu 22.04** | Supported | Native docker engine. |
| **Ubuntu 20.04** | Best-effort | Should work; deadsnakes Python required. |
| **Other Linux (Debian, Arch, …)** | Best-effort | Likely works if you can install Python 3.11 + Docker. |
| **Windows native** | **Not supported** | Use WSL 2 + Ubuntu. The installer detects Linux from inside WSL and behaves correctly. |
| **Windows + WSL 2** | Best-effort | Should work; not actively tested. |

If you need something not listed, file an issue.

---

## Hardware

### Minimum

What CoStaff needs to start and run a single conversation reasonably.

| Resource | Minimum |
|---|---|
| RAM | **4 GB free** |
| CPU | **2 cores** (any modern CPU) |
| Disk | **5 GB free** for installation + images |
| Disk (ongoing) | grows with chat history; budget **+1 GB / month** for active use |

### Recommended

What you want for comfortable day-to-day use, especially with multiple
external agents enabled (coding, BA).

| Resource | Recommended |
|---|---|
| RAM | **8 GB free** |
| CPU | **4 cores** (any modern CPU) |
| Disk | **20 GB free** |

### Why these numbers

The default deployment runs **9 containers** simultaneously:

| Container | Steady-state RAM | Notes |
|---|---|---|
| `costaff-postgres` | ~50 MB | Idle baseline; rises with active queries. |
| `costaff-mcp-costaff` | ~120 MB | Manager core MCP. |
| `costaff-agent-costaff` | ~250 MB | Manager LLM agent (ADK + httpx). |
| `costaff-channel-webchat` | ~200 MB | FastAPI + nginx + supervisord. |
| `costaff-channel-telegram` | ~100 MB | aiogram bot. |
| `costaff-channel-discord` | ~100 MB | If enabled. |
| `costaff-channel-line` | ~100 MB | If enabled. |
| `costaff-agent-coding` | ~250 MB | If enabled. |
| `costaff-agent-business-analysis` | ~250 MB | If enabled. |

Idle total ≈ 1.5 GB. With LLM calls in flight, transient peaks of
2-3 GB. **Disk** is dominated by Docker images (~3-5 GB total) and
postgres growth.

---

## Network

### Outbound (the host needs)

- HTTPS to **GitHub** (cloning the repo + plugin sources, pip
  installing dependencies).
- HTTPS to your **AI provider** (Gemini API → `generativelanguage.googleapis.com`;
  for LiteLLM, whichever provider you point at).
- HTTPS to **Telegram / Discord / LINE / Slack APIs** for whichever
  channels you enable.
- HTTPS to **Docker Hub** for base image pulls.

### Inbound (the host accepts)

- **Localhost only by default.** All published ports bind to `127.0.0.1`
  except the dashboard (`8501`) and the webchat (`18091`).
- For LINE channels you need an **HTTPS-reachable webhook URL** —
  CoStaff doesn't ship a TLS terminator; use Cloudflare Tunnel,
  ngrok, or a reverse proxy you already run.

### Listening ports on the host

| Port | Service | Public exposure |
|---|---|---|
| 8501 | Dashboard | Localhost recommended; loopback for SSH-tunnel from outside. |
| 18080 | Manager A2A endpoint | Localhost only. |
| 18091 | Webchat channel | Localhost recommended; expose through reverse proxy if you want public access. |
| 5432 | PostgreSQL | Localhost only. Don't expose. |

---

## Software prerequisites

The installer (`install.sh`) brings in everything missing. If you
prefer to install manually:

| Tool | Version | Used for |
|---|---|---|
| Python | **3.10+** (3.11 preferred) | The CoStaff CLI runs in a venv at `~/.costaff/.venv`. |
| Docker | **24+** | All services run in containers. |
| Docker Compose | **v2** | Bundled with Docker Desktop / `docker-ce` packages. |
| Git | any modern version | Cloning plugins from GitHub, pip-installing from git URLs. |
| Curl | any | Downloading the installer + various scripts. |

---

## What's not required

- **A GPU.** All inference is offloaded to your AI provider's cloud.
- **A public IP / static DNS.** CoStaff is local-first by default. You
  only need public reachability if you want LINE webhooks or remote
  dashboard access.
- **A separate database server.** Postgres runs as part of the
  CoStaff compose stack. SQLite is also supported for the simplest
  installs.
- **Kubernetes.** Docker Compose is the supported orchestrator. K8s
  manifests may come later but are not required.

---

## Known limitations

- **Single-machine deployment only.** No horizontal scaling, no
  multi-host orchestration. See
  [`DEPLOYMENT_STRATEGY.md`](./DEPLOYMENT_STRATEGY.md) for the v1 vs
  future-roadmap trade-off.
- **Single-tenant.** All chats and data live in one Postgres. If you
  need to separate customers, deploy multiple CoStaff instances.
- **No automatic backup.** Run `costaff database backup` on a cron of
  your choice, or back up the `costaff_postgres_data` Docker volume
  externally.

---

## Validation status

| Validation | Status |
|---|---|
| Fresh install on macOS 14 VM | ⏳ pending — see DEPLOYMENT_STRATEGY.md §5 |
| Fresh install on Ubuntu 22.04 VM | ⏳ pending — see DEPLOYMENT_STRATEGY.md §5 |
| Steady-state RAM measured under load | ⏳ pending |
| Disk growth rate measured | ⏳ pending |
| First paying customer onboarded end-to-end | ⏳ pending |

This page will be updated with measured numbers once those validations
land.
