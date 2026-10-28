# Tasklist: PROCLIFE: process lifecycle made structurally true (minimal plan)

**Revised 15 Oct.** This follows the Opus complexity review (evidence/opus-complexity-review.md), with Astra's principles kept (evidence/astra-*.md):
- tags never authorize a signal;
- pod intent is recorded before launch;
- billing and idle limits are separate;
- provider evidence settles pods;
- an unresolved cleanup blocks only its own attempt or pod.

The general obligations ledger is deferred until a second remote provider or multi-machine scheduling exists.

Routes are normal or xhard (Megado). Sizes are focused days (4.25 in all). Each step's acceptance includes one gate run (step 1) on the normally busy Mac. Work happens on a branch from Astrid main; the user merges.

| id | route | est (d) | deps | outcome | acceptance evidence | xhard justification | stream | status |
|---|---|---|---|---|---|---|---|---|
| PL1 | normal | 0.5 | — | **The gate.** One script runs the film journey (Codex image → sprite → edit → publish → full-film review render) on a copy of the realm, then checks for leftover processes. | fails at the render on unfixed main under normal load; passes on the live line | — | proclife | not started |
| PL2 | xhard | 1.0 | — | **Stop proving during the run.** No in-run observation in the command loops. At teardown: TERM then KILL the group, then one census with the live line's retries. Delete the ordinary-command observer, census reconciliation and per-descendant registration. | the gate passes 3× in a row under load; a cancel at 50% leaves nothing; net lines removed | Invariant: G2, signal only our anchored group. Mistake: deleting symbols other paths import. Surfaces: VibeComfy or Codex custody breaking. | proclife | in progress (fix/pl2-scopes) |
| PL3 | normal | 0.5 | PL2 | **No host-wide latch.** The latch becomes a record only: the task fails as "cleanup unresolved", its folder is kept, and doctor names the survivors. Remove the admission blocks. At startup, kill orphaned groups whose recorded leader is still alive (matching pid and start time). | an injected census failure fails one task and the next render succeeds; after a host SIGKILL mid-render, the next start kills the orphan | — | proclife | not started |
| PL4 | normal | 0.5 | — | **Validate at render time.** Remove startup-wide validation of every worker context. | cold host start < 60 s (6.5 min today); the gate passes from a cold start | — | proclife | in progress (fix/pl1-validation) |
| PL5 | normal | 0.5 | — | **Simple host retirement.** Drop OTTO_HEAVY_LEASE from the host's spawn environment. Retire a host by its registered pid, start time and group. Delete `_pin_native_host_command`, `_framework_reexec_of_launch` and `_darwin_host_command_observation`. | a host started inside a heavy job survives the job; a host whose launching CLI is gone can still be stopped | — | proclife | not started |
| PL7 | normal | 0.25 | PL2–PL6 | **Close-out.** Archive the superseded branches and record their SHAs (T03/U1/V2/W3a, V1, da95959d, fix/main-host-owner). Runtime custody is not deleted: it has 7 importers. | list with SHAs; branches deleted | — | proclife | not started |

**15 Oct ~17:00 (user):**
- No Codex gating or messages; this is Claude's job.
- RunPod spending (PL6) dropped as over-engineering.
- PL2 and PL4 landed on Astrid main 121f2bf3.
- Next, in parallel: PL3 (no latch anywhere), PL5 (recover by registration), the validation cuts.
- Then migrate the remaining ordinary launchers to task scopes and delete the per-descendant path.
- Then commit the journey script (PL1).
