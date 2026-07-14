# Changelog

All notable changes to this project are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[SemVer](https://semver.org/).

## [Unreleased]

## [0.1.0-beta-3] - 2026-07-14

### Added

- **Async task results reach WebChat OSS, not just Enterprise.** Delivering a
  finished background task ("I'll notify you when it's done") is now a shared
  channel capability. The core prefers the generic `WEBCHAT_PUSH_URL` /
  `WEBCHAT_INTERNAL_SECRET` so each stack points at its own webchat container,
  falling back to `WEBCHAT_ENT_PUSH_URL` / `WEBCHAT_ENT_INTERNAL_SECRET` so
  existing Enterprise deployments are unaffected. Pairs with WebChat OSS
  beta-3, which receives these pushes over SSE.
- **`costaff channel add/rebuild webchat` auto-wires async push — zero manual
  setup.** Adding or rebuilding a WebChat channel now generates
  `WEBCHAT_INTERNAL_SECRET` (once, then preserved) and derives
  `WEBCHAT_PUSH_URL` from the core's container prefix, writing both to the core
  `.env`. The webchat container already mounts that `.env`, so the two sides
  line up automatically — "notify you later" works after a plain rebuild +
  `costaff restart`, without anyone hand-editing env files. Other channels are
  left untouched.

### Fixed

- **`channel add/rebuild` and `agent add` no longer break on a secondary core.**
  The compose-fragment generator *appended* the core's docker network to
  whatever the source `docker-compose.yaml` hardcoded (typically
  `costaff_default`) instead of replacing it. On a non-default core (e.g. `twk`
  → `costaff_twk`) the service then referenced `costaff_default`, which the
  fragment doesn't declare, so the build failed with "refers to undefined
  network costaff_default". The service now references exactly the core's
  network. No change on the default core (the network already *is*
  `costaff_default`).
- **`costaff update` now prompts a core rebuild when `core/` changes.** `core/`
  (notifiers, dispatcher, models, license) is baked into `costaff-mcp-costaff`
  via `COPY . .`, but it was missing from the update command's "needs a
  rebuild" path list — so an update whose only image-relevant change was under
  `core/` (e.g. this release's async-push sender) would be silently left
  running the old code after a plain `restart`. `core/` is now in that list, so
  the update offers `costaff core-rebuild` like it does for `mcp_servers/` etc.

## [0.1.0-beta-2] - 2026-07-13

### Changed

- **`costaff channel` is multi-core aware.** `add/list/remove/rebuild/tags`
  now accept `--core` and resolve the target core's config, container
  prefix, workspace, `.env`, and compose project — matching `costaff
  agent`. Channel host ports are reserved across every registered core so
  allocation never collides. Single-install hosts are unaffected (the
  synthetic default core reproduces the historical layout exactly).
- **`costaff agent enable/disable/transfer` recreate the Manager.** They
  changed config and regenerated the env but only told the user to
  `docker restart` — which doesn't re-read env_file, so the change
  silently didn't apply. They now recreate the Manager like add/remove.
- **Dashboard CORS is deny-by-default.** `ALLOWED_ORIGINS` no longer
  defaults to `*` (which let any website script the dashboard). The
  bundled frontend is same-origin and needs no CORS; set `ALLOWED_ORIGINS`
  only when hosting the frontend on a different origin.
- **`costaff database backup/clean/restore` fail friendly without a DB.**
  They dumped a raw AttributeError traceback when no database was
  configured; now they print the same actionable message as `db migrate`
  and exit non-zero (restore also exits non-zero on a missing file).

### Added

- **Durable notification outbox.** A channel push that fails (Telegram 5xx,
  WebChat secret unset, network) is now written to `notification_outbox`
  and retried by a background loop with exponential backoff, marked `dead`
  only after 8 attempts. A task result is no longer lost because a single
  push happened to fail. (migration `0003_notification_outbox`)

### Changed

- **Dashboard passwords use PBKDF2-HMAC-SHA256** (600k iterations) instead
  of a single SHA-256 round. Existing `auth.json` records upgrade
  transparently on the next successful login. Token and password
  comparisons are now constant-time.
- **`costaff agent remove` stops and removes the agent's containers** (like
  `channel remove` / `platform remove`) and recreates the manager, instead
  of leaving an orphaned container holding its host port so the next
  `agent add` fails to bind.
- **`costaff update` detects core-image changes** (anything under
  `mcp_servers/`, `migrations/`, `agents/`, `requirements.txt`,
  `Dockerfile`) and guides — or, on a TTY, runs — `costaff core-rebuild`,
  because a plain `restart` recreates containers without rebuilding and
  would run the old code / skip a new migration.

### Fixed

- **Task lifecycle — no more stranded tasks.** Startup orphan recovery now
  reaps EVERY `doing` row unconditionally (executors die with the process;
  the old 30-minute age gate stranded tasks when the container restarted
  within 30 minutes of a task starting), plus a periodic sweep catches
  workers lost mid-life. Reaped tasks now notify the user, finalize the
  live progress panel, and advance the agent's queue. A failed upstream
  task now cascades `failed` down its dependency chain instead of leaving
  downstream tasks spinning in `queued` forever.
- **Per-agent serialization enforced in the executor.** A second task for
  an agent that is already running one is deferred back to the queue —
  concurrent MCP sessions on one sub-agent trigger the anyio cancel-scope
  race, so this is now a structural guarantee instead of a convention.
- **`costaff agent model` really persists for external agents.** It now
  writes the agent's plugin `.env` (which wins in `env_file` order), backs
  the env-var names into new `agent add` entries, recovers them from the
  manifest for pre-v0.1.0 entries, and exits non-zero instead of printing
  a fake success when the agent has no model surface (url-type).
- **`send_message_now` to WebChat actually sends.** The webchat branch
  used to return "Sent." without delivering anything; it now pushes
  through the same channel endpoint the notification dispatcher uses.
- **`costaff update --all` is no longer a silent no-op.** Called directly
  (not via Typer), the rebuild helpers received the `--core` OptionInfo
  sentinel and every plugin failed in core resolution (`Rebuilt 0/N`).
- **`dispatch_plan` links the chain correctly.** It parsed the task id
  with a loose regex that a step title containing `ID:` could hijack,
  stranding the rest of the chain; it now anchors on the full UUID.
- **Per-agent serialization survives name-spelling drift.** `coding` vs
  `coding_agent` slipped past the busy-check and ran concurrently (the
  anyio race); every per-agent comparison now normalizes the name.
- **Deliveries and failures no longer vanish.** A LINE push with a missing
  token was recorded as success and skipped the outbox; the license gate
  failed a task without advancing the queue (stranding dependents); an
  empty ADK reply was stored as a `done` result. All three are fixed.
- **The manager keeps its own MCP across add/remove.** `agent add` no
  longer appends a sub-agent's MCP to the manager (which triggered the
  anyio cancel-scope race), and `agent remove` tears down the MCP wiring
  it created so a dead URL isn't fed back to the manager.
- **Scheduler / delivery correctness.** Poll no longer starves a ready
  task behind a dependency-blocked one; a finished immediate task isn't
  re-run; and the WebChat-Enterprise env guess can't override an
  explicitly-set channel.
- **Plugin fragments join the core's real network** (a non-default core
  runs on e.g. `costaff_asst`, not `costaff_default`), so the manager can
  reach agents/channels deployed with `--core`.
- **CLI robustness.** A corrupt config on one core no longer aborts port
  allocation on another; `core use` validates on single-install hosts;
  `recreate_manager` warns on failure instead of claiming success;
  `docker up` failures raise a catchable error (no traceback);
  `costaff restart` runs preflight before stopping; and `agent add` rolls
  back a source it cloned when the deploy fails.

### Security

- Every published port now binds `127.0.0.1` by default (manager ADK web,
  bundled Postgres, dashboard, channel fragments) with per-host opt-out
  env vars; fresh installs generate a random Postgres password; corrupt
  `config.json` aborts loudly instead of being overwritten with defaults;
  retry-exhausted agent runs are recorded as `failed`, not `done`.
- External-agent `a2a_url` registration now DNS-resolves and rejects
  hostnames that map to loopback or the cloud-metadata / link-local range
  (SSRF), while still allowing private-LAN federation nodes.
- `GET /api/config` no longer returns bot tokens in plaintext — it reports
  only whether each is configured.

### CI / tooling

- Tests run across the Python 3.10 / 3.11 / 3.12 matrix (the documented
  floor); wheels package the CLI subpackages; Dependabot keeps pip and
  Actions patched; a pushed `v*` tag cuts a GitHub Release from the
  matching CHANGELOG section.

## [0.1.0-beta-1] - 2026-07-08

### Added

- **Dashboard cockpit — 3-tier information architecture.** New dark,
  theme-aware sidebar built on a `--ck-*` token system (`cockpit.css`):
  a System switcher (tier 0), a pinned Manager Agent + expandable External
  Agents tree (tier 1), and per-agent tabbed **MCP / API / Skill** component
  pages (tier 2). External agents render their real skills straight from the
  live A2A card; API/Skill/MCP registries are edited inline.
- **Multi-CoStaff ("Full") support.** A host running several independent
  cores (`stack` / `asst` / `twk` …) is now first-class end to end. The
  dashboard's System switcher and the new `costaff core list/use/discover`
  command share one registry + active-core pointer (`services/cores.py`).
  Every read endpoint and the Runtime Monitor follow the active System.
- **`--core` on every agent command.** `costaff agent
  add/remove/enable/disable/transfer/list/tags/restart/rebuild/model` resolve
  a target core (active core by default, `--core <name>` to override) and
  write to that core's `config.json` / `.env`, driving its compose project.
  Host ports are reserved across all cores so allocation never collides.
  Single-install hosts are unaffected (synthetic default core = historical
  paths). (`tests/test_multicore_cli.py`)
- **`costaff agent mcp list/set` and `costaff agent skills`.** The Component
  layer in the terminal, sharing exact semantics with the dashboard's MCP /
  Skill cards via `services/agent_components.py`.
- **Business Platforms App-Store registration.** Platforms no longer have to
  be installed on the dashboard host: pick an app from the official catalog
  (or Custom) and point it at a URL. Remote entries get full dashboard CRUD
  and URL-based health checks; local (CLI-installed) platforms stay
  CLI-managed. (`tests/test_platform_store.py`)
- **Regular Work multi-channel delivery.** A scheduled job can now deliver
  its result to several channel + recipient targets; the executor fans out
  and one failed channel no longer fails the run. Backed by a new
  `regular_works.channels` column (migration `0002`).
  (`tests/test_regular_work_channels.py`)
- **`costaff update --all`** — after pinning the core, re-pins and rebuilds
  every source-based agent and channel to the same `--tag` (or pulls latest
  when no tag). Reuses the per-plugin `agent rebuild` / `channel rebuild`
  semantics; each plugin is isolated so one failure doesn't abort the batch,
  and remote (`type: "url"`) agents are skipped. (`tests/test_update_all.py`)
- **Alembic database migrations** — the core schema is now managed by
  alembic instead of ad-hoc boot-time `create_all` + `ALTER`s. `init_db()`
  bootstraps via `_bootstrap_schema`: fresh DBs run `upgrade head`,
  pre-alembic deployments are brought to the baseline by the historical
  fixups and then stamped, SQLite/unit-tests fall back to `create_all`.
  New `costaff database migrate` (upgrade head from the host) and
  `costaff database history`. Baseline lives in `migrations/versions/`.
  (`tests/test_migrations.py`)
- **`costaff backup` / `costaff restore`** — whole-install snapshot &
  recovery into a single `.tar.gz` (core `.env`, `config.json`, `auth.json`,
  a `pg_dump` of the database, and the shared `workspace/`). The DB is
  dumped inside the running postgres container (consistent snapshot, no host
  Postgres client needed, no need to stop services). Logic in
  `services/backup.py`. (`tests/test_backup.py`)

### Changed

- **CRUD ownership principle enforced.** A resource is deletable only from
  where it was created: CLI-added agents/platforms are CLI-delete only, and
  UI-registered (remote / URL) resources are UI-deletable. Both surfaces
  stamp origin (`added_by` / platform `type`) and reject cross-surface
  deletes with a pointer to the right tool.
  (`tests/test_agent_crud_ownership.py`)
- **Chat / dashboard markdown** renders single-newline line breaks
  (`marked` `breaks: true`) so agent bullet lists no longer collapse into
  one paragraph.

### Fixed

- Dashboard now scopes the Agents view, Runtime Monitor, and per-core writes
  to the active core instead of hard-coding the `costaff` prefix.
- Renamed channel containers (`asst-channel-*`, `twk-channel-*`) are detected
  as LIVE in the gateways tab.

### Security

- Integration headers are encrypted at rest; the dashboard no longer leaks
  DB engine connections on each poll; defense-in-depth against XSS in the
  admin dashboard; notifiers no longer block the event loop on synchronous
  channel sends.

## [0.1.0-alpha-2] - 2026-06-14

### Added

- **`costaff start` preflight check** — validates `.env` (model API
  key, DB URI, security secrets, workspace dir) before touching
  Docker; fatal issues abort with the exact fix instead of letting
  containers crash-loop. Skippable via `--no-preflight`. Logic lives
  in `services/preflight.py` (12 unit tests in
  `tests/test_preflight.py`); `costaff doctor` reuses it for its
  `.env` section.
- **`costaff doctor` Suggested fixes** — problems detected during the
  run (Docker unreachable, network missing, agent port dead, env
  issues, missing channel sources, DB unreachable) are replayed at the
  end as a deduplicated problem → fix list.
- **Onboard wizard upgrades** — re-running `costaff onboard` now
  defaults every prompt to the existing `.env` value (safe re-entry);
  the Gemini API key is live-verified against the Gemini API with an
  immediate warning on rejection; WebChat is pre-selected in the
  channel list; already-deployed channels are kept instead of
  re-cloned; the wizard can create the dashboard admin account
  (previously only possible in the browser); a "next steps" panel
  closes the wizard.
- **`costaff agent add` seeds `agent_mcp_filters`** — new
  `mcp_configurable` agents get the 4-core-tool whitelist
  (`send_message_now` / `add_task_comment` / `move_to_shared` /
  `list_data_files`) automatically, so fresh sub-agents no longer
  inherit the manager's full ~40-tool MCP spec (token bloat +
  mis-selection). Seed-only-if-absent; constant exported as
  `services.config.CORE_PLUGIN_MCP_TOOLS`.

### Fixed (onboarding)

- `install.sh` no longer aborts on Ubuntu 24.04 — installs
  `python3.12-distutils` only where the package still exists.
- `install.sh` on macOS now launches Docker Desktop and waits for the
  daemon (up to 90s) instead of always deferring to a manual step; on
  Ubuntu it starts the Docker daemon via systemd when stopped.
- `costaff bootstrap` now generates `MCP_SECRET_KEY` /
  `API_HEADERS_KEY` / `ID_SALT` like the interactive wizard — CI
  deploys no longer run with the template salt and unauthenticated
  internal APIs. Default Gemini model bumped `gemini-2.5-flash` →
  `gemini-3-flash-preview` (2.5-flash function-calling is unreliable;
  onboard wizard default bumped likewise).
- `.env.template` documents `COSTAFF_WORKSPACE_DIR` (manual installs
  silently fell back to an anonymous Docker volume) and adds worked
  LiteLLM examples for Ollama / OpenAI / Anthropic.

- **Tag-aware CLI** — `costaff agent add` / `channel add` accept
  `--tag` (alias `--ref`) to pin clones to a release tag, branch, or
  commit. `costaff agent rebuild` / `channel rebuild` read the
  persisted pin from `config.json` and switch the working tree via
  `git fetch --tags && git checkout <ref>` instead of `pull --ff-only`.
  `--tag <new>` on rebuild overwrites the pin. `costaff update --tag`
  pins the core repo itself. `agent list` / `channel list` show the
  current pinned ref in a new "Ref" column.
- `Git` wrapper gained `clone(..., ref=...)`, `fetch_tags()`,
  `checkout()`, and `current_ref()` methods. 10 new unit tests in
  `tests/test_git.py`; 8 new CLI-integration tests in
  `tests/test_cli_tag_flow.py`.

### Changed

- `external_agents[name]` and `dynamic_channels[name]` entries in
  `config.json` may now carry an optional `ref` field. Absence
  preserves the legacy "track default branch" behaviour.

### Fixed

- `costaff agent rebuild` / `channel rebuild` now `force_remove` each
  declared container before `compose up --force-recreate`. compose's
  --force-recreate only recovers containers in the **same** project
  label, so any container created under a different project (very
  common across one host with mixed deploy histories) used to make
  rebuild fail with `Conflict. The container name "/X" is already in
  use`. The pre-up rm is idempotent — no-op when the name is unused —
  and matches operator intent: "rebuild" should rebuild, not fail on
  stale state.
- `costaff agent rebuild --tag <ref>` / `channel rebuild --tag <ref>`
  no longer persist the new `ref` to `config.json` when the underlying
  `git checkout <ref>` fails (e.g. the tag doesn't exist on origin).
  Previously the working tree would stay on whatever HEAD was already
  there while config claimed the new pin — a confusing lie. Now config
  is only written when the checkout actually succeeds.

### Discoverability

- New `costaff agent tags <name>` and `costaff channel tags <name>`
  commands. Lists release tags on the plugin's origin remote via
  `git ls-remote --tags`, sorted newest first, with the currently
  pinned ref annotated `✓ pinned`. Use this before `rebuild --tag`
  to discover what versions exist — saves a round-trip to GitHub.
  Empty remote prints `(no tags found on origin)` so the gap is
  obvious.

## [0.1.0-alpha-1] - 2026-05-27

First tagged pre-release of the CoStaff platform core. Snapshots the
Manager Agent, the `costaff` CLI, the platform server + notifier
fanout, the ProgressContext panel pipeline, the IdentityMap channel
routing, the OSS limits / upgrade gating, and the migration to the
A2A-native task model that the sister channel / agent repos build on.

### Notable in this snapshot

- Manager Agent with async ProjectTask + SYSTEM_CALLBACK re-entry for
  long-running sub-agent work.
- Channel notifiers (Telegram / WebChat OSS / WebChat Enterprise) with
  unified `ProgressContext.session_id = task_<id>` panel-key contract
  and IdentityMap-based delivery routing.
- `costaff` CLI: `start` / `stop` / `restart` / `ps`,
  `agent add|list|remove|restart|rebuild`,
  `channel add|list|remove|rebuild`,
  `config show`, `database backup`.
- Dynamic external agent / channel registration via
  `~/.costaff/costaff-agent/<name>` and
  `~/.costaff/costaff-channel/<name>` clone targets, wired into
  docker-compose via per-plugin `compose-fragment.yaml`.
- OSS limits: `max_agents=3`, upgrade pitch on limit errors.

### Added

- `CHANGELOG.md` (this file).

### Version artefacts in this release

- `VERSION` file: `v0.1.0-alpha-1`
- `utils/paths.py` exports `VERSION = "0.1.0-alpha-1"` (read by CLI
  banner + `/api/health`).
- `setup.py` declares `version="0.1.0a1"` (PEP 440 canonical form of
  the same release).
