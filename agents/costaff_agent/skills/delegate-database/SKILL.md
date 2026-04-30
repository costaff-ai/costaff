---
name: delegate-database
description: >
  Use when a task involves database operations — SQL queries, schema inspection,
  data retrieval, record insertion/update/deletion, or database health checks.
  Load this skill before delegating to the database expert (agent: database).
  IMPORTANT: This agent may not be deployed — check the roster first.
---

# Delegate to Database Expert

## Step 0 — Check Availability First (CRITICAL)

Before doing anything, verify that `database` appears in the **Team Roster** (Section 6.2 of the main instruction).

- **If `database` IS in the roster** → proceed with delegation as described below.
- **If `database` is NOT in the roster** → the database expert is not currently deployed. You MUST:
  1. Inform the user honestly: "資料庫專家目前尚未部署，無法執行此操作。"
  2. Do NOT attempt the task yourself via text or fabricated results.
  3. Do NOT call any database-related tool — you do not have them.
  4. Optionally suggest the user ask you to deploy it: "如需使用，請聯絡管理員部署 database agent。"

## When to Use
- User asks to query, filter, or aggregate data from a database
- User asks to inspect table schema or list tables
- User asks to insert, update, or delete records
- User asks for database health, connection status, or migration checks

## How to Delegate

```
transfer_to_agent(
    agent_name='database',
    message='<clear task description>'
)
```

**What to include in the message:**
- The exact operation (e.g. "Query all users created after 2026-01-01")
- Target database / table names if known
- Any filter conditions or parameters
- Desired output format (e.g. "Return as JSON")

## What the Database Agent Returns

The completion signal contains:
- Query results (JSON or structured text)
- A confirmation message for write operations (INSERT/UPDATE/DELETE)
- An explicit error if the operation failed (e.g. table not found, connection refused)

## CRITICAL — Tools You Must NEVER Call Directly

The following are internal to the database agent. Calling them will crash the run:

| Forbidden tool | Belongs to |
|---|---|
| `run_query` | database MCP |
| `get_schema` | database MCP |
| `list_tables` | database MCP |
| `insert_record` | database MCP |
| `execute_sql` | database MCP |

**If you receive `ValueError: Tool '<name>' not found`** after trying any of the above:
do NOT fabricate results. Call `transfer_to_agent(agent_name='database', message='...')` instead.

## Output Paths

Database results are typically returned inline (not as files). If file output is requested, the agent writes to:
```
/app/data/shared/costaff-agent-database/<filename>
```
