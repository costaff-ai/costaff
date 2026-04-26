---
name: delegate-coding
description: >
  Use when delegating any task to the coding expert — including Python scripting,
  data analysis, SVM / ML algorithms, file I/O, package installation, git operations,
  or running tests. Load this skill before calling transfer_to_agent(agent_name='coding')
  to know exactly what to send and how to interpret the response.
---

# Delegate to Coding Expert

## Step 0 — Check Availability First (CRITICAL)

Before doing anything, verify that `coding` appears in the **Team Roster** (Section 6.2 of the main instruction).

- **If `coding` IS in the roster** → proceed with delegation as described below.
- **If `coding` is NOT in the roster** → the coding expert is not currently deployed. You MUST:
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
transfer_to_agent(
    agent_name='coding',
    message='<clear task description in English or Chinese>'
)
```

**What to include in the message:**
- The exact task (e.g. "Run SVM classification on the wine dataset using scikit-learn")
- Any input file paths (absolute, under `/app/data/shared/`)
- The desired output format and output path (e.g. "Save results to `/app/data/shared/costaff-agent-coding/wine_svm_results.json`")
- Any specific libraries to use

**What to NEVER include in the message (CRITICAL):**
- ❌ Any mention of other agents: "then pass results to business_analysis", "after this, transfer to BA agent"
- ❌ Any orchestration instruction: "use transfer_to_agent", "call the reporting expert"
- `transfer_to_agent` is an ADK mechanism available **only to you (the Manager)**. If you mention it in the message to coding, the coding agent's LLM will attempt to call it and fail with `Tool 'transfer_to_agent' not found`, breaking the task.
- The coding agent's only job is: **do the work, save the file, report back**. Chaining to the next agent is your responsibility after it finishes.

## What the Coding Agent Returns

The coding agent's **completion signal** contains at least one of:
- An absolute output file path: `/app/data/shared/costaff-agent-coding/<filename>`
- Computed values or a structured summary
- An explicit failure message with reason

**Progress signals** (mid-task `send_message_now` messages like "安裝套件中…", "正在執行腳本…") are NOT completion — do not proceed to the next step until the A2A call actually resolves.

## Output Paths

The coding agent always writes to its shared slot:
```
/app/data/shared/costaff-agent-coding/<filename>
```

Use the **exact path returned by the agent** — never reconstruct or guess it.

## Common Mistakes to Avoid

- ❌ Calling `run_python_code`, `write_file`, `pip_install`, `run_shell` yourself — these are the coding agent's **internal** MCP tools and are not in your toolset
- ❌ Proceeding to the next step after only seeing a progress message
- ❌ Inventing the output file path — always use what the agent returned
