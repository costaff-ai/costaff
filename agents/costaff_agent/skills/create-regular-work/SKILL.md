---
name: create-regular-work
description: >
  Activate when the user wants the agent team to perform a recurring task automatically
  on a schedule — e.g. daily news summary, weekly report, nightly diary. Not for
  one-time reminders — use create-reminder for that.
---

# Create Regular Work SOP

## When to Use
- User wants an automated job that repeats on a schedule
- Examples: "每天早上九點幫我總結科技新聞", "每週一寄本週計畫"

**Do NOT use for one-time notifications** → activate `create-reminder` instead.

---

## Steps

1. Call `get_current_time()` to confirm current time and timezone.
2. Call `create_regular_work(user_id, spec, cron, agent_id, channel, recipient)`:
   - `spec`: Full, self-contained instructions the agent needs to execute autonomously (no user context available at run time)
   - `cron`: 5-part cron expression (minute hour day month weekday)
   - `agent_id`: Which agent executes — default `costaff_agent`; use a specialist if the task is domain-specific
   - `channel` + `recipient`: Where to deliver results
3. Confirm to the user: "已加入團隊定期排程，將於每 [schedule] 自動執行。"

**Do NOT execute the work immediately** — only confirm the schedule is set.

---

## Cron Reference

| Schedule | Cron expression |
|---|---|
| Every day at 09:00 | `0 9 * * *` |
| Every Monday at 08:00 | `0 8 * * 1` |
| Every weekday at 18:00 | `0 18 * * 1-5` |
| Every hour | `0 * * * *` |

---

## Writing a Good `spec`

The spec must be fully self-contained — no user will be present when it runs:
- State the exact task and output format
- Include any data sources, API names, or file paths
- Specify where to send the result (`channel`, `recipient`)
- Write in the language the agent should use for its output
