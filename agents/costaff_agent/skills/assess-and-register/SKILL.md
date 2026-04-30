---
name: assess-and-register
description: >
  Activate before executing any substantive work that produces artifacts or requires
  multi-step execution (coding, data analysis, report generation, multi-agent chains).
  Guides you to check past epics for context, register a new Epic/Story/Task when none
  exists, mark tasks as doing before execution, and close them after completion.
---

# Assess & Register SOP

## When to Use
Activate for any request that produces a physical artifact (code, data file, PDF, chart) or requires delegating to a sub-agent.

**Skip this skill** for:
- Pure conversation, greetings, or time queries
- Creating a reminder or regular work (they have their own tracking)
- User explicitly says "直接做" or "不用記錄"
- Simple one-shot lookup with no artifact output (e.g. `get_epics`, `get_user_profile`)

---

## Step 1 — Assess Past Records

Call `get_epics(user_id=EXTRACTED_ID, status="all")` to check all projects (active, completed, archived).

- **Relevant epic found** → call `get_epic_detail(epic_id)` to read what was already done. Use this context when planning the current request (continue, extend, or correct prior work).
- **No relevant epic** → proceed to Step 2.

---

## Step 2 — Register the Work

**Timing**: For single-step requests, register immediately before executing.
For multi-step requests requiring user plan confirmation (see `multi-agent-chain` skill), register **after** the user confirms the plan and **before** calling `transfer_to_agent`.

Create the project structure in order:

1. `create_epic(user_id, title, description)` — one epic per topic/project
2. `create_story(epic_id, user_id, title, priority)` — one story per major phase (e.g., "Backend API", "Data Analysis", "Report Generation")
3. `create_project_task(...)` — one task per concrete unit of work; all tasks are created with `status=backlog`
4. `update_task_status(task_id_1, "doing")` — **mark only the first task as `doing`**; all other tasks remain `backlog` until their turn

Then confirm to the user in one short line:
> "已建立專案記錄，開始執行…"

---

## Step 3 — Per-Task Completion (CRITICAL: close each task immediately, do not batch)

After **each** sub-agent returns a completion signal, run the `acceptance-check` skill **before** marking done:

1. Activate `acceptance-check` skill — verify all required output files exist
   - Files confirmed → proceed to step 2
   - File missing → skill requeues and retries; only proceed to step 2 after retry passes or task is marked `failed`
2. `add_task_comment(task_id, type="result", content="...")` — record the output file path or result summary
3. `update_task_status(next_task_id, "doing")` — if a next task exists, mark it as doing **now**, then immediately call `transfer_to_agent` for it

After **all** tasks are done:
4. `update_story(story_id, status="done")` — close the story
