**Implemented** the offline provenance parity check and product neutralized the shared authoring boundary. The new fixture compares every `ManagedSourceIdentity` field against an inline recorded inventory, with a second active pack to catch inventories that omit other sources. It requires no Astrid import.

The parity test first failed because the tree digest was empty for paths returned relative to a subdirectory; I fixed the Git query to return repository relative paths. The requested check now passes: **13 passed**. The expanded focused checks also passed: **40 passed, 27 subtests**. `git diff --check` passed.

The boundary test checks that Herzchen source contains no Astrid name, `Documents/Codex` path, or Otto owner authority. The `grep -rn Documents/Codex src/herzchen` matches are confined to `src/herzchen/kernel/tests`; there are no matches outside tests.

**Removed:** the Astrid dependent, conditionally skipped parity test and its imports; the hardcoded selected pack authority and host paths from Herzchen’s usage contract; and the `astrid-managed` resource authority. Otto now supplies contract provenance at its boundary.

Additional files changed and why:

- [src/otto/agents/__init__.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PACKPARITY/src/otto/agents/__init__.py): supplies Otto’s authority and paths.
- [src/herzchen/evidence/model.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PACKPARITY/src/herzchen/evidence/model.py), [src/herzchen/content/vision_pack.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PACKPARITY/src/herzchen/content/vision_pack.py), and [src/herzchen/content/vision.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PACKPARITY/src/herzchen/content/vision.py): consume the generic managed source authority.
- [tests/test_usage_contract.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PACKPARITY/tests/test_usage_contract.py) and the two vision test files: cover explicit provenance injection and the generic authority.

Current commit: `c2bc556`. Changes are uncommitted for the launcher; nothing was pushed. I did not run the staging owner.