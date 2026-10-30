## Lens: Worker briefs and task runs

### Findings

1. **The sample supports “specific beats long,” not a reliable length-success relationship.** I read briefs and finals across more than 25 folders spanning UPD, COH, GATE, INS, ASTRA, reviews, and `-F` runs. The index lists 129 run-like folders, including 23 with `-F<number>` in the name and 42 review-named folders; 12 have both. Those are folder counts, not a rework rate: folders include reviews, proposals, retries, and tasks without finals. [run-folders-index.txt](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/retro/data/run-folders-index.txt)

   Brief size varied substantially: the `UPD-AR1-X1-review` brief is 897 bytes; `GATE-11` is 1,484; `INS-C1` is 4,412; and `GATE-13a` is 4,611. Short, bounded briefs worked when the acceptance test matched the task: GATE-11 specified a coherence check before Vite and a skewed-manifest failure test; its final reports that test passing. [GATE-11 brief and final](/home/user/repo/astrid-install/runs/GATE-11/brief.md) [UPD-AR1-X1-review brief and final](/home/user/repo/astrid-install/runs/UPD-AR1-X1-review/brief.md)

2. **A measurable “Done when” helped, but naming tests was not enough if they missed the real caller path.** GATE-11’s focused acceptance passed. COH-C11 specified the guard’s scope, exclusions, and regression cases; its final reports three tests passing in each repo. By contrast, the detailed COH-C3 brief required seven install legs and focused tests, but its reviewer found the real driver rejected a second install in the same evidence directory. The test suite passed because a fake installer bypassed that guard. UPD-F1d also had an extensive approved acceptance list and 714 App tests, yet review found three reachable problems in schema-incompatible authentication and draft-safe reload. [COH-C11 brief and final](/home/user/repo/astrid-install/runs/COH-C11/brief.md) [COH-C3-review final](/home/user/repo/astrid-install/runs/COH-C3-review/final.md) [UPD-F1d final and review](/home/user/repo/astrid-install/runs/UPD-F1d/final.md)

   **Inference:** the strongest apparent predictor of first-pass success was whether the acceptance criterion composed the actual user/caller path, not the brief’s word count or number of tests. These cases are illustrative, not a controlled comparison.

3. **Several rework cycles came from findings that were concrete and user-reachable.** COH-C3 review issued a specific FIX after reproducing the repeated-install failure. UPD-EL-X3-F2 review identified a Windows process probe occurring before C1 admission. UPD-F1d review identified three distinct user-facing problems. UPD-C1a records multiple Astra FIX rounds, with a later review requiring receipt revocation on additional validation-failure paths. [COH-C3-review final](/home/user/repo/astrid-install/runs/COH-C3-review/final.md) [UPD-EL-X3-F2-review final](/home/user/repo/astrid-install/runs/UPD-EL-X3-F2-review/final.md) [UPD-C1a-review brief and final](/home/user/repo/astrid-install/runs/UPD-C1a-review/brief.md)

   The run folders show repeat dispatches, but the total number of “tasks needing re-dispatch” cannot be accurately derived from folder names: an initial proposal-only run followed by an approved implementation dispatch was an intentional gate, not a failed attempt. The raw transcript confirms that proposal/approval pattern and that review rounds were later bounded after C2 had multiple Astra FIXes. [10-26 23:41; 10-26 23:42; 10-27 09:59–10:21] [main-full.txt](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/retro/data/main-full.txt)

4. **Review briefs were most useful when they constrained the reviewer to acceptance and reachable behavior.** The concise `UPD-AR1-X1-review` brief names the real public CLI retry path, the ownership fences, and the “LAND or FIX” result. The much longer `UPD-F1d-review` is also concrete: it enumerates the actual provider/AuthGate, chat draft, and timeline paths, then asks for reachable findings only. Both produced actionable decisions; X1 landed, while F1d surfaced three blockers. [UPD-AR1-X1-review brief and final](/home/user/repo/astrid-install/runs/UPD-AR1-X1-review/brief.md) [UPD-F1d-review brief and final](/home/user/repo/astrid-install/runs/UPD-F1d-review/brief.md)

5. **Worker finals were uneven; evidence often lived in separate files.** Good finals identify changed files, commands/results, limitations, and whether the work is ready for review. GATE-11 and COH-C11 do this. UPD-A2 summarizes the focused suite, hosted build, and direct journey, with exact outputs linked in `tests.txt`. Some indexed folders have no final (`GATE-13a`, `INS-C3`), and reviewer finals use a distinct `LAND`/`FIX` format. [GATE-11 final](/home/user/repo/astrid-install/runs/GATE-11/final.md) [COH-C11 final](/home/user/repo/astrid-install/runs/COH-C11/final.md) [UPD-A2 final](/home/user/repo/astrid-install/runs/UPD-A2/final.md)

### What worked

- **Acceptance criteria were reviewed before implementation when the task lacked them.** The operating process explicitly required a worker proposal and manager approval before code; the transcript records that sequence and the subsequent re-dispatch. [10-26 20:05; 10-26 23:41–23:42] [main-full.txt](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/retro/data/main-full.txt)
- **Strong briefs tied scope to paths and proof.** GATE-11 names the Dockerfile order and the skew failure; COH-C11 names protected files and the two violation forms; both finals report focused results.
- **Good finals separated local evidence from unrun qualification.** INS-C1 and UPD-A2 explicitly report platform/browser/CI checks as unrun rather than implying completion. [INS-C1 final](/home/user/repo/astrid-install/runs/INS-C1/final.md) [UPD-A2 final](/home/user/repo/astrid-install/runs/UPD-A2/final.md)
- **Bounded review findings made fixes dispatchable.** UPD-EL-X3-F2’s FIX names the caller, risky operation, and correction; UPD-F1d review breaks its three findings into files and measurable outcomes.

### What failed / friction

- **Long briefs still accumulated superseded instructions.** Some run briefs append proposal-only rules, approvals, later re-dispatch instructions, and review fixes in one file. UPD-EL-X3 includes multiple dependency and re-dispatch updates. This preserves history but makes the current operative instruction harder to scan. [UPD-EL-X3 brief](/home/user/repo/astrid-install/runs/UPD-EL-X3/brief.md)
- **Tests sometimes proved a mock or component but not the composed workflow.** COH-C3’s fake installer missed a repeated-attempt failure; UPD-A2 required a manager re-dispatch after a browser trace showed the reload notice was unclickable over the editor. [COH-C3-review final](/home/user/repo/astrid-install/runs/COH-C3-review/final.md) [UPD-A2 brief and final](/home/user/repo/astrid-install/runs/UPD-A2/brief.md)
- **The final artifact could be absent or too terse to serve as the handoff.** The index shows empty/missing finals for some runs even where extensive logs exist. The manager then must reconstruct outcome from logs, or the run cannot be handed off cleanly. [run-folders-index.txt](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/retro/data/run-folders-index.txt)
- **First-pass/rework counts are ambiguous.** `-F` folders mix corrective work with naming conventions, and some “second runs” are planned approval gates. A raw folder count would overstate failure. [10-26 23:41–23:42] [main-full.txt](/tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/retro/data/main-full.txt)

### Candidate principles

- When a task changes a user workflow, require a test through its real caller and one representative end-to-end path, because unit/fake coverage missed composed failures in COH-C3 and UPD-A2.
- When acceptance is not approved, keep the run proposal-only; approve measurable criteria and test evidence before authorizing implementation, because the transcript records that gate being used to define scope before dispatch. [10-26 23:41–23:42]
- When reviewing, provide the approved Done when and the real path, and ask for reachable findings with bounded fixes, because X1’s concise review landed while F1d’s detailed review produced implementable blockers.
- When a fix is required, create a new numbered fix task linked to the originating review and preserve the old evidence, because UPD-C1a and UPD-EL-X3-F2 needed multiple revisions and review traceability.
- When reporting, state “written, not run” for unavailable environments and list skips/deselections, because successful local tests did not establish native OS, hosted CI, or production behavior in these runs.

### Structure implications

Make the run record hold one current brief version plus an append-only decision/revision history. Required fields: task ID/tier, repository and base SHA, owned paths, dependencies, scope, exclusions, approved Done when, test commands, evidence location, and run state (`proposal`, `approved`, `implementing`, `review`, `fix`, `landable`, `complete`). Link each FIX dispatch to the finding and round it addresses.

A manager review should ask: “Does the proof exercise the real caller, and does it cover the scenario composition named in Done when?” A reviewer brief should include the approved Done when, caller path, allowed finding threshold, and required verdict.

**Worker brief template**

```text
Task / repo+base / files:
Goal + exclusions:
Done when:
Tests to run:
Report: files, results/evidence, unrun checks.
```

**Worker result template**

```text
Status: ready / blocked
Changed:
Checks: command → result (full output in tests.txt)
Unrun / limits:
```

For review runs, replace `Status` with `LAND` or `FIX` and require each FIX to name the reachable impact and measurable correction.