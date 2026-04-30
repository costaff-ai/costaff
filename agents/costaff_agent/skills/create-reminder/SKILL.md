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
2. Call `create_reminder_tool(user_id, run_at, message)`:
   - `run_at`: ISO 8601 string, e.g. `"2026-04-10T09:00:00"`
   - `message`: The exact message to send at that time
3. Confirm to the user: "已設定提醒，將於 [時間] 通知您。"

---

## Examples

| User says | run_at | message |
|---|---|---|
| "提醒我明天早上九點喝水" | next day 09:00 | "該喝水了！" |
| "下午三點提醒我開會" | today 15:00 | "會議時間到了！" |
| "一小時後提醒我回 email" | now + 1h | "記得回覆 email" |
