Implemented the Orchestrator’s corrections and left the changes uncommitted at rebased HEAD `965f6cc`.

The parity test now compares Herzchen’s provenance field by field with a checked-in recording from Astrid commit `f42eaa6d`. The fixture repo uses fixed Git author and committer identities and dates; its paths are recorded relative to the fixture root. The test imports no Astrid code. The recording script is [record_astrid_provenance.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PACKPARITY/tests/fixtures/managed_source_provenance/record_astrid_provenance.py), beside [recorded_source.json](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/PACKPARITY/tests/fixtures/managed_source_provenance/recorded_source.json).

Herzchen now accepts the source-state path from its caller and no longer reads an environment variable. Otto resolves Astrid’s configured path or its XDG/default location and passes it through the evidence loader. I kept the full-name Git path lookup, moved usage-contract authority and host paths to Otto, and retained the `managed-source` label. The boundary test checks imports and machine paths; `grep -rn Documents/Codex src/herzchen` still finds matches only under test directories.

**Checks**

- Red: the first run exposed a dirty deterministic fixture checkout and a remaining `/Users/` launcher default. Both were corrected.
- Requested check: `14 passed, 8 subtests passed`.
- Additional focused checks: `65 passed, 50 subtests passed`.
- `git diff --check` passed. The Astrid checkout remained clean.

**Changed test expectations**

- Provenance parity now uses Astrid’s recorded JSON fields and verifies the fixture’s deterministic revision.
- The doctored boundary fixture now expects Otto and Astrid imports plus both machine-path markers to be reported.
- Vision fixtures use `managed-source` to match Herzchen’s product-neutral source label.
- Usage-contract tests supply provenance values explicitly to verify caller injection.

Additional files changed: `src/herzchen/evidence/commands.py` and `src/herzchen/evidence/model.py` pass the source-state path through; `src/herzchen/content/vision_pack.py` exposes the same loader option; `src/otto/hostctl/owner.py` resolves and injects Astrid’s path; `src/herzchen/adapters/host.py` removes its machine-specific launcher default. No staging owner was run.