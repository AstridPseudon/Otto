## 1. Design

1. `src/otto/hostctl/product_service.py:518` and `src/otto/hostctl/fleet_landing.py:122` → Resolve the active Due for the landing assignment. Pass its exact task ref, assignment ref, generation, schedule ID and logical request key through the trusted assessment context. Use the existing `wrk.result` candidate (`fleet_landing.py:285–298`) as the retained commit record.
2. `src/herzchen/fleet/landing.py:215` and `src/herzchen/fleet/labs.py:365` → Write a versioned `.landed/<name>` marker containing those occurrence pins, the candidate ref, commit, line ref and a lab incarnation ID. Create the ID with the lab. An identical marker write may retry; a different landing cannot overwrite it.
3. `src/herzchen/fleet/labs.py:301`, `:320`, `:432`, `:340` → Refuse create or resume while a landed marker remains; do not erase it. Exclude marked labs from ordinary orphan sweep, and refuse generic `remove` on a marked lab. Keep ordinary removal of unmarked labs.
4. `src/herzchen/fleet/labs.py:384` → Take the **exclusive lab lock before reading the marker**. Under that lock, check the marker and incarnation, invoke owner capture validation, verify candidate commit, line ancestry, lab HEAD, cleanliness and `refs/labs/<name>`, then unlink. Factor the removal body into a locked helper; do not reacquire the same lock.
5. `src/herzchen/fleet/labs.py:409` → Record a durable “deleting” phase after validation and before unlink. On retry, finish a partially removed directory only when the same marker, captured occurrence and retained ref still match. Delete the ref with its expected SHA, then remove the marker. Missing or ambiguous evidence keeps the lab.
6. `src/otto/hostctl/product_service.py:355` and `:388` → Route by the existing Due and task plan, but reread and compare the exact Due **inside** the fleet’s locked validation callback. Both immediate cleanup and startup must compare every marker pin, including candidate commit; neither may authorize by task name alone. Legacy two-line markers stay until exact evidence can be established.

## 2. Failing test to write first

Add `tests/test_fleet_custody.py::test_startup_retains_new_landing_until_its_due_is_captured`. The proposed `occurrence=` argument is part of the design, so this test is red on `canon/main`.

```python
def test_startup_retains_new_landing_until_its_due_is_captured(tmp_path):
    import threading
    from herzchen.fleet.labs import LabFleet
    from otto.hostctl.product_service import OwnerFleetRegistry
    from test_landing import _project, _run

    line, _, _ = _project(tmp_path)
    root = line.parent / (line.name + ".otto-labs") / hashlib.sha256(b"main").hexdigest()[:20]

    def checkpoint(worktree, paths, *, message):
        _run(Path(worktree), "add", "--", *paths)
        _run(Path(worktree), "-c", "user.name=LAND test",
             "-c", "user.email=land@test.invalid", "commit", "-m", message)

    fleet = LabFleet(line, root, checkpoint=checkpoint, shared_dirs=())
    candidates = {}
    dues = []
    race = [False]
    start_writer, b_landed = threading.Event(), threading.Event()

    def occurrence(label, generation):
        task = dict(authority="fixture", kind="work.task", id="task-lab",
                    revision="task-" + label)
        assignment = dict(authority="fixture", kind="wrk.assignment",
                          id="assignment-" + label, revision="assign-" + label)
        candidate = dict(authority="fixture", kind="wrk.result",
                         id="candidate-" + label, revision="rev-1")
        key, digest = "request-" + label, "digest-" + label
        pin = dict(task_ref=task, assignment_ref=assignment, generation=generation,
                   schedule_id="schedule-" + label, logical_request_key=key,
                   candidate_ref=candidate)
        bound = dict(task_ref=task, assignment_ref=assignment, generation=generation,
                     result_digest=digest, operation_result=dict(
                         result_ref="result-" + label,
                         output={"artifacts": [{"name": "work.txt"}]}))
        result = dict(outcome="succeeded", logical_request_key=key,
                      task_bound_evidence=bound)
        due = dict(role="worker", schedule_id=pin["schedule_id"],
                   assignment_ref=assignment, generation=generation,
                   target={"task_ref": task}, host_evidence=dict(
                       gateway_attempt=dict(state="result", logical_request_key=key,
                                            result=result),
                       captured_artifacts=[{"ref": "artifact-" + label}],
                       captured_result_summary=dict(
                           result_ref="result-" + label, result_digest=digest,
                           logical_request_key=key, assignment_ref=assignment,
                           generation=generation,
                           verification={"context_digest_verified": True})))
        return pin, due

    pin_a, due_a = occurrence("A", 1)
    pin_b, due_b = occurrence("B", 2)
    dues.append(due_a)
    task = SimpleNamespace(payload={"metadata_namespaces": {
        "otto.plan": {"repo": "repo-a", "branch": "main"}}})

    def read_identity(ref):
        return candidates[ref.id] if ref.kind == "wrk.result" else task

    def list_due():
        if race[0]:
            race[0] = False
            start_writer.set()       # Due A was read; sweep has no lab custody yet.
            b_landed.wait()          # Real writer lands B before custody is taken.
        return tuple(dues)

    registry = OwnerFleetRegistry.__new__(OwnerFleetRegistry)
    registry.owner = SimpleNamespace(graph=SimpleNamespace(
        reader=SimpleNamespace(get_identity=read_identity)))
    registry.config = {"repositories": {"repo-a": str(line)}}
    registry.due_port = SimpleNamespace(
        list_due=list_due,
        read_due=lambda schedule: next(d for d in dues if d["schedule_id"] == schedule))
    registry._pair_lock = threading.RLock()
    registry._pairs = {("repo-a", "main"): (fleet, None)}

    def land(lab, pin, label):
        with fleet.writing("task-lab"):
            (lab.path / "work.txt").write_text(label + "\n")
            checkpoint(lab.path, ["work.txt"], message="worker " + label)
        commit = lab.head()
        _run(line, "fetch", str(lab.path), "HEAD")
        _run(line, "merge", "--ff-only", "FETCH_HEAD")
        ref = pin["candidate_ref"]
        candidates[ref["id"]] = SimpleNamespace(ref=ref, payload=dict(
            assignment=pin["assignment_ref"], generation=pin["generation"],
            value=dict(task_ref=pin["task_ref"], assignment_ref=pin["assignment_ref"],
                       admitted_revision="admitted-" + label, lab_commit=commit,
                       repo_name="repo-a", line_ref="refs/heads/main",
                       lab_name="task-lab")))
        fleet.mark_landed("task-lab", commit, "refs/heads/main", occurrence=pin)
        return commit

    lab_a = fleet.create("task-lab", base="refs/heads/main")
    land(lab_a, pin_a, "A")
    assert any(x.action == "removed" for x in registry.sweep_landed_at_start())
    assert not lab_a.path.exists()

    lab_b = fleet.create("task-lab", base="refs/heads/main")
    dues.append({**due_b, "host_evidence": {}})  # B has landed, without capture.
    commits, errors = [], []

    def writer():
        try:
            start_writer.wait()
            commits.append(land(lab_b, pin_b, "B"))
        except BaseException as exc:
            errors.append(exc)
        finally:
            b_landed.set()

    thread = threading.Thread(target=writer)
    thread.start()
    race[0] = True
    outcomes = registry.sweep_landed_at_start()
    thread.join()                       # A hang, rather than elapsed time, fails.
    assert not errors, errors
    assert any(x.name == "task-lab" and x.action == "kept-unsettled"
               for x in outcomes), outcomes
    assert lab_b.path.is_dir() and lab_b.head() == commits[0]
    assert (lab_b.path / "work.txt").read_text() == "B\n"

    dues[1] = due_b                    # Capture B's own occurrence.
    assert any(x.action == "removed" for x in registry.sweep_landed_at_start())
    assert not lab_b.path.exists()
```

## 3–6. Deletion, risk and current-state notes

- **Delete:** the two-field marker format and its overwrite path (`labs.py:375`); pre-lock marker and HEAD checks (`:393–425`); unconditional marker erasure in create/resume (`:312`, `:329`); task-name-only cleanup predicates (`product_service.py:381–383`, `:416–420`). Keep dirty-work and retained Git-ref checks.
- **Plausible mistake:** validate A’s Due before taking the deletion lock, or match only `task-lab`. The test makes a real writer land B after the A-only Due read and before sweep custody; either mistake removes B. A separate lock test should hold `fleet.writing()` while sweep attempts custody and verify the writer’s HEAD and bytes survive.
- **Existing expectations / D19:** no existing assertion should change. Artifact availability before capture, exact cleanup afterward, and dirty/ref protections remain expected. Synthetic marker/Due fixtures in `test_fleet_custody.py:387` and `test_external_owner_execution.py:204,302` need occurrence pins; the former also patches `LabFleet.remove`, contrary to the stated harness rule, so replace that fault setup while preserving its assertions. Any assertion change requires a written D19 decision.
- **Stale or incomplete row evidence:** `labs.py:399` and `:423` validate **before** the removal lock; `:411–421` recovers only after a *fully absent* directory, not partial unlink. `product_service.py:416` ignores the supplied commit. `LABCAPTURE 1–2` is not identifiable as a named row on `canon/main`.

Read-only review only; no tests were run.