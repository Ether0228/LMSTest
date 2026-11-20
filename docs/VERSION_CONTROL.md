# Development and release workflow

This repository is the code review and release source for LMSTest. The production server is not the development workspace. Existing server patches and local uncommitted changes have not yet been fully reconciled with `main`; do not deploy the repository wholesale until that baseline audit is complete.

## Change lifecycle

1. Start a `codex/<change>` branch from current `main` in a clean checkout. Preserve unrelated local work.
2. Develop locally. Use synthetic fixtures or reviewed, de-identified samples; default all write-capable commands to preview.
3. Run relevant tests and review the exact files and diff. Open a pull request with behavior, validation and deployment limitations.
4. Merge reviewed changes. Identify releases by Git commit and, when appropriate, a release tag. A GitHub commit is not evidence of production deployment.
5. Before deployment compare the server source hashes with the reviewed baseline. Stop on unknown drift. Back up changed files and prepare rollback before replacing only the reviewed files.
6. Verify one production cycle, permitted field changes and repeat-run idempotency. Record the deployed commit, source hashes, time, outcome and rollback location. Keep secrets out of that record.

## Repository boundaries

Commit code, synthetic tests, dependency declarations, safe configuration examples, business rules and operational documentation. Never commit real `.env` files, tokens, cookies, keys, raw student records, named student reports, source exports, private backups or service logs. Ignore rules do not remove already tracked data or historical commits; any history audit and cleanup is a separate reviewed task.

This is currently a public repository. Review every staged file before pushing; do not stage an entire project or output directory. Configuration examples must contain placeholders only.

## TASK-019 candidate

`pipeline/sync_course_task_types.py` contains the positive-evidence classifier and a guarded writer. `tests/test_task_types.py` uses only synthetic data and makes no network requests. Run:

```sh
python3 -m unittest discover -s tests -p test_task_types.py
```

Only same-semester Section ID + assignment ID matches can fill an empty type with `算分作业`. Missing Gradebook evidence is not evidence for `日常作业`. Preserve manual conflicts and `单独布置`; do not calculate weight or alter student completion. The caller must supply evidence from a successful current Gradebook read, excluding summary and excluded-from-grade items.

This first version-control change does not wire the helper into a production entry point, deploy it, backfill records, or establish that all historical server functionality is present in `main`.
