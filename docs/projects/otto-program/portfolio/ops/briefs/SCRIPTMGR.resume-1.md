# SCRIPTMGR sendback r4

Apply only the exact Restore in `${TRANSFER_ROOT}/portfolio/ops/reviews/D19-SCRIPTMGR.md.sendback-r4` to `tests/test_perch.py`: in `test_stage_two_manager_uses_installed_review_and_recovery_commands`, add an injected-client case where `review-task` returns `outcome: accepted`, nonempty `gate_refs`, and `completion: {outcome: held}`, and assert `fake.scripted_manager_turn("A", client=...)` raises `RuntimeError` matching `review or finish was refused`.

Preserve the accepted/pending case and all other protections named in the Restore. Do not broaden the edit. Run the focused check from the task brief and report the changed assertion plus check result. The current SCRIPTMGR lab owns its listed files; no other worker is running. Do not touch anything outside the lab. Follow the existing xhard/Codex rules in the lab brief. Leave the changes for the launcher to commit.
