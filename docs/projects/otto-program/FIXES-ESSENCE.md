# Otto fixes: what they protect

The program consolidates Otto around one owner, one project record, bounded execution, and evidence-backed completion.

## What the integration fixes protect

Rounds 1–4 are on `canon/main` at `a70b3f2` (also GitHub main). The landed work and remaining labs address four guarantees (the names below span both):

- **A launched process stays owned and recoverable.** `PINALL`, `OWNERCLAIM`, `INTEG-PROCLIFE-PL1/2`, `LABPIN`, `OBSOWNER`, and `RECEIPTFENCE` tighten process identity, capacity holds, durable reader/worker custody, and receipt replay. A request whose work already ran must retry its receipt, never run the command again; uncertain or still-live work keeps its fence and reservation.
- **A worker cannot borrow authority or lose its assignment.** `MCPPATH`, `ROSTERPIN`, `PARITYFIX`, `ASKDISP`, `CMDTMPDIR`, and related fixes ensure Otto’s MCP code is used from a hostile lab, admitted work stays bound to its project/task, replay evidence remains trustworthy, and temporary sockets are cleaned up. A continuation dispatches once; a shadow package or stale pin cannot redirect it.
- **Launch, landing, and proof use the real product path.** `DEADLAUNCH`, `SCRIPTMGR`, and `INTEG-PROCLIFE-PL1/2` remove unused launch routes, make the fake journey issue real manager commands, and preserve nested-process custody through recovery. `TESTPATCH`, `LANDPROOF`, `XFERMAP`, `BOOTLAND`, and gate tasks were queued or being repaired; they target real-owner test coverage, capture before lab deletion, and complete revision-consistent project transfer.
- **The journey’s evidence must prove the claim.** `INVARIANTS`, `PERCH2C`, and `SCRIPTMGR` make stage reports examine recorded events, identities, process census, resources, and accepted evidence after each step. Missing evidence must fail. A scenario passing because the harness completed work itself is not product proof.

## Unlanded at pause

The most urgent is **`STAGE2CLIENT`**: fresh installation advertises `home/bin/ottoctl` but does not create it. The scripted manager then gets `FileNotFoundError`; the next task never dispatches and stage 2 waits forever. The correct fix is to install the client and refuse registration if the advertised path is absent, plus make the harness fail on retained terminal failure by state, without a timeout. It was committed but not landed or verified when the user paused the run.

Other outstanding fixes: `TESTPATCH`, `LANDPROOF`, `XFERMAP`, `LABPIN`, `OBSOWNER`, `ROLEIDS`, `BOOTCFG`, and `CLIARGS`; resolve regressions and rebase conflicts before landing. `REALSTAGE3` and `DISTURB` await the stage-2 repair. The seven follow-up projects also have committed partial implementations; their branch tips are preserved separately and are not all integrated.

**Status:** user paused the program on 18 Oct; the final pause queue was recorded on 19 Oct. No work should be treated as resumed; this is a handoff summary, not a restart instruction.
