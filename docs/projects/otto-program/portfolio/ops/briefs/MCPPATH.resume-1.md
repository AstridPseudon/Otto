# MCPPATH resume 1: correct Herzchen placement

The MCPPATH landing was refused by D14: the brief's layer is “Herzchen fleet server launch behavior,” but the implementation changed only `src/otto/hostctl/product_service.py` and nothing under `src/herzchen`.

Rework the implementation so the reusable server-launch isolation behavior lives in the Herzchen fleet layer. Keep Otto-specific wiring and names in Otto. Preserve the outcome: an MCP server started from a lab must load Otto's installed code despite lab package and standard-library shadows. Retain the regression's real `OwnerFleetRegistry.grant_for_due` path and do not patch product methods in the test. Follow `ops/prework/MCPPATH.md`'s design and the existing Herzchen/host boundary.

You may edit any files directly required by this outcome. Do not touch files owned by the active RECEIPTFENCE worker; inspect its brief/resume note and current changes before choosing overlapping files. Do not touch production, Stores, `~/.otto`, `~/.codex`, or anything outside this lab. Do not weaken assertions.

Run the focused regression and the task's required check. Report the canon red/lab green results, files changed, and any sandbox-only failures. Leave the work for the launcher to commit.
