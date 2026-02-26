# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A gamified student learning dashboard ("通关指南" / Quest Completion Guide) backed by Feishu Bitable (飞书多维表格) as the database. Students view course progress, missing assignments, recent submissions, and personalized recommendations. A Python pipeline pre-computes summaries into a Feishu summary table for performance.

## Running the Server

**Development (mock auth — no Feishu credentials needed):**
```bash
AUTH_MODE=mock node interactive_web/server.js
```

**Production:**
```bash
node interactive_web/server.js
```
Copy `interactive_web/.env.example` to `interactive_web/.env` and fill in credentials before running in production.

Multi-tenant: pass `?t=tenant_a` or `?t=tenant_b` as URL query param to select tenant.

## Running the Python Data Pipeline

```bash
cd schoology数据转飞书
pip install requests
python build_student_summary.py   # Pre-compute summaries into Feishu summary table
python check_missing_sync.py      # Validate missing assignment table consistency
```

Required env vars for the pipeline: `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `FEISHU_APP_TOKEN`, `FEISHU_TABLE_ID`, `FEISHU_ROSTER_TABLE_ID`, `FEISHU_LIB_TABLE_ID`, `FEISHU_MISSING_TABLE_ID`, `FEISHU_SUMMARY_TABLE_ID`.

## CI/CD

`.github/workflows/summary-test.yml` — manually triggered (`workflow_dispatch`). Runs `build_student_summary.py` against live Feishu using GitHub Secrets. No unit tests exist.

## Architecture

### Data Flow
```
Feishu Bitable tables
  ├── Roster table        (student list)
  ├── Submissions table   (assignment submissions)
  ├── Missing table       (missing assignments)
  ├── Library table       (assignment metadata)
  └── Summary table       (pre-computed per-student aggregates — optional fast-path)
        ↓
  Python pipeline (build_student_summary.py) writes to Summary table
        ↓
  Node.js server (server.js) reads tables via Feishu API, aggregates on-the-fly
  OR reads from Summary table if configured (fast-path)
        ↓
  Vanilla JS frontend (app.js) renders dashboard
```

### Node Backend (`interactive_web/server.js`)
- **Zero npm dependencies** — uses only Node built-ins (`http`, `fs`, `path`, `crypto`).
- Has its own minimal `.env` file parser.
- Manages Feishu tenant access tokens with in-memory caching.
- `bitableFetchAll()` — paginated full-table fetch.
- `bitableFetchByFilterCached()` — filtered fetch with 60s TTL cache (avoids full-table scans).
- `summarizeForStudent()` (line ~259) — core aggregation: merges submissions, missing, roster data per student.
- Recommendation logic: missing assignments → rubric/recovery strategy suggestions tied to student signals.
- Supports Feishu OAuth 免登 (free login) in production; `AUTH_MODE=mock` bypasses auth for dev.

### Python Pipeline (`schoology数据转飞书/build_student_summary.py`)
- Fetches all tables once, aggregates per-student data client-side, then upserts into Feishu summary table.
- Produces JSON blobs: `course_list`, `missing_detail`, `recent_submissions`, `recommendations`.
- Running this script is the performance optimization: the Node server can read a single pre-computed row instead of joining multiple tables at request time.

### Frontend (`interactive_web/public/`)
- `app.js` renders course progress bars, missing items grouped by course, recent submissions, and recommendations.
- `guide.html` / `guide.js` renders the embedded markdown guide content.
- No frontend framework or build step — plain HTML/CSS/JS.

## Key Configuration

`TENANTS_JSON` env var in `.env` configures multi-tenant Feishu credentials. See `interactive_web/README.md` for the full schema and field mapping between Feishu table columns and the expected data model.
