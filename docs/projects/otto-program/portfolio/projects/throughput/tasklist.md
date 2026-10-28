# Tasklist: THROUGHPUT: heavy seconds per accepted task

Routes are normal or xhard (Megado). Deps are task ids in this project. Sizes are focused days (3.25 in all, 2 XHARD).

| id | route | est (d) | deps | outcome | acceptance evidence | xhard justification | stream | status |
|---|---|---|---|---|---|---|---|---|
| TP1 | normal | 0.25 | — | **Read the runner report:** where heavy seconds go (top commands, repeats, waits). | the breakdown recorded | — | throughput | not started |
| TP2 | xhard | 0.75 | TP1 | **The result cache** (the program's CACHE, if it isn't done yet), keyed on the committed tree, environment and toolchain. | `byte_env_toolchain_rerun`, `dirty_lab_uncached` | Invariant: a cached pass applies only to identical inputs. Mistake: leaving the toolchain or environment out of the key. Surfaces: a stale pass. | throughput | not started |
| TP3 | normal | 1.0 | TP1 | **Focused checks by default:** tests selected by the files changed, so `check` takes seconds. The task's full check still runs at landing. | median `check` seconds before and after | — | throughput | not started |
| TP4 | xhard | 1.0 | TP1 | **A warm renderer for Astrid frames:** one runner-held Chrome/Remotion process that previews reuse. | a frame preview median under 15 s on this Mac; nothing leaked | Invariant: a warm process never serves a render from a stale bundle. Mistake: reusing it across code changes. Surfaces: a frame that doesn't match the code. | throughput | not started |
| TP5 | normal | 0.25 | TP3, TP4 | **Measure and clean up:** heavy seconds per accepted task before and after; the superseded cold paths deleted. | the numbers recorded; the ledger updated | — | throughput | not started |
