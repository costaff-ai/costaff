---
name: delegate-business-analysis
description: >
  Use when delegating report generation, PDF creation, chart visualization, or
  data interpretation to the business analysis expert. Load this skill before calling
  transfer_to_agent(agent_name='business_analysis') to know what to send, what it
  returns, and — critically — which tools are internal to that agent and must NEVER
  be called directly by you.
---

# Delegate to Business Analysis Expert

## Step 0 — Check Availability First (CRITICAL)

Before doing anything, verify that `business_analysis` appears in the **Team Roster** (Section 6.2 of the main instruction).

- **If `business_analysis` IS in the roster** → proceed with delegation as described below.
- **If `business_analysis` is NOT in the roster** → the business analysis expert is not currently deployed. You MUST:
  1. Inform the user honestly: "商業分析專家目前尚未部署，無法執行此操作。"
  2. Do NOT attempt the task yourself via text or fabricated results.
  3. Do NOT call any report/chart tools — you do not have them.
  4. Optionally suggest: "如需使用，請聯絡管理員部署 business_analysis agent。"

## When to Use
- User asks for a PDF or PPTX report
- User asks for charts, bar graphs, or data visualizations
- A coding agent has produced CSV/JSON data that now needs a professional report
- User asks for business insight, summary, or interpretation of data

## How to Delegate

```
transfer_to_agent(
    agent_name='business_analysis',
    message='<clear task description>'
)
```

**What to include in the message:**
- The exact task (e.g. "Generate a PDF report on SVM classification of the wine dataset")
- Input file path(s) — **exact absolute paths** returned by the previous agent, e.g.:
  `/app/data/shared/costaff-agent-coding/wine_svm_results.json`
- Desired output path, e.g.:
  `/app/data/shared/costaff-agent-business-analysis/svm_wine_report.pdf`
- Language requirement (e.g. "Report should be in Traditional Chinese")
- Any specific sections to include (e.g. "Include methodology, results table, and analysis")

**What to NEVER include in the message (CRITICAL):**
- ❌ Any mention of other agents or chaining: "then notify the user", "transfer results to X"
- ❌ Any orchestration instruction: "use transfer_to_agent"
- `transfer_to_agent` is an ADK mechanism available **only to you (the Manager)**. Including it in the message causes the sub-agent to attempt the call and fail.

## CRITICAL — Tools You Must NEVER Call Directly

The following are **internal tools of the business analysis agent**. They do NOT exist in your toolset. Calling them will crash the run with `ValueError: Tool '<name>' not found`:

| Forbidden tool | Belongs to |
|---|---|
| `export_pdf` | business_analysis MCP |
| `export_pptx` | business_analysis MCP |
| `create_html_report` | business_analysis MCP |
| `create_report_from_markdown` | business_analysis MCP |
| `generate_chart` | business_analysis MCP |
| `read_csv` | business_analysis MCP |
| `read_result` | business_analysis MCP |
| `analyze_data` | business_analysis MCP |

**If you just received a ValueError for any of the above**: do NOT fabricate a result. Immediately call `transfer_to_agent(agent_name='business_analysis', message='...')` instead and wait for the real response.

## What the Business Analysis Agent Returns

The completion signal contains:
- The absolute path to the generated file, e.g.:
  `/app/data/shared/costaff-agent-business-analysis/svm_wine_report.pdf`
- A brief summary of what was produced

**Copy this path exactly** when reporting to the user — do not retype or reconstruct it.

## Output Paths

The business analysis agent always writes to:
```
/app/data/shared/costaff-agent-business-analysis/<filename>
```
