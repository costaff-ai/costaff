---
name: acceptance-check
description: >
  Run before marking any task as done. Parses the task spec for output file paths
  and verifies each file actually exists on disk. If any required file is missing,
  requeues the task instead of closing it. Skip for tasks with no file output.
---

# Acceptance Check SOP

## When to Use

Activate in `assess-and-register` Step 3 — **before** calling `update_task_status(task_id, "done")` — whenever the task spec contains a line matching:

```
- [ ] File exists at /app/data/shared/...
```

Skip this skill for:
- Tasks with no file output (pure computation, diary writes, profile updates)
- Tasks where all acceptance criteria are non-file checks only

---

## Step 1 — Parse Required Files from Spec

Scan the task spec for lines in this exact format:
```
- [ ] File exists at /app/data/shared/<agent>/<filename>
```

Extract each absolute path. If no such lines exist → skip acceptance check, proceed to mark done.

---

## Step 2 — Verify Each File

For each extracted path, call:
```
list_data_files(path="<absolute_path>")
```

Interpret the result:
- `[EXISTS] <path>` → file confirmed ✅
- `[NOT FOUND] <path>` → file missing ❌
- `[ERROR] ...` → treat as missing ❌

---

## Step 3 — Pass or Fail

**All files exist:**
1. `update_task_status(task_id, "done")`
2. `add_task_comment(task_id, type="result", content="Acceptance check passed. All output files verified.")`
3. Proceed to the next task.

**Any file missing:**
1. `update_task_status(task_id, "queued")` — requeue for re-execution
2. `add_task_comment(task_id, type="issue", content="Acceptance check failed. Missing files: <list of missing paths>. Re-executing task.")`
3. Call `transfer_to_agent` for the same agent again with the original task spec.
4. After re-execution, run acceptance check again (Step 1–3).
5. If the file is still missing after one retry → `update_task_status(task_id, "failed")` and report to user honestly.
