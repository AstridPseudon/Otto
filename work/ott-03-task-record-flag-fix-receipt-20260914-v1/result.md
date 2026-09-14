# OTT-03 selected WorkTemplate task-created correction supplement

Date: 2026-09-14. This is a focused supplement to the prior historical evidence. It makes no remote-write, review, gate, acceptance, or programme-completion claim.

## Lineage and artifacts

- Requested route/reasoning: `gpt-5.6-luna` / `high`.
- Starting HEAD/tree: `ccec6edc059721bfcb9ea8e1e0a31215a777cb2` / `b28c7f1b3977130924840b06c1b1fdb2137529ed`.
- Product/tests commit/tree: `aea1ac6471784256a408daaef324dab9f5cba571` / `0f2246eefb5e5996355a8c31d3cc7a8f76655875`.
- Fresh Otto wheel: `dist/otto_local_candidate-0.0.0-py3-none-any.whl`, SHA-256 `e0e4cfa7f2c8d194ad4863a4e8eb26452704f25eaac415c20c9460508caee595`.
- Accepted Herzchen wheel SHA-256: `2681daaeb673cd636050c3805977a01a670ed6bcfc113fe9d85903af5eeae9bc`.
- Existing validation venv: `/tmp/ott03-template-open.o3HzxD/venv`, Python 3.11.16.

The wheel was built from a `git archive` of the corrected product/tests commit, not from the dirty checkout. Exact commands, cwd, timestamps, environment, exit codes, model/reasoning, and output paths are in `execution-receipts.json` and `execution-receipts.jsonl`.

## Correction

`FiniteWorkOperations.create_pending` now returns `task_created: bool(task_records)` for the selected template pending response. A selected template with a typed task reports `task_created: true`; `executable`, `activation`, `dispatch`, `budget_reserved`, and `session_created` remain false. Existing blank/default and handoff paths still use false when no task records exist.

The narrow selected-template expectation now discriminates the typed task presence from dispatch/execution, budget, and session-created-task flags. Its existing exact replay assertions still require the same task refs and an unchanged event list.

## Receipts

- Source focused campaign: `18 passed`, exit code 0, `18:12:01.242490Z`–`18:12:02.321754Z`, with `PYTHONPATH=src` and `PYTHONHOME` unset. See `source-focused-18.txt`.
- Installed focused campaign: `18 passed`, exit code 0, `18:13:48.760510Z`–`18:13:50.857731Z`, with both `PYTHONPATH` and `PYTHONHOME` unset. See `installed-focused-18.txt`.
- Installed origins: `otto` and `otto.portfolio.owner_bootstrap` resolve from `/private/tmp/ott03-template-open.o3HzxD/venv/lib/python3.11/site-packages`; `herzchen` resolves from that same venv. See `installed-origins.json`.
- Accepted Herzchen reinstall and fresh Otto wheel install both returned exit code 0; raw outputs are retained beside the receipts.

The prior 47/18 campaigns and observation evidence remain historical and were not edited. No broad tests were added.
