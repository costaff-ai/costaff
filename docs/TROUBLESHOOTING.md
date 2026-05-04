# Troubleshooting

A field guide to the issues that actually come up. Organised by symptom,
not by component, so you can find your problem fast.

If your issue isn't here, the **first command to try** is:

```bash
costaff doctor
```

It writes a timestamped diagnostic report and surfaces most common
issues automatically.

---

## Install / first run

### `costaff: command not found` after install

The installer added `costaff` to your shell PATH but your current shell
session was started before that change. Reload it:

```bash
source ~/.zshrc      # macOS default
source ~/.bashrc     # Ubuntu default
```

If it still doesn't work, check the venv exists:

```bash
ls ~/.costaff/.venv/bin/costaff   # should print the path
```

If yes, add it manually:

```bash
echo 'export PATH="$HOME/.costaff/.venv/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

### macOS — Xcode Command Line Tools dialog never appeared

The installer triggers `xcode-select --install`, which on rare occasions
doesn't pop the dialog. Run manually:

```bash
sudo xcode-select --install
```

Wait for it to finish, then re-run the CoStaff installer.

### Ubuntu — `docker: permission denied` after install

The installer added you to the `docker` group, but group membership
isn't applied to your current login session. Either:

```bash
# Quick (this terminal only):
newgrp docker

# Permanent (all future logins):
# Log out completely, then log back in.
```

Verify:

```bash
docker run --rm hello-world
```

### "Cannot connect to the Docker daemon"

| Platform | Cause | Fix |
|---|---|---|
| macOS | Docker Desktop not launched | Open Docker Desktop from Launchpad; wait until the whale icon in the menu bar stops animating. |
| macOS | Docker Desktop crashed | Restart Docker Desktop. If it keeps crashing: Settings → Reset → Restart Docker. |
| Ubuntu | docker daemon not running | `sudo systemctl start docker` (and `enable` for boot start). |
| Ubuntu | not in docker group | See above. |

---

## `costaff start` / `costaff stop`

### Port already in use

CoStaff uses these ports on the host:

| Port | Service |
|---|---|
| 8501 | Dashboard |
| 18080 | Manager agent (ADK API) |
| 18091 | Webchat channel |
| 5432 | PostgreSQL |

Find what's holding a port:

```bash
lsof -i :5432         # macOS / Linux
```

If it's another Postgres on your machine, you have two choices:
stop it, or change CoStaff's port in `~/.costaff/costaff/docker-compose.yaml`.

### Containers start but immediately exit

Tail the logs of the failing container:

```bash
costaff logs costaff-agent-costaff   # or whichever container
docker ps -a --format '{{.Names}}\t{{.Status}}'   # see exit codes
```

The most common causes:

- **Missing required env var** — the container's startup script raises
  before doing anything. Check `~/.costaff/costaff/.env`.
- **Database connection refused** — postgres hasn't finished starting.
  Wait 10 seconds and try `costaff start` again. If it persists, see
  "Postgres won't start".
- **Image build failed** — re-run with `costaff start` (no `--no-build`)
  or `docker compose -f ~/.costaff/costaff/docker-compose.yaml build`.

### Postgres won't start

Usually a stale data volume from an aborted previous run.

```bash
costaff stop
docker volume rm costaff_postgres_data   # ⚠ DESTROYS THE DATABASE
costaff start
```

You'll lose chat history, the identity table, and all reminders.
Bot tokens (in `.env` files) survive.

### Other containers got killed when I ran `costaff channel rebuild` / `costaff start`

Fixed in CoStaff 0.2.5+. If you're on an older version,
`costaff update` then retry. Pre-fix versions used `--remove-orphans`
on the main compose, which silently killed any containers managed by
fragments (other channels, external agents). Modern versions iterate
fragments instead.

If you're stuck on the old behaviour, manually restart the killed
services:

```bash
costaff agent restart business-analysis
costaff agent restart coding
costaff start --no-build              # brings back channels
```

---

## Bot doesn't reply

Run through this list **in order**:

1. **Is the channel container up?**

   ```bash
   docker ps --format '{{.Names}}\t{{.Status}}' | grep channel
   ```

2. **Are there errors in the channel log?**

   ```bash
   costaff logs costaff-channel-telegram   # or discord / line / slack
   ```

   Look for: `Connection refused` (network issue), `401` / `403` (bad
   token), `rate limit` (too many messages).

3. **Is the user approved?**

   Bots reject messages from un-approved users with `⌛ 您的帳號正在等待
   管理員審核中...`. Approve in dashboard → **Users**.

4. **Is the manager agent reachable from the channel?**

   ```bash
   docker exec costaff-channel-telegram \
     curl -sf http://costaff-agent-costaff:8080/.well-known/agent-card.json
   ```

   If this fails: the manager isn't up, or the channel isn't on
   `costaff_default` network. Check `docker network inspect costaff_default`.

5. **Has the user hit the rate limit?**

   Default: 10 messages per 60 seconds. The bot replies `⏳ 訊息太頻繁`.
   Raise via `RATE_LIMIT_MAX` / `RATE_LIMIT_WINDOW` env vars on the
   channel container, then `costaff channel rebuild <name>`.

6. **Bot token wrong?**

   ```bash
   cat ~/.costaff/costaff-channel/telegram/.env
   ```

   Compare against the BotFather page. Update the file, then
   `costaff channel rebuild telegram`.

---

## Agent / sub-agent issues

### Agent shows "offline" in dashboard but container is running

The dashboard health-checks via the `a2a_url` in `config.json`. If the
URL is wrong or unreachable, you see offline.

```bash
# Inspect the configured URL
python3 -c "
import json
print(json.load(open('/Users/simonliuyuwei/.costaff/costaff/config.json'))['external_agents']['<agent-name>']['a2a_url'])
"

# Try reaching it from inside the manager
docker exec costaff-agent-costaff \
  curl -sf <that-url>/.well-known/agent-card.json
```

If reaching it works manually but the dashboard still shows offline,
restart the dashboard server: stop `costaff dashboard` and re-run.

### `Tool 'transfer_to_agent' not found` error

Your leaf agent (one with no sub-agents of its own) is missing the
`disallow_transfer_to_parent=True` and `disallow_transfer_to_peers=True`
flags on its root `LlmAgent`. Without these, Gemini hallucinates a
`transfer_to_agent` call — and there's no such tool.

Fix: in the agent's `agent/agent.py`, add the flags. See
[Agent Protocol §4](./AGENT_PROTOCOL_v1.0.md#4-the-a2a-endpoint).

### Sub-agent receives "OK" or session history instead of an actual task

You wired the sub-agent into `sub_agents=[...]` instead of wrapping it
as `AgentTool(agent=RemoteA2aAgent(...))`. The former triggers ADK's
transfer mechanism, which dumps session history into the sub-agent's
context. The latter calls the sub-agent as a function with a clean
request string.

Fix: in the manager's `sub_agents/__init__.py`, return
`AgentTool(...)` not the bare agent. Add it to the manager's
`tools=[...]`, NOT `sub_agents=[...]`.

### Plugin agent sees too many MCP tools

Symptom: the agent takes ages to respond because the LLM is sifting
through 40+ tools before picking one. Cause: missing or broken MCP
whitelist.

```bash
# What does the agent see?
docker exec costaff-agent-<name> env | grep _MCP_URLS
```

The output should contain a `tool_filter` list. If not, check
`~/.costaff/costaff/config.json` → `agent_mcp_filters`. Then
re-run the env regeneration:

```bash
python3 -c "
import sys; sys.path.insert(0, '/Users/simonliuyuwei/.costaff/costaff')
from services.config import ConfigManager
ConfigManager.update_mcp_urls()
"

costaff agent rebuild <name>
```

Note: `restart` is NOT enough — the env var only re-reads on rebuild.

### `costaff agent add` rejects my manifest

If you used `--strict`, the JSON Schema is enforcing the manifest
structure. Common rejections:

| Error | Fix |
|---|---|
| `'protocol_version' is a required property` | Add `"protocol_version": "1.0"` to your manifest. |
| `'name' does not match pattern '^costaff-agent-...'` | Rename your agent so the manifest `name` starts with `costaff-agent-`. |
| `'health_path' const violation` | Set `"health_path": "/.well-known/agent-card.json"` exactly. |
| `'mcp_env_var' is a required property` | If `mcp_configurable: true`, you also need `mcp_env_var`. Or set `mcp_configurable: false`. |

Without `--strict`, missing fields downgrade to warnings and your agent
still registers — useful for ad-hoc experiments, dangerous for
production.

---

## Update / data / network

### `costaff update` failed mid-update

```bash
cd ~/.costaff/costaff
git status                      # see what's dirty
git stash && git pull origin main && pip install -e .
git stash pop                   # if you had local changes
```

If the database schema changed and the new code panics on old data,
`costaff database backup` before retry.

### Reset everything to a clean state (⚠️ destructive)

```bash
costaff stop
docker compose -f ~/.costaff/costaff/docker-compose.yaml down --volumes
costaff start
```

Loses: chat history, identity table, reminders, recurring tasks.
Survives: bot tokens, API keys (everything in `.env` files).

### Remote SSH to my Mac Mini stopped working

Common when running CoStaff on a home Mac Mini. Two near-certain
causes:

1. **WAN IP changed.** Most home ISPs hand out dynamic IPs that change
   every few hours to days. Your `~/.ssh/config` is pinned to the old
   one.

   Fix: set up Dynamic DNS in your router (UniFi → Settings → Internet
   → WAN1 → Dynamic DNS). Free providers: DuckDNS, No-IP. Update your
   ssh config to use the hostname instead of the IP.

2. **From inside the same LAN, hairpin NAT not enabled.** If you SSH
   from a laptop on the same home network using the public IP, your
   router has to "loopback" the packet to itself. Many routers (UniFi
   included) don't do this by default.

   Fix in UniFi: **Settings → Security → Port Forwarding** → your SSH
   rule → enable **Hairpin NAT** (sometimes called NAT Loopback or
   NAT Reflection).

   Or: add a separate ssh config entry that uses the LAN IP when at
   home.

### `git: 'credential-LIUYUWEI' is not a git command` warning on every push

You set `credential.helper` to a username string by mistake. The
helper is supposed to be a program name — `osxkeychain` on macOS.

```bash
git config --global credential.helper osxkeychain
```

This affects nothing but the warning. `user.name` / `user.email` are
separate fields and unrelated.

---

## License / commercial use

### Can I run CoStaff at work?

Yes. AGPL v3 lets you use, modify, and run it for any purpose, including
commercial. The disclosure obligations only kick in if you **distribute**
the modified software or **provide it as a network service to third
parties**.

If you only use CoStaff inside your company, even with modifications,
no disclosure is required.

### I want to host CoStaff as a SaaS for my own customers

That's the AGPL §13 case — running modified CoStaff as a network
service triggers source-disclosure of your modifications under AGPL v3.
Either:

- Release your CoStaff fork (and any modifications) under AGPL v3, or
- Acquire a commercial license: simonliuyuwei@gmail.com

---

## Got bigger problems?

- **`costaff doctor`** writes a timestamped report — attach it when
  asking for help.
- **GitHub Issues**: https://github.com/costaff-ai/costaff/issues
- **Email**: simonliuyuwei@gmail.com
