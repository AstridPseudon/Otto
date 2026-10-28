## Design, in implementation order

1. **Write the failing journey test first** in `tests/test_codex_owner_journey.py`. Its fixture must use a disposable real owner, Store, git line, lab, and MCP facade. Only the Codex executable is a model stand-in. It must emit an initializer and verified work stream, call the real `task`, `check`, and `done` tools through the issued MCP grant, and retain a completed native command plus final answer. Do not patch `attach`, `materialize`, `_execution`, or landing methods.

2. [config.py:118](<${TRANSFER_ROOT}/source/otto/src/otto/hostctl/config.py:118>) → give the admitted Codex entry finite model and reasoning qualifications derived from the Codex host profile, and require an executable pin for launch. A registered client without a usable launcher may remain registered, but execution must fail closed.

3. [adapters.py:18](<${TRANSFER_ROOT}/source/otto/src/otto/hostctl/adapters.py:18>) → make one host-kind-selected composition and trusted-selection table. Add Codex composition using `HerzchenCodexAdapter`, owner-held context capture and the existing qualified Codex thread reader. Resolve settings from the **admitted host entry**; do not let a Codex project find the installation’s Claude settings. Use that same table for readiness and live selection.

4. [cli.py:458](<${TRANSFER_ROOT}/source/otto/src/otto/hostctl/cli.py:458>) and [cli.py:695](<${TRANSFER_ROOT}/source/otto/src/otto/hostctl/cli.py:695>) → qualify the manager’s actual adapter **before** `materialize`; use the shared host-kind composition for setup and admission reads. Replace the Claude-shaped dry-run assumptions at lines 755–778 with host-neutral composition evidence.

5. [serve.py:91](<${TRANSFER_ROOT}/source/otto/src/otto/hostctl/serve.py:91>) and [serve.py:448](<${TRANSFER_ROOT}/source/otto/src/otto/hostctl/serve.py:448>) → select from `session.host["kind"]`. For a Codex manager, grant only its managed IPC write root and paired caller socket/observer. For a Codex worker, use the exact Due-resolved lab as worktree and source, no extra write roots or caller socket, and pass the exact token-bound `worker_mcp` already obtained by [serve.py:463–550](<${TRANSFER_ROOT}/source/otto/src/otto/hostctl/serve.py:463>). Keep those owner checks on both paths.

6. [serve.py:395](<${TRANSFER_ROOT}/source/otto/src/otto/hostctl/serve.py:395>) and [product_service.py:1302](<${TRANSFER_ROOT}/source/otto/src/otto/hostctl/product_service.py:1302>) → project the adopted role’s `adapter` into the generated run view and install the live trusted selection on `ManagerJourneyService`. Its compose callback must return through `HostOwnerService._execution`, preserving Due, lab, and grant checks; [manager_journey_service.py:220](<${TRANSFER_ROOT}/source/otto/src/otto/portfolio/manager_journey_service.py:220>) otherwise takes the selection’s compose path.

7. [herzchen_adapter.py:127](<${TRANSFER_ROOT}/source/otto/src/otto/agents/herzchen_adapter.py:127>), [herzchen_adapter.py:179](<${TRANSFER_ROOT}/source/otto/src/otto/agents/herzchen_adapter.py:179>), and [herzchen_adapter.py:475](<${TRANSFER_ROOT}/source/otto/src/otto/agents/herzchen_adapter.py:475>) → retain the validated sole-server worker grant across owner binding and pass it as `mcp` to **both** real and model-stand-in `CodexCliBinding` constructors for the authorized work turn. The inert initializer gets no grant. The binding and Codex host already carry `mcp` into the launch plan and token environment ([host.py:504](<${TRANSFER_ROOT}/source/otto/src/herzchen/adapters/host.py:504>), [codex.py:127](<${TRANSFER_ROOT}/source/otto/src/herzchen/fleet/hosts/codex.py:127>)).

8. [product_service.py:304](<${TRANSFER_ROOT}/source/otto/src/otto/hostctl/product_service.py:304>) → let the cleanup gate recognize a Codex worker’s exact, verified captured result even when its output has `commands` rather than Claude `artifacts`. Require matching Due, assignment, generation, result ref and digest, and a retained `captured_artifacts` list; an empty list is valid when Codex captured no command stdout. Cleanup still follows capture and the landed marker. Codex’s native verifier is already the owner runtime default ([owner_runtime.py:601](<${TRANSFER_ROOT}/source/otto/src/otto/agents/owner_runtime.py:601>)); keep its bounded stdout capture and verified final answer.

## Failing test to write first

`tests/test_codex_owner_journey.py::test_codex_worker_uses_owner_grant_lands_and_reaps_lab`. The new `cold_codex_owner` fixture supplies the real owner journey described in step 1; `start()` activates the Codex project and dispatches one worker through the owner. The fake executable records its argv/environment and tool replies from its actual MCP calls.

```python
def test_codex_worker_uses_owner_grant_lands_and_reaps_lab(cold_codex_owner):
    with cold_codex_owner() as journey:
        base = journey.line_head()
        result = journey.start()  # Fails in Claude composition on canon/main.
        due = journey.worker_due()
        argv = journey.worker_argv
        replies = journey.tool_replies

        assert result["outcome"] == "succeeded", result
        assert [call["name"] for call in journey.tool_calls] == [
            "task", "check", "done"
        ]
        assert replies["task"]["ok"] is True
        assert replies["check"]["feedback"] is True
        assert replies["check"]["accepted"] is False
        assert replies["done"]["submitted"] is True
        assert replies["done"]["accepted"] is False
        assert replies["done"]["result"]["landed"] is True

        assert ("-C", str(journey.lab)) in tuple(zip(argv, argv[1:]))
        assert ("-s", "workspace-write") in tuple(zip(argv, argv[1:]))
        assert "--add-dir" not in argv
        assert journey.worker_env["OTTO_WORKER_TOKEN"] == journey.worker_token
        assert all(journey.worker_token not in arg for arg in argv)
        assert (journey.line / "answer.txt").read_text() == "Codex answer\n"
        assert journey.line_head() != base
        assert not (journey.manager_workspace / "answer.txt").exists()

        assert due["completion_state"] == "succeeded"
        capture = due["host_evidence"]
        assert capture["captured_result_summary"]["verification"][
            "context_digest_verified"
        ] is True
        assert capture["captured_artifacts"]
        assert not journey.lab.exists()
```

The fake stream checks the requested Codex fence and grant. SKEL and MANY also need cold runs with the real Codex executable to prove an outside-lab write is denied by its native sandbox; a fake executable cannot prove native enforcement.

## Delete

Delete the Claude-only default wrapper at [serve.py:448–461](<${TRANSFER_ROOT}/source/otto/src/otto/hostctl/serve.py:448>) and the duplicate Claude-only manager composition at [cli.py:695–702](<${TRANSFER_ROOT}/source/otto/src/otto/hostctl/cli.py:695>) as they are replaced by the shared host-kind composer. Do not add a second Codex owner or landing path.

## Mistake, D19, and stale row details

The plausible mistake is switching the adapter while dropping `worker_mcp` or composing against the project workspace. The test catches the former through real tool replies and token/argv checks; it catches the latter through `-C`, write-root, and landed-file assertions. The cold Codex runs catch actual outside-lab writes.

**Existing assertions to change: none identified; no D19 decision is needed for this design.** In particular, [test_fleet_custody.py:351](<${TRANSFER_ROOT}/source/otto/tests/test_fleet_custody.py:351>) correctly expects `done` to retain the lab *until* native result capture. Add new assertions for cleanup after capture; preserve that expectation.

The row misses three current blockers: activation checks adapter **membership**, so a registered Codex manager can reach materialization before Claude-only setup fails ([cli.py:484–497](<${TRANSFER_ROOT}/source/otto/src/otto/hostctl/cli.py:484>)); the generated run view drops adopted adapter names; and the cleanup predicate requires Claude-shaped artifacts. Thus [portfolio.md:58–63](<${TRANSFER_ROOT}/source/otto/docs/portfolio.md:58>) is stale about Codex activation refusing before materialization. “Nothing in `hostctl` selects Codex” remains accurate; Codex binding, fence, grant rendering, and native result verification already exist outside `hostctl`. No files were changed and no tests were run.