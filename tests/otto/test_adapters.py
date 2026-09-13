import pytest

from otto.agents import OttoGateway, Responsibility
from otto.cli import main


def responsibility(operation="invoke", *, physical=None, digest="packet-digest"):
    return Responsibility("owner-1", "logical-1", operation, digest,
                          physical_session_id=physical)


def test_read_status_and_inspect_are_non_mutating(capsys):
    gateway = OttoGateway(binding_available=False, authority_available=False)
    assert gateway.read()["queue"] == "none"
    assert gateway.status()["status"] == "blocked"
    result = gateway.inspect(responsibility("inspect"))
    assert result["observed"] is False and result["state"] == "unknown"
    with pytest.raises(SystemExit) as help_exit:
        main(["--help"])
    assert help_exit.value.code == 0


def test_preflight_rejects_unavailable_binding_and_missing_identity():
    unavailable = OttoGateway(binding_available=False)
    result = unavailable.invoke(responsibility(), object())
    assert result["error"]["code"] == "binding_unavailable"
    gateway = OttoGateway(object())
    result = gateway.resume(responsibility("resume"), object())
    assert result["error"]["code"] == "missing_physical_session"


def test_all_operations_delegate_to_one_injected_adapter():
    class FakeAdapter:
        def __init__(self): self.calls = []
        def __getattr__(self, operation):
            def call(request):
                self.calls.append((operation, request))
                return {"outcome": "unknown", "operation": operation}
            return call

    adapter = FakeAdapter()
    gateway = OttoGateway(adapter)
    for operation in ("invoke", "resume", "send", "cancel", "wait"):
        session = "session-1" if operation in {"resume", "send", "cancel"} else None
        result = gateway.operation(responsibility(operation, physical=session), "packet")
        assert result["outcome"] == "unknown"
    assert [call[0] for call in adapter.calls] == ["invoke", "resume", "send", "cancel", "wait"]


def test_unsupported_adapter_operation_is_explicit():
    class OnlyInspect:
        def inspect(self, request): return {"outcome": "unknown"}
    result = OttoGateway(OnlyInspect()).invoke(responsibility(), "packet")
    assert result["error"]["code"] == "unsupported_operation"


def test_cli_status_and_inspect(capsys):
    assert main(["dry-run"]) == 0
    assert '"effects": "none"' in capsys.readouterr().out
    assert main(["status"]) == 0
    assert '"status": "blocked"' in capsys.readouterr().out
    assert main(["inspect", "logical-1", "--owner", "owner-1"]) == 0
    assert '"observed": false' in capsys.readouterr().out
    assert main(["invoke", "logical-1", "--owner", "owner-1", "--packet-digest", "digest"]) == 0
    assert '"code": "authority_unavailable"' in capsys.readouterr().out
