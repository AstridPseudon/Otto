"""Portfolio status stays scoped, read-only and independent of sheet/history size."""
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from herzchen.contracts import ResourceRef
from herzchen.kernel import LimitService, Store
from otto.attention import DueRecord, issue_store_due_record_port, due_record_contribution
from otto.hostctl.owner import host_domains
from otto.portfolio.dependencies import PortfolioDependencies
from otto.portfolio.herzchen_binding import HerzchenBindingConfig
from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap
from otto.portfolio.status import manager_activity, portfolio_status


class PortfolioStatusTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="portfolio-status-")
        self.addCleanup(temporary.cleanup)
        self.store = Store.create(Path(temporary.name) / "owner.sqlite", authority="owner")
        self.addCleanup(self.store.close)
        self.store.register_domain_handler(host_domains())
        binding = HerzchenBindingConfig("owner", "credential")
        owner = PortfolioOwnerBootstrap(self.store, binding=binding, owner_actor="owner")
        self.portfolio = ResourceRef("owner", "wrk.portfolio", "portfolio")
        root = owner.assignments.assign(self.portfolio, role="orchestrator", principal="orchestrator",
                                        logical_request_key="root")
        owner = PortfolioOwnerBootstrap(self.store, binding=binding, owner_actor="owner",
                                        portfolio_ref=self.portfolio, main_assignment_ref=root.ref)
        self.owner = owner
        self.projects = [owner.graph.create_project(title="Project " + str(i), logical_request_key="p" + str(i))
                         for i in range(3)]
        attached = owner.consumer_operations().execute("work.orchestrator.projects.attach", {
            "target_assignment_ref": root.ref.to_dict(), "target_assignment_revision": root.revision,
            "target_assignment_generation": root.generation,
            "projects": [{"project_ref": item.ref.to_dict(), "project_version": item.version,
                          "assignment_ref": None, "assignment_revision": None, "assignment_generation": None}
                         for item in self.projects]}, request_id="attach", actor="owner")
        self.assertEqual(attached["outcome"], "attached")
        self.session = SimpleNamespace(store=self.store, owner=owner, binding=binding,
            config={"home": temporary.name}, host={"portfolio_ref": self.portfolio.to_dict(), "principal": "orchestrator"})
        self.deps = PortfolioDependencies(owner.graph, self.store.consumer(), actor=owner.owner_actor,
                                          owner_actor=owner.owner_actor, portfolio_ref=self.portfolio)
        self.now = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)

    def status(self, **kwargs):
        return portfolio_status(self.session, now=self.now, service_status=kwargs.pop("service_status", {}), **kwargs)

    def manager(self):
        return self.owner.assignments.assign(self.projects[1].ref, role="manager", principal="manager",
                                              logical_request_key="manager")

    def due(self, **kwargs):
        record = DueRecord(schedule_id="manager-due", recipient="manager", instruction="coordinate",
            profile="manager", anchor="2026-10-11T10:00:00+00:00", last_covered_slot=0,
            invocation_identity="invocation", due_at="2026-10-11T10:00:00+00:00",
            project_ref=self.projects[1].id, role="manager", **kwargs)
        port = issue_store_due_record_port(self.store.domain_handler((due_record_contribution(),)), self.owner.owner_actor)
        port.save_due(record.schedule_id, record.to_dict(), request_id="due", expected_version=0)

    def test_readiness_counts_and_override_without_exports_events_or_writes(self):
        foreign = self.owner.graph.create_project(title="Not enrolled", logical_request_key="foreign")
        self.owner.graph.create_task(foreign.ref, logical_request_key="foreign-task")
        self.owner.graph.create_task(self.projects[0].ref, logical_request_key="pending-task")
        task = self.owner.graph.create_task(self.projects[1].ref, logical_request_key="finished-task")
        self.owner.graph.set_lifecycle(task.ref, "completed")
        gate = self.owner.graph.create_gate(self.projects[0].ref, logical_request_key="gate")
        self.deps.change(self.projects[1], gate, request_id="depends")
        self.deps.activation_check(self.projects[1], override=True, reason="walking skeleton", request_id="override")
        before = self.store.consumer().snapshot_counts()
        queries = []
        self.store.connection.set_trace_callback(queries.append)
        with patch.object(type(self.owner.sheet), "export", side_effect=AssertionError("sheet export forbidden")), \
                patch.object(Store, "list_events", side_effect=AssertionError("event history forbidden")):
            result = self.status()
        self.store.connection.set_trace_callback(None)
        self.assertEqual(self.store.consumer().snapshot_counts(), before)
        self.assertEqual(result["totals"]["projects"], 3)
        self.assertEqual(result["totals"]["tasks"], {"pending": 1, "completed": 1})
        self.assertEqual(result["totals"]["readiness"], {"ready": 2, "blocked": 1})
        self.assertTrue(any(row["reason"] == "readiness_overridden" for row in result["needs_orchestrator"]))
        self.assertTrue(all(row["last_activity_at"] for row in result["projects"]))
        # One projection each for task/assignment/Due/report kinds, independent
        # of project count. SELECT does not fetch complete report/Due payloads.
        projections = [query for query in queries if "json_object(" in query and "FROM identities" in query]
        self.assertEqual(len(projections), 4)
        self.assertFalse(any("SELECT *" in query for query in projections))
        self.owner.graph.set_lifecycle(gate.ref, "completed")
        self.assertEqual(self.status()["totals"]["readiness"], {"ready": 3})

    def test_host_cannot_select_another_portfolio_owner_can(self):
        with self.assertRaises(PermissionError):
            self.status(portfolio_ref="other")
        self.session.host = None
        self.assertEqual(self.status(portfolio_ref="other")["totals"]["projects"], 0)
        with self.assertRaises(ValueError):
            self.status()

    def test_help_resolution_manager_heartbeat_and_allowances(self):
        manager = self.manager()
        limits = LimitService(self.store)
        pool = limits.create_pool(ResourceRef("owner", "limit", "oracle"), capacity_units=1,
                                 cumulative_allowance_units=4, actor=self.owner.owner_actor, logical_request_key="pool")
        held = limits.reserve(pool.ref, "reservation", 1, actor=self.owner.owner_actor, logical_request_key="reserve")
        limits.settle(held, 1, actor=self.owner.owner_actor, logical_request_key="settle")
        self.due(in_flight_request="turn", delivered_at="2026-10-11T10:00:00+00:00",
                 timeout_seconds=60, allowance_ref=pool.ref.to_dict())
        issue = {"schema": "otto.issue.v1", "issue_id": "decision", "issue_version": 1,
                 "project_ref": self.projects[1].ref.to_dict(), "problem": "Contract choice",
                 "awaiting": "orchestrator", "observed_at": "2026-10-11T10:01:00+00:00"}
        self.owner.assignments.append_report(manager.ref, issue, logical_request_key="help")
        service = {"attached_project": {"project_id": self.projects[1].id}, "manager_turn_active": True,
                   "state": "serving", "heartbeat_at": self.now.isoformat(), "heartbeat_seconds": 1}
        result = self.status(service_status=service)
        row = next(item for item in result["projects"] if item["project_ref"]["id"] == self.projects[1].id)
        self.assertEqual(row["manager"]["state"], "running")
        self.assertEqual(row["manager"]["last_heartbeat"], self.now.isoformat())
        self.assertTrue(row["manager"]["stalled"])
        self.assertEqual(row["open_help_requests"][0]["purpose"], "operational_help")
        self.assertEqual(result["totals"]["allowances"]["used"], 1)
        self.assertEqual(result["totals"]["allowances"]["remaining"], 3)
        self.assertEqual(result["totals"]["open_help_requests"], 1)
        self.owner.assignments.append_report(manager.ref, {**issue, "schema": "otto.issue.outcome.v1",
            "issue_version": 2, "disposition": "resolved", "awaiting": "none"}, logical_request_key="resolved")
        self.assertEqual(self.status()["totals"]["open_help_requests"], 0)

    def test_assigned_manager_is_paused_and_missing_manager_is_none(self):
        self.manager()
        self.assertEqual(self.status()["totals"]["managers"], {"none": 2, "paused": 1})

    def test_queued_manager_with_retained_due_is_running_for_detach(self):
        self.manager()
        self.due(in_flight_request="running-native-turn")
        activity = manager_activity(self.store, self.projects[1].ref)
        self.assertEqual(activity["state"], "running")
        self.assertEqual(activity["assignments"][0]["status"], "queued")
        self.assertEqual(manager_activity(self.store, self.projects[0].ref)["state"], "none")

    def test_owner_status_does_not_borrow_host_principal(self):
        self.session.host["principal"] = "stale-host-principal"
        with self.assertRaises(PermissionError):
            self.status()
        self.assertEqual(self.status(owner_authorized=True)["totals"]["projects"], 3)

    def test_concurrent_status_does_not_attribute_other_project_turn(self):
        self.manager()
        service = {"attached_projects": [{"project_id": p.id} for p in self.projects],
            "manager_turn_active": True, "heartbeat_at": self.now.isoformat(),
            "manager_turns": {"active_projects": [self.projects[0].id],
                              "queued_by_project": {self.projects[2].id: 1}}}
        rows = {row["project_ref"]["id"]: row["manager"]
                for row in self.status(service_status=service)["projects"]}
        self.assertEqual(rows[self.projects[0].id]["state"], "running")
        self.assertEqual(rows[self.projects[1].id]["state"], "paused")
        self.assertEqual(rows[self.projects[2].id]["state"], "running")
        self.assertTrue(rows[self.projects[2].id]["queued"])
        self.assertEqual(rows[self.projects[1].id]["last_heartbeat"], self.now.isoformat())


if __name__ == "__main__":
    unittest.main()
