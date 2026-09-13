from types import SimpleNamespace

from herzchen.adapters import CodexCliBinding, HerzchenHostAdapter
from herzchen.contracts.model import (
    HostIdentity,
    HostOperation,
    HostOutcome,
    HostPort,
    HostReceipt,
    HostRequest,
    ResourceRef,
)


LAUNCHER = "/Users/hannahomalley/.local/bin/codex"


def request(operation, *, physical=None):
    return HostRequest(operation, HostIdentity("logical-1", physical),
                       ResourceRef("neutral", "packet", "packet-1", "rev-1"),
                       "ott02-scratch-readonly")


def test_injected_neutral_adapter_preserves_logical_and_physical_identity():
    class NeutralPort(HostPort):
        def __init__(self):
            super().__init__({HostOperation.INVOKE})

        def execute(self, value):
            return HostReceipt(value.operation, HostOutcome.SUCCEEDED,
                               HostIdentity(value.identity.logical_agent_id, "physical-1"),
                               "request-1", value.requested_profile,
                               observed_runner="neutral-runner", process_id="process-1")

    adapter = HerzchenHostAdapter(NeutralPort(), owner="owner-1", source="source-1",
                                  worktree="worktree-1", launcher=LAUNCHER)
    receipt, envelope = adapter.invoke(request(HostOperation.INVOKE))
    assert receipt.identity.logical_agent_id == "logical-1"
    assert receipt.identity.physical_session_id == "physical-1"
    assert envelope.logical_agent_id == "logical-1"
    assert envelope.physical_session_id == "physical-1"


def test_preflight_and_invoke_command_shape(monkeypatch, tmp_path):
    observed_commands = []

    def fake_run(command, **kwargs):
        observed_commands.append(command)
        return SimpleNamespace(returncode=0, stdout="codex-cli 0.150.1\n", stderr="")

    class FakeProcess:
        pid = 4242
        returncode = 0

        def communicate(self, prompt, timeout):
            assert prompt.startswith("Return exactly READY")
            return ('{"type":"thread.started","thread_id":"physical-1",'
                    '"model":"gpt-5.6-luna","reasoning_effort":"high"}\n'), ""

    monkeypatch.setattr("herzchen.adapters.host.subprocess.run", fake_run)
    monkeypatch.setattr("herzchen.adapters.host.subprocess.Popen",
                        lambda command, **kwargs: (observed_commands.append(command) or FakeProcess()))
    evidence = tmp_path / "invoke.jsonl"
    binding = CodexCliBinding("/scratch/ott02", evidence_path=str(evidence),
                             prompt="Return exactly READY. Do not inspect, create, or modify files;")
    assert binding.preflight()["command"] == [LAUNCHER, "--version"]
    adapter = HerzchenHostAdapter(binding, owner="owner-1", source="source-1",
                                  worktree="/scratch/ott02", launcher=LAUNCHER)
    receipt, envelope = adapter.invoke(request(HostOperation.INVOKE))
    assert receipt.outcome == HostOutcome.SUCCEEDED
    assert envelope.physical_session_id == "physical-1"
    assert envelope.command == tuple(observed_commands[-1])
    assert observed_commands[-1] == [LAUNCHER, "exec", "-C", "/scratch/ott02", "-m",
                                     "gpt-5.6-luna", "-c", "model_reasoning_effort=high",
                                     "-s", "read-only", "--json", "-"]
    assert evidence.read_text() == '{"type":"thread.started","thread_id":"physical-1","model":"gpt-5.6-luna","reasoning_effort":"high"}\n'


def test_resume_reuses_only_supplied_physical_identity(monkeypatch, tmp_path):
    commands = []

    class FakeProcess:
        pid = 4343
        returncode = 0

        def communicate(self, prompt, timeout):
            assert prompt.startswith("Return exactly CORRECTED")
            return '{"type":"turn.completed","model":"gpt-5.6-luna"}\n', ""

    monkeypatch.setattr("herzchen.adapters.host.subprocess.Popen",
                        lambda command, **kwargs: (commands.append(command) or FakeProcess()))
    binding = CodexCliBinding("/scratch/ott02", evidence_path=str(tmp_path / "resume.jsonl"),
                             prompt="Return exactly CORRECTED. Do not inspect, create, or modify files;")
    adapter = HerzchenHostAdapter(binding, owner="owner-1", source="source-1",
                                  worktree="/scratch/ott02", launcher=LAUNCHER)
    receipt, envelope = adapter.resume(request(HostOperation.RESUME, physical="physical-1"))
    assert receipt.outcome == HostOutcome.SUCCEEDED
    assert receipt.identity.physical_session_id == "physical-1"
    assert envelope.reconciliation is None
    assert commands[0] == [LAUNCHER, "exec", "resume", "physical-1", "-m",
                           "gpt-5.6-luna", "-c", "model_reasoning_effort=high", "--json", "-"]


def test_unsupported_and_unknown_delivery_are_recoverable(monkeypatch, tmp_path):
    binding = CodexCliBinding("/scratch/ott02", evidence_path=str(tmp_path / "unknown.jsonl"))
    adapter = HerzchenHostAdapter(binding, owner="owner-1", source="source-1",
                                  worktree="/scratch/ott02", launcher=LAUNCHER)
    unsupported, unsupported_envelope = adapter.send(request(HostOperation.SEND, physical="physical-1"))
    assert unsupported.outcome == HostOutcome.UNSUPPORTED
    assert unsupported_envelope.delivery_state == "unknown"

    class UnknownProcess:
        pid = 4444
        returncode = 0

        def communicate(self, prompt, timeout):
            return '{"type":"turn.completed","model":"gpt-5.6-luna"}\n', ""

    monkeypatch.setattr("herzchen.adapters.host.subprocess.Popen",
                        lambda command, **kwargs: UnknownProcess())
    unknown, unknown_envelope = adapter.invoke(request(HostOperation.INVOKE))
    assert unknown.outcome == HostOutcome.UNKNOWN
    assert unknown.identity.physical_session_id is None
    assert unknown_envelope.reconciliation == "session unresolved"
    assert unknown_envelope.delivery_state == "unknown"
