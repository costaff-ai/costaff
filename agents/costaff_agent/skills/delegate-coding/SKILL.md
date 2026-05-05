---
name: delegate-coding
description: >
  Use when delegating any task to the coding expert — Python scripting,
  data analysis, SVM / ML algorithms, file I/O, package installation,
  git operations, or running tests. Load this skill before calling
  `coding(request='...')` so you know what to send and how to read the
  response.
---

# Delegate to Coding Expert

## Step 0 — Check Availability First (CRITICAL)

Before doing anything, verify that a `coding` agent tool appears in your tool spec.

- **If `coding` IS registered** → proceed with delegation as described below.
- **If `coding` is NOT registered** → the coding expert is not currently deployed. You MUST:
  1. Inform the user honestly: "程式開發專家目前尚未部署，無法執行此操作。"
  2. Do NOT attempt the task yourself via text or fabricated results.
  3. Do NOT call any coding-related tool — you do not have them.
  4. Optionally suggest: "如需使用，請聯絡管理員部署 coding agent。"

## When to Use
- User asks to write, run, or debug Python code
- User asks for data analysis, statistical computation, or ML (SVM, regression, clustering…)
- User asks to install packages, read/write files, or run shell commands
- A prior step produced data (CSV/JSON) that now needs further computation

## How to Delegate

```
coding(request="<self-contained, imperative task description>")
```

The specialist sees **only the `request` string** — no session history, no plan, no prior turns. Write a complete imperative.

**What to include in `request`:**
- The exact task (e.g. "Run SVM classification on the wine dataset using scikit-learn")
- Any input file paths (absolute, under `/app/data/shared/`)
- The desired output format and output path (e.g. "Save results to `/app/data/shared/costaff-agent-coding/wine-svm/outputs/wine_svm_results.json`"). **Always include a kebab-case `<project>/` subdirectory** — never prescribe a path directly under `costaff-agent-coding/`.
- Any specific libraries to use
- A `[PROGRESS_CONTEXT]` block with `user_id`, `channel`, `session_id` if user-facing progress messages are wanted

**What to NEVER include in `request` (CRITICAL):**
- ❌ Mentions of other specialists or chaining: "then pass results to business_analysis", "after this, transfer to BA agent"
- ❌ Single-word acknowledgements like "OK" or "go" — the specialist cannot infer the task from those
- ❌ References to "the user's earlier message" or "the plan we discussed" — the specialist cannot see those
- The coding agent's only job is: **do the work, save the file, report back**. Chaining to the next specialist is your responsibility after `coding(...)` returns.

## What the Coding Agent Returns

The return value contains at least one of:
- An absolute output file path: `/app/data/shared/costaff-agent-coding/<project>/[outputs|src]/<filename>`
- Computed values or a structured summary
- An explicit failure message with reason

**Progress signals** (mid-task `send_message_now` messages like "安裝套件中…", "正在執行腳本…") are NOT completion — do not proceed to the next step until the `coding(...)` call actually resolves.

## Output Paths (CRITICAL)

The coding agent writes inside a **kebab-case project subdirectory** under its shared slot:
```
/app/data/shared/costaff-agent-coding/<project>/outputs/<filename>   ← data, charts, results, reports
/app/data/shared/costaff-agent-coding/<project>/src/<filename>       ← source code
```

Never prescribe (or expect) a file directly under `/app/data/shared/costaff-agent-coding/` with no subdirectory — the coding agent will refuse to obey such a path and normalize it to a project subdirectory, returning the corrected path. Use the **exact path returned by the agent** when reporting to the user or chaining to the next specialist.

## Common Mistakes to Avoid

- ❌ Calling `run_python_code`, `write_file`, `pip_install`, `run_shell` yourself — these are the coding agent's **internal** MCP tools and are not in your toolset
- ❌ Proceeding to the next step after only seeing a progress message
- ❌ Inventing the output file path — always use what the agent returned
- ❌ Writing an empty or single-word `request` — the coding agent will reply conversationally and do no work
