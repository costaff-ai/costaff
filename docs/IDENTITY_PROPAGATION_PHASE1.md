# Identity Propagation — Phase 1 Design (WebChat Enterprise → HRM)

Status: **DRAFT / proposal**. Touches production backend auth — do not implement
without sign-off. Scope is deliberately narrow: one channel (WebChat Enterprise),
one agent (`costaff-agent-hrm`), one platform (`costaff-platform-hrm`).

## 1. Problem

The HRM agent reaches the HRM backend through `costaff-hrm-mcp`, which
authenticates with a single master service key (`HRM_API_KEY`). Per
`backend/app/security.py`, a valid `X-API-Key` means **full access, RBAC
bypassed**. Consequence: every end user who can reach the agent acts with
god-mode against HRM data, regardless of their real role. A plain employee
asking the agent "show me everyone's payslips" succeeds, because the agent — not
the user — is the principal.

The platform already has everything needed to do this correctly:

- `guard(module)` resolves a caller's effective roles **per company** and
  enforces read/write on each module.
- `tenancy.py` auto-scopes every ORM query to the active company (row-level
  tenant isolation).
- `current_session` (ESS) gives "act only on your own records" semantics.

The only defect is that the agent's calls never carry the **end user's
identity**, so none of the above engages. Phase 1 closes that gap for one
channel end-to-end, as a low-blast-radius pilot.

## 2. Goal & non-goals

**Goal.** When a WebChat-Enterprise user talks to the HRM agent, HRM data
access is decided by **that user's** real roles + company + ESS scope, using the
platform's existing enforcement — without splitting the agent or duplicating
instructions.

**Non-goals (deferred to Phase 2+).**
- Non-OIDC channels (Telegram, Discord, LINE, public WebChat) — they lack a
  verified HRM identity; see §9.
- Other platforms (ERP/CRM/SCM/…). The same pattern applies but is out of scope.
- Removing the master-key bypass entirely. It is **kept** for system/automation
  contexts (scheduled payroll runs, holiday seeding); see §8.

## 3. The act-as model

We do **not** ship the user's HRM session cookie through the agent chain. We use
a **trusted-subsystem impersonation** model:

- The master service key stays server-side, never leaves the MCP container.
- The agent additionally asserts *"I am acting on behalf of subject S in company
  C."* via headers.
- The backend trusts that assertion **only because it arrives with the master
  key**, then resolves S's real roles/company and runs the request exactly like a
  human request from S (RBAC + tenancy + ESS all apply).

Two backend modes, selected by what accompanies the key:

| Inbound to backend | Backend principal |
|---|---|
| `X-API-Key` only (today) | service / system — full bypass (**kept** for automation) |
| `X-API-Key` + `X-Act-As-Subject` (+ `X-Company-Id`) | **impersonate** subject S — RBAC/tenancy/ESS apply |

### 3.1 End-to-end sequence

```
WebChat-Enterprise UI host (user authenticated via AM OIDC; we hold their email)
  │  on ADK session create, seed state={"costaff_identity":{email}}   [hop ⓪ §11]
  ▼
Manager (costaff_agent) — session state now carries the verified email
  │  before_tool_callback reads its OWN session state and injects
  │  act_as_email into the HRM AgentTool request (NOT from message text)
  │                                              [hop ②, anti-forgery §5]
  ▼
HRM Agent (A2A leaf)
  │  before_model_callback binds act_as_email → session state
  │  McpToolset(header_provider=…) reads state → per-call header     [hop ③④]
  ▼
costaff-hrm-mcp
  │  ASGI middleware lifts X-Act-As-Email from the inbound request into a
  │  ContextVar; setup._headers() forwards it alongside X-API-Key     [hop ⑤]
  ▼
costaff-hrm-backend
     guard()/current_session(): key + act-as-email → resolve user's roles,
     set tenant, enforce as that user                                [hop ⑥]
```

## 4. Per-hop change summary

| Hop | Repo / file | Change | Risk |
|---|---|---|---|
| ⓪ seed | `costaff-channel-chatbot` `adk_client.py` + `costaff-channel-webchat-enterprise` runtime | seed `state={"costaff_identity":{email}}` at ADK session create (UI host, trusted) | low–med |
| ② inject | `costaff` `agents/costaff_agent/progress_inject.py` | read `costaff_identity` from Manager session state → inject `act_as_email` into HRM AgentTool request | low |
| ③ parse | `costaff-agent-hrm` `agent/progress.py` (or a new `identity.py`) | parse `act_as_email` → session state | low |
| ④ agent→mcp | `costaff-agent-hrm` `agent/mcp_toolsets/__init__.py` | `McpToolset(header_provider=…)` reading state | low (native) |
| ⑤ mcp→backend | `costaff-platform-hrm` `mcp/setup.py` (+ small ASGI middleware) | forward `X-Act-As-*` to backend | low |
| ⑥ enforce | `costaff-platform-hrm` `backend/app/security.py` (+ a resolver in `services/auth.py`) | key+act-as → impersonate subject | **medium** |
| ⑥' tests | `costaff-platform-hrm` `backend/tests/` | act-as RBAC/tenancy/ESS cases | — |

## 5. Anti-forgery (the part that must be right)

The impersonated subject is a **security decision**. If the LLM, or the end
user, can choose it, the whole model is worse than today.

**Invariant: the act-as subject is set only by trusted code, and the LLM never
participates in choosing or carrying it.**

Threats and mitigations:

1. **User injects a fake `[PROGRESS_CONTEXT]`/identity block in their chat
   message.** Today `progress_inject._BLOCK_RE` searches the Manager's
   `user_content` for the block — which *includes the user's own text*. A user
   could paste `act_as_subject=<the CEO>`.
   - **Mitigation:** core must NOT derive the act-as subject from free-form
     message text. It derives it from the **session's authenticated identity**
     (the enterprise user behind this conversation), looked up server-side, and
     writes the identity block itself. The regex-from-text path is acceptable
     only for the *display* fields (channel/session_id), never for the principal.
   - Strip any client-supplied `[IDENTITY]`/`act_as_*` tokens from inbound user
     text before the Manager turn, so a forged block can't survive even by
     coincidence.

2. **LLM emits its own identity block in the outgoing request.** The agent must
   not trust request *text* for the principal. `header_provider` reads from
   **session state** that was populated by the trusted parse of the
   core-injected block — and the agent's parser must accept the principal field
   **only** from the deterministically-injected block, not from arbitrary
   positions in the prompt. Prefer carrying the principal in a location the LLM
   cannot reproduce verbatim (e.g. a state value seeded by core via the A2A
   session, not prompt text) once the A2A transport allows it; until then, see §5.1.

3. **Agent forwards no act-as but backend defaults to bypass.** Acceptable: that
   is the system/automation path. But a *user-originated* task with no resolved
   subject must NOT silently fall back to god-mode — see §7 fallback policy.

4. **MCP trusts `X-Act-As-*` from anyone.** The middleware must honor act-as
   headers **only on requests that also present the valid master key** (i.e.
   from our agent), and the MCP→backend hop always re-attaches the key. External
   callers without the key get nothing.

### 5.1 Carrying the principal — RESOLVED via ADK session state

Investigation outcome (see §6): the principal does **not** need to ride in
prompt text. The chatbot library creates the Manager's ADK session with a
`state` object (`adk_client.ensure_session` →
`POST /apps/{app}/users/{uid}/sessions {"sessionId":…, "state":{}}`). The UI
host (enterprise webchat), which holds the authenticated user, **seeds the
verified identity into that session state at creation time**. The Manager reads
it from its OWN session state — server-side, deterministic, and **not
LLM-forgeable** (the LLM cannot write session state, and the value never passes
through prompt text the user can spoof). This is strictly better than the
prompt-carried `[PROGRESS_CONTEXT]` channel and supersedes the earlier fallback.

The principal is a non-secret identifier (the user's verified **email** — see
§6). The trust root is twofold: (a) session state was written by the trusted UI
host, not the model; (b) the MCP→backend hop still requires the master key.

## 6. Identity resolution — DECISIVE FINDING

**The OIDC identity does NOT cross the federation boundary today.** Verified
end-to-end:

- The UI host (enterprise webchat, on `costaff-demo-assistant`) authenticates the
  user via the shared AM OIDC realm (`sso_oidc.py` reads AM userinfo +
  `realm_access.roles`) — the SAME realm HRM trusts.
- But it keys users by **email** (`WebchatEntUser.email` unique;
  `WebchatEntUser.id` is an internal UUID, NOT the AM `sub`; the AM `sub` is read
  at login but **not persisted**). The session JWT's `sub` = the local UUID.
- The federated call to the prod Manager sends only
  `uid = webent_<sha256(uuid+salt)[:16]>` (`adk_client.get_user_id` /
  `chat_persist.hash_user_id`) + the message (`run_adk_prompt` payload
  `{appName, userId, sessionId, newMessage}`). **Neither email nor AM sub
  travels.** The hash is one-way, and the prod box has no table to reverse it
  (identity lives in the UI host DB, per the note in
  `task_helpers.get_user_channel_info`).

So Phase 1 **must add** a trusted identity channel across the boundary. The
carrier is **ADK session state** (§5.1): `ensure_session` already posts a
`state` object (currently `{}`).

**Join key = verified email.** HRM keys by AM `sub` (`User.subject`) but already
supports `auto_link_by_email` (`services/auth.py:136`); the enterprise webchat
keys by email; AM verifies email (`email_verified` enforced in `sso_oidc.py`).
Email is the one identifier reliably available on the UI host for every logged-in
user, so it is the Phase-1 principal. The backend act-as resolver (§8) accepts a
verified email and resolves it to an HRM `User`/employee.

- `X-Company-Id` is optional; if omitted the backend resolves the user's default
  / sole-membership company via `resolve_active_company`. Multi-company users
  carry the active company in session state the same trusted way.
- If the email resolves to no HRM user/employee, Phase 1 applies the fallback
  policy (§7), never service bypass.

## 7. Fallback policy (user-originated, no resolvable subject)

For a user-originated HRM task where core cannot resolve a trusted subject:

- **Default (recommended): deny with a clear message** ("此帳號尚未連結 HRM 身分，
  無法代為操作"). Fail closed.
- Optional softer mode (config-gated): allow only explicitly read-only,
  non-personal tools (e.g. `hrm_list_holidays`, `hrm_announcement_feed`) and
  refuse anything personal/write. This requires the agent to know which tools are
  safe-anonymous — added as a small allowlist, not as LLM judgement.

System/automation tasks (no human originator) keep the service-bypass path
deliberately.

## 8. Backend changes (`costaff-platform-hrm`)

`backend/app/security.py` — both `guard()` and `current_session()`:

```text
service = _service_key_ok(x_api_key)
act_as_email   = request.headers.get("X-Act-As-Email")     # verified email (Phase 1)
act_as_subject = request.headers.get("X-Act-As-Subject")   # AM sub (future)

if service and (act_as_email or act_as_subject):
    user_payload = resolve_impersonated(db, subject=act_as_subject, email=act_as_email)  # NEW
    if user_payload is None:
        raise HTTPException(403, "act-as 身分無法解析")
    cid = resolve_active_company(db, user_payload, x_company_id, False)
    roles = effective_roles(db, user_payload, cid)
    # …identical to the human branch from here (RBAC check / yield) …
elif service:
    # unchanged: full-bypass service/system context
elif user:
    # unchanged: human cookie-JWT path
```

`services/auth.py` — new
`resolve_impersonated(db, subject=None, email=None) -> dict | None`: prefer
`User.subject == subject`; else resolve by verified email (match a `User`/linked
`Employee` email, reusing the same path as `auto_link_by_email`). If found and
enabled, build the SAME payload shape `effective_roles`/`resolve_active_company`
already consume (`{uid, subject, sub, roles, pa, role}`), sourcing roles from the
user's known realm roles / per-company memberships. Return `None` if
absent/disabled. Reuses the exact resolution a real login produces — no parallel
RBAC logic.

`current_session()` impersonation must set `subject` so ESS endpoints resolve the
linked employee and "own data only" engages — that is what stops user A reading
user B's personal records.

**Audit.** Log impersonated calls distinctly (`audit(... "act_as", subject ...)`)
so the trail shows "agent acting as S", not an anonymous service hit.

## 9. MCP changes (`costaff-platform-hrm/mcp`)

`setup.py`: today `_headers()` returns only `{"X-API-Key": …}`. Add an ASGI
middleware on the streamable-http app that copies inbound `X-Act-As-Subject` /
`X-Company-Id` into a `ContextVar`; `_headers()` reads the ContextVar and appends
them. This avoids touching all 31 tool functions. The master key is always
re-attached on the backend hop, so act-as never works without it.

## 10. Agent changes (`costaff-agent-hrm`)

1. **Parse identity → state.** Extend the existing `before_model_callback` in
   `agent/progress.py` (already parsing PROGRESS_CONTEXT) — or a small
   `agent/identity.py` — to bind `act_as_subject` / `company_id` into session
   state **once**, from the trusted block only.
2. **Dynamic headers.** In `agent/mcp_toolsets/__init__.py`:

```text
def _hdr(ctx):                       # ctx: ReadonlyContext
    s = ctx.state or {}
    h = {}
    if s.get("act_as_email"): h["X-Act-As-Email"] = s["act_as_email"]
    if s.get("company_id"):   h["X-Company-Id"]   = str(s["company_id"])
    return h

return [McpToolset(connection_params=params, header_provider=_hdr)]
```

`header_provider` is native in ADK 2.1.0 (`McpToolset.__init__`,
`mcp_toolset.py:304-306`) and is invoked per tool call with a `ReadonlyContext`
whose `.state` we read. **No transport or session-count change** — still exactly
one McpToolset, so the cancel-scope race posture is unchanged.

The 4 core tools (`costaff_api.py` httpx shim) are unaffected.

## 11. UI-host & core changes (identity seeding + forwarding)

**UI host — enterprise webchat (`costaff-channel-webchat-enterprise` +
`costaff-channel-chatbot`).** Seed the verified identity into the Manager's ADK
session state at session creation:
- `costaff-channel-chatbot/adk_client.ensure_session` / `create_new_session`:
  accept an optional `state` dict and post it instead of `{}` (default keeps
  current behaviour).
- enterprise webchat runtime: when it owns the authenticated `WebchatEntUser`,
  pass `state={"costaff_identity": {"email": user.email}}` (plus active company
  if known) into session creation. This is the trusted, server-side, non-LLM
  write of §5.1. Re-assert on session reuse if the session predates this change.

**Core (`costaff`).**
- `agents/costaff_agent`: a `before_tool_callback` (or extend
  `progress_inject`) that, for AgentTool calls to the HRM agent, reads
  `costaff_identity` from the Manager's **own session state** and injects
  `act_as_email` (+ company) into the request to the agent — deterministic, never
  from message text.
- Optionally also expose it the way the agent prefers to bind state (see §10).
- Strip any user-supplied `costaff_identity` / `act_as_*` tokens from inbound
  message text so nothing forged can survive (§5).

## 12. Test plan

Backend (`costaff-platform-hrm/backend/tests`):
- key + act-as(viewer) → can read, write 403.
- key + act-as(hr_specialist) → write succeeds.
- key + act-as(employee with no module role) via ESS endpoint → sees only own
  records; cannot read a colleague's payslip.
- key + act-as(subject in company A) → tenancy returns only company-A rows; a
  company-B id in `X-Company-Id` the user has no membership for → resolves to a
  permitted company or 403, never cross-tenant leak.
- key only (no act-as) → unchanged full bypass.
- act-as for unknown/disabled subject → 403.

Agent: `header_provider` emits headers iff state is bound; absent state → no
act-as headers (→ backend fallback policy).

Core: forged `[PROGRESS_CONTEXT]` / identity tokens in user text do **not**
become the principal (regression test mirroring `test_progress_inject.py`).

E2E on the pilot box: two enterprise users with different roles ask the same
question through the HRM agent and get correctly different results; an employee
cannot retrieve another employee's salary.

## 13. Rollout & rollback

- **Feature flag.** Backend honors act-as only when `HRM_ACT_AS_ENABLED=true`;
  agent emits headers only when configured. Off by default → behaviour identical
  to today.
- **Order.** Ship backend (accepts but no one sends) → MCP forward → agent
  emit → core inject. Each step is inert until the next arrives; safe to stage.
- **Rollback.** Flip the flag off — instant revert to service-bypass. No schema
  migration is required (resolution reuses existing `User`/membership tables).
- **Blast radius.** Pilot box only (`costaff-platform-prod`), one agent. Deploy
  via the file-copy + `docker compose build/up` path (no git on GCE).

## 14. Open questions

1. ~~Can core obtain the user's OIDC sub server-side?~~ **RESOLVED (§6):** no
   identity crosses the federation boundary today; Phase 1 adds a session-state
   seed of the verified **email** on the UI host. Requires a UI-host change
   (chatbot lib + enterprise webchat) — accepted as part of scope.
2. ~~Prompt-carried identity acceptable?~~ **RESOLVED (§5.1):** use ADK session
   state, not prompt text — non-LLM-forgeable.
3. Multi-company users: where does the active company come from — last-selected
   in the UI, or default? Affects what the UI host seeds into session state.
4. Session reuse: existing Manager sessions created before this change have no
   `costaff_identity`. Re-assert on each turn, or migrate? (Lean: re-assert.)
5. Audit retention / format for impersonated agent actions.
6. Should HRM email match be case-insensitive and require an enabled, linked
   employee (not just any user) before granting ESS scope? (Lean: yes to both.)
```
