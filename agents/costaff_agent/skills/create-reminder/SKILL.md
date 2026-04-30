---
name: create-reminder
description: >
  Activate when the user wants a one-time message sent to them at a specific future
  time (e.g. "提醒我明天早上九點喝水"). Not for recurring work — use create-regular-work for that.
---

# Create Reminder SOP

## When to Use
- User specifies a **single, one-time** notification at a future time
- No agent work involved — just a message sent at a specific moment

**Do NOT use for recurring work** (e.g. "每天提醒我") → activate `create-regular-work` instead.

---

## Steps

1. Call `get_current_time()` to calculate the correct absolute datetime.
2. Call `create_reminder_tool` with **all** of these parameters:
   - `user_id`: the **hashed_id** from the current session (a 16-character hex string, e.g. `c9e4719ba839d6b6`). This is the same identifier you receive in every tool call. **Never** put the user's display name (e.g. `"Simon"`) here.
   - `session_id`: the current `session_id` (e.g. `tg_12345`).
   - `channel`: `"telegram"` / `"discord"` / `"line"` — derive from the session_id prefix (`tg_*` → telegram, `dc_*` → discord, `line_*` → line).
   - `recipient`: **same as `user_id`** (the hashed_id). The notifier will resolve it to the real chat_id via the IdentityMap. **Do NOT** put the user's name here.
   - `message`: The exact text to send at that time.
   - `run_at`: ISO 8601 datetime string, e.g. `"2026-04-10T09:00:00"`.
3. Confirm to the user: "已設定提醒，將於 [時間] 通知您。"

> **Important**: `recipient` is an internal routing key, not a human-readable name. Always pass the same hashed_id you got from `check_identity` / session context.

---

## Examples

| User says | run_at | message |
|---|---|---|
| "提醒我明天早上九點喝水" | next day 09:00 | "該喝水了！" |
| "下午三點提醒我開會" | today 15:00 | "會議時間到了！" |
| "一小時後提醒我回 email" | now + 1h | "記得回覆 email" |
