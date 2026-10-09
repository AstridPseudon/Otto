"""Host-selected native schema verifier; provider prose cannot select this seam."""
from __future__ import annotations
from typing import Any, Mapping


class CodexNativeResultVerifier:
    identity = "otto.codex-native-result-verifier.v1"
    final_format = "codex-cli-0.158.0-native-final-text-v1"

    def capture_summary(self, evidence: Mapping[str, Any], *, result_ref: Mapping[str, Any]) -> Mapping[str, Any]:
        """Retain bounded tool-output bytes, never read a provider-selected path.

        The owner calls this only after native context/final verification. These
        are stdout artifacts from the completed native command records, not
        claims that a filesystem file was written or that a test passed.
        """
        import base64
        import hashlib
        from .herzchen_adapter import _digest
        operation = evidence.get("operation_result") or {}
        output = operation.get("output") or {}
        commands = output.get("commands", [])
        records = (evidence.get("host_records") or {}).get("commands", [])
        usage = {"state": "unavailable", "reason": "no qualified native usage summary retained"}
        if not commands:
            return {"artifacts": [], "usage": usage}
        if (evidence.get("provenance") not in {"host_command_execution/item_completed", "host_final_answer/item_completed"}
                or operation.get("status") != "completed"
                or operation.get("result_digest") != evidence.get("result_digest")
                or operation.get("result_digest") != _digest(output)
                or not isinstance(commands, list) or not isinstance(records, list)
                or len(commands) != len(records)
                or result_ref.get("kind") != "wrk.result" or not result_ref.get("revision")):
            raise ValueError("Codex stdout capture requires exact verified completed evidence")
        captured = []
        for index, (command, record) in enumerate(zip(commands, records)):
            if (not isinstance(command, Mapping) or not isinstance(record, Mapping)
                    or record.get("session_id") != evidence.get("session_id")
                    or record.get("turn_id") != evidence.get("turn_id")
                    or record.get("event_type") != "item_completed"
                    or record.get("item_type") != "CommandExecution"
                    or not isinstance(record.get("item_id"), str) or not record["item_id"]
                    or not isinstance(record.get("raw_line_sha256"), str)
                    or len(record["raw_line_sha256"]) != 64
                    or any(c not in "0123456789abcdef" for c in record["raw_line_sha256"])):
                raise ValueError("Codex stdout capture has foreign or missing native command binding")
            text = command.get("stdout")
            if command.get("status") != "completed" or type(command.get("exit_code")) is not int or command.get("exit_code") != 0 or not isinstance(text, str) or not text:
                continue
            body = text.encode("utf-8")
            if len(body) > 65536 or len(captured) == 16:
                continue
            sha = hashlib.sha256(body).hexdigest()
            captured.append({"name": "native-command-" + str(index) + ".stdout.txt",
                "tool_use_id": record["item_id"], "bytes": len(body), "sha256": sha,
                "content_base64": base64.b64encode(body).decode("ascii"),
                "ref": {"result_ref": dict(result_ref), "index": len(captured), "sha256": sha},
                "availability": "retained", "source": "verified native CommandExecution stdout and owner capture"})
        return {"artifacts": captured, "usage": usage}

    def observe_context(self, context: Any, **expected: Any) -> Mapping[str, Any]:
        from .herzchen_adapter import HerzchenCodexAdapter
        return HerzchenCodexAdapter._observed_context(context, **expected)

    def supports_final_answer(self, answer: Mapping[str, Any]) -> bool:
        return (answer.get("format") == self.final_format and answer.get("phase") == "final_answer"
                and (answer.get("host_record") or {}).get("item_type") == "AgentMessage"
                and (answer.get("host_record") or {}).get("event_type") == "item_completed")


def require_native_verifier(value: Any) -> Any:
    if (not isinstance(getattr(value, "identity", None), str) or not value.identity
            or not callable(getattr(value, "observe_context", None))
            or not callable(getattr(value, "supports_final_answer", None))):
        raise TypeError("host-owned finite native context/final schema verifier required")
    return value
