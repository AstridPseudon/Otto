# PACKPARITY resume-1 — implement the Orchestrator's exact corrections

Resume the same worker session after rebasing `lab/PACKPARITY` onto current `canon/main`. Keep the existing task outcome and all previously accepted work. Do not land yet; the Orchestrator will write `D19-PACKPARITY.md` after your report.

Keep:
- `ls-files --full-name` (it matches Astrid's own `_tree_digest`, `~/Developer/astrid-video/astrid-local/live-main/Astrid/astrid/core/pack/source_setup.py:286`);
- the Otto constants moved out of `herzchen/usage/contract.py`;
- the `astrid-managed` → `managed-source` authority rename (Herzchen's own label; Astrid never uses it).

Change:
1. The parity test checks the code against itself: its "recorded Astrid provenance" is rebuilt with the same hashing the product uses. Make it a real recording: run Astrid's own loader once (read-only checkout above, commit f42eaa6d, on PYTHONPATH; don't edit it) on a deterministic fixture repo (fixed author and committer names and dates, so the revision is stable), and check in its `source.to_dict()` as JSON with paths made relative to the fixture root, beside the small script that recorded it. The test builds the same fixture and compares Herzchen's output with the JSON field by field, with no Astrid import.
2. `ASTRID_SOURCE_STATE` → `HERZCHEN_SOURCE_STATE` silently drops the inventory Astrid points to, and with no variable set the inventory identity still differs from Astrid's (the review's finding). Herzchen reads no environment variable for this: its loader takes the source-state path from its caller. Otto passes Astrid's location, the way `source_state_path()` resolves it (`source_setup.py` ~208-215: `ASTRID_SOURCE_STATE` if set, else `$XDG_STATE_HOME` or `~/.local/state`, then `astrid/<default profile>/pack-sources.json`). Plumb it the shortest way.
3. The boundary test refuses `otto`/`astrid` imports and machine paths (`/Users/`, `Documents/Codex`) in Herzchen source outside tests. It need not refuse every product word.

Then re-run the focused tests and report which existing test expectations changed and why, one line each. Follow the original brief's Check command and Codex working rules. Do not touch `production/`, any Store, `~/.otto`, `~/.codex`, or the active-task files listed in `.brief.md`. Leave changes uncommitted for the launcher.
