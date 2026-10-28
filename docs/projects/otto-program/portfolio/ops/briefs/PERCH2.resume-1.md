# PERCH2 resume 1

The landing gate refused `perch.sh all --fake`: stage 0 and stage 1 passed, while stage 2 reported zero of the expected events/tasks and `admit-and-dispatch` did not run because the staging checkout reported “COMPOSEFLEET has not landed.” The task row requires stage 2 to pass once COMPOSEFLEET has landed; the orchestrator says COMPOSEFLEET landed as `fe17d49` and ordered PERCH2 first.

After the required rebase, inspect why the current stage runner/staging tree does not see the landed COMPOSEFLEET implementation. Work only within the PERCH2-authorized files already listed in your brief and preserve the acceptance contract. Fix a PERCH2 defect if the current canon provides the needed dispatch capability. If staging genuinely cannot run until an external owner stage/setup step or another prerequisite, do not fake green results or weaken the gate; report the precise blocker and stop. Run focused checks and leave work for the launcher to commit.

No other worker is active. Do not touch `land.sh`, production state, Stores, `~/.otto`, or `~/.codex`. Keep the existing check command and run commands to completion with a long timeout.
