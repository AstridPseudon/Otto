"""Focused lifecycle checks for owner command transports."""
import os
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from herzchen import command_ports as cp


class _Facade:
    endpoints = ("status",)

    def status(self, marker=0):
        return {"ok": True, "marker": marker}


class CommandPortsLifecycleTests(unittest.TestCase):
    def test_socket_is_bound_only_when_transport_is_activated_and_close_releases_it(self):
        with tempfile.TemporaryDirectory() as root:
            transport = cp._start_service(_Facade(), "test.domain", "test.Facade", ("status",), None, root)
            service = cp._OWNER_SERVICES[transport.session_id]
            directory = os.path.dirname(transport.socket_path)
            self.assertIsNone(service.socket)
            self.assertFalse(os.path.exists(transport.socket_path))

            # Same process calls use the retained facade without socket activation.
            self.assertEqual(cp.connect_consumer_facade(transport).status(), {"ok": True, "marker": 0})
            self.assertFalse(os.path.exists(transport.socket_path))

            cp._activate_transport(transport)
            self.assertTrue(os.path.exists(transport.socket_path))
            actual_getpid = cp.os.getpid
            cp.os.getpid = lambda: transport.owner_pid + 1
            try:
                cp.close_consumer_facade(transport)
                self.assertTrue(os.path.exists(transport.socket_path))
            finally:
                cp.os.getpid = actual_getpid
            cp.close_consumer_facade(transport)
            self.assertFalse(os.path.exists(directory))

    def test_cross_process_client_uses_activated_socket_and_audit_is_bounded(self):
        with tempfile.TemporaryDirectory() as root:
            transport = cp._start_service(_Facade(), "test.domain", "test.Facade", ("status",), None, root)
            service = cp._OWNER_SERVICES[transport.session_id]
            cp._activate_transport(transport)
            descriptor = json.dumps(transport.to_dict())
            child_code = (
                "import json,sys; from herzchen import command_ports as cp; "
                "t=cp.SerializedFacadeTransport.from_dict(json.loads(sys.argv[1])); "
                "print(json.dumps(cp.connect_consumer_facade(t).status()))"
            )
            child = subprocess.run([sys.executable, "-c", child_code, descriptor],
                env={**os.environ, "PYTHONPATH": os.pathsep.join(["src", os.environ.get("PYTHONPATH", "")])},
                capture_output=True, text=True, timeout=10)
            self.assertEqual(child.returncode, 0, child.stderr)
            self.assertEqual(json.loads(child.stdout), {"ok": True, "marker": 0})
            remote = cp.SerializedFacadeTransport(transport.socket_path, transport.token, transport.domain_id,
                transport.facade, transport.endpoints, transport.schema_revision, os.getpid() + 1, transport.session_id)
            client = cp.connect_consumer_facade(remote)
            try:
                for marker in range(cp._AUDIT_LIMIT + 9):
                    self.assertEqual(client.status(marker), {"ok": True, "marker": marker})
                audit = cp.consumer_facade_audit(transport)
                self.assertEqual(len(audit), cp._AUDIT_LIMIT)
                oldest_payload = cp.decode_wire(audit[0]["request"]["bindings"]["payload"])
                newest_payload = cp.decode_wire(audit[-1]["request"]["bindings"]["payload"])
                self.assertEqual(oldest_payload["args"], (9,))
                self.assertEqual(newest_payload["args"], (cp._AUDIT_LIMIT + 8,))
                self.assertEqual(cp.decode_wire(audit[-1]["response"]["result"]),
                    {"ok": True, "marker": cp._AUDIT_LIMIT + 8})
            finally:
                cp.close_consumer_facade(transport)

    def test_thread_start_failure_releases_new_listener(self):
        class FailedThread:
            def __init__(self, *args, **kwargs):
                pass

            def start(self):
                raise RuntimeError("thread start failed")

        with tempfile.TemporaryDirectory() as root:
            transport = cp._start_service(_Facade(), "test.domain", "test.Facade", ("status",), None, root)
            service = cp._OWNER_SERVICES[transport.session_id]
            with patch.object(cp.threading, "Thread", FailedThread):
                with self.assertRaisesRegex(RuntimeError, "thread start failed"):
                    service.activate()
            self.assertIsNone(service.socket)
            self.assertFalse(os.path.exists(transport.socket_path))
            cp.close_consumer_facade(transport)


if __name__ == "__main__":
    unittest.main()
