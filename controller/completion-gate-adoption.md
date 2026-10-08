# Completion gate read adoption

This patch adds `manager_ctl.py completion-gate --task PA01`. It forwards a read
of the existing `ResponsibilityAssignments.completion_blockers` predicate through
`otto.portfolio.completion_gate`. It creates no assessment or completion record.

The operational controller remains the existing outside-Git file:
`/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/otto-project-advisor-20260930/work/canonical-bootstrap/controller/launch_manager_once.py`.
The diff baseline SHA256 is `a33eb72c268ad9fb71baaf4dbc3cca102118d526e145352cbac3a6eaeac6f496`.
There is no runnable controller copy in this directory.

For adoption, stop the owner service gracefully and confirm custody release.
Merge only this commit into the canonical current manager worktree, preserving
its later completion-command repair. Reconcile and apply this diff to the existing
operational controller. Install the matching client and runtime module, then
restart through the ordinary owner lifecycle. Do not hot-edit or replay a worker.

Start with `completion-gate --task PA01` and inspect `owner_gate_state`.
If required scopes exist, add the exact current candidate, accepted decision
refs, and retained evidence refs. Read evidence hashes are bare SHA256 values,
repeated in the same order as evidence refs. The read supplies the owner-bound
actor so DAT evidence verification uses its ordinary visibility rules.

`eligibility` is `blocked`, `unknown`, or `clear`; every response is provisional
and records no acceptance. Missing/unverified required evidence is unknown even
when blockers are empty. A clear predicate with no required scope does not prove
C01/C02 behavior. Use the adopted scope policy and criteria without inventing an
additional review invocation. Formal completion rechecks the predicate atomically.

PA01's historical rev-1 occurrence stays unknown. Its CLI exit 0, source changes,
and capture-parser fix do not produce native execution acceptance. Assess current
PA01 rev-2 source independently; C02 still needs actual introduction and same
conversation/recovery evidence. Do not change old refs to make them current.
