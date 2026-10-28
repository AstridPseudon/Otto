# D19-TOOLING5: orchestrator decision (no Opus call)

1. **Verdict: LAND.**
2. **The changed line:** `tests/test_bootstrap_gate.py:147`, `self.ops / "baseline"` becomes `self.ops / ".baseline"`.
3. **Why it's not a weakened expectation:** the assertion still requires the gate to cache BASE's output for `test_mod.py`. Only the folder changed, to where `land.sh` writes it since TOOLING3B (`baseline_out`, `ops/bootstrap/land.sh:145`: `$OPS_DIR/.baseline/$BASE/$1.txt`). On canon 198883c the test fails for that reason alone (`test_failure_also_on_base_is_pre_existing`: `AssertionError: [] is not true`); with the change it passes, twice in the gate.
4. **Why the orchestrator decides it:** D19 keeps workers and the manager from rewriting expectations to pass. This change is the orchestrator's own, to the bootstrap tooling's test, restoring a path the orchestrator moved; an Opus call would buy nothing here. Logged in `ops/STATUS.log`.
