# Quickstart — Zero to Chat in 5 Minutes

Goal: a working CoStaff install on your machine, talking to a real AI
assistant via the built-in web chat. No bot tokens needed for the
minimum demo.

This guide assumes a fresh macOS 12+ or Ubuntu 20.04+ host. For
production deployment, system-tuning, channel onboarding, and
day-two ops, see the [main README](../README.md).

---

## What you'll need

- **5 minutes** and a terminal
- **Outbound HTTPS** access (the installer pulls Python, Docker, and
  the CoStaff containers)
- **A Gemini API key** — free tier from [Google AI Studio](https://aistudio.google.com/app/apikey)
  is enough. Have it pasted somewhere ready.

That's it. Docker, Python, and everything else are installed
automatically.

---

## Step 1 — Install (≈ 2 min)

```bash
curl -fsSL https://raw.githubusercontent.com/costaff-ai/costaff/main/install.sh | bash
```

The installer is interactive. When the **setup wizard** appears:

- Paste your **Gemini API key** when prompted
- Pick a username + password for the operator dashboard
- When asked which channels to add, press Enter to skip — we'll use the
  built-in web chat first

If the installer asks you to log out and back in (Linux Docker group
membership), do that, then run `costaff onboard` to resume the wizard.

---

## Step 2 — Start the platform (≈ 1 min)

```bash
costaff start
```

This boots, in order:

1. Postgres (session + identity DB)
2. The Manager Agent + core MCP server
3. The built-in WebChat channel

When `costaff start` returns, all containers are running. Verify:

```bash
costaff ps
```

Every row should show **Up** in the Status column. If anything's red,
`costaff doctor` writes a diagnostic report you can grep.

---

## Step 3 — Open the chat (≈ 30 sec)

```bash
costaff dashboard
```

A browser tab opens at **http://localhost:8501**. Log in with the
credentials you set in Step 1.

Click the **Chat** tab in the left sidebar.

---

## Step 4 — Talk to your assistant

Type any of these:

- `Hi, what can you do?` — the Manager will list available specialists
- `Remind me to drink water at 4pm every weekday` — the scheduler picks
  it up; you'll get a notification at 4pm in this same chat surface
- `What's the latest in AI?` — if a web-search agent is wired up, it
  fetches and summarizes; otherwise the Manager says it doesn't have
  that capability (try Step 5 below)

The cursor blinks while the Manager thinks. Replies arrive as soon as
the agent returns — usually 2–10s for plain Q&A.

---

## Step 5 (Optional) — Add a specialist agent

Want the assistant to handle Taiwan open-data queries? Pull in the
**Twinkle Hub** agent:

```bash
costaff agent add twinkle-hub --github https://github.com/costaff-ai/costaff-agent-twinkle-hub --tag v0.1.0-alpha-1
```

The CLI clones the repo at the pinned tag, generates a compose
fragment, prompts for any required env vars (e.g. a Twinkle Hub API
key), builds the container, and registers it with the Manager.

Verify:

```bash
costaff agent list
```

You should see `twinkle-hub` with a green Health dot and the `Ref`
column reading `v0.1.0-alpha-1`.

Now go back to the chat and ask: *"找一下台北的實價登錄"*. The
Manager will hand off to the new specialist.

---

## Step 6 (Optional) — Add Telegram

Have a Telegram bot token from [@BotFather](https://t.me/BotFather)?

```bash
costaff channel add telegram --tag v0.1.0-alpha-1
# (paste your TELEGRAM_BOT_TOKEN when prompted)
```

Your bot is online. DM it `/start`.

---

## What just happened

You ran:

- A **Manager Agent** that orchestrates specialists and handles
  scheduling, plain-text chat, reminders, and async work
- A **Core MCP server** that exposes ~42 platform tools the Manager
  uses (`dispatch_task`, `send_message_now`, `add_task_comment`, etc.)
- A **WebChat channel** (the simplest channel to verify with) backed
  by FastAPI + a static HTML/CSS/JS frontend served by nginx

The Manager talks to channels via the **A2A protocol** and to
specialists via the same A2A — every "agent" in CoStaff is a
self-contained service the Manager invokes by URL. That's why you can
add new specialists with `costaff agent add` without restarting the
core.

---

## What's next

| If you want to... | Read |
|---|---|
| ...stop / restart / update | [README §Day-to-day commands](../README.md#day-to-day-commands) |
| ...understand the architecture | [README §Architecture](../README.md#architecture) |
| ...write your own agent | [`HOW_TO_WRITE_YOUR_OWN_AGENT.md`](./HOW_TO_WRITE_YOUR_OWN_AGENT.md) |
| ...pin every plugin to a release tag | [`TROUBLESHOOTING.md` §tag pinning](./TROUBLESHOOTING.md) — and `costaff agent tags <name>` lists available versions |
| ...host CoStaff for paying customers (AGPL §13) | See [LICENSE](../LICENSE) — you'll need a commercial license. https://costaffs.app |
| ...hit a wall | [`TROUBLESHOOTING.md`](./TROUBLESHOOTING.md), then [GitHub Discussions](https://github.com/costaff-ai/costaff/discussions) |

---

## Common gotchas

**`costaff start` hangs on "waiting for Postgres"** → Docker isn't
running. Start Docker Desktop (macOS) or `sudo systemctl start docker`
(Linux).

**The chat says "I don't have a Gemini API key configured"** → the
key didn't make it into `~/.costaff/costaff/.env`. Run `costaff onboard`
to re-enter it, then `costaff restart`.

**Bot replies to the wrong account** → bot tokens are 1:1 with a chat
account. If you cloned a bot or restarted with a different `ID_SALT`,
identity hashes diverge. Reset with `costaff database backup` then
`docker compose down -v && costaff start`.

More in [TROUBLESHOOTING.md](./TROUBLESHOOTING.md).
