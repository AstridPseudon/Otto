"""SUP-02 bridge-repair evidence against the qualified installed runtime.

These tests deliberately assert the boundary of the shipped host binding. A
logical target in ``HostRequest.target`` must not be mistaken for a native
conversation route when the binding does not consume it.
"""

from herzchen.adapters import CodexCliBinding
from herzchen.contracts.model import HostIdentity, HostOperation, HostOutcome, HostRequest, ResourceRef


def _request(operation=HostOperation.INVOKE, *, physical=None):
    return HostRequest(
        operation,
        HostIdentity("logical-manager", physical),
        ResourceRef("work", "conversation", "manager-native-01a0b384-c87a-78e2-ae76-33e9ea9cf8cb", "rev-2"),
        "normal",
    )


def test_qualified_binding_exposes_no_trigger_lifecycle_operations():
    binding = CodexCliBinding("/tmp/sup02-bridge-repair", prompt="Return exactly READY.")
    assert binding.preflight()["available"] is True
    assert binding.supports(HostOperation.INVOKE)
    assert binding.supports(HostOperation.RESUME)
    assert not binding.supports(HostOperation.SEND)
    assert not binding.supports(HostOperation.INSPECT)
    assert not binding.supports(HostOperation.CANCEL)
    assert not binding.supports(HostOperation.WAIT)
    assert not callable(getattr(binding, "ensure_trigger", None))
    assert not callable(getattr(binding, "pause_trigger", None))
    assert not callable(getattr(binding, "read_trigger", None))


def test_invoke_does_not_route_by_host_request_target(monkeypatch):
    commands = []

    class FakeProcess:
        pid = 90202
        returncode = 0

        def communicate(self, prompt, timeout):
            assert prompt == "Return exactly READY."
            return '{"type":"thread.started","thread_id":"new-session","model":"gpt-5.6-luna"}\n', ""

    monkeypatch.setattr(
        "herzchen.adapters.host.subprocess.Popen",
        lambda command, **kwargs: (commands.append(command) or FakeProcess()),
    )
    binding = CodexCliBinding("/tmp/sup02-bridge-repair", prompt="Return exactly READY.")
    receipt, metadata = binding.execute(_request())
    assert receipt.outcome == HostOutcome.SUCCEEDED
    assert receipt.identity.physical_session_id == "new-session"
    assert metadata["reconciliation"] is None
    assert "manager-native-01a0b384-c87a-78e2-ae76-33e9ea9cf8cb" not in commands[0]
    assert commands[0][:2] == [binding.launcher, "exec"]


def test_resume_requires_observed_physical_identity_and_preserves_unknown():
    binding = CodexCliBinding("/tmp/sup02-bridge-repair", prompt="Return exactly RESUMED.")
    receipt, metadata = binding.execute(_request(HostOperation.RESUME))
    assert receipt.outcome == HostOutcome.UNKNOWN
    assert receipt.unsupported_reason == "resume requires supplied physical session identity"
    assert metadata["delivery_state"] == "unknown"
