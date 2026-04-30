---
name: team-diary
description: >
  Activate when the user asks about team diary entries, standup summaries, recent
  agent activity, or when it is time to write the end-of-day diary for costaff_agent.
---

# Team Diary SOP

## Reading the Diary

At session start, `get_recent_diaries(user_id, days=3)` is already called (Section 2 initialization). Use that data to:
- Know what each agent did recently
- Spot blockers that need attention
- Understand project momentum

For a fresh or longer read: `get_recent_diaries(user_id, days=<N>)`

---

## Writing the Diary (end-of-day)

Each agent writes its own diary via its nightly `RegularWork`.
You (costaff_agent) write your own diary when asked or at end-of-session:

```
write_diary(
    user_id=EXTRACTED_ID,
    agent_name="costaff_agent",
    date="YYYY-MM-DD",
    done="What you coordinated or answered today",
    next="What is planned for tomorrow",
    blocker="Any unresolved issues (or empty string if none)",
    ref_task_ids=[task_id_1, task_id_2]   # tasks worked on today
)
```

---

## Morning Standup Report Format

When generating a standup summary for the user, use this format (Telegram HTML):

```
📋 <b>昨日團隊工作摘要 YYYY-MM-DD</b>

🤖 <b><agent_name></b>
✅ <done>
⚠️ blocker: <blocker>   (omit line if no blocker)
→ 明天: <next>
```

One block per agent that has a diary entry for that date.
