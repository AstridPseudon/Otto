Implemented and committed the selected `WorkTemplate` create-and-open path. The worktree is clean; Herzchen source and sealed v2 evidence are unchanged.

### Commits and artifacts

- Product/tests commit: `14510f49514587ecda265fb3e38c632f9ebe3179`
- Product tree: `2d213ad75bb3a730bfed8c31eff9c4d2597ec4df`
- Evidence commit: `012b77efa1d939b0100f69972fe318e4d6ba7827`
- Evidence tree: `f95dfc04b26f6d9886c33c2474f2ca6769e94fb7`
- Fresh Otto wheel SHA-256: `578c72f042a915510dc4dd1a10d78f82350231ac5029d2bf10f7a55b2febdf19`
- Accepted Herzchen wheel SHA-256 reverified: `2681daaeb673cd636050c3805977a01a670ed6bcfc113fe9d85903af5eeae9bc`
- Artifact manifest SHA-256: `6d1ebe1a97a2d0bb4d69bb0dedc33db9556310f1a277c3b382dc595493939a88`

Evidence: [result.md](/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Otto-ott03-template-open-worker/work/ott-03-template-open-receipt-20260914-v3/result.md:1), [capability matrix](/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Otto-ott03-template-open-worker/work/ott-03-template-open-receipt-20260914-v3/capability-coverage-matrix.json:1), [execution receipts](/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Otto-ott03-template-open-worker/work/ott-03-template-open-receipt-20260914-v3/execution-receipts.json:1), and [wheel](/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Otto-ott03-template-open-worker/work/ott-03-template-open-receipt-20260914-v3/dist/otto_local_candidate-0.0.0-py3-none-any.whl).

### Verification

- Source focused campaign: `18 passed`, return code 0.
- Installed focused campaign: `18 passed`, return code 0, `PYTHONPATH`/`PYTHONHOME` unset.
- Source complete Otto-owned campaign: `47 passed`, return code 0.
- Installed complete campaign: `47 passed`, return code 0, `PYTHONPATH`/`PYTHONHOME` unset.
- Installed observation: return code 0.
- Python: 3.11.16; model `gpt-5.6-sol`, reasoning `high`.

### Raw observation

Full JSON: [selected-create-open-observation.json](/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Otto-ott03-template-open-worker/work/ott-03-template-open-receipt-20260914-v3/selected-create-open-observation.json:1).

- Outcome/open: `created` / `opened`
- Project: `project-15384ab8984c18eb304d1af79bc4@rev-2`
- Typed task: `task-6dd8626381ab90945b4436b894b2`
- Template: `ott03.observed.selected-open@observed-v1`
- Session: `session-56053d6970295d65b0a2c8c3`
- Event delta: 6
- Exact replay: zero delta
- Changed resource and parameters: `replay_conflict`, zero delta
- Invalid resource: `invalid_template_resource`, zero delta
- Fresh reopen: selected title/tasks and open authoring scope preserved
- Dispatch, manager launch, budget, session-created task, and execution: all false

The formerly pending capability row is now explicitly supported. No unresolved named product issue remains. A first evidence-harness serialization attempt returned 1 and is retained truthfully; it was corrected without changing product source.