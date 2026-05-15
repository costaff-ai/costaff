---
name: delegate-business-analysis
description: >
  Use when delegating report generation, PDF creation, chart visualization, or
  data interpretation to the business analysis expert. Load this skill before
  calling `business_analysis(request='...')` so you know what to send, what it
  returns, and which tools are internal to that specialist (and must NEVER be
  called directly).
---

# Delegate to Business Analysis Expert

## Step 0 — Check Availability First (CRITICAL)

Before doing anything, verify that a `business_analysis` agent tool appears in your tool spec.

- **If `business_analysis` IS registered** → proceed with delegation as described below.
- **If `business_analysis` is NOT registered** → the business analysis expert is not currently deployed. You MUST:
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
business_analysis(request="<self-contained, imperative task description>")
```

The specialist sees **only the `request` string** — no session history, no plan, no prior turns. Write a complete imperative.

**What to include in `request`:**
- The exact task (e.g. "Generate a PDF report on SVM classification of the wine dataset")
- Input file path(s) — **exact absolute paths** returned by the previous specialist (use whatever path the specialist actually reported back, including any `outputs/` or other inner directory it chose), e.g.
  `/app/data/shared/costaff-agent-coding/wine-svm/wine_svm_results.json`
- Desired output path including a kebab-case `<report-name>/` subdirectory, e.g.
  `/app/data/shared/costaff-agent-business-analysis/svm-wine-report/svm_wine_report.pdf`
- Language requirement (e.g. "Report should be in Traditional Chinese")
- Any specific sections to include (e.g. "Include methodology, results table, and analysis")

**What to NEVER include in `request` (CRITICAL):**
- ❌ Mentions of other specialists or chaining: "then notify the user", "transfer results to X"
- ❌ Single-word acknowledgements like "OK" or "go" — the specialist cannot infer the task from those
- ❌ References to "the user's earlier message" or "the plan we discussed" — the specialist cannot see those

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

**If you just received a ValueError for any of the above**: do NOT fabricate a result. Immediately call `business_analysis(request='...')` instead and wait for the real response.

## What the Business Analysis Agent Returns

The completion signal contains:
- The absolute path to the generated file, e.g.
  `/app/data/shared/costaff-agent-business-analysis/svm-wine-report/svm_wine_report.pdf`
- A brief summary of what was produced

**Copy this path exactly** when reporting to the user — do not retype or reconstruct it.

## Output Paths (CRITICAL)

The business analysis agent writes inside a **kebab-case `<report-name>/` subdirectory** under its shared slot:
```
/app/data/shared/costaff-agent-business-analysis/<report-name>/<filename>
```

Never prescribe (or expect) a file directly under `/app/data/shared/costaff-agent-business-analysis/` with no subdirectory.
