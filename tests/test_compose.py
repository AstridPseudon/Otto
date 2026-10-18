"""COMPOSE: ``ottoctl service run`` composes the owner the live start composes.

What is proven: the product start (otto.hostctl.product_service) opens the one Store, composes one shared
bounded ExecutionHost with one ManagerJourneyService view per activated project behind the ProjectServices
router, settles retained handles BEFORE the host starts, honours the dispatch hold, records a startup
refusal and exits 78, publishes closed only after the host and Store are released, and seals the Store on
an orderly close. No provider is called anywhere: the fixtures use the fake launcher of test_hostctl_cli.

What is not proven: a live model turn, the native caller socket with a real launched manager, or the
onboarding wrapper's own start (it is untouched and retires at CUTOVER).
"""
import json
import os
import queue
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from otto.hostctl import config as host_config, lanes
from otto.hostctl.service import read_status, status_path, stop_marker
from tests.test_hostctl_cli import HostctlFixture

ROOT = Path(__file__).resolve().parents[1]
PY = "/opt/homebrew/bin/python3.11"


class ProductFixture(HostctlFixture):
    """An activated canary project, then the PRODUCT start in place of the plain owner service."""

    def setUp(self):
        super().setUp()
        # A Unix socket address is limited to 103 bytes: use a short home.
        short = os.path.realpath(tempfile.mkdtemp(prefix="ocp-", dir="/tmp"))
        self.addCleanup(shutil.rmtree, short, True)
        self.home = os.path.join(short, "h")

    def _stop_plain_service(self):
        stop_marker(Path(self.home)).write_text("stop\n")
        self.service_thread.join(timeout=60)
        self.assertFalse(self.service_thread.is_alive(), "the plain owner service did not close")

    def _prepared(self):
        self._ready()
        self._stop_plain_service()

    def _product(self, **options):
        """Run the product start in a thread; returns (events queue, thread). Stop it with _stop_product."""
        from otto.hostctl.product_service import run_product_service  # absent on canon/main
        config = host_config.load(Path(self.home))
        events = queue.Queue()
        self.product_result = {}

        def target():
            try:
                self.product_result["value"] = run_product_service(
                    config, emit=lambda value: events.put(value), **options)
            except BaseException as exc:  # SystemExit(78) included
                self.product_result["error"] = exc

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        self.addCleanup(self._stop_product, thread)
        return events, thread

    def _stop_product(self, thread):
        if thread.is_alive():
            stop_marker(Path(self.home)).write_text("stop\n")
            thread.join(timeout=60)
            self.assertFalse(thread.is_alive(), "the product service did not close")

    def _ready_doc(self, events):
        document = events.get(timeout=60)
        self.assertEqual(document["outcome"], "ready", document)
        return document

    def _retained_runner_queue(self):
        from herzchen.fleet.runner.commit import git_commit_identity
        from herzchen.fleet.runner.store import ResultStore

        repo = Path(self.home).parent / "runner-repo"
        repo.mkdir()
        subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
        (repo / "seed").write_text("seed\n")
        subprocess.run(["git", "-C", str(repo), "add", "seed"], check=True)
        subprocess.run(
            ["git", "-C", str(repo),
             "-c", "user.name=owner-claim",
             "-c", "user.email=owner-claim@example.invalid",
             "commit", "-qm", "seed"],
            check=True,
        )
        commit = git_commit_identity(str(repo))
        self.assertIsNotNone(commit)

        marker = repo.parent / "runner-launched"
        argv = [sys.executable, "-c",
                f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')"]
        results = ResultStore(Path(self.home) / "runner-results")
        results.put({
            "run_id": "retained-q", "seq": results.next_seq(),
            "binding": results.binding(argv, str(repo), commit),
            "argv": argv, "cwd": str(repo), "commit": commit,
            "task": "custody", "purpose": "retained-q", "units": 1,
            "weight_requested": 1, "max_seconds": 3600,
            "state": "queued", "outcome": None, "exit_code": None,
            "nested_in": None, "backfill": False, "submitted_at": time.time(),
            "started_at": None, "settled_at": None, "seconds": None,
            "unit_seconds": None, "tokens": 0, "custody": None,
            "output_sha256": None, "output_bytes": None,
        })
        return results, marker


class ProductStartTests(ProductFixture):
    def test_service_run_attaches_registered_project(self):
        self._prepared()
        events, thread = self._product()
        ready = self._ready_doc(events)
        self.assertEqual(ready["attached_projects"], ["demo-run"], ready)
        self.assertEqual((ready["dues_started"], ready["provider_called"], ready["dispatch"]), (0, False, "open"))
        status = read_status(status_path(Path(self.home)))
        self.assertEqual(status["outcome"], "running", status)
        self.assertEqual([row["run_id"] for row in status["attached_projects"]], ["demo-run"])
        self.assertTrue(status["shared_project_owner"])
        # The canary's manager lane serves through the router: the orchestrator's host lane relays a
        # help read into the shared host, and the owner-issued grant routes it to this project's view.
        code, relayed = self._ottoctl("--wait-seconds", "60", "help", "read", "--project", "demo-run")
        self.assertEqual(code, 0, relayed)
        self.assertEqual(relayed["relayed"]["from"], "manager lane", relayed)
        self.assertEqual(relayed["relayed"]["command"], "read-help")
        # Nothing but a grant routes a shared-lane request: a bare request file is refused.
        host_dir = Path(self.home) / "shared-host"
        token = lanes.new_token()
        lanes.submit(host_dir, {"command": "read-help"}, token=token)
        deadline = __import__("time").monotonic() + 30
        reply = host_dir / ("response-" + token + ".json")
        while not reply.exists() and __import__("time").monotonic() < deadline:
            __import__("time").sleep(0.05)
        self.assertEqual(json.loads(reply.read_text())["outcome"], "error")
        # A second owner finds the Store busy and refuses without a refusal record.
        code, busy = self._ottoctl("service", "run")
        self.assertEqual((code, busy["error"]["code"]), (3, "owner_service_running"))
        self.assertEqual(list((Path(self.home) / "run").glob("owner-startup-refusal-*.json")), [])


ENTRY = "import sys; from otto.hostctl.cli import main; sys.exit(main())"


def documents(text):
    """Every JSON document a product process printed (they are indented, so not one per line)."""
    decoder, found, index = json.JSONDecoder(), [], 0
    while True:
        index = text.find("{", index)
        if index < 0:
            return found
        try:
            value, end = decoder.raw_decode(text, index)
        except ValueError:
            index += 1
            continue
        found.append(value)
        index = end


class SpawnedProduct:
    """`ottoctl service run` as its own process, as staging and launchd start it."""

    count = 0

    def __init__(self, home, *flags):
        SpawnedProduct.count += 1
        suffix = str(SpawnedProduct.count)
        self.out, self.err = Path(home).parent / ("spawn%s.out" % suffix), Path(home).parent / ("spawn%s.err" % suffix)
        env = {key: value for key, value in os.environ.items() if not key.startswith("OTTO_")}
        env["PYTHONPATH"] = str(ROOT / "src")
        self.process = subprocess.Popen([PY, "-c", ENTRY, "--home", home, "service", "run", *flags],
                                        stdout=self.out.open("ab"), stderr=self.err.open("ab"), env=env, cwd=ROOT)

    def documents(self):
        return documents(self.out.read_text()) if self.out.exists() else []

    def wait_for(self, outcome, seconds=60):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            for document in self.documents():
                if document.get("outcome") == outcome:
                    return document
            if self.process.poll() is not None:
                break
            time.sleep(0.1)
        raise AssertionError("no %r document; exit %r; out=%r; err=%r" % (
            outcome, self.process.poll(), self.out.read_text()[-800:], self.err.read_text()[-1500:]))

    def kill(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=30)


class SpyMixin:
    def _spy(self):
        """Capture the composed owner and the order of its startup events."""
        from otto.hostctl import product_service
        from otto.portfolio.execution_host import ExecutionHost
        from otto.portfolio.project_services import ProjectServices
        events, captured = [], {}
        real_compose, real_reconcile = product_service.compose, ProjectServices.reconcile_startup
        real_inert, real_start = ProjectServices.install_inert, ExecutionHost.start

        def compose(*args, **kwargs):
            captured["owner"] = real_compose(*args, **kwargs)
            return captured["owner"]

        def reconcile(router):
            events.append(("reconcile", bool(router.host._threads), router.host.dispatch_held))
            return real_reconcile(router)

        def inert(router, **kwargs):
            events.append(("inert", bool(router.host._threads), router.host.dispatch_held))
            return real_inert(router, **kwargs)

        def start(host):
            events.append(("host-start", bool(host._threads), host.dispatch_held))
            return real_start(host)

        for target, name, value in ((product_service, "compose", compose),
                                    (ProjectServices, "reconcile_startup", reconcile),
                                    (ProjectServices, "install_inert", inert), (ExecutionHost, "start", start)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        return events, captured


class OrderTests(SpyMixin, ProductFixture):
    def test_reconcile_before_admission(self):
        self._prepared()
        events, captured = self._spy()
        run = self._product()
        self._ready_doc(run[0])
        # Settlement ran on a closed host and finished before the host began to serve anything.
        self.assertEqual([name for name, *_ in events], ["reconcile", "host-start"], events)
        self.assertFalse(events[0][1], "reconciliation must run before any host thread exists")
        self.assertIs(captured["owner"].host.handler, captured["owner"].router)

    def test_retained_handle_that_cannot_be_settled_blocks_admission(self):
        """A killed run's retained handle: the restart settles it or admits nothing."""
        self._prepared()
        host_dir = lanes.private_dir(Path(self.home) / "shared-host")
        lanes.submit(host_dir, {"command": "start-retained-worker", "schedule_id": "killed-run-handle"},
                     token=lanes.new_token())
        events, captured = self._spy()
        events_q, thread = self._product()
        thread.join(timeout=60)
        refused = events_q.get(timeout=5)
        self.assertEqual(refused["outcome"], "startup-refused", refused)
        self.assertIsInstance(self.product_result["error"], SystemExit)
        self.assertEqual(self.product_result["error"].code, 78)
        self.assertEqual([name for name, *_ in events], ["reconcile"], "the host must never start: " + repr(events))

    def test_killed_owner_is_settled_by_the_restart_before_it_serves(self):
        self._prepared()
        first = SpawnedProduct(self.home)
        self.addCleanup(first.kill)
        first_ready = first.wait_for("ready")
        first.kill()
        second = SpawnedProduct(self.home)
        self.addCleanup(second.kill)
        second_ready = second.wait_for("ready")
        self.assertEqual(second_ready["startup"]["outcome"], "reconciled", second_ready)
        self.assertGreater(second_ready["generation"], first_ready["generation"])
        self.assertEqual(second_ready["attached_projects"], ["demo-run"])


class RefusalTests(ProductFixture):
    def test_refusal_leaves_retained_runner_queue_unlaunched(self):
        self._prepared()
        results, marker = self._retained_runner_queue()

        host_dir = lanes.private_dir(Path(self.home) / "shared-host")
        lanes.submit(host_dir,
                     {"command": "start-retained-worker",
                      "schedule_id": "killed-run-handle"},
                     token=lanes.new_token())
        events, thread = self._product()
        thread.join(timeout=60)

        self.assertFalse(thread.is_alive())
        self.assertEqual(events.get(timeout=5)["outcome"], "startup-refused")
        self.assertEqual(self.product_result["error"].code, 78)
        self.assertEqual(results.get("retained-q")["state"], "queued")
        self.assertFalse(marker.exists())

    def test_startup_refusal_records_exit_78(self):
        self._prepared()
        host_dir = lanes.private_dir(Path(self.home) / "shared-host")
        lanes.submit(host_dir, {"command": "start-retained-worker", "schedule_id": "killed-run-handle"},
                     token=lanes.new_token())
        spawned = SpawnedProduct(self.home)
        self.addCleanup(spawned.kill)
        self.assertEqual(spawned.process.wait(timeout=60), 78, spawned.err.read_text()[-1500:])
        refused = spawned.wait_for("startup-refused")
        self.assertEqual(refused["error"]["code"], "PermissionError")
        self.assertFalse(any(document.get("outcome") == "ready" for document in spawned.documents()))
        records = list((Path(self.home) / "run").glob("owner-startup-refusal-*.json"))
        self.assertEqual(len(records), 1)
        record = json.loads(records[0].read_text())
        self.assertEqual(record["schema"], "otto.owner-startup-refusal.v1")
        self.assertEqual(record["pid"], spawned.process.pid)
        self.assertIs(record["native_admission_started"], False)
        self.assertEqual(record["canonical_effects"], "preserved-not-inferred")
        self.assertEqual(record["error"]["code"], "PermissionError")
        self.assertIs(record["startup_store_observation"]["store_closed"], True)
        self.assertIs(record["startup_store_observation"]["seal_requested"], False)
        self.assertEqual(oct(records[0].stat().st_mode & 0o777), "0o600")
        # Released, not sealed: the Store is free for the next owner and no clean-close record was written.
        self.assertFalse(os.path.exists(self._store_path() + ".fnd-clean-close"))
        self.assertEqual(read_status(status_path(Path(self.home)))["outcome"], "closed")

    def test_manager_limit_above_the_pool_is_refused(self):
        self._prepared()
        events, thread = self._product(requested_manager_limit=99)
        thread.join(timeout=60)
        self.assertEqual(events.get(timeout=5)["error"]["code"], "ValueError")
        self.assertEqual(self.product_result["error"].code, 78)


class HoldTests(SpyMixin, ProductFixture):
    def test_held_then_normal_restart_admits_the_same_retained_record(self):
        self._prepared()
        results, marker = self._retained_runner_queue()

        held_events, held_thread = self._product(hold_dispatch=True)
        self.assertEqual(self._ready_doc(held_events)["dispatch"], "held")
        self.assertEqual(results.get("retained-q")["state"], "queued")
        self.assertFalse(marker.exists())
        stop_marker(Path(self.home)).write_text("stop\n")
        held_thread.join(timeout=60)
        self.assertFalse(held_thread.is_alive())
        self.assertEqual(results.get("retained-q")["state"], "queued")
        self.assertFalse(marker.exists())

        normal_events, normal_thread = self._product()
        self.assertEqual(self._ready_doc(normal_events)["dispatch"], "open")
        deadline = time.monotonic() + 30
        while results.get("retained-q")["state"] != "settled" and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(results.get("retained-q")["state"], "settled")
        self.assertTrue(marker.exists())
        stop_marker(Path(self.home)).write_text("stop\n")
        normal_thread.join(timeout=60)
        self.assertFalse(normal_thread.is_alive())

    def test_dispatch_hold_refuses_admission(self):
        self._prepared()
        events, captured = self._spy()
        run = self._product(hold_dispatch=True)
        ready = self._ready_doc(run[0])
        self.assertEqual(ready["dispatch"], "held")
        host = captured["owner"].host
        self.assertTrue(host.dispatch_held)
        # Held start reads custody only: it never settles (reconcile) and it admits nothing.
        self.assertEqual([name for name, *_ in events], ["inert", "host-start"], events)
        self.assertTrue(events[0][2], "the hold must be installed before the router reads retained custody")
        for command in ("start-manager", "start-retained-worker"):
            held = host.submit({"command": command, "schedule_id": "any"})
            self.assertEqual((held["outcome"], held["dispatch"]), ("held", "held"), held)
            self.assertFalse(held["effects_started"] or held["provider_called"])
        status = captured["owner"].service._owner_command(
            "owner", {"command": "status"}, lanes.new_token(), owner_lane_path(self.home))
        self.assertEqual(status["dispatch"], "held")
        self.assertFalse(status["startup"]["provider_called"])

    def test_launchd_product_form_runs_service_run_directly(self):
        import plistlib
        from otto.hostctl.supervision import launchd_definition
        config = {"python": PY, "home": self.home, "max_active_manager_turns": 3,
                  "owner_composition": {"kind": "product-service", "cwd": str(ROOT), "src": str(ROOT / "src"),
                                        "stdout": "/tmp/otto.out", "stderr": "/tmp/otto.err"}}
        value = plistlib.loads(launchd_definition(config, label="org.otto.owner"))
        self.assertEqual(value["ProgramArguments"], [PY, "-c", ENTRY, "--home", self.home, "service", "run"])
        self.assertEqual(value["EnvironmentVariables"]["PYTHONPATH"], str(ROOT / "src"))
        self.assertEqual(value["KeepAlive"], {"SuccessfulExit": False})
        config["owner_composition"]["hold_dispatch"] = True
        held = plistlib.loads(launchd_definition(config, label="org.otto.owner"))
        self.assertEqual(held["ProgramArguments"][-1], "--hold-dispatch")
        with self.assertRaises(PermissionError):
            launchd_definition({**config, "python": "python3"}, label="org.otto.owner")


class HomeCustodyTests(ProductFixture):
    def test_distinct_stores_under_one_home_admit_only_one_starter(self):
        from herzchen.kernel.store import WriterBusyError
        from otto.hostctl import product_service
        from otto.hostctl.owner import create_store
        from otto.hostctl.serve import socket_path

        self._prepared()
        config = host_config.load(Path(self.home))
        alternate = create_store({**config, "store": {
            "path": str(Path(self.home) / "store" / "alternate.sqlite"),
            "authority": config["store"]["authority"],
        }})
        self.assertNotEqual(config["store"]["device_inode"], alternate["store"]["device_inode"])

        first = SpawnedProduct(self.home)
        self.addCleanup(first.kill)
        self.assertEqual(first.wait_for("ready")["outcome"], "ready")
        owner_file = Path(self.home) / "run" / "shared-host-owner.json"
        caller_socket = socket_path(config, "shared-project-services")
        owner_contents = owner_file.read_bytes()
        owner_identity = (owner_file.stat().st_dev, owner_file.stat().st_ino)
        socket_identity = (caller_socket.stat().st_dev, caller_socket.stat().st_ino)
        self.assertTrue(stat.S_ISSOCK(caller_socket.stat().st_mode))

        emitted = []
        with mock.patch.object(product_service, "compose", side_effect=AssertionError("loser composed")) as composed:
            with self.assertRaises(WriterBusyError):
                product_service.run_product_service(alternate, emit=emitted.append)
        composed.assert_not_called()
        self.assertEqual(emitted, [])
        self.assertEqual(owner_file.read_bytes(), owner_contents)
        self.assertEqual((owner_file.stat().st_dev, owner_file.stat().st_ino), owner_identity)
        self.assertEqual((caller_socket.stat().st_dev, caller_socket.stat().st_ino), socket_identity)
        self.assertTrue(stat.S_ISSOCK(caller_socket.stat().st_mode))
        self.assertIsNone(first.process.poll())
        self.assertEqual(read_status(status_path(Path(self.home)))["outcome"], "running")
        self.assertEqual(list((Path(self.home) / "run").glob("owner-startup-refusal-*.json")), [])


def owner_lane_path(home):
    from otto.hostctl.service import owner_lane
    return owner_lane(Path(home))


class CloseTests(SpyMixin, ProductFixture):
    def test_closed_only_after_store_release(self):
        from herzchen.kernel.store import Store
        self._prepared()
        events, captured = self._spy()
        seen = []
        real_close = Store.close

        def close(store, *args, **kwargs):
            state = json.loads(status_path(Path(self.home)).read_text())
            seen.append((state["state"], any(t.is_alive() for t in captured["owner"].host._threads)))
            return real_close(store, *args, **kwargs)

        with mock.patch.object(Store, "close", close):
            events_q, thread = self._product()
            self._ready_doc(events_q)
            owner = captured["owner"]
            owner.service.begin_draining()
            with self.assertRaisesRegex(RuntimeError, "still open"):
                owner.service.finalize_closed()
            self.assertEqual(read_status(status_path(Path(self.home)))["outcome"], "draining")
            stop_marker(Path(self.home)).write_text("stop\n")
            thread.join(timeout=60)
        # While the Store was being closed the status said draining and the host had no threads left.
        self.assertEqual(seen, [("draining", False)])
        closed = json.loads(status_path(Path(self.home)).read_text())
        self.assertEqual((closed["state"], closed["closure_provenance"], closed["store_closed"]),
                         ("closed", "host-and-store-released", True))
        self.assertEqual(self.product_result["value"]["outcome"], "closed")

    def test_orderly_close_seals_store(self):
        self._prepared()
        events, captured = self._spy()
        events_q, thread = self._product()
        self._ready_doc(events_q)
        self.assertEqual(captured["owner"].store.admission_report["mode"], "clean-close")
        stop_marker(Path(self.home)).write_text("stop\n")
        thread.join(timeout=60)
        self.assertEqual(self.product_result["value"]["outcome"], "closed")
        self.assertTrue(os.path.exists(self._store_path() + ".fnd-clean-close"), "an orderly close seals the Store")
        # The next owner admits through the sealed fast path.
        events_q, thread = self._product()
        self._ready_doc(events_q)
        self.assertEqual(captured["owner"].store.admission_report["path"], "clean-close")

    def test_close_after_a_failed_serve_does_not_seal(self):
        from otto.portfolio.execution_host import ExecutionHost
        self._prepared()
        with mock.patch.object(ExecutionHost, "wait_until_stopped", side_effect=RuntimeError("interrupted")):
            events_q, thread = self._product()
            self._ready_doc(events_q)
            thread.join(timeout=60)
        self.assertIsInstance(self.product_result["error"], RuntimeError)
        self.assertFalse(os.path.exists(self._store_path() + ".fnd-clean-close"))
        # Released all the same, and honestly closed.
        self.assertEqual(read_status(status_path(Path(self.home)))["outcome"], "closed")


class CloseoutScanTests(unittest.TestCase):
    def _owner(self, count):
        refs = tuple(SimpleNamespace(id="due-%d" % index) for index in range(count))
        reader = mock.Mock()
        reader.find_identity_refs.return_value = refs
        reader.project_identity_fields_for_refs.side_effect = lambda refs, **kwargs: [
            {"state": "available", "present": {name: True for name in FIELD_NAMES},
             "fields": {"schedule_id": ref.id, "project_ref": "p", "owner": "someone", "interval_seconds": None,
                        "stop_state": "completed"}} for ref in refs]
        store = SimpleNamespace(consumer=lambda: reader, authority="a")
        return SimpleNamespace(store=store, owner_actor=SimpleNamespace(actor="owner")), reader

    def test_closeout_scan_bounded(self):
        from otto.hostctl.product_service import CLOSEOUT_RECORD_LIMIT, closeout_observer
        self.assertEqual(CLOSEOUT_RECORD_LIMIT, 100)
        owner, reader = self._owner(101)
        observed = closeout_observer(owner, "p")("p")
        self.assertEqual((observed["mode"], observed["unknown_ownership"], observed["records_modified"]),
                         ("unknown", True, False))
        self.assertIn("100-record bound", observed["reason"])
        reader.project_identity_fields_for_refs.assert_not_called()  # past the bound nothing is projected
        owner, reader = self._owner(100)
        observed = closeout_observer(owner, "p")("p")
        self.assertEqual(observed["mode"], "no-owned-schedule")
        self.assertEqual(reader.project_identity_fields_for_refs.call_args.kwargs["max_refs"], 100)
        with self.assertRaises(PermissionError):  # a view answers only for its own project
            closeout_observer(owner, "p")("other")


FIELD_NAMES = ("schedule_id", "project_ref", "owner", "interval_seconds", "stop_state")


class InstallationConfigTests(SpyMixin, ProductFixture):
    def _configure(self, **sections):
        config = host_config.load(Path(self.home))
        config.update(sections)
        host_config.write(Path(self.home), config, replace=True)

    def test_turn_limits_come_from_the_pool_not_pins(self):
        self._prepared()
        self._configure(capacity={"turn_units": 4, "manager_reserve": 1, "heavy_headroom": 2, "worker_floor": 1})
        events, captured = self._spy()
        events_q, thread = self._product()
        ready = self._ready_doc(events_q)
        self.assertEqual(ready["capacity"], {"manager_units": 4, "worker_units": 4, "heavy_headroom": 2, "turn_units": 4})
        capacity = read_status(status_path(Path(self.home)))["native_capacity"]
        self.assertEqual((capacity["manager_limit"], capacity["worker_limit"], capacity["heavy_limit"]), (4, 4, 2))
        self.assertEqual(captured["owner"].host.capacity.policy.manager_units, 4)

    def test_default_pool_is_not_the_wrappers_3_2_3(self):
        self._prepared()
        events, captured = self._spy()
        events_q, thread = self._product()
        self._ready_doc(events_q)
        policy = captured["owner"].host.capacity.policy
        self.assertNotEqual((policy.manager_units, policy.worker_units), (3, 2))

    def test_policies_come_from_the_installation(self):
        self._prepared()
        delegation = {"mode": "owner-installed", "note": "from installation.json"}
        external = {"mode": "held"}
        self._configure(policies={"delegation": delegation, "external_execution": external})
        self.assertFalse(list(Path(self.home).rglob("canonical-state.json")))
        events, captured = self._spy()
        events_q, thread = self._product()
        self._ready_doc(events_q)
        (view,) = captured["owner"].views.values()
        self.assertEqual(view.delegation_policy, delegation)
        self.assertEqual(view.external_execution_policy, external)


class EmptyOwnerTests(ProductFixture):
    def test_an_owner_with_no_project_still_composes_and_serves(self):
        self._init()
        self._stop_plain_service()
        events, thread = self._product()
        ready = self._ready_doc(events)
        self.assertEqual((ready["attached_projects"], ready["skipped_projects"], ready["dues_started"]), ([], [], 0))
        self.assertEqual(read_status(status_path(Path(self.home)))["outcome"], "running")

    def _event_count(self):
        from herzchen.kernel.store import Store
        from otto.hostctl.owner import host_domains
        config = host_config.load(Path(self.home))
        target = config["store"]
        store = Store.open(target["path"], authority=target["authority"], expected_domains=host_domains(),
                           expected_domain_digest=target["domain_descriptor_digest"])
        try:
            return len(store.list_events())
        finally:
            store.close()

    def test_a_start_and_orderly_stop_leave_the_store_and_the_run_folder_as_they_were(self):
        # Staging stage 0 expects an empty Store after a start, and `down` must leave only the
        # files a closed Otto leaves in home/run (perch_report.AT_REST_RUN).
        self._init()
        self._stop_plain_service()
        before = self._event_count()
        events, thread = self._product()
        self._ready_doc(events)
        stop_marker(Path(self.home)).write_text("stop\n")
        thread.join(timeout=60)
        self.assertEqual(self.product_result["value"]["outcome"], "closed")
        self.assertEqual(self._event_count(), before, "the product start must not write to the Store")
        left = sorted(path.name for path in (Path(self.home) / "run").iterdir())
        self.assertEqual(left, ["generation", "service-stop", "service.json"])

    def test_an_unrouted_request_is_refused_before_any_grant_exists(self):
        self._prepared()
        events, thread = self._product()
        self._ready_doc(events)
        self.assertFalse((Path(self.home) / "run" / "shared-grants").exists())
        host_dir = Path(self.home) / "shared-host"
        token = lanes.new_token()
        lanes.submit(host_dir, {"command": "read-help"}, token=token)
        reply = host_dir / ("response-" + token + ".json")
        deadline = time.monotonic() + 30
        while not reply.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(json.loads(reply.read_text())["outcome"], "error")

    def test_unknown_project_is_refused(self):
        self._init()
        self._stop_plain_service()
        events, thread = self._product(project="nope")
        thread.join(timeout=60)
        self.assertEqual(events.get(timeout=5)["error"]["code"], "LookupError")


if __name__ == "__main__":
    unittest.main()
