# RECEIPTFENCE sendback r4

Apply only the exact Restore in `${TRANSFER_ROOT}/portfolio/ops/reviews/D19-RECEIPTFENCE.md.sendback-r4`: in `tests/test_manager_reentrant_ipc.py`, replace `pending = self.wait_file(self.directory / "pending-abc123.json")` with `pending = json.loads((self.directory / "pending-abc123.json").read_text())`.

Retain all six marker assertions and every other existing protection. Do not broaden the edit. Run the task's focused check and report the changed assertion plus check result. The current RECEIPTFENCE lab owns its listed files; no other worker is running. Do not touch anything outside the lab. Follow the existing xhard/Codex rules in the lab brief. Leave the changes for the launcher to commit.
