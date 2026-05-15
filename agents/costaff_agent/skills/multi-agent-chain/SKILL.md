---
name: multi-agent-chain
description: >
  Activate for ANY request involving specialist delegation — single or multi-step.
  Contains the complete orchestration SOP: plan-and-confirm format, sequential
  execution rules, how to write a complete `request` argument, recovery from
  errors, retry limits, file delivery rules, and output presentation.
---

# Multi-Agent Orchestration SOP

## When to Use
- A task requires delegating to one or more registered specialist agent tools (`<agent_name>(request: str)`)
- Two or more specialists need to work in sequence (output of one → input of next)
- User asks to combine multiple specialist capabilities in a single workflow

---

## Principle 1 — Present a Plan First (multi-step only)

When a request requires **two or more** specialist calls (any file or data hand-off between specialists), present a written plan and wait for user confirmation **before calling any agent tool**.

**Skip the plan (proceed immediately) when**:
- A single specialist fulfils the whole request
- User already confirmed a plan earlier in this session
- User says "直接做", "不用計劃", "go ahead", or similar

**Plan format (Telegram HTML — use exactly):**
```
📋 <b>執行計劃</b>

<b>Step 1: [專家職稱] (agent: <code>&lt;agent_name&gt;</code>)</b>
• 任務：...
• 輸入：...
• 預期產出：<code>/app/data/shared/costaff-agent-&lt;hyphen-name&gt;/&lt;project&gt;/xxx.ext</code>

<b>Step 2: [專家職稱] (agent: <code>&lt;agent_name&gt;</code>)</b>
• 任務：...
• 輸入：Step 1 的產出
• 預期產出：<code>/app/data/shared/costaff-agent-&lt;hyphen-name&gt;/&lt;project&gt;/yyy.ext</code>

請回覆「OK」開始執行，或告訴我需要調整的地方（工具、順序、輸出格式等）。
```

After presenting the plan: **STOP**. Do not call any tool. Wait for the user's next message.
- Confirmation ("OK", "好", "同意", "開始", "go") → proceed to execute
- Change request → update plan, present again for re-confirmation
- Clarifying question → answer it, then re-confirm the (possibly revised) plan

---

## Principle 0 — Use `dispatch_task` for Every Dispatch

To send work to a specialist agent, call **one** tool: `dispatch_task`. It atomically creates the ProjectTask and queues it for immediate execution, so a task can never be stranded in `backlog`.

**🟢 The one and only dispatch pattern:**

```
dispatch_task(
  epic_id=...,
  user_id=...,
  title=...,
  assigned_agent="<agent_name>",   # REQUIRED — cannot dispatch to nobody
  spec=...,                          # write a real spec, see Principle 2
  session_id=..., channel=..., recipient=...,   # for callback / progress
)
→ returns task_id, executor triggered immediately
```

This single call replaces the old two-step pattern (`create_project_task` + `update_task_queue`).

**❌ LEGACY — do not use for new dispatches:**

`create_project_task` is now flagged LEGACY. It leaves the task in `backlog` and requires a follow-up `update_task_queue` in the same turn — easy to forget, and a missing queue means the task is stranded forever. Only fall back to it if you genuinely need a two-phase create (rare; the only normal case is re-ordering an existing queue via `update_task_queue` alone).

The 2026-05-15 PM2.5 stuck-task incident on Mac Mini happened because the manager called `create_project_task` but skipped `update_task_queue`. `dispatch_task` makes that incident structurally impossible — there is no second step to forget.

**Rule of thumb:** every reply to the user that says "task created" / "已派 … 處理（任務編號：xxx）" / "已建立新任務 #xxx" MUST be preceded by exactly one `dispatch_task` call in the same turn. A reply that cites a task ID without a matching `dispatch_task` call is a hallucinated dispatch.

---

## Principle 0A — On Plan Approval, Dispatch the ENTIRE Chain in One Turn

When the user confirms a multi-step plan ("OK", "好", "go"), you **MUST** call `dispatch_task` for **every step** of the plan in the same turn — not just the first. The executor handles ordering automatically: the auto-link mechanism (or an explicit `depends_on` you set) keeps each downstream task in `backlog` until its upstream finishes, then promotes it to `queued` and runs it. **You do NOT need to wait for the upstream to complete before dispatching the downstream.** That's the whole point of `depends_on` + auto-link.

**🟢 CORRECT — fire the whole chain at OK:**

```
User: OK
Manager turn (one turn, multiple tool calls):
  ① dispatch_task(title="Step 1: load wine CSV",
                   assigned_agent="coding_agent", ...)
     → returns task_id_A   (status=queued, executor triggered)
  ② dispatch_task(title="Step 2: generate PDF report",
                   assigned_agent="business_analysis_agent",
                   depends_on=task_id_A,   # explicit chain link
                   ...)
     → returns task_id_B   (status=backlog, waits for A; auto-promoted when A done)
  reply to user: "已派工。Coding (#A) 處理中，BA (#B) 已排入待辦、A 完成後自動接續。"
```

**❌ FORBIDDEN — dispatch only Step 1, then ask "should I continue?":**

```
User: OK
Manager turn:
  dispatch_task(Step 1 only)
  reply: "已派 Coding 處理 (#A)。完成後我會通知您。"
…(Coding finishes, SYSTEM_CALLBACK fires)…
Manager turn (callback):
  reply: "Step 1 完成。要不要派 BA 處理 Step 2？"     ← ❌ 不要問
```

The user already approved the plan. Asking again between steps is annoying and turns a 2-minute auto-chain into a multi-prompt slog. Reproduced 2026-05-15 in the wine PDF retest — Manager dispatched only Coding, then asked "您希望我將這個 JSON 數據交給 Business Analysis 代理人進行進一步的分析並製作報告嗎？", requiring the user to OK again before BA started.

**The only valid reasons to ask between steps:**
- Step N's actual output makes Step N+1 obsolete or invalid (e.g. Coding reports the dataset is empty → BA's report makes no sense). Tell the user honestly.
- The upstream step failed and the user needs to decide retry vs abandon.
- The user has interjected a new instruction that changes the plan mid-stream.

If none of the above applies and the plan is still valid, do NOT ask. The chain auto-advances; just report progress when the last step finishes.

**The synthetic callback's job is to summarise, not to gate-keep.** When the Coding callback fires, your reply should describe what was produced AND state that the downstream step is already in motion (because it is — you dispatched it back when the user said OK). Do not phrase it as a question.

---

## Principle 1A — Iteration: Use the Existing Path (apply BEFORE drafting the Plan)

Classify the request before planning. **An iteration is anything that touches a deliverable that already exists in this session.**

**Iteration signals** (any of these → treat as iteration):
- The request refers to a previously delivered file or feature
- The request uses modify / fix / extend verbs. Examples (Chinese): 改, 修, 加, 優化, 升級, 修復, 沒了, 不見了, 不能用. Examples (English): fix, update, extend, broken, bug, missing, not working
- The request reports a defect in something already shipped this session
- The request adds a feature to a deliverable already produced

**When the request is iteration — strict rules**:

0. **🔴 MUST dispatch a real task — NOT just a verbal promise.**

   When the user asks to modify / extend / fix an already-completed deliverable (e.g. "改成 10 頁", "加結論段落", "換更深的模型", "報告再詳細一點"), you **MUST** call `dispatch_task` **before** replying to the user:

   1. Call `dispatch_task` — write the `spec` to clearly state the modification (referencing the prior task's output path and the requested change). One atomic call creates and queues the task.
   2. **Only after** the call returns successfully → reply to the user, citing the new task ID.

   ❌ **FORBIDDEN — verbal-only acknowledgment:**
   ```
   User:    "可以擴展到 10 頁嗎？"
   Manager: "沒問題，我會請 BA 擴展到 10 頁…我會將此要求更新到任務規格中
            （任務編號：f12d8d10）。完成後我會立即通知您。"
            [no dispatch_task call — user waits forever for work that never starts]
   ```
   Reproduced 2026-05-15 on costaff-prod-test: manager promised an update to a *done* task, never dispatched, user spent minutes asking "有在做事嗎？". The DB had zero new rows.

   ✅ **CORRECT — dispatch first, then reply:**
   ```
   User:    "可以擴展到 10 頁嗎？"
   Manager: [call dispatch_task(title="[Iteration] 擴展論文至 10 頁",
                                spec="In-place modify of .../thesis.pdf,
                                      extend to ≥10 pages…",
                                assigned_agent="business_analysis_agent")]
            → task id e.g. abc12345
            [reply to user]: "已建立新任務 #abc12345 給 BA 擴展報告至 10 頁，
                              完成後我會通知您。"
   ```

   The Task DB is the source of truth — a promise that is not backed by a row in `project_tasks` is a hallucination, no matter how friendly the wording.

1. **Reuse the existing path.** The plan's expected-output path MUST be the **same path** as the previous deliverable.
   **FORBIDDEN suffixes** on the filename: `_v2`, `_v3`, `_new`, `_fixed`, `_updated`, `-mobile`, `-deluxe`, `-final`, or any version marker. The file is updated in place — git is for tracking history, not filenames.

2. **Plan wording**: describe the action as "modify the existing file at `<path>`" (in the user's preferred language), not "create a new file".

3. **The `request` you pass to a coding-style specialist MUST contain this exact instruction block** (in addition to describing the change):
   ```
   This is an in-place modification of an existing file at <absolute path>.
   Use patch_file() or insert_after_line() for surgical edits.
   Do NOT call write_file() to overwrite the whole file.
   Do NOT create a new versioned filename (no _v2, _new, _fixed suffixes).
   ```

4. **Keep all related files under the same project subdirectory.** Do not spawn a new project dir per iteration.

**When the request is a brand-new build** (no prior deliverable in this session, no existing file referenced): proceed normally — choose a fresh project directory and filename.

---

## Principle 1B — Path Format (CRITICAL)

Every path you write in a plan or in a `request` MUST include a kebab-case **project subdirectory** under the agent's shared slot. Format:

```
/app/data/shared/costaff-agent-<name>/<project>/.../<filename>
```

- `<project>` = kebab-case name inferred from the user's task (e.g. `wine-eda`, `quicksort-practice`, `wine-svm-report`).
- The exact inner structure (`outputs/`, `src/`, or files at the project root) is the specialist's responsibility — describe **what** the file is, let the specialist decide the inner layout.
- Reuse the same `<project>` across every step of the plan so the user sees one consistent project name.

**FORBIDDEN**: never prescribe a path directly under `/app/data/shared/costaff-agent-<name>/` (no subdirectory). The agent will normalize it elsewhere; your plan and final `[FILE: ...]` summary will then point at a non-existent path, confusing the user. Examples of bad vs good:

| ❌ Bad (flat root) | ✅ Good (with project subdir) |
|---|---|
| `/app/data/shared/costaff-agent-coding/wine_stats.csv` | `/app/data/shared/costaff-agent-coding/wine-eda/wine_stats.csv` |
| `/app/data/shared/costaff-agent-business-analysis/wine_report.pdf` | `/app/data/shared/costaff-agent-business-analysis/wine-eda-report/wine_report.pdf` |

Do NOT add inner directories like `outputs/` or `src/` to the path you prescribe — that is the specialist's own decision. Your job is only to ensure the kebab-case `<project>/` segment is present.

---

## Principle 2 — Write a Complete `request` (CRITICAL)

The specialist agent tool receives **only the `request` string you write** — it does not see the user's prior messages, your plan text, or the conversation history. If `request` is vague, ambiguous, or just an acknowledgement like "OK" or "go", the specialist has no context and will reply conversationally without doing any work.

**Every `request` must be self-contained and imperative.** Include:

| Element | Required? | Example |
|---|---|---|
| Concrete action verb | always | "Load the wine dataset and run EDA…" |
| Input source / file paths | if any | "Read `/app/data/shared/costaff-agent-coding/wine-svm/wine_results.json`" (use the exact path the upstream specialist returned — including any `outputs/` it added) |
| Expected output format & path | always | "Save as `/app/data/shared/costaff-agent-business-analysis/wine-svm-report/wine_report.pdf`" |
| Constraints / language / quality bar | as needed | "Report in Traditional Chinese; include charts and analysis narrative" |
| `[PROGRESS_CONTEXT]` block (when applicable) | if user-facing progress matters | with `user_id`, `channel`, `session_id` |

**Forbidden in `request`:**
- ❌ Mentions of other specialists or chaining ("then pass to X", "after this, transfer to Y")
- ❌ Orchestration verbs aimed at the specialist ("delegate", "transfer", "hand off")
- ❌ Empty / single-word strings ("OK", "go", "do it") — the specialist will not act
- ❌ References to "the user's earlier message" or "what was discussed" — the specialist cannot see those

The specialist's only job: **do the work, save the file, report back**. Chaining to the next specialist is your responsibility after the current call returns.

---

## Principle 3 — Execute One Specialist at a Time, In Order

**THIS IS THE MOST COMMONLY VIOLATED RULE — READ CAREFULLY.**

Call only one agent tool per step. **Wait for the tool to return** before calling the next. The return value is the specialist's completion signal — do not begin the next step until you have it.

### Scope of this principle

This principle applies to **direct AgentTool invocation** — i.e. calling `coding(request=...)` or `business_analysis(request=...)` as if they were synchronous function calls. **It does NOT apply to `dispatch_task`**: `dispatch_task` is the async dispatch path, and the executor handles ordering via `depends_on` + auto-link (see Principle 0A). When you dispatch multiple steps in one turn via `dispatch_task` with a `depends_on` chain, the downstream task waits in `backlog` until the upstream finishes — there is no race.

### ⛔ ABSOLUTELY FORBIDDEN (direct AgentTool invocation only)

- Invoking two or more specialist agent tools in the same turn / response
- Invoking the downstream specialist (e.g. `business_analysis`) before the upstream specialist (e.g. `coding`) has returned, *even if* you believe the downstream specialist can start partial work
- Calling `business_analysis(request=...)` and `coding(request=...)` back-to-back without an intervening completion signal
- "Just kicking them off in parallel to save time" — this **breaks the chain**: the downstream specialist runs against missing files and fails silently

### ✅ Correct sequence (Coding → BA chain)

```
turn N    : call coding(request=...)
          → wait for coding's return value (absolute path to output file)
          → coding returns: "...wrote /app/data/shared/costaff-agent-coding/<project>/results.json"
turn N+1  : (optional) brief send_message_now: "▶️ BA 正在生成報告，請稍候"
turn N+1  : call business_analysis(request=...) — request includes the EXACT path coding returned
          → wait for BA's return value
turn N+2  : final consolidated reply to user with all artifacts
```

### ❌ Wrong sequence (today's reproduced bug — 2026-05-14)

```
turn N    : call business_analysis(request=...)   ← FIRES BA FIRST
turn N    : call coding(request=...)              ← FIRES CODING 30s LATER
                                                    in the same turn
          → BA can't find coding's output → reports "file not found"
          → coding finishes later, but BA already failed
```

Even if these two calls were made in opposite order, **putting them in the same turn is the violation**. The chain requires the upstream tool's **return value** to thread into the downstream tool's `request`. You cannot have that value until the upstream call returns.

### Completion signal — what counts

A valid completion signal always includes at least one of:
- An absolute output file path (e.g. `/app/data/shared/costaff-agent-<name>/<project>/result.csv`)
- A concrete computed result or value
- A structured analysis, summary, or conclusion
- An explicit failure declaration explaining why the task cannot be completed

Mid-task progress messages sent via `send_message_now` (e.g. "安裝中…", "🔍 開始調查") are **NOT** completion signals — the specialist may emit several before its tool call finally returns.

### Recovery if you realise you already invoked two specialists in parallel

1. **Do NOT** retry calling the downstream specialist again "just in case it works this time" — the upstream output is still missing
2. **Wait** for the upstream specialist (e.g. coding) to actually return
3. Read its return value, extract the artefact path
4. Then call the downstream specialist again with the extracted path in `request`
5. Apologise briefly to the user only if the first BA failure was already reported — don't re-report it

---

## Principle 4 — Pass Exact Results, Never Reconstruct

Extract the **exact** output from the specialist's return value (file path, value, identifier) and pass it verbatim into the next specialist's `request`. Never retype, reconstruct, or guess.

**Path naming (CRITICAL — common bug source)**:
- Filesystem paths use **hyphens**: `costaff-agent-business-analysis`
- Agent tool names use **underscores**: `business_analysis(request=...)`
- Never derive one from the other; refer to each registered tool's exact name

---

## Principle 5 — Brief Progress Updates Are Allowed Between Calls

Between two specialist calls, you may emit a brief `send_message_now` progress line so the user knows work is continuing. Keep it to one Chinese sentence (e.g. "▶️ 商業分析專家正在生成報告，請稍候。"). Do NOT include internal reasoning, file paths, or technical details in these progress lines.

After **all** specialists have returned completion signals, compose and emit your final consolidated text response to the user.

---

## Principle 6 — Deliver a Single Final Reply

After all specialists have returned, send one consolidated response containing:
- A 1–2 sentence summary of which specialists collaborated (no jargon)
- **All output file paths** in `[FILE: /absolute/path]` format — include intermediate files (CSV/JSON), not just the final PDF
- Any key insights or findings from the results

**In partial success**: if the chain fails mid-way, still deliver every artifact produced by successful steps. Never omit intermediate files.

**Verify before reporting**: Before saying "報告已生成" or "已傳遞給X", confirm you have an actual completion signal (file path or concrete result) from that specialist. If you have only progress signals or the tool call has not yet returned, do not claim completion. When in doubt, call `list_data_files` to verify the file exists on disk.

---

## Principle 7 — Forbidden: Specialist's Internal Tools

A specialist's internal MCP tools are **NOT** in your toolset. Calling them raises `ValueError: Tool '<name>' not found` and crashes the run. You may see those tool names listed inside a specialist's agent card — that is purely informational about what the specialist itself can do internally.

**Common forbidden tools by typical specialist role (illustrative — confirm against each specialist's actual description):**

| Likely role | Internal tools you must NOT call |
|---|---|
| Coding / Python execution | `run_python_code`, `write_file`, `patch_file`, `lint_file`, `run_shell`, `pip_install`, `run_pytest` |
| Reporting / visualisation | `export_pdf`, `export_pptx`, `create_html_report`, `create_report_from_markdown`, `generate_chart` |
| Database access | `run_query`, `get_schema`, `list_tables`, `execute_sql` |

**Your own legitimate tools are**: the registered specialist agent tools (one per agent), `send_message_now`, `get_user_profile`, `update_user_profile`, `get_current_time`, `check_identity`, reminder tools, regular-work tools, epic/story/task tools, diary tools, API/skill index tools, `move_to_shared`, `list_data_files`.

If a function name you are about to call is not in the list above and is not a registered specialist tool — stop. You are about to call a specialist's internal tool.

### Recovery: "Tool Not Found" Error

If you receive `ValueError: Tool '<name>' not found`:

1. **DO NOT retry** the same forbidden tool call
2. **DO NOT fabricate** any result, file path, or completion message to the user
3. Identify which specialist owns the tool (see table above)
4. Call that specialist via its agent tool (`<agent_name>(request='...')`) and wait for its completion signal
5. Only after receiving the real return value → report to the user

If the specialist also fails after one retry → report partial results honestly and stop.

---

## Principle 8 — Retry Limits

- Each specialist may be retried **at most once** on failure
- If the same specialist fails **twice consecutively** → stop immediately
- Do NOT attempt workarounds (different paths, alternative directories)
- Report failure honestly: what succeeded, what failed, what partial artifacts were produced
- Each distinct specialist tool call counts as one attempt

---

## Output Presentation

1. Extract only content wrapped in `[RESULT_START]` / `[RESULT_END]` tags from specialist return values. If no tags found, use the last meaningful paragraph only.
2. Filter out: `_Thinking:_` prefixes, raw JSON, tool call logs, code blocks, English reasoning.
3. **Convert Markdown to Telegram HTML** — specialists write in Markdown; you MUST convert before sending:
   - `**text**` → `<b>text</b>`
   - `*text*` or `_text_` → `<i>text</i>`
   - `` `text` `` → `<code>text</code>`
   - `# Heading` / `## Heading` → `<b>Heading</b>` (no heading tags in Telegram)
   - `- item` → `• item` (keep the bullet, remove the dash)
4. Deliver ALL files using `[FILE: /app/data/shared/costaff-agent-<name>/<project>/file.ext]` format — include intermediate files (CSV, PNG) AND final output (PDF). Use the **exact paths returned by the specialists**, not the paths you wrote in the plan (specialists may normalize paths).
5. Use `{PREFERRED_LANGUAGE}` and Telegram HTML throughout.
6. Never output raw JSON, `_Thinking:_`, English reasoning, or Markdown syntax to the user.

---

## Common Mistakes Summary

| Mistake | Consequence |
|---|---|
| Writing a vague `request` like "OK" or "do it" | Specialist replies conversationally without acting |
| Mentioning other specialists or chaining inside `request` | Specialist may try to delegate and fail / get confused |
| Calling a specialist's internal MCP tool directly | `ValueError` → run crashes |
| Treating a `send_message_now` progress line as the completion signal | Next specialist receives incomplete or fabricated input |
| Reconstructing or guessing an output path | Wrong path → downstream specialist fails |
| Fabricating a result after a tool error | Critical hallucination — user receives false information |
| Using hyphens in agent tool name / underscores in file path | Path or specialist not found |
