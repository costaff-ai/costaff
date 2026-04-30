---
name: multi-agent-chain
description: >
  Activate for ANY request involving sub-agent delegation — single or multi-step.
  Contains the complete orchestration SOP: plan-and-confirm format, sequential
  execution rules, progress vs completion signal distinction, forbidden tool patterns,
  recovery from errors, retry limits, file delivery rules, and output presentation.
---

# Multi-Agent Orchestration SOP

## When to Use
- A task requires delegating to one or more sub-agents via `transfer_to_agent`
- Two or more agents need to work in sequence (output of one → input of next)
- User asks to combine multiple specialist capabilities in a single workflow

---

## Principle 1 — Present a Plan First (multi-step only)

When a request requires **two or more** sub-agent calls (any file or data hand-off between agents), present a written plan and wait for user confirmation **before calling any agent tool**.

**Skip the plan (proceed immediately) when**:
- A single sub-agent fulfils the whole request
- User already confirmed a plan earlier in this session
- User says "直接做", "不用計劃", "go ahead", or similar

**Plan format (Telegram HTML — use exactly):**
```
📋 <b>執行計劃</b>

<b>Step 1: [專家職稱] (agent: <code>&lt;a2a_name&gt;</code>)</b>
• 任務：...
• 輸入：...
• 預期產出：<code>/app/data/shared/costaff-agent-&lt;hyphen-name&gt;/xxx.ext</code>

<b>Step 2: [專家職稱] (agent: <code>&lt;a2a_name&gt;</code>)</b>
• 任務：...
• 輸入：Step 1 的產出
• 預期產出：<code>...</code>

請回覆「OK」開始執行，或告訴我需要調整的地方（工具、順序、輸出格式等）。
```

After presenting the plan: **STOP**. Do not call any tool. Wait for the user's next message.
- Confirmation ("OK", "好", "同意", "開始", "go") → proceed to execute
- Change request → update plan, present again for re-confirmation
- Clarifying question → answer it, then re-confirm the (possibly revised) plan

---

## Principle 2 — Execute One Agent at a Time, In Order

Call only one agent per step via `transfer_to_agent`. **Wait for the A2A call to fully resolve** before proceeding to the next.

Each agent emits two types of events — you MUST distinguish them:

| Event type | Characteristics | Action |
|---|---|---|
| **Progress signal** (mid-task) | Status messages sent via `send_message_now` — "安裝中…", "正在執行…", "🔍 開始調查" | Keep waiting — the agent is still running |
| **Completion signal** (final A2A response) | Contains a file path, computed result, structured summary, or explicit failure message | Proceed to next step |

A valid completion signal always includes at least one of:
- An absolute output file path (e.g. `/app/data/shared/costaff-agent-coding/result.csv`)
- A concrete computed result or value
- A structured analysis, summary, or conclusion
- An explicit failure declaration explaining why the task cannot be completed

If you only have progress signals, the task is **still in progress**. While in this state, you are **strictly forbidden** from fabricating results, calling the next agent, or telling the user the task is done.

---

## Principle 3 — Pass Exact Results, Never Reconstruct

Extract the **exact** output from the completion signal (file path, value, identifier) and pass it verbatim to the next agent. Never retype, reconstruct, or guess.

**Path naming (CRITICAL — common bug source)**:
- Filesystem paths use **hyphens**: `costaff-agent-business-analysis`
- `transfer_to_agent(agent_name=...)` uses **underscores**: `business_analysis`
- Never derive one from the other

---

## Principle 4 — No Plain Text or Internal Reasoning Between Agent Calls

Emitting a plain-text response in a multi-step chain **immediately terminates the current ADK run**. Subsequent `transfer_to_agent` calls will never execute.

**The only two allowed actions between agent calls:**
1. `send_message_now(body="...")` — a brief progress update in {PREFERRED_LANGUAGE} only
2. `transfer_to_agent(...)` — the next agent call

**Absolutely forbidden between agent calls:**
- ❌ Any English reasoning or narration: "The coding_agent has finished...", "Now I need to...", "I will use transfer_to_agent..."
- ❌ Any text response explaining what you are about to do
- ❌ Markdown formatted summaries or results mid-chain

If you catch yourself writing explanatory text between two agent calls — **STOP**. Delete it. Call `send_message_now` with a brief Chinese status line, or call the next `transfer_to_agent` directly.

**`send_message_now` content rules:**
- Write in **{PREFERRED_LANGUAGE}** only (not English)
- Maximum one sentence, e.g. "▶️ 商業分析專家正在生成報告，請稍候。"
- Never include internal reasoning, file paths, or technical details

**Only after ALL agents complete**: compose and emit your final text response to the user.

---

## Principle 5 — Deliver a Single Final Reply

After all agents have returned completion signals, send one consolidated response containing:
- A 1–2 sentence summary of which specialists collaborated (no jargon)
- **All output file paths** in `[FILE: /absolute/path]` format — including intermediate files (CSV/JSON), not just the final PDF
- Any key insights or findings from the results

**In partial success**: if the chain fails mid-way, still deliver every artifact produced by successful steps. Never omit intermediate files.

---

## Principle 6 — Check Roster Before Each Agent Call

Before each `transfer_to_agent` call, verify the target agent appears in the **Team Roster** (Section 6.2 of the main instruction).
- If the agent is in the roster → proceed
- If the agent is NOT in the roster → inform the user it is not deployed and stop the chain at that step

---

## Principle 7 — Forbidden: Sub-Agent Internal Tools

Sub-agent MCP tools are **NOT** available in your toolset. Calling them raises `ValueError: Tool '<name>' not found` and crashes the run. You may see these tools listed in a sub-agent's agent card — that is purely informational.

**Common forbidden tools by agent:**

| Tool | Belongs to |
|---|---|
| `export_pdf`, `export_pptx`, `create_html_report`, `create_report_from_markdown`, `generate_chart`, `read_csv`, `analyze_data` | business_analysis |
| `run_python_code`, `write_file`, `patch_file`, `lint_file`, `run_shell`, `pip_install`, `run_pytest` | coding |
| `run_query`, `get_schema`, `list_tables`, `execute_sql` | database |

**Your legitimate tools**: `transfer_to_agent`, `send_message_now`, `get_user_profile`, `update_user_profile`, `get_current_time`, `check_identity`, reminder tools, regular-work tools, epic/story/task tools, diary tools, API/skill index tools, `move_to_shared`.

If a function name you are about to call is not in this list and is not obviously one of the above — stop. You are about to call a sub-agent's internal tool.

### Recovery: "Tool Not Found" Error

If you receive `ValueError: Tool '<name>' not found`:

1. **DO NOT retry** the same forbidden tool call
2. **DO NOT fabricate** any result, file path, or completion message to the user
3. Identify which agent owns the tool (see table above)
4. Call `transfer_to_agent(agent_name='<correct_agent>', message='...')` and wait for its genuine completion signal
5. Only after receiving the real response → report to user

If the sub-agent also fails after one retry → report partial results honestly and stop.

---

## Principle 8 — Retry Limits

- Each sub-agent may be retried **at most once** on failure
- If the same sub-agent fails **twice consecutively** → stop immediately
- Do NOT attempt workarounds (different paths, alternative directories)
- Report failure honestly: what succeeded, what failed, what partial artifacts were produced
- Each distinct `transfer_to_agent` call to the same agent counts as one attempt

---

## Output Presentation

1. Extract only content wrapped in `[RESULT_START]` / `[RESULT_END]` tags from sub-agent responses. If no tags found, use the last meaningful paragraph only.
2. Filter out: `_Thinking:_` prefixes, raw JSON, tool call logs, code blocks, English reasoning
3. **Convert Markdown to Telegram HTML** — sub-agents write in Markdown; you MUST convert before sending:
   - `**text**` → `<b>text</b>`
   - `*text*` or `_text_` → `<i>text</i>`
   - `` `text` `` → `<code>text</code>`
   - `# Heading` / `## Heading` → `<b>Heading</b>` (no heading tags in Telegram)
   - `- item` → `• item` (keep the bullet, remove the dash)
4. Deliver ALL files using `[FILE: /app/data/shared/costaff-agent-<name>/file.ext]` format — include intermediate files (CSV, PNG) AND final output (PDF)
5. Use `{PREFERRED_LANGUAGE}` and Telegram HTML throughout
6. Never output raw JSON, `_Thinking:_`, English reasoning, or Markdown syntax to the user

**Verify before reporting**: Before saying "報告已生成" or "已傳遞給X", confirm you have an actual completion signal (file path or concrete result) from that agent. If you only have progress signals or the A2A call has not yet resolved, do not claim completion.

---

## Common Mistakes Summary

| Mistake | Consequence |
|---|---|
| Calling a sub-agent's internal MCP tool directly | `ValueError` → run crashes |
| Emitting plain text between two `transfer_to_agent` calls | ADK run terminates — next agent never executes |
| Treating a progress signal as a completion signal | Next agent receives incomplete input |
| Reconstructing or guessing an output path | Wrong path → downstream agent fails |
| Fabricating a result after a tool error | Critical hallucination — user receives false information |
| Skipping roster check | Agent not deployed, call fails with no meaningful error |
| Using hyphens in `agent_name` / underscores in file path | Path or agent not found |
