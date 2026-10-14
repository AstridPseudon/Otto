"""Finite, inert-by-default Codex CLI host adapter.

This module prepares one absolute argv/stdin operation behind Herzchen's
public HostRequest/HostReceipt contracts.  It has no scheduler, socket,
ledger, retry loop, or automatic launch.  Tests inject a process factory;
production callers must still pass the owner claim through OttoGateway.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import selectors
import subprocess
import time
from typing import Any, Callable, Iterable, Mapping, Optional


from herzchen.usage.capture import UsageStream

RUNNER_ID = "codex-cli"


class CodexCliAdapterError(ValueError):
    """Invalid or unsafe bounded CLI adapter input."""


class LaunchUncertainError(RuntimeError):
    """The process factory cannot prove whether a process was created."""


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise CodexCliAdapterError(f"{field} must be non-blank text")
    return value.strip()


def _json_copy(value: Any, field: str = "value") -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise CodexCliAdapterError(f"{field} must contain finite JSON") from exc


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _host_event(item: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only host-owned JSONL evidence, never arbitrary worker content."""

    allowed = ("type", "event_id", "thread_id", "turn_id", "model", "model_name", "reasoning_effort", "reasoning", "usage", "status")
    result = {key: _json_copy(item[key], f"host_event.{key}") for key in allowed if key in item}
    if isinstance(result.get("usage"), Mapping):
        result["usage"] = _json_copy(result["usage"], "host_event.usage")
    return result


def _worker_text(item: Mapping[str, Any]) -> Optional[str]:
    if item.get("type") != "item.completed":
        return None
    content = item.get("item")
    if not isinstance(content, Mapping) or content.get("type") not in {"agent_message", "message"}:
        return None
    text = content.get("text")
    if isinstance(text, str):
        return text
    return None


def normalize_codex_jsonl(
    lines: Iterable[str],
    *,
    on_thread_started: Optional[Callable[[str], None]] = None,
    on_usage: Optional[Callable[[Mapping[str, Any]], Any]] = None,
    adapter_id: str = "codex-direct",
    turn_resolver: Optional[Callable[[str], Optional[str]]] = None,
) -> dict[str, Any]:
    """Normalize native JSONL while separating host evidence and worker text."""

    usage_stream = UsageStream(adapter_id, on_usage=on_usage, turn_resolver=turn_resolver)
    host_events: list[dict[str, Any]] = []
    worker_content: list[str] = []
    thread_id: Optional[str] = None
    turn_id: Optional[str] = None
    observed_model: Optional[str] = None
    observed_reasoning: Optional[str] = None
    usage: Optional[Mapping[str, Any]] = None
    turn_completed = False
    invalid_lines = 0
    for raw in lines:
        completion_observation = usage_stream.feed(raw)
        try:
            item = json.loads(raw)
        except (TypeError, ValueError):
            invalid_lines += 1
            continue
        if not isinstance(item, Mapping):
            invalid_lines += 1
            continue
        event_type = item.get("type")
        if event_type == "thread.started":
            candidate = item.get("thread_id") or item.get("session_id")
            if isinstance(candidate, str) and candidate.strip() and thread_id is None:
                thread_id = candidate
                if on_thread_started is not None:
                    on_thread_started(thread_id)
            if isinstance(item.get("model"), str):
                observed_model = observed_model or item["model"]
            if isinstance(item.get("reasoning_effort"), str):
                observed_reasoning = observed_reasoning or item["reasoning_effort"]
            host_events.append(_host_event(item))
            continue
        if event_type == "turn.completed":
            turn_completed = True
            latest = completion_observation or {}
            turn_id = item.get("turn_id") or (latest.get("identity") or {}).get("turn_id")
            usage = _json_copy(item["usage"], "turn_completed.usage") if isinstance(item.get("usage"), Mapping) else None
            if isinstance(item.get("model"), str):
                observed_model = observed_model or item["model"]
            if isinstance(item.get("reasoning_effort"), str):
                observed_reasoning = observed_reasoning or item["reasoning_effort"]
            host_events.append(_host_event(item))
            continue
        text = _worker_text(item)
        if text is not None:
            worker_content.append(text)
    return {
        "host_evidence": {
            "thread_id": thread_id,
            "turn_id": turn_id,
            "thread_started": thread_id is not None,
            "turn_completed": turn_completed,
            "observed_model": observed_model,
            "observed_reasoning": observed_reasoning,
            "usage": usage,
            "events": host_events,
            "invalid_lines": invalid_lines,
        },
        "usage_capture": usage_stream.snapshot(),
        "worker_content": worker_content,
    }


class CodexCliAdapter:
    """One explicit fresh ``codex exec --json`` operation.

    Construction and argv generation are inert.  A real process is possible
    only when ``execute`` is called by an already-authorized owner path.
    """

    def __init__(
        self,
        executable: str,
        worktree: str,
        *,
        model: str,
        reasoning: str,
        config: Optional[Mapping[str, Any]] = None,
        prompt: str,
        timeout_seconds: int = 120,
        process_factory: Optional[Callable[..., Any]] = None,
        on_thread_started: Optional[Callable[[str], None]] = None,
        on_usage: Optional[Callable[[Mapping[str, Any]], Any]] = None,
        turn_resolver: Optional[Callable[[str], Optional[str]]] = None,
    ) -> None:
        self.executable = _text(executable, "executable")
        self.worktree = _text(worktree, "worktree")
        if not Path(self.executable).is_absolute():
            raise CodexCliAdapterError("executable must be an absolute path")
        if not Path(self.worktree).is_absolute():
            raise CodexCliAdapterError("worktree must be an absolute path")
        self.model = _text(model, "model")
        self.reasoning = _text(reasoning, "reasoning")
        self.prompt = _text(prompt, "prompt")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or timeout_seconds <= 0:
            raise CodexCliAdapterError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds
        raw_config = {} if config is None else _json_copy(config, "config")
        if not isinstance(raw_config, Mapping):
            raise CodexCliAdapterError("config must be an object")
        normalized: dict[str, Any] = {}
        for key, value in raw_config.items():
            key = _text(key, "config key")
            if "bypass" in key.lower() or key.startswith("--"):
                raise CodexCliAdapterError("bypass and raw CLI flags are not allowed in config")
            if isinstance(value, (Mapping, list, tuple)):
                raise CodexCliAdapterError("config values must be scalar")
            normalized[key] = value
        configured_reasoning = normalized.get("model_reasoning_effort")
        if configured_reasoning is not None and configured_reasoning != self.reasoning:
            raise CodexCliAdapterError("config model_reasoning_effort conflicts with explicit reasoning")
        normalized["model_reasoning_effort"] = self.reasoning
        self.config = normalized
        self._process_factory = process_factory or subprocess.Popen
        self._on_thread_started = on_thread_started
        self._on_usage = on_usage
        self._turn_resolver = turn_resolver

    def set_thread_started_callback(self, callback: Optional[Callable[[str], None]]) -> Optional[Callable[[str], None]]:
        """Install one synchronous early-identity callback and return prior state."""

        if callback is not None and not callable(callback):
            raise CodexCliAdapterError("thread.started callback must be callable")
        prior = self._on_thread_started
        self._on_thread_started = callback
        return prior

    def set_usage_callback(self, callback):
        if callback is not None and not callable(callback):
            raise CodexCliAdapterError("usage callback must be callable")
        prior, self._on_usage = self._on_usage, callback
        return prior

    def build_argv(self, operation: Any = "invoke", physical_session_id: Optional[str] = None) -> list[str]:
        operation_value = getattr(operation, "value", operation)
        if operation_value == "resume":
            session_id = _text(physical_session_id, "physical_session_id")
            argv = [self.executable, "exec", "-C", self.worktree, "-m", self.model]
        elif operation_value == "invoke":
            if physical_session_id is not None:
                raise CodexCliAdapterError("fresh invoke cannot receive an existing session")
            argv = [self.executable, "exec", "-C", self.worktree, "-m", self.model]
        else:
            raise CodexCliAdapterError("unsupported host operation")
        for key in sorted(self.config):
            value = self.config[key]
            if isinstance(value, bool):
                rendered = "true" if value else "false"
            else:
                rendered = str(value)
            argv.extend(["-c", f"{key}={rendered}"])
        argv.extend(["-s", "read-only", "--json"])
        if operation_value == "resume":
            argv.extend(["resume", session_id])
        argv.append("-")
        return argv

    def supports(self, operation: Any) -> bool:
        return getattr(operation, "value", operation) in {"invoke", "INVOKE", "resume", "RESUME"}

    def _write_prompt(self, process: Any, deadline: float) -> None:
        stream = process.stdin
        if stream is None:
            return
        payload = self.prompt.encode("utf-8")
        try:
            fd = stream.fileno()
            os.set_blocking(fd, False)
        except (AttributeError, OSError, ValueError):
            stream.write(self.prompt)
            stream.close()
            return
        selector = selectors.DefaultSelector()
        try:
            selector.register(fd, selectors.EVENT_WRITE)
            offset = 0
            while offset < len(payload):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(self.executable, self.timeout_seconds)
                if not selector.select(remaining):
                    raise subprocess.TimeoutExpired(self.executable, self.timeout_seconds)
                try:
                    offset += os.write(fd, payload[offset:])
                except BlockingIOError:
                    continue
            stream.close()
        finally:
            selector.close()

    def execute(self, request: Any) -> tuple[Any, Mapping[str, Any]]:
        from herzchen.contracts import HostIdentity, HostOperation, HostOutcome, HostReceipt, HostRequest

        if not isinstance(request, HostRequest) or request.operation not in {HostOperation.INVOKE, HostOperation.RESUME}:
            identity = request.identity if isinstance(request, HostRequest) else HostIdentity("unknown")
            operation = request.operation if isinstance(request, HostRequest) else HostOperation.INVOKE
            return HostReceipt(operation, HostOutcome.UNSUPPORTED, identity, identity.logical_agent_id, unsupported_reason="CodexCliAdapter supports invoke and exact-ID resume only"), {"launch_state": "not_started"}
        if request.operation == HostOperation.INVOKE and request.identity.physical_session_id:
            return HostReceipt(request.operation, HostOutcome.UNSUPPORTED, request.identity, request.identity.logical_agent_id, request.requested_profile, unsupported_reason="fresh invoke cannot receive an existing session"), {"launch_state": "not_started"}
        if request.operation == HostOperation.RESUME and not request.identity.physical_session_id:
            return HostReceipt(request.operation, HostOutcome.UNSUPPORTED, request.identity, request.identity.logical_agent_id, request.requested_profile, unsupported_reason="exact physical session identity is required for resume"), {"launch_state": "not_started"}
        argv = self.build_argv(request.operation, request.identity.physical_session_id)
        started_at = _now()
        process = None
        process_created = False
        parsed = normalize_codex_jsonl((), on_thread_started=self._on_thread_started)
        stderr = ""
        exit_status: Optional[int] = None
        error_text: Optional[str] = None

        usage_stream = UsageStream("codex-direct", session_id=request.identity.physical_session_id,
            requested_model=self.model, on_usage=self._on_usage, turn_resolver=self._turn_resolver)
        started_identity: Optional[str] = None

        def refresh_parsed(lines: list[str]) -> None:
            nonlocal parsed, started_identity
            usage_stream.feed(lines[-1])
            observed: list[str] = []
            parsed = normalize_codex_jsonl(lines, on_thread_started=observed.append)
            current = parsed["host_evidence"].get("thread_id")
            if current and current != started_identity:
                started_identity = current
                if self._on_thread_started is not None:
                    self._on_thread_started(current)

        def read_process_output(lines: list[str], deadline: float) -> str:
            """Drain both pipes with a single bounded selector deadline."""

            streams = (("stdout", process.stdout), ("stderr", process.stderr))
            selector = selectors.DefaultSelector()
            buffers = {"stdout": "", "stderr": ""}
            stderr_lines: list[str] = []
            registered = 0

            def consume(name: str, data: bytes) -> None:
                buffers[name] += data.decode("utf-8", errors="replace")
                while "\n" in buffers[name]:
                    line, buffers[name] = buffers[name].split("\n", 1)
                    if name == "stdout":
                        lines.append(line + "\n")
                        refresh_parsed(lines)
                    else:
                        stderr_lines.append(line + "\n")

            try:
                for name, stream in streams:
                    if stream is None:
                        continue
                    try:
                        fd = stream.fileno()
                        os.set_blocking(fd, False)
                    except (AttributeError, OSError, ValueError):
                        continue
                    selector.register(fd, selectors.EVENT_READ, name)
                    registered += 1

                if registered == 0:
                    # Injected fixtures may expose finite iterators instead of
                    # OS pipes.  Real Popen always takes the selector path.
                    if self._process_factory is subprocess.Popen:
                        raise CodexCliAdapterError("process streams must expose nonblocking file descriptors")
                    for line in process.stdout or ():
                        text = line.decode("utf-8", errors="replace") if isinstance(line, bytes) else str(line)
                        lines.append(text)
                        refresh_parsed(lines)
                    stderr_value = process.stderr.read() if process.stderr is not None else ""
                    return stderr_value.decode("utf-8", errors="replace") if isinstance(stderr_value, bytes) else str(stderr_value)

                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(self.executable, self.timeout_seconds)
                    events = selector.select(remaining)
                    if not events:
                        raise subprocess.TimeoutExpired(self.executable, self.timeout_seconds)
                    for key, _ in events:
                        try:
                            data = os.read(key.fd, 65536)
                        except BlockingIOError:
                            continue
                        if not data:
                            selector.unregister(key.fd)
                            continue
                        consume(key.data, data)

                for name, value in buffers.items():
                    if value:
                        if name == "stdout":
                            lines.append(value)
                            refresh_parsed(lines)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(self.executable, self.timeout_seconds)
                process.wait(timeout=remaining)
                return "".join(stderr_lines) + buffers["stderr"]
            finally:
                selector.close()

        try:
            process = self._process_factory(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=self.worktree, shell=False)
            process_created = True
            deadline = time.monotonic() + self.timeout_seconds
            self._write_prompt(process, deadline)
            lines: list[str] = []
            stderr = read_process_output(lines, deadline)
            exit_status = process.returncode if getattr(process, "returncode", None) is not None else process.wait(timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            error_text = "codex execution timed out"
            if process is not None:
                process.kill()
                try:
                    process.wait()
                except Exception:
                    pass
        except LaunchUncertainError as exc:
            process_created = True
            error_text = str(exc)
        except OSError as exc:
            error_text = str(exc)
            process_created = process_created or process is not None
        except Exception as exc:
            error_text = str(exc)
            process_created = process_created or process is not None
        host = parsed["host_evidence"]
        thread_id = host.get("thread_id")
        if process_created and thread_id is None:
            outcome = HostOutcome.UNKNOWN
            launch_state = "unknown_before_id"
        elif error_text is not None:
            outcome = HostOutcome.UNKNOWN if process_created else HostOutcome.FAILED
            launch_state = "unknown_after_id" if process_created and thread_id else ("unknown_before_id" if process_created else "not_started")
        elif exit_status == 0 and thread_id and host.get("turn_completed"):
            outcome = HostOutcome.SUCCEEDED
            launch_state = "identified"
        elif process_created:
            outcome = HostOutcome.UNKNOWN
            launch_state = "unknown_after_id" if thread_id else "unknown_before_id"
        else:
            outcome = HostOutcome.FAILED
            launch_state = "not_started"
        identity = HostIdentity(request.identity.logical_agent_id, thread_id)
        receipt = HostReceipt(
            request.operation, outcome, identity, request.identity.logical_agent_id,
            request.requested_profile, observed_runner=RUNNER_ID,
            process_id=None if process is None else str(getattr(process, "pid", "unknown")),
            unsupported_reason=error_text or (None if outcome == HostOutcome.SUCCEEDED else "codex result is unresolved"),
        )
        metadata = {
            "usage_capture": usage_stream.snapshot(),
            "argv": argv,
            "stdin_sha256": hashlib.sha256(self.prompt.encode("utf-8")).hexdigest(),
            "host_evidence": {**host, "requested_model": self.model, "requested_reasoning": self.reasoning, "process_created": process_created, "launch_unknown": process_created and outcome == HostOutcome.UNKNOWN, "launch_state": launch_state, "retry_allowed": False},
            "worker_content": parsed["worker_content"],
            "stderr": stderr,
            "exit_status": exit_status,
            "delivery_state": "done" if outcome == HostOutcome.SUCCEEDED else "unknown",
            "reconciliation": None if outcome == HostOutcome.SUCCEEDED else "same occurrence requires owner reconciliation",
            "started_at": started_at,
            "ended_at": _now(),
        }
        return receipt, metadata

    def invoke(self, request: Any) -> tuple[Any, Mapping[str, Any]]:
        return self.execute(request)

    def resume(self, request: Any) -> tuple[Any, Mapping[str, Any]]:
        return self.execute(request)


__all__ = ["CodexCliAdapter", "CodexCliAdapterError", "LaunchUncertainError", "normalize_codex_jsonl"]
