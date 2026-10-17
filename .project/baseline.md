# Throughput baseline (17 Oct 2026)

Reproduce with `python3 ops/bootstrap/throughput_report.py /Users/hannahomalley/Developer/otto-program/ops/runs/*/land.out`. The parser derives logged gate elapsed from the first to last UTC timestamp in each `land.out`, groups repeated sweep inputs by test filename, and measures each run-1 to run-2 completion interval. These are elapsed intervals, not CPU time; the sweep interval includes anything between the two completion log messages.

The 103 historical logs contain 1,835 paired sweep inputs. Largest cumulative run-2 intervals:

| Test input | Pairs | Cumulative elapsed | Median elapsed | Source log paths |
|---|---:|---:|---:|---|
| `tests/test_hostctl_serve.py` | 25 | 3,394 s | 157 s | `/Users/hannahomalley/Developer/otto-program/ops/runs/{A4,A6,ACTCRIT,AUTODISPATCH,AUTODISPATCH2,COMPOSEFLEET,CUSTODY,DISPATCHSEEN,FAILCLOSED,HOSTKIT,LABCAPTURE,LANDASSESS,LIVENESS,MGR,OPERATOR-ADMIT,ORPHANWORKER,PINCONTENT,POOL,PYSTUB,REDS2,REDS3,RUNNER,STAGESETUP,TOOLS}/land.out` |
| `tests/test_bootstrap_gate.py` | 21 | 2,301 s | 62 s | `/Users/hannahomalley/Developer/otto-program/ops/runs/{CODEXHOST,TOOLING3,TOOLING5,TOOLING6,TOOLING7,TOOLING9,TOOLING10,TOOLING11,TOOLING12,TOOLING13,TOOLING15,TOOLING16,TOOLING17,TOOLING18,TOOLING19,TOOLING20,TOOLING21,TOOLING22,TOOLING23,TOOLING24,TOOLING25}/land.out` |
| `tests/test_perch.py` | 15 | 1,300 s | 87 s | `/Users/hannahomalley/Developer/otto-program/ops/runs/{COMPLETECITE,FAKECOMPLETE,FAKECOMPLETE2,FAKECOMPLETE3,LANDASSESS,ORPHANWORKER,PERCH,PERCH0FIX,PERCH2,PERCH2B,PYSTUB,SKEL0,STAGE2C,TOOLING14,TOOLING22}/land.out` |

Runner execution (`seconds`), queue wait (`started_at - submitted_at`), and submitted-to-settled elapsed can be computed from sealed runner records. No sealed runner record export was present in the historical run directories, so all three are unavailable here. The runner's aggregate `otto run report` counters do not expose per-record queue wait or command identity. The logs show no command-level execution records to distinguish from gate elapsed. Summing gate elapsed over separate logs yields 43,710 s and is not wall-clock time for one landing because runs are independent and may overlap.
