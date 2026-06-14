# Changelog

All notable changes to this project are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[SemVer](https://semver.org/).

This repository is **private** — for internal / paid-tier consumption only.

## [Unreleased]

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
