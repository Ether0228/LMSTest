# Student Learning Operations Workflows (V1 fixture harness)

This package implements the dependency order defined by the school operations
specification without writing to Feishu, Schoology, or any production service.
Every run is a dry-run and emits auditable local/GitHub Actions artifacts.
Selectors execute only their required dependency DAG; `all` executes the full
chain. A blocked fact module never produces its module AI draft, and publishing
also blocks when a critical fact module is blocked.

| Workflow | Rule boundary | Output |
| --- | --- | --- |
| `session_content` | `SESSION-01—06` | Six-section AI candidate plus deterministic schema result |
| `course_weekly` | `COURSEW-01—04` | Candidate based only on confirmed actual session facts |
| `participation` | `PART-01—03` | Objectively sourced, uniquely matched candidates only |
| `tasks` | `TASK-03—06` | Effective deadline and backlog facts; no completion inference |
| `grades` | `GRD-03—05` | Stable append-only grade events and observations |
| `ielts` | `IELTS-01—04` | Candidate/approved-task separation |
| `pbl` | `PBL-03—04` | Evidence manifest and review candidates only |
| `weekly_payload` | `WEEK-01—04/10` | Deterministic fact payload with module state |
| `weekly_drafts` | `WEEK-05—08` | Review-only module and overall drafts |
| `publish` | `WEEK-11—13` | Local immutable HTML/PDF preview only after confirmation |

Run all fixtures locally:

```bash
python -m unittest discover -s tests -v
python pipeline/run_student_ops.py --workflow all --fixture tests/fixtures/student_ops/week_v1.json --output-dir artifacts/student_ops --dry-run
```

`--ai-mode fixture` is the default and uses the anonymized fixture responses.
`--ai-mode live` uses an OpenAI-compatible HTTP endpoint with `AI_API_KEY`,
`AI_BASE_URL`, and `AI_MODEL`; missing configuration exits explicitly without
printing a value. The session adapter sends the complete confirmed
`session_course_minutes_v1` prompt. Weekly module calls only receive a fact
payload and failure leaves that module's draft absent/partial.

PDF is rendered by installed Chromium/Chrome from the same HTML preview, so
Chinese is rendered by the browser font stack. A missing or failing browser is
recorded as `pdf_status: failed`; the system never creates an ASCII fallback
PDF. GitHub Actions installs Chrome before fixture runs.

The course minutes candidate and its human confirmation are separate fixture
inputs. `publication.approved_at` and `publication.version` are mandatory for
a stable, idempotent publication snapshot; no runtime timestamp becomes a
published fact.
