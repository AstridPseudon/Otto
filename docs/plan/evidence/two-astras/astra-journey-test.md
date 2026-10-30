> Astra (read-only review, 30 Oct). Links into `/tmp/...scratchpad` point at the clones used for the review; they are not in this repo.

**Add one complete journey to D3, using the installed Otto wheel and real omp processes with scripted model replies.** Keep the focused acceptance tests for failure cases; the journey proves that the pieces connect. This extends the agreed [B7 testing design][b7] and [three-review decision][testing], rather than adding another testing layer.

This is a read-only design. Runtime and size estimates below are targets, not measured results.

**1. Run one scenario, from installation to landed work.**

Use one small Python project, one manager, an implementation worker, and a `sense-checker` worker. The implementation worker also invokes `sense-checker` through omp’s native `task` tool. This exercises the same specialist role file at both ranks, as [B6.11 requires][acceptance].

| Run for real | Script or control |
|---|---|
| Wheel installation into a fresh virtualenv; installed `otto` executable | Initial project/spec fixture |
| `otto init`, `project new`, `run`, and agent CLI commands | Model replies, including tool calls |
| Pinned omp binary and matching `omp-rpc` client | Isolated, credential-free loopback provider |
| SQLite, checkouts, Git worktrees, commits, checks and landing | Otto’s schedule clock |
| Pack loading, instructions, native sub-agents and session persistence | Named barriers for observation and one crash |

Run from outside the source checkout, with no editable installation or source `PYTHONPATH`. Preconfigure fake model choices in the isolated omp profile; `otto init` must preserve them. Fresh Mac/Linux installation and service reboot qualification remain D1/D1b responsibilities, as [the plan already separates them][delivery].

The driver performs owner actions: create the project, submit the mandate, change the spec, advance test time and kill/restart. **Agents perform planning, dispatch, editing, submission and acceptance through actual tools.** The driver must never manufacture their database effects.

**2. Use ordinary Python response lists, with a small provider adapter.**

The upstream [loopback provider][provider] already emits OpenAI-compatible tool calls and SSE responses without authentication. Its existing behavior is only `read`, `write`, `echo_host` and `pong`; it needs an Otto-specific script. Adapt its small wire implementation into a Python test fixture, so CI does not require an upstream source checkout.

The [in-process mock model][mock] offers response lists, generators and handlers, but it does not itself exercise the installed omp executable. Use that scripting style behind HTTP here.

For example:

```python
from shlex import join

def call(step, tool, **args):
    return {"id": step, "tool": tool, "args": args}

def example_scripts(review_task_id, message_id):
    return {
        ("manager", "dispatch-review"): [
            call("spawn-review", "bash", command=join([
                "otto", "spawn", "sense-checker",
                "--task", review_task_id,
                "--operation-key", f"{message_id}/spawn-review",
            ])),
            {"text": "Review dispatched."},
        ],
        ("worker", "implement"): [
            call("write-code", "write",
                 path="greeting.py",
                 content='def greet(name):\n    return f"Hello, {name}"\n'),
            call("ask-helper", "task",
                 agent="sense-checker",
                 task="Check greeting.py against the assigned spec.",
                 solutionSpace="Read the implementation; report discrepancies."),
            {"text": "Implementation and helper check complete."},
        ],
        ("sense-helper", "check"): [
            call("read-code", "read", path="greeting.py"),
            {"text": "The implementation meets the initial requirement."},
        ],
    }
```

This is an excerpt; later worker steps handle the amended requirement, commit and submit. `--operation-key` is proposed CLI spelling for the already-required operation key; L0 must freeze it. The native `task` example uses omp’s [single-spawn schema][task-schema]; S0 must verify that schema against the selected configuration and pin.

Keep selection explicit:

- Assign distinct fake model IDs through ordinary omp model roles or supported overrides. Distinguish the supervised specialist from its helper using an override on the supervised task.
- Select the conversation script using model ID and the actual job/message identifier. Do not match whole prompt paragraphs.
- Give tool calls stable IDs. Advance only when the corresponding tool result appears in conversation history. Repeated requests return the same response.
- Handle the one interrupted/replayed turn explicitly. Reissued Otto commands retain their original operation keys.
- Fail immediately on an unknown route, missing tool, unexpected result or exhausted script. Never fall back to `pong`.

The provider returns instructions; it does not execute commands or edit the application database. omp executes its real `bash`, `write`, `read` and `task` tools. No host-tool wrapper is needed.

**3. Make each checkpoint an observable assertion.**

Use JSON output from ordinary status/task/inbox/schedule commands. L0/C2 should expose the required fields there if they are not yet specified; do not add a general SQL command.

| Checkpoint | Required observations |
|---|---|
| **Install and initialise** | Installed entry point works; one advisor and one orchestrator exist; their sessions are recorded; model choices survive init; default schedules are 60/180 minutes. |
| **Create project and manager** | Spec content round-trips through checkout. Orchestrator’s command creates exactly one active manager with the correct parent, project and pack. No manager appears before dispatch. |
| **Plan and dispatch** | Manager creates two tasks and starts their workers. Assignments record the initial spec revision. Status agrees with task detail and shows configured versus actual models. |
| **Specialist and native helper** | `sense-checker` has worker rank and its own task/session. Native helper events belong to the implementation worker and appear in status. Both recorded instruction hashes match the same role source file. |
| **Change spec during work** | Hold the implementation worker before its turn settles. Owner checks in revision two. Manager receives the durable notification and explicitly amends that running assignment. Its original snapshot remains identifiable; the new instructions and decision are recorded. Worker notification stays queued while the worker is busy. |
| **Crash and recover** | Original message remains unacknowledged at the crash barrier. Restart preserves identities, worktrees and current attempts. Replay produces one logical amendment and one worker notification. The worker subsequently receives the amendment and continues. |
| **Submit, accept, land** | Submission alone leaves the target unchanged and the code task unfinished. Hold landing before publication: acceptance must still not imply `done`. After release, the check-recorded commit equals the landed commit, the original target is its ancestor, and final program output satisfies revision two. |
| **Requested and scheduled advice** | Both round-trip through the same advisor session. Replies correlate to the correct requests. The orchestrator records a disposition; the later consultation includes earlier advice and its disposition. |
| **Finish** | Status matches task, message, schedule and Git observations; no unresolved required work remains; all scripted obligations were exercised; no test-owned processes survive teardown. |

The spec already requires these [assignment, message, advice and landing contracts][contracts]. Use a check command that records `git rev-parse HEAD` before running the project’s real tests, so “checked commit” has an independent witness.

At quiescent checkpoints, compare logical database contents before and after repeated `otto status` calls using a read-only SQLite CLI connection. Do not hash the database file: WAL and checkpoint behavior make that a poor oracle. Keep the stronger attempted-write detection in the focused B6.9 test.

The journey does **not** replace the focused cases for stale saves, cancellation races, failed checks, moving targets, paused schedules, idle escalation or incorrect recovery identity. Those remain in the [agreed acceptance matrix][acceptance].

**4. Synchronise on events; keep elapsed-time limits separate.**

`prompt` admission, `prompt_result` and `session_settled` mean different things. The Python client explicitly documents that a prompt can yield while background work continues; its [`wait_for_settled()` implementation][settle-client] handles the state/event race. The [client test][settle-test] demonstrates that distinction.

For this journey:

- **`otto run` owns the RPC clients.** Subscribe before prompting, including `subagent_*` events. Do not have the test open competing clients for the same seats.
- Relay correlated lifecycle notifications into the existing D3 test-control channel. Wait for the relevant prompt outcome and settled state, then read the observable result. An old settle notification must not satisfy a new turn’s wait.
- Treat error or abort as failure unless it is the deliberately interrupted turn. Settlement alone is not success.
- Use a shared test clock for Otto’s schedule and activity calculations. Advancing it wakes the actual scheduler; it does not directly create schedule messages.
- After requested advice completes, advance to just past 180 minutes. Assert one coalesced check-in and one scheduled consultation, with future due dates. Do not change the OS or omp clock.
- Use real monotonic deadlines for readiness, barriers and total execution. No fixed sleeps.

Target **60–120 seconds for the journey** on a warm CI machine, within the existing **3–5 minute serial job**. Allow a diagnostic hard timeout, initially 180 seconds for this scenario; measure before committing to the target.

Use isolated directories, loopback port zero, pinned artifacts, no inherited credentials, deterministic fixture files and no cross-agent global response counter. On failure preserve status, relevant rows, Git state, provider requests, supervisor logs and omp stderr. Hangs, unexpected skips and leaked processes fail, as [already agreed][testing].

**5. Kill once, after the spec-change effect but before acknowledgement.**

Choose the existing R3 boundary: **the manager’s amendment and outgoing notification are committed, but the incoming spec-change message has not been acknowledged**. This is one of the [named crash cases][crashes].

The test waits for that hook, records message/session/attempt IDs and worktree paths, then sends `SIGKILL` to `otto run`. Disarm the one-shot hook and restart against the same state.

Assert:

1. The incoming message survives and is redelivered with the same ID.
2. The replayed commands use the same operation keys; no duplicate amendment, notification, task or worker appears.
3. Recovery uses `--resume <exact session file>` and verifies identity. **Do not use `open_session()`**, which may select or create another conversation; [B2 explicitly rules it out][runtime].
4. Worktrees and current attempts survive, and recovery supplies the interrupted-work context.
5. Old holders are resolved before replacements start. Do not silently clean up surviving children in the driver before recovery gets a chance to handle them.
6. Acknowledgement occurs only after the successful handling/reply condition.

Keep the Git-fast-forward-before-`done` crash in D2’s focused test. That boundary is [already D2’s responsibility][delivery]; adding another full journey for it buys little.

The replay guarantee covers Otto state. Fixture file writes should be repeatable, but this test must not claim exactly-once arbitrary shell execution.

**6. Use the same checkpoints for the live variant.**

Replace the loopback model configuration with the owner’s real omp profile and model choices. Remove scripted replies. Keep the project, owner actions, observable assertions and named restart barrier.

Allow different task decompositions, tool sequences and wording. Require the actual outcomes: specialist participation, useful helper work, explicit spec reconciliation, correlated advice, checked landing and continuity after restart. Use short configured schedule intervals with the real clock.

Run live checks at the agreed gates:

- S0 proves the substrate; the full application does not exist yet.
- VS runs the available spawn/ask/answer/resume spine.
- D5 runs the complete journey; D6 repeats it after fixes.
- Repeat affected live checks after pin or login changes. No routine nightly model run is necessary. [Agreed frequency][testing].

**Yes, this can be the pilot’s backbone**, but the tiny greeting fixture is not the entire pilot. Substitute the owner’s real project and retain evidence per checkpoint. Add the pilot’s two concurrent checkouts, alternative-pack project and over-engineering helper; exercise idle enforcement in its second half. These requirements remain in [B6 and the pilot plan][pilot]. Attach belongs to its follow-up project.

**7. Keep the implementation around 600 lines.**

Proposed layout in the new tool repository:

```text
tests/
  conftest.py                  # ~80 lines of shared process/barrier fixtures
  omp/
    scripted_provider.py      # ~180 lines: HTTP/SSE, routing, replay
    journey_script.py         # ~120 lines: explicit role responses
    test_journey.py           # ~180 lines: owner actions and assertions
  fixtures/journey/           # ~40 lines: spec, program skeleton, check
```

Allow roughly **500–700 test lines**, plus the small clock/crash seams already assigned to D3’s infrastructure. Keep the live switch in the same driver. The existing fake-RPC acceptance fixture stays separate and is reused.

Do not build a scenario language, agent simulator, second RPC transport, generic workflow engine, SQL mutation helper, record/replay platform, LLM judge or model/provider matrix. A few response constructors and named barriers are sufficient.

**8. Keep ownership in D3; make the journey explicit in its completion criteria.**

D3 already owns the fake RPC fixture, loopback provider, crash hooks and integration coverage for **three days**. Keep that estimate initially, allocating approximately:

| D3 work | Days |
|---|---:|
| Shared process cleanup, clock and crash barriers | 1 |
| Provider adapter and complete journey | 1 |
| Coverage integration, CI and diagnostics | 1 |

This assumes C3, C4, C5, R1, R3, R4 and D2 implement and test their own contracts. D3 cannot absorb their implementation work.

Add this completion criterion to [D3][delivery]:

> The installed Otto wheel and pinned omp binary complete one credential-free journey covering init, project import, manager-led dispatch, specialist worker and native helper, mid-work spec amendment, delivery crash/replay, submission and checked landing, both advisor paths, and truthful status at every checkpoint.

Start the fixtures after S0/L0, in the [existing skeleton window][schedule]. Finish after C1–C6, R1–R6, P1–P5 and D1/D2 are integrated; D1b remains a separate pre-pilot qualification. L0 must freeze operation-key spelling, observable JSON fields and the barrier/clock seam.

Tomorrow’s first implementation should prove just **installed omp → loopback tool call → installed `otto status`**, followed by one native helper call. Then extend that same test into the journey above.

[b7]: /home/user/repo/astrid-install/retro/13-spec.md:271
[testing]: /home/user/repo/astrid-install/retro/16-three-reviews.md:69
[acceptance]: /home/user/repo/astrid-install/retro/13-spec.md:245
[delivery]: /home/user/repo/astrid-install/retro/14-plan.md:141
[contracts]: /home/user/repo/astrid-install/retro/13-spec.md:105
[crashes]: /home/user/repo/astrid-install/retro/16-three-reviews.md:79
[runtime]: /home/user/repo/astrid-install/retro/13-spec.md:179
[pilot]: /home/user/repo/astrid-install/retro/13-spec.md:261
[schedule]: /home/user/repo/astrid-install/retro/14-plan.md:173
[provider]: /tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/two-astras/oh-my-pi/packages/coding-agent/test/rpc-wire/fake-openai-server.ts:43
[mock]: /tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/two-astras/oh-my-pi/packages/ai/src/providers/mock.ts:7
[task-schema]: /tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/two-astras/oh-my-pi/packages/coding-agent/src/task/types.ts:97
[settle-client]: /tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/two-astras/oh-my-pi/sdk/python/omp-rpc/src/omp_rpc/client.py:1177
[settle-test]: /tmp/claude-0/-home-user/61c0e870-3601-52f0-903b-3607ce5e0548/scratchpad/two-astras/oh-my-pi/sdk/python/omp-rpc/tests/test_client.py:1528