## 1. Design, in implementation order

1. [landing.py:21](${TRANSFER_ROOT}/source/otto/src/herzchen/fleet/landing.py:21) → Give `LandingError` `code = "landing_refused"` and a `message` equal to its existing text. Add an explicit owner-only settlement fact to known safe failures, including the aborted rebase conflict at [landing.py:107](${TRANSFER_ROOT}/source/otto/src/herzchen/fleet/landing.py:107). Default that fact to **unknown**. A stable tool error code alone must never authorize continuation: `LandingError` also covers failures near line advancement.
2. [product_service.py:221](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/product_service.py:221) → When an owner-executed `worker-done` raises `LandingError`, retain its exact assignment, Due schedule, lab path, refusal text, and settlement fact in that Due’s existing evidence, using owner CAS. Return the exception to `ToolFacade`. `worker-check` reports the same code but creates no landing attempt. A failed evidence write leaves the attempt unknown.
3. [execution.py:839](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/execution.py:839) → Reuse the existing worker correction preparation path for rework. Require a terminal, captured native turn; a retained **settled** landing refusal; the same current assignment, session, task, and lab; and an unused continuation allowance. Prepare a distinct, deterministic continuation Due tied to the prior attempt. Recover that Due after interruption instead of creating another. A claimed or unknown effect is held. Use one continuation per refusal as the explicit bound.
4. [manager_journey_service.py:1125](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/manager_journey_service.py:1125) → At worker turn completion, inspect that retained refusal before ordinary result notification. Start the prepared continuation through the bounded owner route; notify the manager only after the final worker result. Keep the dispatch token and lab through refusal. Preserve the existing capture-gated lab removal at [product_service.py:355](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/product_service.py:355).
5. [claude_adapter.py:389](${TRANSFER_ROOT}/source/otto/src/otto/agents/claude_adapter.py:389) → Replace the blanket worker-resume veto with an exact worker rework gate. Keep `_used` single-use, the fresh owner authorization/readback before input at lines 429–439, and native session/cwd verification. Carry the retained landing log into the admitted prompt. Wire this branch through [contract.py:369](${TRANSFER_ROOT}/source/otto/src/herzchen/fleet/hosts/contract.py:369); adapt its launch call to the existing Claude transport so it does not start a second, differently authorized process. Keep both `run_turn` and `run_continuation`.

## 2. Failing test to write first

Add `test_conflicting_done_reworks_exact_worker` in `tests/test_reworkwire.py`. Its `rework_owner` fixture must compose the real owner, Due port, fleet, landing service, facade, gateway, capture, and disposable Git line/lab. Substitute only a scripted Claude process: turn one writes a conflicting file and calls `done`; turn two repairs it and calls `done`. `run()` drains owner work and records the stated observations without timed assertions.

```python
def test_conflicting_done_reworks_exact_worker(rework_owner):
    trace = rework_owner.run()
    first, second = trace["work_turns"]

    assert first["done_reply"] == {
        "ok": False,
        "error": "landing_refused",
        "detail": first["rebase_message"],
    }
    assert "rebase conflict" in first["rebase_message"]
    assert trace["after_first"]["line_head"] == trace["line_head_before"]
    assert trace["after_first"]["lab_exists"] is True

    assert len(trace["work_turns"]) == 2
    assert second["session_id"] == first["session_id"]
    assert second["cwd"] == first["cwd"] == trace["lab_path"]
    assert second["argv"][-2:] == ["--resume", first["session_id"]]
    assert first["rebase_message"] in second["admitted_prompt"]
    assert second["authorization"] != first["authorization"]
    assert second["done_reply"]["ok"] is True
    assert second["done_reply"]["result"]["landed"] is True

    assert trace["captured_second_write"] is True
    assert trace["lab_exists_after_capture"] is False
    assert trace["final_line_head"] == second["landed_commit"]
```

Follow it with focused cases where the scripted native stream ends **unknown** after the refusal, and where the continuation also conflicts. Assert one work turn for unknown and at most two for the bound; neither may allocate a fresh session.

## 3. Delete

Delete the blanket `role != "manager"` refusal at `claude_adapter.py:389`. Do not add a second attempt ledger or a fresh-session retry path. Replace the `run_turn` product-method patches in [test_host_contract.py:668](${TRANSFER_ROOT}/source/otto/tests/test_host_contract.py:668) and line 698 with fake process/stream inputs; those existing harness patches conflict with the program rule.

## 4. Plausible mistake

A new Due can accidentally become a new Claude session, or a saved refusal can be mistaken for proof that an otherwise unknown native attempt settled. The test checks `--resume`, session, lab cwd, fresh authorization, and the repaired line. The unknown case proves that a refusal record alone cannot trigger replay.

## 5. Existing expectation requiring a D19 decision

[evidence_status_owner_facade.py:148](${TRANSFER_ROOT}/source/otto/tests/test_evidence_status_owner_facade.py:148) currently expects `owner_unavailable` and a `LandingError:` prefix. Record a D19 decision to expect `landing_refused` and the unchanged refusal message, because the exception now has its own stable code. Other generic `owner_unavailable` assertions remain applicable.

## 6. Stale or incorrect row detail on `canon/main`

The cited `run_continuation` exists, has no product caller, and the adapter veto is present. Its claimed “retry bound” is **not** a product bound yet: [test_host_contract.py:686](${TRANSFER_ROOT}/source/otto/tests/test_host_contract.py:686) supplies a fake callback that denies a second call. The owner must define and retain the bound. Separately, [test_tools.py:184](${TRANSFER_ROOT}/source/otto/tests/test_tools.py:184) already disagrees with current facade behavior for a `RuntimeError` containing text; that pre-existing assertion should not be silently changed as part of REWORKWIRE. No tests were run.