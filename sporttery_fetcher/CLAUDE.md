# CLAUDE.md

## Project goal

Keep the repository stable, debuggable, and easy to validate.
Prefer minimal changes unless broader changes are explicitly requested.

## Main entry points

- CLI fetch: `python -m src.main --date YYYY-MM-DD`
- Streamlit app: `python -m streamlit run app/app.py`

## Autonomous workflow (required)

You must operate autonomously end-to-end. Do not ask the user to read logs, run commands, or check results manually.

1. **Read logs yourself** — check `logs/` and terminal output; use the `debugger` subagent proactively on any traceback or error
2. **Fix code yourself** — apply the minimal fix directly after identifying the root cause
3. **Validate yourself** — use the `test-runner` subagent after every code change; run `scripts\verify.bat` and `scripts\smoke.bat` at minimum
4. **Keep fixing until green** — if validation fails, do not stop; loop back to step 1
5. **Commit and push yourself** — only after validation passes, use the `git-shipper` subagent to stage, commit, and push

Never report completion if validation was skipped or failed.

## Default debugging workflow

When fixing a bug, always:

1. Read relevant files first
2. Explain the call chain briefly
3. Give up to 3 root-cause hypotheses
4. Reproduce the issue with the smallest possible command
5. Apply the minimal fix
6. Re-run validation
7. Report:
   - Root cause
   - Changed files
   - Commands run
   - Why the fix works
   - Remaining risks

## Validation policy

After code changes, prefer:

- `scripts\verify.bat`
- `scripts\smoke.bat`
- `scripts\run_app.bat` (when the task involves app startup)

Do not claim completion if validation was skipped or failed.

## Project subagents

| Agent | When to use |
|---|---|
| `debugger` | MUST use proactively on any error, traceback, or unexpected output |
| `test-runner` | MUST use after every code change to run validation scripts |
| `git-shipper` | Use ONLY after test-runner confirms all validations pass |

## Safety and scope

- Do not edit unrelated files
- Do not add dependencies unless necessary
- Do not expose secrets in logs or UI
- Do not rely on external APIs for default validation
- Treat Streamlit UI, fetch pipeline, and tests as separate layers

## Git rules

- Work only on the current feature branch
- Never force-push unless explicitly instructed
- Do not modify `main` directly
