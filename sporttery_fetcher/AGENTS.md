# AGENTS.md

## Project overview
This is a Python project for China Sporttery football workflows.

Main entry paths:
1. CLI fetch pipeline: `python -m src.main --date YYYY-MM-DD`
2. Streamlit dashboard: `streamlit run app/app.py`

## Repo layout
- `app/`: Streamlit UI and app services
- `src/`: fetchers, parsers, backend logic
- `tests/`: tests
- `config/`: config files
- `scripts/`: validation scripts

## Working rules
- Read relevant files before editing
- Explain root-cause hypotheses before changing code
- Prefer the smallest safe fix
- Do not refactor unrelated modules
- Do not hardcode secrets or local absolute paths
- Avoid network-dependent validation unless required

## Validation
Before claiming success, run:
1. `scripts\verify.bat`
2. targeted pytest if needed
3. `scripts\smoke.bat`

## For bug fixes
Always follow:
1. Reproduce
2. Inspect traceback / logs
3. Identify root cause
4. Apply minimal fix
5. Re-run relevant tests
6. Summarize risks

## Done when
A task is only done if:
- root cause is explained
- files changed are listed
- validation commands are listed
- relevant tests passed
- remaining risks are stated