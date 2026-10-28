# PERCH2 resume 2

The last landing refusal says the stage-2 scenario is still a stub: it feature-detects by grepping for `COMPOSEFLEET` and skips instead of driving the owner. COMPOSEFLEET is now landed (`fe17d49`), and Orchestrator 02:07Z requires a real stage-2 dispatch scenario. Implement that scenario and its focused tests; do not land or ask for another prerequisite.

Acceptance requirements:
- Save the stage-2 canary with `check-accepted` scope and `otto.plan` repo and branch.
- Admit every revision except one.
- Drive the composed owner to dispatch fake workers. Record the resulting dispatch and lab events, kill one worker mid-task, and stop staging cleanly.
- Assert the actual dispatch, refusal, event recording, and recovery behavior. Do not synthesize green observations or use string-grep feature detection. If owner dispatch cannot run, fail the scenario with the concrete reason.
- Keep the stage-2 gate strict: a skipped in-scope scenario is a failure. Preserve stage 0 and stage 1.

Work in the PERCH2 lab only. The existing authorized files are listed in `.brief.md`; you may also edit any file the outcome directly requires, except `land.sh`, production state, Stores, `~/.otto`, or `~/.codex`. No other worker owns files in this scope. Do not weaken assertions or change task scope. Run the exact `Check command:` from `.brief.md` to completion with a long timeout, plus focused checks for the actual stage-2 dispatch path. Leave changes for the launcher to commit and report the exercised owner path, event evidence, worker kill/recovery result, and any concrete blocker.
