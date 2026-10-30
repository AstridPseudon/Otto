**Recommend hardening the thin path once and keeping it as the control system: 24 engineer-days, with a 30-day planning envelope.** This is a credible route to all 13 requirements at one-owner scale. The 8–12-day option buys a useful pilot with material gaps. A literal 14-day, complete end state is not supported by the evidence.

There is one decisive condition: **prove that every paid turn—including wakes, resumes and scheduled supervision—can obey an enforceable budget and capacity boundary.** The supplied platform primitives do not establish that. A larger harness does not automatically solve it.

The comparison also needs correcting: **137 days includes 29 days of Windows product work.** The system-only baseline is 108 days. My recommendation is 22% of that; retaining the same Windows deliverable makes it **53 days, or 59 with contingency**, conservatively retaining C’s entire estimate. Product work has not disappeared. [Effort breakdown](/home/user/repo/astrid-install/retro/09-otto-breakdown.md:12)

I rank the options as **completed destinations**:

| Rank | Option | Engineer-days | Main risk / loss | Cost later |
|---:|---|---:|---|---|
| **1** | **Permanent thin path: strengthened Option 1** | **24; envelope 30** | One active control writer; interrupted or ambiguous operations can require exceptional reconciliation. No seamless failover or hardened Mac fleet. | Full custody and distributed authority remain substantial work. Use **D+G’s 42 days as a budgeting reference**, then re-estimate for this architecture. |
| **2** | **Option 2: Otto-lite** | **35–45** | Same platform uncertainties; extra service and library integration may add little initial value. Carries the same strategic departure from Otto. | Similar custody/fencing work remains. Its extra initial effort pays back only if it demonstrably improves operations. |
| **3** | **Full plan** | **137**, including C29 | Broadest coverage; highest integration and migration exposure. Benefits arrive late. | Includes the specified full guarantees; platform feasibility still needs proving. |
| **4** | **Option 1 as written** | **8–12** | Strong first tranche, incomplete destination. Several claimed guarantees are only conventions or markers. | Approximately **12–22 additional days** to reach the recommended scope. |
| **5** | **Option 3: Otto-minimum** | **60–70 quoted** | Retains Otto’s coupling while leaving cloud/git incomplete and important control work unspecified. | **G’s 24 days**, plus omitted gateway, worker and qualification work. The initial estimate also needs a reconciled task breakdown. |

Option 3’s named untrimmed streams—A14+B18+F22—total 54 days. Its 60–70 estimate does not identify whether C or additional repairs are included. I would not use it as a comparable quote yet.

**Coverage below is for completed, qualified implementations.** F = full; P = partial or essential work unspecified; N = absent. “F*” depends on the paid-turn boundary proof. Option 2 earns its claimed coverage only by including the concrete obligations in this table.

| End-state point and what completion requires | Recommended | O1 | O2 | O3 | Full |
|---|:---:|:---:|:---:|:---:|:---:|
| **1. Mandate:** revisioned outcome, user-path acceptance, scope/effects, budget, reserved decisions; changes applied to affected work | F | P | F | P | F |
| **2. Managers dispatch:** explicit manager intent; events wake the responsible manager | F | F | F | F | F |
| **3. Exits:** declarations checked against evidence; self-nudge, then supervisor; observation first | F | F | F | F | F |
| **4. Liveness:** independently scheduled detection of missing starts, dead sessions and overdue waits; unavailable evidence stays unknown | F | P | F | P | F |
| **5. Receipts:** launch/check/land/publish tools record intent and outcome, identities and hashes; views derive from them | F | P | F | F | F |
| **6. Launch boundary:** all roles and paid reactivations; model, budget and capacity enforced | F* | P | F* | P | F* |
| **7. Messages:** durable threads, wake, reply, resolution, assignment generation and authenticated decisions | F | P | F | P | F |
| **8. Supervisor:** cheap hourly sweep; direct nudges; only exceptions reach orchestrator | F | F | F | F | F |
| **9. Workers:** shell/check, ask, appropriate allowance, resume with retained log | F | P | F | P | F |
| **10. Verification:** separate acceptance states, sampled claims, batch integration, exact-candidate qualification, review stopping rule | F | P | F | P | F |
| **11. Instructions:** small core plus judgement guidance; incident replay and setup canary | F | P | F | P | F |
| **12. Measurement:** completion time, owner intervention, stalls, false alarms, rework and supervision cost | F | P | F | P | F |
| **13. Cloud/git:** authoritative durable records and demonstrated fresh-cloud recovery | F | P | F | N | F |

The main corrections to Option 1 are substantive: dispatcher-written markers do not establish receipts from every tool; message files plus wake-up do not authenticate decisions; POLICY plus role guides do not establish incident replay; using cloud sessions and git does not demonstrate recovery.

These gaps are visible in the current scripts. Managers launch directly through [keepalive.sh](/home/user/repo/astrid-install/tools/keepalive.sh:5), while [recover.sh](/home/user/repo/astrid-install/tools/recover.sh:5) clears launch markers to restart missing workers. Both need replacing to establish one launch boundary and avoid blindly repeating uncertain work.

The recommended scope is **one owner, several managers, multiple repositories, one active credential-holding broker, and a bounded worker pool**. Cloud sessions remain the agent runtime. Git holds authoritative control records; local state is rebuildable. The broker executes manager requests and supplies deterministic monitoring. It must run independently of the orchestrator’s conversational container.

Keep existing scripts where useful, introducing a small structured module for shared records and transitions. Avoid a line-count target. Reuse Otto’s tests, contracts and isolated algorithms first: its landing service requires admission, assessment, completion and sealed-result interfaces, so it is not a free library extraction. [Landing dependencies](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/otto-restored/otto/src/herzchen/fleet/landing.py:62)

**In scope:** all 13 points, authenticated reserved decisions, safe handling of uncertain effects, cloud recovery, real qualification and measured operation.

**Excluded:** carrying Otto’s codebase forward, transparent controller failover, distributed writers, comprehensive local process custody, the hardened Mac fleet, generic policy packs and automatic publication. An owner-authorized publication still runs through a receipt-producing tool. Exceptional recovery can pause until uncertainty is resolved; frequent pauses would invalidate the value proposition.

| Task | Concrete completion condition | Days | Difficulty |
|---|---|---:|---:|
| **1. Prove the platform contract and freeze the mandate** | Inventory every paid entry point; demonstrate bounded usage, protected credentials, owner authentication and independent scheduling. Include native wakes/subscriptions. Record scope, reserved decisions and acceptance. | 3 | 7 |
| **2. Establish one durable writer** | Immutable operation IDs, authoritative git append, replayable projections and retained unknowns. Demonstrate restart without releasing reservations or recreating uncertain operations. | 3 | 7 |
| **3. Enforce the common launch boundary** | Every role/start/resume/wake checks current authority, model, budget and capacity. Reject bypasses. Reserve before invocation; reconcile actual usage afterward. | 3 | 8 |
| **4. Instrument tools and complete workers** | Launch/check/integrate/publish wrappers produce identity-bound receipts. Workers can diagnose, ask and resume with logs. Status and handoffs rebuild from evidence. | 3 | 6 |
| **5. Complete messages and exits** | Durable outbox, reply/resolution, generation checks and wake acknowledgement. Stop checks observe first; repeated discrepancies escalate without loops. | 3 | 7 |
| **6. Add independent monitoring and supervision** | Monitor missing starts/deaths/deadlines without depending on the affected session. Cheap hourly sweep reads compact evidence; metrics distinguish natural incidents, drills and false alarms. | 3 | 6 |
| **7. Establish delivery acceptance** | Manager-selected batches; regression attribution; exact source/artifact qualification; three acceptance states; sampled claims; uncertainty-based review stopping. Prove runner access early. | 3 | 7 |
| **8. Qualify recovery and judge the controls** | Inject lost acknowledgements, duplicate wakes, manager death, stale generations and wrong candidates. Restore from a fresh cloud environment. Run the real canary and assess a week of operation. | 3 | 7 |
| **Total** | **24 planned; 6 days contingency** | **24** | |

The last task includes three engineer-days of work distributed around **at least seven calendar days of observation**. Product fixes and unavailable Windows runners can extend elapsed time. A clean replay suite alone does not qualify the operational result.

The following guarantees remain non-negotiable even with one owner:

| Guarantee | Cheapest adequate implementation |
|---|---|
| **Owner authority cannot be forged** | Verify an authenticated platform principal, or verify owner-signed decision records using a key unavailable to agents. Bind approval to mandate revision, operation and candidate. Git author names and `sender: owner` fields are insufficient. |
| **Budget and capacity are real limits** | One serialized reservation ledger plus an enforceable execution bound/provider quota. Include managers, reviewers, supervisors and wake-triggered turns. Retain uncertain charges and capacity until reconciled. |
| **Unknown effects are not blindly repeated** | Persist intent before invocation; retain the operation identity; use provider idempotency where available. Otherwise hold and reconcile. This sacrifices automatic recovery speed rather than silently risking another paid or irreversible action. |
| **There is one active authority** | Keep launch/control credentials out of worker shells. No automatic controller takeover: confirm the old authority is stopped or revoked before activating its replacement. A git push conflict alone does not fence external effects. |
| **Evidence describes the actual candidate** | Tools write protected receipts containing full base/candidate hashes, execution identity and retained logs. Qualification belongs to that candidate; changed candidates require new evidence. Accepted gaps remain gaps. |
| **Dead agents cannot hide indefinitely** | Independent deterministic monitoring, durable messages and observable overdue states. The supervisor handles exceptions; the orchestrator retains judgement and replacement responsibility without doing integration. |

The budget requirement is already explicit in the roadmap: a hard ceiling requires enforceable bounded usage. **Polling `get_session.cost`, checking a spend line, or interrupting after an overrun cannot supply that guarantee.** [Budget invariant](/home/user/repo/astrid-install/retro/evidence/otto-roadmap/astra-roadmap.md:129)

If Task 1 cannot prove this for native cloud wakes, route events through the broker and use a bounded execution adapter. If neither route is feasible, **point 6 remains partial and the 24-day complete-end-state claim fails**. Option 2 and the full plan face the same platform dependency.

I would change the recommendation on this evidence:

- **Otto continuity is itself an acceptance requirement.** Choose an Otto-backed path and budget the port; the recommended scope deliberately gives up that continuity.
- **Multiple independent authorities or unattended controller failover become necessary.** Add durable fencing and transfer machinery.
- **Paid or irreversible effects regularly become ambiguous.** Full custody and reconciliation earn their cost when exceptional holds become routine.
- **Wake latency or monitor reliability misses the review’s proposed operating targets:** failed starts within 10 minutes, unanswered questions within an hour, overdue waits within 30 minutes of the declared deadline.
- **The week shows continued status-chasing, recurring owner repair, excessive false alarms or high supervision cost.** Expand only the mechanisms implicated by those measurements.
- **Isolated Otto components demonstrably reduce implementation and qualification effort.** Reuse them after a bounded integration spike; source-code availability alone is insufficient.