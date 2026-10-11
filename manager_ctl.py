#!/usr/bin/env python3
"""Thin client for the live owner-held Otto manager command port."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

_RUN = Path(__file__).resolve().parent.parent
# Defaults are the original Codex-run layout. A host selects its own port with
# OTTO_MANAGER_CONFIG (a JSON object, e.g. host.json's "manager_port") and/or
# the individual OTTO_MANAGER_* variables; a variable beats the file.
DEFAULTS = {
    "ipc_dir": str(_RUN / "controller" / "manager-ipc"),
    "service_socket": "/tmp/otto-project-advisor-manager-ops.sock",
    "offline_reader": str(_RUN / "controller" / "read_manager_status.py"),
    "status_owner": str(_RUN / "controller" / "manager-status-owner.json"),
    "owner_python": "/Users/hannahomalley/Documents/Codex/2026-09-27/ba/.otto/runs/otto-worker-project-readiness-20260927/work/o12/d97-successor-integration/env/bin/python",
    "tasks": [f"PA0{i}" for i in range(1, 7)],
}
ENVIRONMENT = {"ipc_dir": "OTTO_MANAGER_IPC", "service_socket": "OTTO_MANAGER_SERVICE_SOCKET",
               "offline_reader": "OTTO_MANAGER_OFFLINE_READER", "status_owner": "OTTO_MANAGER_STATUS_OWNER",
               "owner_python": "OTTO_OWNER_PYTHON", "tasks": "OTTO_MANAGER_TASKS"}


def load_port_config(environ=None) -> dict:
    """Resolve the manager command port: env var > OTTO_MANAGER_CONFIG > default."""
    environ = os.environ if environ is None else environ
    config = dict(DEFAULTS)
    source = environ.get("OTTO_MANAGER_CONFIG")
    if source:
        loaded = json.loads(Path(source).read_text())
        loaded = loaded.get("manager_port", loaded) if isinstance(loaded, dict) else loaded
        if not isinstance(loaded, dict) or set(loaded) - set(DEFAULTS):
            raise RuntimeError("OTTO_MANAGER_CONFIG must be an object with keys " + ", ".join(sorted(DEFAULTS)))
        config.update({key: value for key, value in loaded.items() if value is not None})
    for key, name in ENVIRONMENT.items():
        if environ.get(name):
            config[key] = environ[name].split(",") if key == "tasks" else environ[name]
    tasks = config["tasks"]
    if (not isinstance(tasks, list) or not tasks or len(tasks) > 256
            or any(not isinstance(task, str) or not task.strip() for task in tasks)):
        raise RuntimeError("manager port tasks must be a nonempty list of task aliases")
    config["tasks"] = [task.strip() for task in tasks]
    return config


PORT = load_port_config()
IPC = Path(PORT["ipc_dir"])
SERVICE = Path(PORT["service_socket"])
OFFLINE_READER = Path(PORT["offline_reader"])
STATUS_OWNER = Path(PORT["status_owner"])
OWNER_PYTHON = Path(PORT["owner_python"])
TASKS = list(PORT["tasks"])


def call(payload: dict) -> dict:
    retained_status = False
    if payload.get("command") == "status" and not SERVICE.exists():
        try:
            owner_pid = json.loads(STATUS_OWNER.read_text())["pid"]
            os.kill(int(owner_pid), 0)
            retained_status = True
        except PermissionError:
            # Managed sandboxes may deny cross-process liveness probes even
            # when the owner file is readable and the file-IPC service is live.
            # Keep the bounded IPC status path; it will still fail closed if
            # no response arrives.
            retained_status = True
        except (FileNotFoundError, KeyError, ValueError, ProcessLookupError,
                json.JSONDecodeError):
            retained_status = False
    if payload.get("command") == "status" and not SERVICE.exists() and not retained_status:
        completed = subprocess.run(
            [str(OWNER_PYTHON), str(OFFLINE_READER)],
            text=True, capture_output=True, timeout=10,
        )
        if completed.returncode != 0:
            raise RuntimeError("offline owner status failed: " + completed.stderr.strip())
        return json.loads(completed.stdout)
    token = uuid.uuid4().hex
    request = IPC / ("request-" + token + ".json")
    response = IPC / ("response-" + token + ".json")
    if not IPC.is_dir():
        raise RuntimeError("owner command channel is unavailable")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(request, flags, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(payload, stream, separators=(",", ":"))
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    status_deadline = time.monotonic() + 5 if payload.get("command") == "status" else None
    while status_deadline is None or time.monotonic() < status_deadline:
        try:
            value = json.loads(response.read_text())
        except FileNotFoundError:
            if status_deadline is None and not SERVICE.exists() and not STATUS_OWNER.exists():
                raise RuntimeError(
                    "owner command service ended before a terminal response; "
                    "inspect the exact canonical request without retry"
                )
            time.sleep(0.1)
            continue
        response.unlink(missing_ok=True)
        return value
    raise TimeoutError("read-only status service did not respond within five seconds")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="read current canonical project/task/assignment state")
    continuation = commands.add_parser("manager-continue", help="consume an explicit durable same-manager report")
    continuation.add_argument("--report-key", required=True)
    continuation.add_argument("--operation", choices=["status", "prepare", "dispatch", "dispose-no-overlap", "mandate-status", "reconcile-manager-task", "preprovider-status", "dispose-preprovider"], default="prepare")
    continuation.add_argument("--request-key")
    continuation.add_argument("--disposition", choices=["root-host-recovery", "fresh-explicit-manager-continuation"])
    continuation.add_argument("--new-report-key")
    for name in ("attempt-sha256", "callback-due-sha256", "mandate-sha256"):
        continuation.add_argument("--expected-" + name)
    for name in ("current-schedule-id", "continuation-schedule-id", "project-id", "manager",
                 "native-session-id", "latest-turn-id"):
        continuation.add_argument("--expected-" + name)
    for name in ("current-version", "continuation-version", "generation"):
        continuation.add_argument("--expected-" + name, type=int)
    for name in ("report-task-ref", "execution-task-ref", "mandate-ref", "assignment-ref", "report-ref"):
        continuation.add_argument("--expected-" + name, type=json.loads)
    report = commands.add_parser("report", help="append a canonical manager progress report")
    report.add_argument("--task", required=True, choices=TASKS)
    report.add_argument("--summary", required=True)
    report.add_argument("--next-action", required=True)
    report.add_argument("--request-key", required=True)
    report.add_argument("--continue-project", action="store_true",
                        help="persist a same-manager request; consume with manager-continue --report-key")
    task_state = commands.add_parser("task-state", help="update one canonical task lifecycle through the owner work port")
    task_state.add_argument("--task", required=True, choices=TASKS)
    task_state.add_argument("--lifecycle", required=True, choices=["pending", "active", "paused", "withdrawn"])
    task_state.add_argument("--request-key", required=True)
    pair = commands.add_parser(
        "project-advisor-pair",
        help="read or create the one advisor assignment for the current manager",
    )
    pair.add_argument("--request-key", required=True)
    pair.add_argument("--advisor-principal",
                      help="omit for a read-only current-pair lookup")
    pair.add_argument("--pin", action="append", dest="pins", default=[],
                      help="exact owner resource-ref JSON; repeat for adopted inputs")
    advisor_start = commands.add_parser(
        "advisor-start", help="launch the current paired project advisor and ask one concrete question",
    )
    advisor_start.add_argument("--request-key", required=True)
    advisor_start.add_argument("--question", required=True)
    advisor_wake = commands.add_parser(
        "advisor-wake", help="resume the exact paired advisor session to inspect manager effect",
    )
    advisor_wake.add_argument("--request-key", required=True)
    advisor_wake.add_argument("--focus", required=True)
    advisor_deliver = commands.add_parser(
        "advisor-deliver", help="persist and receive one decision from the paired advisor",
    )
    advisor_deliver.add_argument("--request-key", required=True)
    advisor_deliver.add_argument("--decision-id", required=True)
    advisor_deliver.add_argument("--action", required=True)
    advisor_deliver.add_argument("--rationale", required=True)
    advisor_deliver.add_argument("--evidence", action="append", required=True)
    advisor_deliver.add_argument("--expected-evidence", required=True)
    advisor_recover = commands.add_parser(
        "advisor-delivery-recover",
        help="reconcile one started/unknown advisor delivery by owner readback without resend",
    )
    advisor_recover.add_argument("--decision-id", required=True)
    advisor_state = commands.add_parser(
        "advisor-decision-state",
        help="read persisted, sent, acknowledged, implemented, and effect-observed state",
    )
    advisor_state.add_argument("--decision-id", required=True)
    manager_state = commands.add_parser(
        "advisor-manager-state",
        help="record manager acknowledgement, implementation, or observed effect for a delivered decision",
    )
    manager_state.add_argument("--request-key", required=True)
    manager_state.add_argument("--decision-id", required=True)
    manager_state.add_argument(
        "--state", required=True,
        choices=["acknowledged", "implemented", "effect_observed"],
    )
    manager_state.add_argument("--evidence", action="append", required=True)
    followup = commands.add_parser(
        "advisor-followup-schedule",
        help="schedule the delivered decision's same-advisor effect check from its native delivery time",
    )
    followup.add_argument("--request-key", required=True)
    followup.add_argument("--decision-id", required=True)
    followup.add_argument("--interval-seconds", required=True, type=int)
    followup_tick = commands.add_parser(
        "advisor-followup", help="read an existing follow-up; explicit dispatch uses owner admission",
    )
    followup_tick.add_argument("--schedule-id", required=True)
    followup_tick.add_argument("--decision-id", required=True)
    followup_tick.add_argument("--operation", choices=["status", "dispatch"], default="status",
                               help="status is read-only; dispatch may claim the existing occurrence")
    lifecycle = commands.add_parser("advisor-followup-lifecycle", help="supplemental guard checks or read-only host capability; proves no host lifecycle")
    lifecycle.add_argument("--schedule-id", required=True)
    lifecycle.add_argument("--decision-id", required=True)
    lifecycle.add_argument("--automation-id", required=True)
    lifecycle.add_argument("--operation", choices=["guard-exercise", "host-capability"], default="guard-exercise")
    paused_host = commands.add_parser(
        "advisor-followup-bind-paused", help="bind and acknowledge one existing paused owner automation",
    )
    paused_host.add_argument("--schedule-id", required=True)
    paused_host.add_argument("--decision-id", required=True)
    paused_host.add_argument("--automation-id", required=True)
    paused_host.add_argument("--expected-version", required=True, type=int)
    paused_host.add_argument("--request-key", required=True)
    advisor_correct = commands.add_parser(
        "advisor-delivery-correct",
        help="append a correction for a historical false sent claim",
    )
    advisor_correct.add_argument("--request-key", required=True)
    advisor_correct.add_argument("--decision-id", required=True)
    advisor_correct.add_argument("--reason", required=True)
    advisor_correct.add_argument("--evidence", action="append", required=True)
    assessment = commands.add_parser("manager-assessment", help="record inspected assessment/acceptance through the current manager owner")
    assessment.add_argument("--task", required=True, choices=TASKS)
    assessment.add_argument("--operation", required=True,
                            choices=["declare-scope", "freeze-input", "select-candidate", "assess", "accept", "close-finding", "coverage"])
    assessment.add_argument("--arguments", required=True, type=json.loads,
                            help="operation-specific JSON object; exact owner refs, no actor overrides")
    assessment.add_argument("--request-key", required=True)
    assessment.add_argument("--expected-task-ref", required=True, type=json.loads)
    assessment.add_argument("--expected-assignment-ref", required=True, type=json.loads)
    assessment.add_argument("--expected-generation", required=True, type=int)
    assessment_pool = commands.add_parser(
        "manager-assessment-pool",
        help="admit the bounded local assessment-accounting pool (never the advisor model pool)",
    )
    assessment_pool.add_argument("--task", required=True, choices=TASKS)
    assessment_pool.add_argument("--request-key", required=True)
    assessment_pool.add_argument("--expected-task-ref", required=True, type=json.loads)
    assessment_pool.add_argument("--expected-assignment-ref", required=True, type=json.loads)
    assessment_pool.add_argument("--expected-generation", required=True, type=int)
    gate = commands.add_parser("completion-gate", help="read provisional owner completion blockers; records no acceptance")
    gate.add_argument("--task", required=True, choices=TASKS)
    gate.add_argument("--candidate-ref", help="exact current candidate resource-ref JSON")
    gate.add_argument("--gate-ref", action="append", dest="gate_refs", default=[],
                      help="exact accepted assessment decision-ref JSON; repeat")
    gate.add_argument("--evidence-ref", action="append", dest="evidence_refs", default=[],
                      help="exact retained evidence resource-ref JSON; repeat")
    gate.add_argument("--evidence-hash", action="append", dest="evidence_hashes", default=[],
                      help="SHA256 digest aligned with each evidence-ref; repeat in the same order")
    complete = commands.add_parser(
        "complete-task", help="request guarded canonical task completion with exact evidence refs",
    )
    complete.add_argument("--task", required=True, choices=TASKS)
    complete.add_argument("--request-key", required=True)
    complete.add_argument("--disposition", required=True)
    complete.add_argument("--evidence-ref", action="append", dest="evidence_refs", required=True,
                          help="exact resource-ref JSON; repeat for all evidence")
    complete.add_argument("--evidence-hash", action="append", dest="evidence_hashes", required=True,
                          help="label=sha256; repeat for all evidence")
    complete.add_argument("--gate-ref", action="append", dest="gate_refs", required=True,
                          help="exact accepted assessment gate-ref JSON; repeat for all gates")
    for name in ("candidate", "result", "attempt"):
        complete.add_argument("--" + name + "-ref", dest=name + "_ref",
                              help="exact owner resource-ref JSON for " + name)
    complete.add_argument("--source-set-digest",
                          help="digest of the reviewed source set, when required by the gate")
    commit = commands.add_parser("commit", help="create one owner-authorized local Git checkpoint")
    commit.add_argument("--message", required=True)
    commit.add_argument("--path", action="append", dest="paths", required=True,
                        help="worktree-relative path; repeat for multiple paths")
    assign = commands.add_parser("assign-worker", help="create one canonical worker assignment and adopted task guide")
    assign.add_argument("--task", required=True, choices=TASKS)
    assign.add_argument("--principal", required=True)
    assign.add_argument("--route", required=True, choices=["normal", "xhard"])
    assign.add_argument("--request-key", required=True)
    run = commands.add_parser("run-worker", help="assign, launch, and collect one canonical bounded worker")
    run.add_argument("--task", required=True, choices=TASKS)
    run.add_argument("--principal", required=True)
    run.add_argument("--route", required=True, choices=["normal", "xhard"])
    run.add_argument("--request-key", required=True)
    run.add_argument("--focus", help="task-specific outcome or integration constraint to include in the worker brief")
    resume = commands.add_parser("resume-worker", help="resume and collect one inspected interrupted worker")
    resume.add_argument("--task", required=True, choices=TASKS)
    resume.add_argument("--principal", required=True)
    resume.add_argument("--route", required=True, choices=["normal", "xhard"])
    resume.add_argument("--request-key", required=True)
    args = parser.parse_args(argv)
    payload = vars(args)
    response = call(payload)
    print(json.dumps(response, indent=2, sort_keys=True))
    if args.command == "advisor-followup-bind-paused" and response.get("outcome") == "reconciled":
        return
    if response.get("outcome") not in {
        "ok", "committed", "replayed", "created", "read", "started", "corrected", "recorded",
        "scheduled", "completed", "returned", "prepared", "idle",
    }:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
