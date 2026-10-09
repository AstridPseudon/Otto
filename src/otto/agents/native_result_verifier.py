"""Host-selected native schema verifier; provider prose cannot select this seam."""
from __future__ import annotations
from typing import Any, Mapping


class CodexNativeResultVerifier:
    identity = "otto.codex-native-result-verifier.v1"
    final_format = "codex-cli-0.158.0-native-final-text-v1"

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
