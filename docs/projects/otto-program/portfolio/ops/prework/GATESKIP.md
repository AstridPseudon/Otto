## Design, in implementation order

1. `tests/test_bootstrap_gate.py:226` → Write the failing regression test below first. It covers a skip-only check and a skip-only file reached by the sweep.
2. `ops/bootstrap/otto_gate_exit.py:13` → Extend the existing pytest gate plugin to track outcomes by test file. Count collection and test skips, but count a failure, pass, xfail, or xpass as an executed outcome. At terminal summary, emit one bounded `otto-gate: all skipped in <file>: <reason>` line for each file with skips and no executed outcomes. Include collection-level skips and a skip reason.
3. `ops/bootstrap/land.sh:279` → Refuse the check immediately if its output contains that line. Do this before logging “check passed” or crediting the check as a sweep run. `ops/bootstrap/land.sh:389` → Refuse a skip-only sweep run immediately, including when the same file skips on BASE; this is missing coverage, not a baseline failure to excuse.
4. `tests/test_manager_journey_service.py:54` → Replace the external-module `setUp` with a disposable, in-repo product owner fixture. Compose `HostOwnerService` and `ManagerJourneyService` through the maintained owner path at `src/otto/hostctl/serve.py:73,720` (or the shared composition at `src/otto/hostctl/product_service.py:1302`). Supply a fake **model** through the existing adapter factory seam. Keep the real owner state, Due port, `ExecutionHost`, and command routing. The fixture must fail on setup errors, never skip.
5. `tests/test_manager_journey_service.py:107` → Route identity-bearing requests through the product caller boundary; `src/otto/portfolio/manager_journey_client.py:14` now classifies `run-worker`, `report`, review, and finish commands that way. Use the maintained client at `src/otto/hostctl/manager_client.py:66` for subprocess manager turns. Keep owner-custody file-lane requests on their supported route.
6. `tests/test_manager_journey_service.py:246` → Install the journey with the product hook at `src/otto/portfolio/manager_journey_service.py:2480`. Put a single `run.json` in the disposable run view (`src/otto/portfolio/run_config.py:14`), and provide criterion and worker policy through owner records. Adapt the 18 non-legacy journey tests to that composition while preserving their substantive outcome and retained-effect assertions.
7. `tests/test_manager_journey_service.py:157,266,395,435,476,575,589,615` → Remove touched tests’ substitutions of product methods. Drive answer/route through owner paths; inspect Store and budget effects instead of wrapping `_journal` or `save_due`; seed historical records and tampered content as fixture data; persist Due state for the unsettled case; write the disposable run configuration instead of patching `Path.read_text`. Only the model/person stand-in remains.

## Failing test to write first

Add to `tests/test_bootstrap_gate.py`, in `LandGate`:

```python
def test_all_skipped_check_and_swept_file_are_refused_with_reason(self):
    reason = "GATESKIP fixture deliberately unavailable"
    source = ("import pytest\n\n"
              "def test_needs_fixture():\n"
              "    pytest.skip(%r)\n" % reason)

    self.lab("T31", {"tests/test_skip_only.py": source})
    check = "%s -m pytest -q tests/test_skip_only.py" % sys.executable
    checked = self.land("T31", "--check", check)
    self.assertRefused(checked, "T31", reason)
    self.assertIn("tests/test_skip_only.py", self.log("T31"))
    self.assertNotIn("sweep:", self.log("T31"))

    self.lab("T32", {"tests/test_skip_only.py": source})
    swept = self.land("T32")
    self.assertRefused(swept, "T32", reason)
    self.assertIn("sweep tests/test_skip_only.py", self.log("T32"))
```

On current canon, the first landing reaches a successful merge: pytest reports `1 skipped` with exit 0, and the check’s completion test at `land.sh:279` accepts it.

## Delete

Delete the external baseline/env loader and skip at `tests/test_manager_journey_service.py:56-68`, its fabricated baseline globals at `:71-77`, and the external `manager_ctl.py` dependencies at `:343,672,772`. Replace `test_baseline_real_run_worker_starves_nested_report_until_worker_returns` at `:231` with an event-driven test of the product’s supported nested progress while a worker is blocked. Remove its `sleep(.2)` absence assertion; elapsed time is not the behavior under test.

## Plausible mistake the test catches

A worker may fix only the check’s summary parsing. The first half then refuses, but a passing check followed by a swept file with every test skipped still lands. The second half catches that gap and requires the refusal to name the skipped file’s reason.

## D19 decisions

A written D19 decision is required for deleted or changed existing assertions in `tests/test_manager_journey_service.py`, notably the retired starvation assertion (`:231`), mocked answer/route outcomes (`:157`), and the baseline-specific `project_scope_denied` assertion (`:557`). Preserve other expectations unless product-backed evidence requires a change; name and justify each such change in the decision. The new gate test changes no existing assertion in `tests/test_bootstrap_gate.py`.

## Row corrections on canon

The count **19** is correct for `ManagerJourneyServiceTests` (`:51-887`). The skip is conditional on an absent external fixture; the gate sweeps this file when selected, not on every landing (`land.sh:287-319`). The gate also handles `SUBFAILED` and nonzero exits (`:233-237`), so “fails only on FAILED or ERROR lines” is too narrow. No skip-based PACKPARITY test is present on `canon/main`; the recorded provenance parity test at `tests/test_evidence_lifecycle.py:395` has no skip guard.

This is a read-only design. No tests were run and no files were changed.