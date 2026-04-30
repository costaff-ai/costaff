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
2. Call `create_regular_work` with these parameters:
   - `user_id`: the **hashed_id** from the current session (a 16-character hex string, e.g. `c9e4719ba839d6b6`). **Never** the user's display name.
   - `session_id`: the current `session_id`.
   - `title`: short human-readable name for the work (e.g. `"每日科技新聞摘要"`).
   - `spec`: Full, self-contained instructions the agent needs to execute autonomously (no user context available at run time).
   - `cron`: 5-part cron expression (minute hour day month weekday).
   - `agent_id` *(optional)*: Which agent executes — default `costaff_agent`; pass a specialist name if the task is domain-specific.
   - `channel` *(optional)*: `"telegram"` / `"discord"` / `"line"`. If omitted, the system auto-resolves from the user's IdentityMap.
   - `recipient` *(optional)*: **same as `user_id`** (the hashed_id) when explicitly delivering to the requesting user. If omitted, auto-resolved.
3. Confirm to the user: "已加入團隊定期排程，將於每 [schedule] 自動執行。"

**Do NOT execute the work immediately** — only confirm the schedule is set.

> **Important**: `recipient` is an internal routing key (a hashed_id), not a human-readable name. Either omit it (let the system auto-resolve) or pass the same hashed_id you got from `check_identity` / session context.

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
