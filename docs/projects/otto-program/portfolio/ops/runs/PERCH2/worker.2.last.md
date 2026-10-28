I didn’t implement the real stage-2 dispatch scenario, so PERCH2 is incomplete. The working tree is clean at `0f9839f`; there is no new commit for the launcher.

The stage-2 tests currently exercise synthetic observations, not a composed owner dispatch. The landed owner code supports `run-worker`, and staging supports attaching a project after activation, so I found no concrete external prerequisite that would justify stopping.

The requested check completed with **16 failed, 29 passed, and 30 subtests passed**. Process census and staging startup failures trace to `ps` being denied with `Operation not permitted`. Four focused stage-2 canary, gate, and seeded-fault tests passed, but they do not verify dispatch. No worker kill, recovery, or stage-2 event evidence was produced.