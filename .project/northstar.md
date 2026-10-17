# Northstar: PROCLIFE — Otto process scopes

Every Otto process launch has an owner-held private-group scope. Cleanup records intent before launch or signal, stops the anchored group with TERM then KILL, and reports `settled` only when current evidence supports that result. Missing evidence remains unresolved across restart and holds only the affected capacity lease. No ancestry, tag, or bare PID can authorize a signal.

Preserve landed KILLFENCE and ORPHANWORKER behavior, never retry an unknown native worker turn, and remove only the per-descendant/tag machinery whose callers have migrated. Follow `.project/tasklist.md`; stage/ps/sandbox-dependent proof runs at the external gate.
