## Design for FACADEFD

Use **`canon/main` at `eb9b6cd`** for these line references. The intended invariant is that local dispatch creates no listening socket, while an explicitly exported facade retains a working socket until its owner closes it.

1. `src/herzchen/command_ports.py:333-364,464-496` → Make `_start_service` create an inert owner service. Move socket creation, bind, permissions, listen and thread start into the idempotent `_activate_transport`, guarded against concurrent activation. Keep the existing finite endpoint and token checks.
2. `src/herzchen/command_ports.py:234-243,630-645` → Keep the current local `SerializedCommandClient` path, but give each factory-created client ownership of its service so a discarded per-call facade releases its registry entry and empty directory. A client made by `connect_consumer_facade` must not own that service. Make retirement PID-safe; explicit exports remain live while their owning facade is retained and close through `close_consumer_facade`.
3. `src/herzchen/command_ports.py:515-537,662-665` → Activate only on `consumer_transport()` or `serve_consumer_facade()`. Verify a child process can call the exported endpoint, then closing it removes the socket. A local call must never activate it.
4. `src/otto/portfolio/owner_bootstrap.py:776-795` → Pass `create_and_open_bridge.command_port` directly into the already local `FiniteWorkOperations`. Delete the `consumer_transport()` → `to_dict()` → `connect_consumer_facade()` round trip, which currently activates a socket for every composed `HostSession`.
5. `src/otto/portfolio/manager_journey_service.py:646-656` → Read the live pool through `self.server.owner._limit_service`, already retained at `src/otto/portfolio/owner_bootstrap.py:676-684`. Preserve the current unknown/error results.
6. `src/otto/portfolio/owner_bootstrap.py:1012-1077` and `src/herzchen/domains/assessment/module.py:250-264` → Keep each `ManagerAssessmentCommands`, `OttoAssessment`, actor and evidence grant issuer **request-scoped**. The now inert local facade constructors make the fresh `AssessmentModule`, `LimitService` and `OperationManager` safe. Preserve `authorize()` on each request and evidence read.
7. `src/herzchen/command_ports.py:335,411-415,540-544` → Bound the owner audit by both entry count and retained bytes; redact tokens and replace oversized payloads with size and digest. Synchronize append and snapshot. Local fast-path calls do not append today, but exported facades can otherwise grow this list indefinitely.
8. `tests/test_command_dir_cleanup.py:14-30,60-73` → Explicitly activate the transport in its socket-mode fixture. Add a separate real-facade subprocess test for successful socket call and explicit close.
9. `ops/bootstrap/perch.sh:598-615,660-667`, `ops/bootstrap/perch_report.py:53-56,424-510,1333-1476`, `tests/test_perch.py:124,618-662` → Capture before/after descriptor counts for the **same staging owner PID** at comparable idle points, including `herzchen-command-*/owner.sock` counts. Add `owner-descriptors-bounded`: fail on missing or mismatched evidence, total growth above +3, or socket growth; seed a fault that makes only this assertion red. The check measures counts, not elapsed time.

## First failing test

Add `tests/test_facadefd.py` with this process-wide regression. It uses real disposable owners, the existing fake provider fixture, 200 calls through each affected path, and a second-task grant check.

```python
import os
import unittest
from types import SimpleNamespace

from herzchen.command_ports import owner_local_engine
from herzchen.contracts import ResourceRef
from otto.portfolio.local_assessment_policy import LocalAssessmentPolicy
from otto.portfolio.manager_journey_service import ManagerJourneyService
from tests.test_hostctl_cli import HostctlFixture
from tests.test_local_assessment_composition import LocalAssessmentCompositionTests


def descriptor_count():
    for directory in ("/dev/fd", "/proc/self/fd"):
        if os.path.isdir(directory):
            return len(os.listdir(directory))
    raise unittest.SkipTest("process descriptor census unavailable")


class FacadeDispatchFDTests(unittest.TestCase):
    def test_200_budget_assessment_and_routed_host_reads_keep_fds_flat(self):
        local = LocalAssessmentCompositionTests()
        local.setUp()
        self.addCleanup(local.doCleanups)
        host = HostctlFixture()
        host.setUp()
        self.addCleanup(host.doCleanups)
        host._init()

        f, state = local.f, local.state
        policy = LocalAssessmentPolicy.from_run_config(local.config, state=state)
        f.owner.create_manager_assessment_pool(
            project_ref=state["project_ref"],
            task_ref=state["task_refs"]["PA01"],
            manager_assignment_ref=state["assignment_ref"],
            manager_actor=state["manager"],
            manager_generation=state["manager_generation"],
            logical_request_key="facadefd-pool",
            assessment_policy=policy,
        )
        server = SimpleNamespace(
            owner=f.owner, portfolio=f.app.portfolio, state=state,
            store=f.store, due_port=f.port, _execution=lambda **_: f.app,
        )
        journey = ManagerJourneyService(
            server=server, host=None, run_path=f.temporary.name,
            workspace=f.temporary.name,
        )

        def assessment(alias):
            return f.owner.manager_assessment(
                project_ref=state["project_ref"],
                task_ref=state["task_refs"][alias],
                manager_assignment_ref=state["assignment_ref"],
                manager_actor=state["manager"],
                manager_generation=state["manager_generation"],
                assessment_policy=policy,
            )

        assessment("PA01")
        second = assessment("PA06")
        task_a = ResourceRef.from_dict(state["task_refs"]["PA01"])
        task_b = ResourceRef.from_dict(state["task_refs"]["PA06"])
        evidence = ResourceRef(f.actor.authority, "dat.content.document",
                               "facadefd-evidence", "rev-1")
        issuer = owner_local_engine(
            second._assessment._assessment
        )._evidence_read_grant_issuer
        self.assertEqual(issuer(evidence, task_b).parent, task_b)
        with self.assertRaises(PermissionError):
            issuer(evidence, task_a)

        before = descriptor_count()
        for index in range(200):
            self.assertEqual(journey._budget()["state"], "known")
            alias = "PA01" if index % 2 == 0 else "PA06"
            self.assertEqual(
                local.call(alias, "coverage", {}, f"facadefd-{index}")["outcome"],
                "read",
            )
            code, routed = host._ottoctl("projects")
            self.assertEqual((code, routed["outcome"]), (0, "read"))
        self.assertLessEqual(descriptor_count() - before, 3)
```

## Delete and preserve

Delete the eager constructor bind and the `HERZCHEN_IN_PROCESS_COMMAND_FALLBACK` split at `command_ports.py:341-358,473-480`; explicit activation supplies the one transport path. Delete the redundant bridge serialization at `owner_bootstrap.py:779-782`. **Do not cache an assessment module or its grant callback.**

The plausible shortcut is to cache that whole module. The positive grant assertion for `PA06` then fails if it retained `PA01`’s issuer; the negative assertion rejects reuse in the other direction. The subprocess and close test catches a lazy socket that is never bound or never released.

No existing assertion needs a changed expectation, so no D19 decision is needed if they are preserved. The socket cleanup fixture needs an explicit activation step to keep testing its present assertion. Any weakened or changed existing assertion requires a written D19 decision.

## Row corrections on `canon/main`

`_activate_transport` already exists at `command_ports.py:492`, but currently starts only the thread: `_start_service` still binds the socket. `owner_bootstrap.py:681` already retains one owner `LimitService`. `hostctl/service.py:441` routes the handler; the repeated bootstrap is composed inside its `HostSession` call chain. Neither cited audit Markdown file nor an `owner-descriptors-bounded` check exists in `canon/main`, so the reported staging counts are external evidence, not independently verifiable from this ref. Also, the current stage-2 fake owner harness patches `_OwnerExecutorPort.call` at `ops/bootstrap/perch_stage2_owner.py:75-91`, contrary to the stated rule against harness patches of product methods.