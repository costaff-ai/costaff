---
name: project-management
description: >
  Activate when the user asks to create a new project, view project status, manage
  epics/stories/tasks, set execution priority, or query an agent's workload. Also
  activate when scheduling work as a project task with a cron (future execution).
---

# Project Management SOP

## Creating a New Project

When user asks to start a long-term project or explicitly requests project tracking:

1. `create_epic(user_id, title, description)` — one epic per project
2. `create_story(epic_id, user_id, title, priority)` — one story per major phase
3. `create_project_task(epic_id, user_id, title, spec, story_id, assigned_agent, priority)` — one task per unit of work
4. `update_task_queue(user_id, assigned_agent, [task_id_1, task_id_2, ...])` — set execution order

After setting the queue, tasks with `status=queued` are automatically picked up by agents.

> **Note**: `update_task_queue` is for **scheduled / queued** work only. For **immediate** execution, always call the matching specialist agent tool directly (e.g. `coding(request='...')`). See Section 4.1 of the main instruction.

---

## Queue Priority Rules

1. **Blocking** — tasks that other tasks depend on go first
2. **Urgency** — tasks the user marked as urgent
3. **Source** — user-requested > regular work > system-generated
4. **Independence** — tasks with no dependencies can run in parallel if assigned to different agents

---

## Checking Project Status

- Full project picture (stories + tasks + comments): `get_epic_detail(epic_id)`
- Agent workload: `get_agent_queue(user_id, assigned_agent)`
- All projects: `get_epics(user_id, status="all")`

---

## Task Lifecycle

- Agents pick up queued tasks automatically and set `status=done` when complete, leaving a `TaskComment` with `type=result`.
- For tasks you executed immediately (via `assess-and-register`): you manually call `update_task_status(task_id, "done")` and `add_task_comment`.
- When all tasks in a story are done → `update_story(story_id, status="done")`.
- Inform the user of completion.

---

## Scheduling a Task for Future Execution

If user wants a one-time task executed at a future date (not recurring):
- `create_project_task(... cron="<expression>", ...)` with `cron` set to fire once
- Then `update_task_queue` to place it in the agent's queue

For recurring automated jobs → activate `create-regular-work` skill instead.
