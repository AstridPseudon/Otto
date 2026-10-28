## 1. Design, in implementation order

1. `src/otto/hostctl/product_service.py:355` → Make `settle_landed_worker` the single exact-Due removal path. Keep the captured-result check and marker/line checks. Return `cleanup_pending` plus a concrete `cleanup_error` for `kept-error`, missing proof, or a lab that still exists. Retain each schedule’s latest cleanup result in the live registry; clear it only after removal succeeds. Do not treat absence from `fleet.names()` alone as success: the landed marker and lab ref may still need cleanup.
2. `src/otto/hostctl/product_service.py:388` → Replace the duplicated startup removal body with a bounded retry over captured worker Dues that calls `settle_landed_worker`. Use it at startup and at the next live owner cleanup opportunity. An uncaptured Due must never authorize removal.
3. `src/otto/hostctl/product_service.py:49` and `src/otto/hostctl/project_service.py:91,478` → Retry after owner-file custody is acquired, then from the existing serialized owner poll. Publish the retained pending schedules and errors in owner status; refresh that projection after success.
4. `src/otto/agents/owner_runtime.py:1145` → Preserve the callback’s error/reason in the acceptance response, as exceptions already are. Give completed worker recovery an exact captured-evidence cleanup call that performs no publication or acceptance.
5. `src/otto/portfolio/execution.py:1401,1447,1475` → Retain the acceptance response in the first recovery result. On a completed worker’s explicit recovery, retry cleanup only; keep the occurrence’s successful completion and return the current cleanup state. Never enter provider, check, acceptance, or completion again.

## 2. First failing test

Add `test_live_owner_retries_captured_lab_after_real_unlink_failure` to `tests/test_fleet_custody.py`. This uses the real `LabFleet` removal path; the injected failure is at `shutil.rmtree`, not a patched product method. The proposed `landed_cleanup_status` and `retry_captured_landed` are the registry API from step 2.

```python
def test_live_owner_retries_captured_lab_after_real_unlink_failure(tmp_path, monkeypatch):
    import copy
    import hashlib
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path
    from types import SimpleNamespace

    from herzchen.fleet.labs import LabFleet
    from otto.hostctl.product_service import OwnerFleetRegistry
    from test_landing import _project, _run

    root = tmp_path / "project"
    root.mkdir()
    line, _, _ = _project(root)

    def checkpoint(worktree, paths, *, message):
        _run(Path(worktree), "add", "--", *paths)
        _run(Path(worktree), "-c", "user.name=LAB test",
             "-c", "user.email=lab@test.invalid", "commit", "-m", message)

    branch_key = hashlib.sha256(b"main").hexdigest()[:20]
    labs_root = line.parent / (line.name + ".otto-labs") / branch_key
    fleet = LabFleet(line, labs_root, checkpoint=checkpoint, shared_dirs=())
    lab = fleet.create("task-lab", base="refs/heads/main")
    (lab.path / "answer.txt").write_text("captured\n")
    fleet.checkpoint(str(lab.path), ["answer.txt"], message="worker output")
    commit = lab.head()
    _run(line, "fetch", str(lab.path), "HEAD")
    _run(line, "merge", "--ff-only", "FETCH_HEAD")
    fleet.mark_landed("task-lab", commit, "refs/heads/main")
    other = fleet.create("unsettled-lab", base="refs/heads/main")

    task_ref = {"authority": "fixture", "kind": "work.task",
                "id": "task-lab", "revision": "task-r1"}
    assignment_ref = {"authority": "fixture", "kind": "wrk.assignment",
                      "id": "assignment-r1", "revision": "assign-r1"}
    published = {"result_ref": "result-r1", "result_digest": "digest-r1"}
    key = "worker-request-r1"
    due = {
        "version": 1, "role": "worker", "schedule_id": "schedule-r1",
        "assignment_ref": assignment_ref, "generation": 1,
        "target": {"task_ref": task_ref},
        "host_evidence": {
            "gateway_attempt": {
                "state": "result", "logical_request_key": key,
                "result": {
                    "outcome": "succeeded", "logical_request_key": key,
                    "task_bound_evidence": {
                        "task_ref": task_ref, "assignment_ref": assignment_ref,
                        "generation": 1, "result_digest": "digest-r1",
                        "operation_result": {
                            "result_ref": "result-r1",
                            "output": {"artifacts": [{"name": "answer.txt"}]}}}}},
            "captured_artifacts": [{"ref": "artifact-r1"}],
            "captured_result_summary": {
                **published, "logical_request_key": key,
                "assignment_ref": assignment_ref, "generation": 1,
                "verification": {"context_digest_verified": True}}}}
    captured_before = copy.deepcopy(due["host_evidence"])

    class DuePort:
        def read_due(self, schedule_id):
            assert schedule_id == "schedule-r1"
            return due

        def list_due(self):
            return [due]

    task = SimpleNamespace(payload={
        "metadata_namespaces": {"otto.plan": {"repo": "repo-a", "branch": "main"}}})
    owner = SimpleNamespace(graph=SimpleNamespace(
        reader=SimpleNamespace(get_identity=lambda ref: task)))
    with tempfile.TemporaryDirectory(prefix="labr-") as home:
        (Path(home) / "run").mkdir()
        registry = OwnerFleetRegistry(
            owner, {"repositories": {"repo-a": str(line)}}, home, object(),
            checkpoint=checkpoint, due_port=DuePort(),
            landing_factory=lambda **kwargs: object())
        try:
            real_rmtree = shutil.rmtree

            def inaccessible(path, *args, **kwargs):
                if Path(path) == lab.path:
                    raise PermissionError("lab removal denied")
                return real_rmtree(path, *args, **kwargs)

            with monkeypatch.context() as failure:
                failure.setattr(shutil, "rmtree", inaccessible)
                first = registry.settle_landed_worker(
                    task_ref=task_ref, assignment_ref=assignment_ref,
                    generation=1, schedule_id="schedule-r1", published=published)

            assert first["cleanup_pending"] is True
            assert "lab removal denied" in first["cleanup_error"]
            assert lab.path.is_dir()
            assert registry.landed_cleanup_status()["pending"] is True

            retried = registry.retry_captured_landed()
            assert retried["provider_called"] is False
            assert not lab.path.exists()
            assert other.path.is_dir()
            assert registry.landed_cleanup_status()["pending"] is False
            assert due["host_evidence"] == captured_before
        finally:
            registry.close()
```

Add a companion execution test using the real owner fixture to compare provider calls and check, acceptance, and completion event counts before and after completed-occurrence recovery. The test above establishes the filesystem failure and live-registry retry.

## 3. Delete

Delete `OwnerFleetRegistry.sweep_landed_at_start`’s separate removal implementation (`product_service.py:388–425`) after routing startup through the shared retry. In-tree caller search found no production caller for generic orphan `LabFleet.sweep` (`src/herzchen/fleet/labs.py:432–435`) or `_sweep_one` (`:583–594`); delete those and their four sweep-only tests. Keep `sweep_landed`: production and capture-order tests call it.

## 4. Plausible mistake

A worker may propagate `cleanup_pending` from `owner_runtime.py` but still discard it at `execution.py:1447`, or retry by reaccepting the result. The first test catches lost error/status and failure to retry in the same registry; the companion test catches any increase in provider, check, acceptance, or completion counts.

## 5. Existing expectations and D19

A written D19 decision is needed to replace `test_owner_start_retries_only_captured_landed_lab_after_remove_failure`’s second-registry expectation (`tests/test_fleet_custody.py:469–477`) with a same-owner retry expectation. Its `LabFleet.remove` patch (`:446–455`) also needs replacement under the program’s test rule. Renaming the startup-custody test (`:480–507`) and deleting the four generic-sweep tests (`tests/test_labs.py:351–452`) should be recorded in that decision. The existing accepted capture-order test can retain its expectations.

## 6. Row corrections

`owner_runtime.py:1145–1151` already returns pending for a callback failure; **`execution.py:1447` discards that response**. Restart retry also already exists at `product_service.py:49–53,388–425` and is tested. The missing behavior is visible pending/error state and retry by the live owner. No tests were run; this was read-only inspection of `canon/main`.