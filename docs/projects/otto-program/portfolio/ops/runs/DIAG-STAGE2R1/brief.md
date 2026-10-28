# Brief: DIAG-STAGE2R1 (xhard, read-only audit)

**Outcome:** Diagnose the failed stage-2 run below. Classify every failing assertion as product or harness, cite `file:line` evidence, explain the concrete scenario and smallest fix. Do not create any fix tasks or alter files; report findings for the manager to act on.

**Question and evidence:** Stage-run `STAGE2R1` tested commit `193e2b89c9deae914446c9ac2c475a1d6e079920` (canon/main `e56707e` plus PERCH2C). Report: `${TRANSFER_ROOT}/portfolio/ops/perch-reports/2/20261017T204125Z/report.md`. Kept staging root: `/private/tmp/sr224125` (`run/staging.log`, `home/shared-host/`, `store/`). The final `LAND RESULT` is failed because `labs-left-behind` reported owner markers under lab `68006181e11fc5c4fd81/.creating`, `.landed`, and `.locks`; all other assertions in the report pass or skip. Inspect the exact report evidence and source path producing that assertion. Determine whether those entries are an actual leaked lab or marker artifacts, and whether the product or check is wrong. Also verify the report's other checks and disclose any failure it misses or any actual discrepancy.

**Read-only sources:** current tested product tree is `/private/tmp/sr224125/tree`; compare against the report's tested commit and current program sources as needed. You may read the report, raw evidence, stage logs and Store read-only. Do not delete `/private/tmp/sr224125`.

**Do not:** edit, create or delete files; commit; run tests; start a staging owner or any `ottoctl`/owner/service command; read `~/.otto`, `~/.otto-clients`, `~/.codex` or `~/Documents/Codex`. No fixes or staging reruns. This is a diagnosis only.

**Report:** Findings most severe first, each with title, `file:line`, concrete failing scenario, real-use impact, smallest fix and classification (product/harness). Label inferences. Then “Checked and sound” and “Not checked, and why.” Keep it concise and evidence-based.
