# THROUGHPUT after report (17 Oct 2026)

## Comparison

The historical measurement baseline is [baseline.md](baseline.md), reproducible with `python3 ops/bootstrap/throughput_report.py /Users/hannahomalley/Developer/otto-program/ops/runs/*/land.out`. It parses 103 `land.out` logs and 1,835 paired sweep inputs. The largest recorded second-run completion intervals were:

| Test input | Pairs | Total elapsed | Median elapsed |
|---|---:|---:|---:|
| `tests/test_hostctl_serve.py` | 25 | 3,394 s | 157 s |
| `tests/test_bootstrap_gate.py` | 21 | 2,301 s | 62 s |
| `tests/test_perch.py` | 15 | 1,300 s | 87 s |

These are elapsed intervals between logged completions, not CPU time. Exact source log references for the largest costs:

- `tests/test_hostctl_serve.py`: `/Users/hannahomalley/Developer/otto-program/ops/runs/{A4,A6,ACTCRIT,AUTODISPATCH,AUTODISPATCH2,COMPOSEFLEET,CUSTODY,DISPATCHSEEN,FAILCLOSED,HOSTKIT,LABCAPTURE,LANDASSESS,LIVENESS,MGR,OPERATOR-ADMIT,ORPHANWORKER,PINCONTENT,POLICYPIN,POOL,PYSTUB,REDS2,REDS3,RUNNER,STAGESETUP,TOOLS}/land.out`.
- `tests/test_bootstrap_gate.py`: `/Users/hannahomalley/Developer/otto-program/ops/runs/{CODEXHOST,TOOLING3,TOOLING5,TOOLING6,TOOLING7,TOOLING9,TOOLING10,TOOLING11,TOOLING12,TOOLING13,TOOLING15,TOOLING16,TOOLING17,TOOLING18,TOOLING19,TOOLING20,TOOLING21,TOOLING22,TOOLING23,TOOLING24,TOOLING25}/land.out`.
- `tests/test_perch.py`: `/Users/hannahomalley/Developer/otto-program/ops/runs/{COMPLETECITE,FAKECOMPLETE,FAKECOMPLETE2,FAKECOMPLETE3,LANDASSESS,ORPHANWORKER,PERCH,PERCH0FIX,PERCH2,PERCH2B,PYSTUB,SKEL0,STAGE2C,TOOLING14,TOOLING22}/land.out`.

The reported aggregate 43,710 s of gate elapsed is a sum across independent logs, not one landing's wall-clock duration.

No sealed runner records or accepted-task runs are available in the supplied history or this clone. Therefore runner execution seconds, queue wait, submitted-to-settled time, accepted-task throughput, and feedback latency have no measured before/after values. TP3's median check time is also unmeasured: its regression fixture uses `/usr/bin/true`, not a pytest workload. Focused test runtimes are correctness evidence only and are not production throughput measurements.

## Changes and deletion accounting

| Task | Actual task diff | Outcome |
|---|---:|---|
| TP1 | +126/-0 | Added the historical log parser and baseline. |
| TP3 | +100/-0 | Changed feedback `check` to select focused tests. The broad feedback-selection behavior is superseded, but TP3 removed no physical source lines. |
| TP6 | +114/-8 | Made worker refusal responses actionable and recorded the cold-agent UX pass. |

These are task diffs recorded by their landed commits, not the cumulative project diff. No additional cold feedback path is provably unused by callers: the feedback operation remains directly called through the landing owner port and test adapters. No source deletion is justified. The deletion budget used is zero physical lines; TP3 only superseded broad selection behavior.

## Checks and limits

- `tests/test_throughput_report.py`: 2 passed (TP1 parser and runner-summary checks).
- `tests/test_landing.py`: 16 passed (TP3 selection checks).
- `tests/test_worker_refusal_next_action.py`: 3 passed (TP6 refusal checks).
- TP3 worker-reported checks: `tests/test_fleet_custody.py` 15 passed / 14 sandbox failures, and `tests/test_tools.py` 22 passed / 7 environment failures. These require the gate environment.
- TP2 is blocked: only repeated D19 sweeps are evidenced, and those must not be cached; no sealed runner records establish a separate eligible repeat.
- TP4 is blocked: the Astrid renderer and benchmark are outside this clone and its write boundary.
- The landing/staging gate was not run. Checks requiring `sandbox-exec`, `ps`, or a staging owner need the gate.

This report's consistency check is `tests/test_throughput_after.py`. It checks the distinctions and figures recorded above; it does not claim fresh production measurements.
