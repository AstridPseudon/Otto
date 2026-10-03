"""Thin adapter over the FND neutral HostPort.

No process, queue, persistence, or session ledger is owned here. The injected
port is the only transport authority; this layer adds truthful envelope data.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional
import ast
import hashlib
import json
import os
import subprocess
import re
import math
import shlex
import zlib
import signal
import threading
import time
from urllib.parse import unquote, urlparse
from pathlib import Path

from herzchen.contracts.model import HostOperation, HostOutcome, HostPort, HostReceipt, HostRequest, ContractError
from .receipt import AdapterReceiptEnvelope

RUNNER_ID = "codex-cli"
MAX_SUBMISSION_SIZE = 1_000_000


def _terminate_owned_process(process: Any) -> None:
    """Cancel one launched CLI occurrence without claiming provider release."""

    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (OSError, AttributeError):
        try:
            process.kill()
        except OSError:
            pass


def _communicate_after_native_start(
    process: Any,
    prompt: str,
    *,
    expected_session_id: str,
    start_timeout_seconds: float,
    monotonic_clock: Callable[[], float] = time.monotonic,
    native_start_callback: Optional[Callable[[Optional[str], str], None]] = None,
) -> tuple[str, str, int | None, bool]:
    """Bound transport/start, then retain an identified native turn to terminal.

    Ordinary owner work is not a wall-clock timer.  The finite phase ends only
    after the launched CLI reports both the exact expected thread and a native
    turn start.  From there the owning caller waits for the useful turn to
    finish, or explicitly cancels it by unwinding this call.
    """

    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    stream_lock = threading.Lock()
    native_started = threading.Event()
    thread_matched = threading.Event()
    writer_error: list[BaseException] = []
    start_callback_error: list[BaseException] = []

    def read_stdout() -> None:
        stream = process.stdout
        if stream is None:
            return
        for line in iter(stream.readline, ""):
            with stream_lock:
                stdout_parts.append(line)
            try:
                event = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(event, Mapping) and event.get("type") == "thread.started":
                if event.get("thread_id") == expected_session_id:
                    thread_matched.set()
            elif isinstance(event, Mapping) and event.get("type") == "turn.started" and thread_matched.is_set():
                turn_id = event.get("turn_id")
                if not native_started.is_set() and native_start_callback is not None:
                    try:
                        native_start_callback(
                            turn_id.strip() if isinstance(turn_id, str) and turn_id.strip() else None,
                            _now(),
                        )
                    except BaseException as exc:
                        start_callback_error.append(exc)
                native_started.set()
        stream.close()

    def read_stderr() -> None:
        stream = process.stderr
        if stream is None:
            return
        for value in iter(stream.readline, ""):
            with stream_lock:
                stderr_parts.append(value)
        stream.close()

    def write_prompt() -> None:
        try:
            if process.stdin is None:
                raise BrokenPipeError("Codex CLI stdin is unavailable")
            process.stdin.write(prompt)
            process.stdin.close()
        except BaseException as exc:  # Transport failure is reconciled below.
            writer_error.append(exc)

    readers = (
        threading.Thread(target=read_stdout, name="codex-cli-stdout", daemon=True),
        threading.Thread(target=read_stderr, name="codex-cli-stderr", daemon=True),
    )
    writer = threading.Thread(target=write_prompt, name="codex-cli-stdin", daemon=True)
    for thread in (*readers, writer):
        thread.start()
    deadline = monotonic_clock() + start_timeout_seconds
    timed_out = False
    try:
        while process.poll() is None and not native_started.is_set():
            remaining = deadline - monotonic_clock()
            if remaining <= 0:
                timed_out = True
                _terminate_owned_process(process)
                process.wait()
                break
            native_started.wait(min(0.05, remaining))
        if not timed_out:
            # There is deliberately no ordinary work-duration deadline here.
            # The owner keeps custody until the identified turn is terminal.
            process.wait()
    except BaseException:
        _terminate_owned_process(process)
        try:
            process.wait()
        finally:
            raise
    finally:
        for thread in (*readers, writer):
            thread.join(timeout=2)
    with stream_lock:
        stdout, stderr = "".join(stdout_parts), "".join(stderr_parts)
    if writer_error and not timed_out and process.returncode == 0:
        raise OSError("Codex CLI prompt transport failed") from writer_error[0]
    if start_callback_error:
        raise OSError("native turn-start capture failed") from start_callback_error[0]
    return stdout, stderr, None if timed_out else process.returncode, native_started.is_set()


def _owner_delivery_appendix(authorization: Mapping[str, Any], profile: str = "read-only",
                             read_scope: str | None = None) -> str:
    permission = (
        ("inspect the delivered context and linked sources as needed, then return the requested judgment. "
         "Do not write files or owner state."
         if read_scope == "linked_context" else
         "perform only the brief's exact read-only inspection and return evidence. "
         "Do not write files or owner state.")
        if profile == "read-only" else
        "work only inside the selected workspace-write root under the brief's mandate. "
        "Do not write owner state except through an explicit supported owner operation."
    )
    return ("\nThe receiving host has just verified the current owner gateway claim below. "
            "You may now " + permission + " This context applies only to this delivery; "
            "the owner publishes verified output.\n"
            + '<otto-owner-delivery sha256="' + _digest_json(authorization) + '">\n'
            + json.dumps(authorization, sort_keys=True, ensure_ascii=False) + "\n</otto-owner-delivery>\n")


def _linked_context_read_contract(contract: Mapping[str, Any], profile: str) -> bool:
    """Recognize the generic read-only judgment contract at the host boundary."""
    authority = contract.get("authority", {})
    allowed = set(contract.get("allowed_operations", ()))
    permitted = set(authority.get("permitted_effects", ()))
    return (
        profile == "read-only"
        and authority.get("effect_profile") is None
        and contract.get("read_scope") == "linked_context"
        and not contract.get("read_targets")
        and allowed.issubset({
            "read_project_context", "inspect_recorded_effect", "return_advice", "return_result",
        })
        and bool(allowed & {"return_advice", "return_result"})
        and {"read_delivered_context", "read_linked_sources"}.issubset(permitted)
        and permitted.issubset({
            "read_delivered_context", "read_linked_sources", "return_advice", "return_result",
        })
        and bool(permitted & {"return_advice", "return_result"})
        and authority.get("owner_write") is False
        and authority.get("dispatch") is False
    )


def _verify_model_projection(text: str, brief: Mapping[str, Any], projection: Mapping[str, Any],
                             authorization: Mapping[str, Any] | None = None) -> dict[str, str]:
    """Validate trusted Otto projection bytes at submission and native readback."""
    canonical = _digest_json(brief)
    if (not isinstance(projection, Mapping) or projection.get("schema") != "otto.o12.d241-t01-task-projection.v1"
            or projection.get("canonical_owner_brief_sha256") != canonical):
        raise ValueError("projection canonical binding mismatch")
    encoded = json.dumps(projection, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    projected = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    block = (f'<otto-task-projection canonical-brief-sha256="{canonical}" projection-sha256="{projected}">\n'
             + encoded + "\n</otto-task-projection>\n")
    expected = "Verified T01 task projection.\n" + block
    if authorization is not None:
        expected += _owner_delivery_appendix(authorization)
    if (text != expected or text.count("<otto-task-projection ") != 1
            or text.count("</otto-task-projection>") != 1 or "<otto-resource-brief" in text):
        raise ValueError("projection block bytes are malformed, duplicate or foreign")
    blocks = re.findall(r'<otto-task-projection canonical-brief-sha256="([a-f0-9]{64})" projection-sha256="([a-f0-9]{64})">\n(.*?)\n</otto-task-projection>', text, re.S)
    if (len(blocks) != 1 or blocks[0][:2] != (canonical, projected)
            or json.loads(blocks[0][2]) != projection
            or hashlib.sha256(blocks[0][2].encode("utf-8")).hexdigest() != projected):
        raise ValueError("projection digest or decoded value mismatch")
    return {"canonical_brief_sha256": canonical, "projection_sha256": projected, "schema": projection["schema"]}



_CURSOR_CORE = r"""/* Reference code for a generated functions.exec cursor; no source hashing.
 * The host must verify the full initializer bytes and SHA-256 queue digest
 * before delivery. Adler-32 catches accidental model-copy/state alterations.
 */
function adler32Ascii(value) {
  let a = 1, b = 0;
  for (let i = 0; i < value.length; i++) {
    const c = value.charCodeAt(i);
    if (c > 127) throw Error('NON_ASCII_QUEUE');
    a = (a + c) % 65521;
    b = (b + a) % 65521;
  }
  return (((b << 16) >>> 0) | a) >>> 0;
}

function cursorKeys(binding) {
  if (!binding || !/^[a-f0-9]{64}$/.test(binding.nonce || '')) throw Error('INVALID_NONCE');
  const key = 'otto.t01.cursor.' + binding.nonce;
  return [key, key + '.lock'];
}

function validateQueue(spec) {
  if (!spec || !Array.isArray(spec.queue) || spec.queue.length !== 145) throw Error('QUEUE_MISSING_OR_WRONG_LENGTH');
  const raw = JSON.stringify(spec.queue);
  if (raw.length !== spec.queue_chars || adler32Ascii(raw) !== spec.queue_adler32) throw Error('QUEUE_ALTERED');
  for (let i = 0; i < 145; i++) {
    const row = spec.queue[i];
    const kind = i < 130 ? 'cat' : i < 144 ? 'git' : 'rg';
    if (!row || row.ordinal !== i + 1 || row.kind !== kind || typeof row.cmd !== 'string' || !row.cmd) throw Error('QUEUE_GAP_OR_JUMP');
    if (kind === 'cat' && !row.cmd.startsWith('cat -- ')) throw Error('CAT_COMMAND_ALTERED');
    if (kind === 'git' && !row.cmd.startsWith('git --no-optional-locks ')) throw Error('GIT_COMMAND_ALTERED');
    if (kind === 'rg' && (!row.cmd.startsWith('/Applications/ChatGPT.app/Contents/Resources/rg ') || !row.cmd.includes(' -F '))) throw Error('RG_COMMAND_ALTERED');
  }
}

function sameBinding(a, b) {
  const fields = ['canonical_brief_sha256','projection_sha256','generation','logical_request_key','physical_session_id','turn_intent','nonce'];
  return fields.every(k => a && b && a[k] === b[k]);
}

function cursorInit(spec, store, load) {
  validateQueue(spec);
  const [key, lockKey] = cursorKeys(spec.binding);
  if (load(key) !== undefined || load(lockKey) !== undefined) throw Error('CURSOR_ALREADY_INITIALIZED_OR_RESET');
  const lock = {nonce: spec.binding.nonce, cursor: 0, pending: null, phase: 'ready'};
  const state = {spec, cursor: 0, pending: null, completed: [], notes: {}, phase: 'ready'};
  store(lockKey, lock);
  store(key, state);
  return {status: 'READY', nonce: spec.binding.nonce, cursor: 0, count: 145, queue_sha256: spec.queue_sha256};
}

function cursorRead(binding, load) {
  const [key, lockKey] = cursorKeys(binding);
  const state = load(key), lock = load(lockKey);
  if (!state || !lock || !sameBinding(state.spec.binding, binding) || lock.nonce !== binding.nonce) throw Error('STALE_OR_MISSING_BINDING');
  validateQueue(state.spec);
  if (state.cursor !== lock.cursor || state.phase !== lock.phase || state.completed.length !== state.cursor) throw Error('CURSOR_RESET_OR_GAP');
  for (let i = 0; i < state.completed.length; i++) if (state.completed[i] !== i + 1) throw Error('COMPLETION_JUMP');
  if (JSON.stringify(state.pending) !== JSON.stringify(lock.pending)) throw Error('PENDING_STATE_MISMATCH');
  return {state, lock, key, lockKey};
}

function cursorInspect(binding, load) {
  const {state} = cursorRead(binding, load);
  return {status: state.phase, nonce: binding.nonce, cursor: state.cursor,
          completed_count: state.completed.length,
          pending_ordinal: state.pending && state.pending.ordinal,
          pending_phase: state.pending && state.pending.phase,
          next_kind: state.cursor < 145 ? state.spec.queue[state.cursor].kind : null,
          receipt_withheld: true, analytical_notes_not_evidence: state.notes};
}

async function cursorStep(binding, ack, store, load, execute, emit) {
  const {state, lock, key, lockKey} = cursorRead(binding, load);
  if (state.phase === 'done') throw Error('CURSOR_ALREADY_DONE');
  if (state.pending) {
    if (state.pending.phase !== 'completed' || ack !== state.pending.receipt) throw Error('UNCERTAIN_PENDING_NO_REPLAY');
    if (state.pending.ordinal !== state.cursor + 1) throw Error('PENDING_JUMP');
    const saved = load(key + '.response.' + state.pending.ordinal);
    if (!saved || saved.receipt !== ack || saved.ordinal !== state.pending.ordinal || typeof saved.output !== 'string') throw Error('COMPLETED_OUTPUT_MISSING');
    const next = state.cursor + 1;
    lock.cursor = next; lock.pending = null;
    state.cursor = next; state.pending = null; state.completed.push(next);
    store(lockKey, lock); store(key, state);
  } else if (ack !== null) {
    throw Error('UNEXPECTED_ACK');
  }
  if (state.cursor === 145) {
    lock.phase = state.phase = 'done';
    store(lockKey, lock); store(key, state);
    emit({status: 'DONE_145_OF_145', nonce: binding.nonce, queue_sha256: state.spec.queue_sha256});
    return;
  }
  const item = state.spec.queue[state.cursor];
  const pending = {ordinal: item.ordinal, kind: item.kind, cmd: item.cmd, phase: 'prepared', receipt: null};
  lock.pending = {...pending}; state.pending = {...pending};
  store(lockKey, lock); store(key, state); // Both writes precede shell execution.
  let result;
  try { result = await execute({cmd: item.cmd, max_output_tokens: 30000, yield_time_ms: 10000}); }
  catch (error) { throw Error('EXECUTION_UNCERTAIN_NO_REPLAY: ' + String(error)); }
  if (!result || result.session_id !== undefined || result.exit_code !== 0 || typeof result.output !== 'string') {
    throw Error('COMMAND_INCOMPLETE_NO_REPLAY');
  }
  const receipt = 'o12-cursor:' + binding.nonce.slice(0, 16) + ':' + item.ordinal + ':' +
      String(result.chunk_id || 'no-chunk') + ':' + Math.random().toString(36).slice(2);
  lock.pending = {...pending, phase: 'completed', receipt};
  state.pending = {...lock.pending};
  store(key + '.response.' + item.ordinal, {ordinal:item.ordinal, receipt, output:result.output});
  store(lockKey, lock); store(key, state);
  emit(result.output); // Worker must see the full body before using the receipt below.
  emit({cursor_receipt: receipt, ordinal: item.ordinal, next_after_ack: item.ordinal + 1,
        queue_sha256: state.spec.queue_sha256});
}


function cursorRecover(binding, load, emit) {
  const {state,key} = cursorRead(binding,load);
  if (!state.pending || state.pending.phase !== 'completed') throw Error('NO_COMPLETED_OUTPUT_NO_REPLAY');
  const saved=load(key+'.response.'+state.pending.ordinal);
  if (!saved || saved.ordinal!==state.pending.ordinal || saved.receipt!==state.pending.receipt || typeof saved.output!=='string') throw Error('COMPLETED_OUTPUT_MISSING');
  emit(saved.output);
  emit({cursor_receipt:saved.receipt,ordinal:saved.ordinal,next_after_ack:saved.ordinal+1,queue_sha256:state.spec.queue_sha256});
}
function cursorNote(binding,note,store,load) {
  const {state,key}=cursorRead(binding,load);
  if (!state.pending || state.pending.phase!=='completed' || typeof note!=='string' || note.length>512) throw Error('NOTE_REQUIRES_COMPLETED_TARGET_AND_512_CHAR_BOUND');
  state.notes[state.pending.ordinal]=note;
  if (JSON.stringify(state.notes).length>8000) throw Error('ANALYTICAL_NOTES_TOTAL_BOUND');
  store(key+'.note.'+state.pending.ordinal,{ordinal:state.pending.ordinal,note,acceptance_evidence:false});
  store(key,state);
  return {status:'NOTE_STORED_NOT_EVIDENCE',ordinal:state.pending.ordinal};
}
"""

def _cursor_bundle(brief, projection, authorization, queue):
    """Generate only after current authorization; no source or process reads."""
    canonical, projected = _digest_json(brief), _digest_json(projection)
    generation = brief["resource_resolution"]["generation"]
    recipient = projection.get("owner_context", {}).get("recipient_permission_contract", {})
    if (type(generation) is not int or generation < 11 or authorization.get("generation") != generation
            or authorization.get("brief_sha256") != canonical
            or projection.get("canonical_owner_brief_sha256") != canonical
            or recipient.get("model") != "gpt-6-luna" or recipient.get("reasoning") != "xhigh"
            or recipient.get("profile") != "read-only" or recipient.get("approval_policy") != "never"
            or not all(isinstance(authorization.get(k), str) and authorization[k] for k in ("physical_session_id", "logical_request_key"))):
        raise ValueError("cursor recipient/owner binding mismatch")
    constraints = brief["operating_core"]["operational_constraints"]
    commands = ["cat -- " + shlex.quote(p) for p in brief["instruction_contract"]["read_targets"]]
    commands += constraints[6].splitlines()[1:] + constraints[7].splitlines()[1:]
    exact = [{"cmd":cmd,"kind":"cat" if i<130 else "git" if i<144 else "rg","ordinal":i+1} for i,cmd in enumerate(commands)]
    if queue != exact or _digest_json(queue) != "ca4efcc3123056554d475a70b481c2992715bba47394c5b5b76816dfafa42d10":
        raise ValueError("cursor canonical command queue mismatch")
    binding = {"canonical_brief_sha256":canonical,"projection_sha256":projected,"generation":generation,
               "logical_request_key":authorization["logical_request_key"],"physical_session_id":authorization["physical_session_id"],
               "turn_intent":"otto.d256.one-resume.v1"}
    binding["nonce"] = _digest_json(binding)
    compact = lambda v: json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":"))
    raw = compact(queue)
    spec = {"schema":"otto.d256.cursor.v1","binding":binding,"queue":queue,"queue_sha256":_digest_json(queue),
            "queue_chars":len(raw),"queue_adler32":zlib.adler32(raw.encode("ascii"))}
    key = "otto.t01.cursor."+binding["nonce"]+".core"
    bootstrap = ("const CORE = "+json.dumps(_CURSOR_CORE)+";\nconst SPEC = "+compact(spec)+";\nconst CORE_KEY = "+json.dumps(key)+";\n"
        'if (load(CORE_KEY) !== undefined) throw Error("CURSOR_CORE_ALREADY_INITIALIZED");\nstore(CORE_KEY, CORE);\n'
        'const init = new Function("spec","store","load",CORE+"\\nreturn cursorInit(spec,store,load);");\ntext(init(SPEC,store,load));\n')
    common = ("const BINDING = "+compact(binding)+";\nconst CORE_KEY = "+json.dumps(key)+";\nconst CORE = load(CORE_KEY);\n"
        'function check(s){let a=1,b=0;for(let i=0;i<s.length;i++){let c=s.charCodeAt(i);if(c>127)throw Error("NON_ASCII_CORE");a=(a+c)%65521;b=(b+a)%65521;}return (((b<<16)>>>0)|a)>>>0;}\n'
        +f'if(typeof CORE!=="string"||CORE.length!=={len(_CURSOR_CORE)}||check(CORE)!=={zlib.adler32(_CURSOR_CORE.encode())})throw Error("MISSING_OR_ALTERED_CURSOR_CORE");\n')
    cap = '// @exec: {"max_output_tokens": 30000}\n'
    step = common + 'const ACK = __ACK_JSON__;\nconst run=new Function("binding","ack","store","load","tools","text",CORE+"\\nreturn cursorStep(binding,ack,store,load,(args)=>tools.exec_command(args),text);");\nawait run(BINDING,ACK,store,load,tools,text);\n'
    scripts = {"initialize":cap+bootstrap,"first_step":cap+step.replace("__ACK_JSON__","null"),"next_step":cap+step,
        "peek":cap+common+'const run=new Function("binding","load",CORE+"\\nreturn cursorInspect(binding,load);");\ntext(run(BINDING,load));\n',
        "recover":cap+common+'const run=new Function("binding","load","text",CORE+"\\nreturn cursorRecover(binding,load,text);");\nrun(BINDING,load,text);\n',
        "note":cap+common+'const NOTE = __NOTE_JSON__;\nconst run=new Function("binding","note","store","load",CORE+"\\nreturn cursorNote(binding,note,store,load);");\ntext(run(BINDING,NOTE,store,load));\n'}
    payload = {"binding":binding,"queue_sha256":spec["queue_sha256"],"scripts":scripts,
        "instructions":"Use functions.exec with exactly these generated snippets. Initialize once; first_step executes row1. For each next_step replace __ACK_JSON__ only with the JSON string of the last visible cursor_receipt. No path/index edits, loop, direct shell call, or reinitialization. Each step emits one complete command body then receipt; inspect that body and preserve concise C01 analysis using note (__NOTE_JSON__ is a JSON string, max512 chars per note, max8000 chars total). Notes are not acceptance evidence. After compaction use peek then recover to redisplay completed output and receipt without source reread or cursor advance. Prepared/uncertain pending or lost state means STOP; never replay. Final next_step acknowledges row145 without executing. Original native commands and SourceVerifier remain authoritative; DONE is not owner acceptance."}
    block = '\n<otto-command-cursor sha256="'+_digest_json(payload)+'">\n'+compact(payload)+'\n</otto-command-cursor>\n'
    return {"binding":binding,"queue":queue,"queue_sha256":spec["queue_sha256"],"scripts":scripts,"block":block}


def _extended_timeout_brief(brief, model, reasoning):
    """Finite owner-supplied generation12 admission; never inferred from prompt."""
    if not isinstance(brief, Mapping) or model != "gpt-6-luna" or reasoning != "xhigh": return False
    snapshot = brief.get("context", {}).get("canonical_snapshot", {})
    task = brief.get("instruction_contract", {}).get("task_ref", {})
    project = brief.get("context", {}).get("project_state", {}).get("project", {}).get("ref", {})
    spec = brief.get("instruction_contract", {}).get("source_inspection", {})
    return (all(task.get(k)==v for k,v in {"authority":"o01-worker-readiness-operational-pending-d7","kind":"work.task","id":"task-02ce5a517090e99c5335f62a3e75"}.items())
        and all(project.get(k)==v for k,v in {"authority":"o01-worker-readiness-operational-pending-d7","kind":"work.project","id":"project-1f94173efd5ad5811c329af6f459"}.items())
        and type(snapshot.get("generation")) is int and snapshot["generation"] == 12 and snapshot.get("principal") == "worker_normal"
        and brief.get("resource_resolution", {}).get("generation") == 12
        and spec.get("timeouts") == {"inert_seconds":120,"delivery_seconds":4500,"total_seconds":4620}
        and spec.get("manifest_sha256") == "9d72c9b3efa302900a37cd279829285b823f70e57bc7e15d744570d05c7f45fe")


class CodexCliBinding(HostPort):
    """Opt-in receiving binding for the observed local Codex executable.

    Construction is inert. ``preflight`` checks only the executable metadata;
    ``execute`` is the explicit, authority-gated launcher operation. It never
    invents a session: a physical session is taken only from native JSONL.
    """

    def __init__(self, worktree: str, *, launcher: str = "/Users/hannahomalley/.local/bin/codex",
                 model: str = "gpt-5.6-luna", reasoning: str = "high",
                 receipt_path: Optional[str] = None, prompt: str = "",
                 evidence_path: Optional[str] = None,
                 native_receipt_path: Optional[str] = None,
                 native_trace_path: Optional[str] = None,
                 delivered_brief: Optional[Mapping[str, Any]] = None,
                 model_projection: Optional[Mapping[str, Any]] = None,
                 cursor_queue: Optional[list[dict[str, Any]]] = None,
                 trusted_thread_reader: Optional[Callable[[str], Mapping[str, Any]]] = None,
                 recipient_authorizer: Optional[Callable[[HostRequest], Mapping[str, Any]]] = None,
                 native_start_callback: Optional[Callable[[str, str], None]] = None,
                 writable_roots: tuple[str, ...] = (),
                 timeout_seconds: Optional[float] = None, occurrence_deadline: Optional[float] = None,
                 timeout_brief: Optional[Mapping[str, Any]] = None,
                 source_verifier: Any = None, monotonic_clock: Callable[[], float] = time.monotonic) -> None:
        super().__init__({HostOperation.INVOKE, HostOperation.RESUME})
        self.worktree, self.launcher, self.model, self.reasoning = worktree, launcher, model, reasoning
        roots = tuple(os.path.realpath(value) for value in writable_roots)
        if any(not os.path.isabs(value) or not os.path.isdir(value) for value in roots) or len(set(roots)) != len(roots):
            raise ValueError("writable_roots must be distinct existing absolute directories")
        self.writable_roots = roots
        self.receipt_path = native_receipt_path or receipt_path
        self.prompt = prompt
        self.evidence_path = evidence_path
        self.native_trace_path = native_trace_path
        self.trusted_thread_reader = trusted_thread_reader
        self._recipient_authorizer = recipient_authorizer
        self._native_start_callback = native_start_callback
        self._delivery_consumed = False
        self.timeout_brief = None if timeout_brief is None else json.loads(json.dumps(timeout_brief))
        self.extended_timeout = _extended_timeout_brief(self.timeout_brief, model, reasoning)
        if timeout_brief is not None and not self.extended_timeout:
            raise ValueError("extended timeout admission mismatch")
        self.timeout_seconds, self.occurrence_deadline = timeout_seconds, occurrence_deadline
        self.source_verifier, self.monotonic_clock = source_verifier, monotonic_clock
        if timeout_seconds is not None or occurrence_deadline is not None:
            if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
                    or not math.isfinite(timeout_seconds) or not (timeout_seconds in (120,4500) if self.extended_timeout else 0 < timeout_seconds <= 1800)
                    or isinstance(occurrence_deadline, bool) or not isinstance(occurrence_deadline, (int, float))
                    or not math.isfinite(occurrence_deadline)
                    or not 0 < occurrence_deadline - monotonic_clock() <= (4620 if self.extended_timeout else 1920)):
                raise ValueError("invalid bounded host deadline")
        self.delivered_brief = None if delivered_brief is None else json.loads(json.dumps(delivered_brief))
        self.model_projection = None if model_projection is None else json.loads(json.dumps(model_projection))
        self.cursor_queue = None if cursor_queue is None else json.loads(json.dumps(cursor_queue))

    def _trace_path(self, session_id: str, *, deadline: float | None = None) -> str:
        """Resolve only the exact host-issued session via an injected read port."""
        deadline = self.occurrence_deadline if deadline is None else deadline
        path = self.native_trace_path
        if self.trusted_thread_reader is not None:
            if deadline is not None:
                read = getattr(self.trusted_thread_reader, "read_with_deadline", None)
                if not callable(read):
                    raise ValueError("trusted metadata reader has no finite deadline seam")
                response = read(session_id, deadline)
            else:
                response = self.trusted_thread_reader(session_id)
            thread = response.get("thread") if isinstance(response, Mapping) else None
            if not isinstance(thread, Mapping) or thread.get("id") != session_id:
                raise ValueError("trusted thread read returned a different session")
            path = thread.get("path")
        if not isinstance(path, str) or not Path(path).is_absolute():
            raise ValueError("trusted exact-session trace path is unavailable")
        return path

    def _trace(self, session_id: str, *, deadline: float | None = None) -> tuple[str, bytes]:
        """Read a bounded complete trace for a fresh invocation."""
        deadline = self.occurrence_deadline if deadline is None else deadline
        path = self._trace_path(session_id, deadline=deadline)
        if deadline is None:
            data = Path(path).read_bytes()
        else:
            if self.monotonic_clock() >= deadline:
                raise ValueError("trace deadline exhausted")
            with Path(path).open("rb") as stream:
                data = stream.read(32 * 1024 * 1024 + 1)
            if len(data) > 32 * 1024 * 1024 or self.monotonic_clock() >= deadline:
                raise ValueError("trace size or deadline exceeded")
        records = [json.loads(line) for line in data.decode("utf-8").splitlines()]
        sessions = [v["payload"].get("session_id", v["payload"].get("id")) for v in records
                    if isinstance(v, Mapping) and v.get("type") == "session_meta"]
        if sessions != [session_id]:
            raise ValueError("native trace session is missing, ambiguous or different")
        return path, data

    def _resume_trace_boundary(self, session_id: str) -> tuple[str, int, bytes]:
        """Snapshot an existing conversation without rereading its full history."""
        path = self._trace_path(session_id)
        trace = Path(path)
        size = trace.stat().st_size
        with trace.open("rb") as stream:
            first = stream.readline(MAX_SUBMISSION_SIZE + 1)
            if len(first) > MAX_SUBMISSION_SIZE or not first.endswith(b"\n"):
                raise ValueError("native trace session header is unavailable")
            try:
                event = json.loads(first.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError("native trace session header is malformed") from exc
            payload = event.get("payload", {}) if isinstance(event, Mapping) else {}
            observed = payload.get("session_id", payload.get("id")) if isinstance(payload, Mapping) else None
            if event.get("type") != "session_meta" or observed != session_id:
                raise ValueError("native trace session is missing or different")
            if size:
                stream.seek(size - 1)
                if stream.read(1) != b"\n":
                    raise ValueError("native trace boundary is incomplete")
        return path, size, first

    @staticmethod
    def _resume_trace_tail(path: str, boundary: int, session_header: bytes) -> bytes:
        """Read the authentic session header and current occurrence records."""
        with Path(path).open("rb") as stream:
            stream.seek(0, 2)
            current_size = stream.tell()
            if current_size < boundary:
                raise ValueError("native trace boundary changed")
            stream.seek(boundary)
            data = stream.read(32 * 1024 * 1024 + 1)
        if len(data) > 32 * 1024 * 1024:
            raise ValueError("native current-occurrence trace is too large")
        if data and not data.endswith(b"\n"):
            data = data.rsplit(b"\n", 1)[0] + b"\n" if b"\n" in data else b""
        return session_header + data

    def preflight(self) -> dict[str, Any]:
        try:
            result = subprocess.run([self.launcher, "--version"], capture_output=True, text=True,
                                    check=False, timeout=10)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"available": False, "launcher": self.launcher, "error": str(exc)}
        return {"available": result.returncode == 0, "launcher": self.launcher,
                "command": [self.launcher, "--version"], "exit_status": result.returncode,
                "stdout": result.stdout, "stderr": result.stderr}

    def execute(self, request: HostRequest) -> tuple[HostReceipt, Mapping[str, Any]]:
        if request.operation not in {HostOperation.INVOKE, HostOperation.RESUME}:
            return (HostReceipt(request.operation, HostOutcome.UNSUPPORTED, request.identity,
                                request.identity.logical_agent_id, request.requested_profile,
                                unsupported_reason=f"codex CLI binding does not support {request.operation.value}"), {})
        if request.operation == HostOperation.RESUME and not request.identity.physical_session_id:
            return (HostReceipt(request.operation, HostOutcome.UNKNOWN, request.identity,
                                request.identity.logical_agent_id, request.requested_profile,
                                observed_runner=RUNNER_ID,
                                unsupported_reason="resume requires supplied physical session identity"),
                    {"reconciliation": "resume cannot run without an observed physical session",
                     "delivery_state": "unknown"})
        # Only these explicit permission profiles have supported CLI translations.
        # Arbitrary labels (including "default") do not establish a contract.
        if request.requested_profile not in {"read-only", "workspace-write"}:
            return (HostReceipt(request.operation, HostOutcome.UNSUPPORTED, request.identity,
                                request.identity.logical_agent_id, request.requested_profile,
                                observed_runner=RUNNER_ID,
                                unsupported_reason="codex CLI binding requires an explicit supported profile"),
                    {"delivery_state": "not_started",
                     "reconciliation": "unsupported or missing requested permission profile"})
        # Codex 0.150.1 exposes --sandbox on exec, not exec resume. Common
        # restrictions precede the subcommand; config/rules and approvals must
        # not silently broaden them. Requested argv is not observed evidence.
        command = [self.launcher, "exec", "-C", self.worktree, "-m", self.model,
                   "-c", f"model_reasoning_effort={self.reasoning}",
                   "-s", request.requested_profile, "-c", 'approval_policy="never"',
                   "--ignore-user-config", "--ignore-rules", "--json"]
        if request.requested_profile == "workspace-write":
            for root in self.writable_roots:
                command.extend(["--add-dir", root])
        if request.operation == HostOperation.RESUME:
            command.extend(["resume", request.identity.physical_session_id])
        if self.receipt_path:
            command.extend(["-o", self.receipt_path])
        command.append("-")
        started = _now()
        resume_boundary = None
        resume_header = None
        trace_path = None
        delivered_authorization = None
        prompt = self.prompt
        cursor_bundle = None
        try:
            if self.extended_timeout and (request.requested_profile != "read-only"
                    or request.target.to_dict() != self.timeout_brief["instruction_contract"]["task_ref"]
                    or request.identity.logical_agent_id != "worker_normal"
                    or (request.operation == HostOperation.RESUME and (self.timeout_seconds != 4500 or self.delivered_brief != self.timeout_brief))
                    or (request.operation == HostOperation.INVOKE and self.timeout_seconds != 120)):
                raise ValueError("extended timeout receiving scope mismatch")
            if self.model_projection is not None:
                _verify_model_projection(prompt, self.delivered_brief, self.model_projection)
            elif "<otto-task-projection" in prompt:
                raise ValueError("unbound model projection")
            if (self.model_projection is not None and self.delivered_brief.get("resource_resolution", {}).get("generation", 0) >= 11 and self.cursor_queue is None):
                raise ValueError("required cursor queue missing")
            contract = (self.delivered_brief or {}).get("instruction_contract", {})
            if contract.get("authority", {}).get("gateway_claim_required") is True:
                if (request.operation != HostOperation.RESUME or self._delivery_consumed
                        or not callable(self._recipient_authorizer)
                        or not (self.native_trace_path or self.trusted_thread_reader)
                        or "<otto-owner-delivery" in prompt):
                    raise ValueError("trusted one-delivery recipient context is required")
                self._delivery_consumed = True
                authorization = self._recipient_authorizer(request)
                principal = authorization.get("principal") if isinstance(authorization, Mapping) else None
                principal_id = principal if isinstance(principal, str) else principal.get("id") if isinstance(principal, Mapping) else None
                authority = contract.get("authority", {})
                read_contract = (
                    request.requested_profile == "read-only"
                    and authority.get("effect_profile") is None
                    and set(contract.get("allowed_operations", ())) == {"read_only_inspection", "return_evidence"}
                )
                linked_read_contract = _linked_context_read_contract(contract, request.requested_profile)
                selected_roots = tuple(dict.fromkeys((os.path.realpath(self.worktree), *self.writable_roots)))
                write_operations = {"read_project_context", "edit_candidate_workspace", "run_focused_tests", "return_progress"}
                write_effects = {"read_delivered_context", "read_linked_sources", "file_write_in_workspace", "return_result"}
                effect_profile = authority.get("effect_profile")
                if effect_profile == "workspace-write-manager":
                    write_operations.add("canonical_manager_commands")
                    write_effects.add("canonical_manager_commands")
                workspace_contract = (
                    request.requested_profile == "workspace-write"
                    and effect_profile in {"workspace-write-manager", "workspace-write-worker"}
                    and set(contract.get("allowed_operations", ())) == write_operations
                    and tuple(authority.get("workspace_roots", ())) == selected_roots
                    and set(authority.get("permitted_effects", ())) == write_effects
                )
                if (not isinstance(authorization, Mapping) or authorization.get("status") != "authorized"
                        or authorization.get("physical_session_id") != request.identity.physical_session_id
                        or authorization.get("task_ref") != request.target.to_dict()
                        or authorization.get("brief_sha256") != _digest_json(self.delivered_brief)
                        or principal_id != request.identity.logical_agent_id
                        or not (read_contract or linked_read_contract or workspace_contract)
                        or authority.get("owner_write") is not False
                        or authority.get("dispatch") is not False):
                    raise ValueError("trusted recipient authorization is not exact")
                delivered_authorization = json.loads(json.dumps(authorization))
                prompt += _owner_delivery_appendix(
                    delivered_authorization, request.requested_profile,
                    read_scope=contract.get("read_scope"),
                )
            if self.model_projection is not None:
                _verify_model_projection(prompt, self.delivered_brief, self.model_projection, delivered_authorization)
            if self.cursor_queue is not None:
                if delivered_authorization is None or self.model_projection is None or request.requested_profile != "read-only" or self.model != "gpt-6-luna" or self.reasoning != "xhigh":
                    raise ValueError("cursor requires exact authorized receiving binding")
                cursor_bundle = _cursor_bundle(self.delivered_brief, self.model_projection, delivered_authorization, self.cursor_queue)
                prompt += cursor_bundle["block"]
                if prompt.count("<otto-command-cursor ") != 1 or prompt.count("</otto-command-cursor>") != 1:
                    raise ValueError("cursor block duplicated or foreign")
            elif "<otto-command-cursor" in prompt:
                raise ValueError("unbound cursor block")
            # Check the complete submitted text, including owner authorization,
            # before trace-reader subprocesses, source checks, or provider launch.
            chars, utf8_bytes = len(prompt), len(prompt.encode("utf-8"))
            if chars > MAX_SUBMISSION_SIZE or utf8_bytes > MAX_SUBMISSION_SIZE:
                reason = (f"prompt_size_limit_exceeded: characters={chars}, utf8_bytes={utf8_bytes}, "
                          f"limit={MAX_SUBMISSION_SIZE}; no process started")
                return (HostReceipt(request.operation, HostOutcome.FAILED, request.identity,
                                    request.identity.logical_agent_id, request.requested_profile,
                                    observed_runner=RUNNER_ID, unsupported_reason="prompt_size_limit_exceeded"),
                        {"command": command, "started_at": started, "ended_at": _now(),
                         "exit_status": None, "stdout": "", "stderr": reason,
                         "delivery_state": "not_started", "reconciliation": reason})
            if request.operation == HostOperation.RESUME and (self.native_trace_path or self.trusted_thread_reader):
                trace_path, resume_boundary, resume_header = self._resume_trace_boundary(
                    request.identity.physical_session_id
                )
        except Exception as exc:  # Trusted read/admission ports may fail; never launch.
            return (HostReceipt(request.operation, HostOutcome.UNKNOWN, request.identity,
                                request.identity.logical_agent_id, request.requested_profile,
                                observed_runner=RUNNER_ID, unsupported_reason="recipient_context_unavailable"),
                    {"delivery_state": "not_started", "reconciliation": str(exc)})
        if self.source_verifier is not None:
            try:
                if delivered_authorization is None:
                    raise ValueError("bounded inspection requires current owner authorization")
                self.source_verifier.begin()
            except Exception as exc:
                return (HostReceipt(request.operation, HostOutcome.UNKNOWN, request.identity,
                                    request.identity.logical_agent_id, request.requested_profile,
                                    observed_runner=RUNNER_ID, unsupported_reason="source_admission_failed"),
                        {"delivery_state": "not_started", "reconciliation": str(exc)})
        effective_timeout = 120 if self.timeout_seconds is None else min(
            self.timeout_seconds, self.occurrence_deadline - self.monotonic_clock())
        if effective_timeout <= 0 or (request.operation == HostOperation.INVOKE and effective_timeout > 120):
            return (HostReceipt(request.operation, HostOutcome.UNKNOWN, request.identity,
                                request.identity.logical_agent_id, request.requested_profile,
                                observed_runner=RUNNER_ID, unsupported_reason="occurrence_deadline_exhausted"),
                    {"delivery_state": "not_started", "reconciliation": "finite deadline exhausted"})
        native_start_callback = None
        if request.operation == HostOperation.RESUME and self._native_start_callback is not None:
            def native_start_callback(cli_turn_id: Optional[str], observed_at: str) -> None:
                turn_id, admitted_at = cli_turn_id, observed_at
                if turn_id is None:
                    if trace_path is None or resume_boundary is None:
                        raise ValueError("native trace boundary is unavailable at turn start")
                    deadline = min(
                        self.monotonic_clock() + 5,
                        self.occurrence_deadline or self.monotonic_clock() + 5,
                    )
                    admitted = None
                    while admitted is None and self.monotonic_clock() < deadline:
                        data = self._resume_trace_tail(trace_path, resume_boundary, resume_header)
                        admitted = _select_admitted_turn(
                            data.decode("utf-8").splitlines(),
                            session_id=request.identity.physical_session_id,
                            prompt=prompt,
                            boundary=0,
                            started_at=started,
                        )
                        if admitted is None:
                            time.sleep(0.01)
                    if admitted is None:
                        raise ValueError("exact native message admission is unavailable")
                    turn_id, admitted_at = admitted
                self._native_start_callback(turn_id, admitted_at)
        try:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True, cwd=self.worktree,
                                       env=os.environ.copy(), start_new_session=True)
            if request.operation == HostOperation.RESUME and not self.extended_timeout:
                stdout, stderr, exit_status, _ = _communicate_after_native_start(
                    process, prompt,
                    expected_session_id=request.identity.physical_session_id,
                    start_timeout_seconds=effective_timeout,
                    monotonic_clock=self.monotonic_clock,
                    native_start_callback=native_start_callback,
                )
            else:
                # Fresh initialization and the explicitly adopted bounded
                # inspection route retain their finite wall-clock contract.
                stdout, stderr = process.communicate(prompt, timeout=effective_timeout)
                exit_status = process.returncode
        except subprocess.TimeoutExpired:
            _terminate_owned_process(process)
            if self.occurrence_deadline is None:
                stdout, stderr = process.communicate()
            else:
                remaining = max(0.0, min(2.0, self.occurrence_deadline - self.monotonic_clock()))
                try:
                    stdout, stderr = process.communicate(timeout=remaining)
                except subprocess.TimeoutExpired as exc:
                    def retained(value):
                        try: return value.decode("utf-8") if isinstance(value, bytes) else value if isinstance(value, str) else ""
                        except UnicodeError: return ""
                    stdout, stderr = retained(exc.output), retained(exc.stderr)
                    for pipe in (process.stdin, process.stdout, process.stderr):
                        if pipe is not None: pipe.close()
            exit_status = None
        except OSError as exc:
            return (HostReceipt(request.operation, HostOutcome.FAILED, request.identity,
                                request.identity.logical_agent_id, request.requested_profile,
                                observed_runner=RUNNER_ID, unsupported_reason="codex_launcher_os_error"),
                    {"command": command, "started_at": started, "stderr": str(exc),
                     "delivery_state": "unknown"})
        observed_session = None
        observed_turn_id = None
        native_turn_started = False
        observed_model = None
        observed_reasoning = None
        observed_profile = None
        # Identity comes only from host record headers, never recursively from
        # worker text or tool output. CLI stdout alone need not expose context.
        native_lines = stdout.splitlines()
        for line in native_lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, Mapping) and event.get("type") == "thread.started":
                observed_session = event.get("thread_id")
            if isinstance(event, Mapping) and event.get("type") == "turn.started":
                native_turn_started = True
            if isinstance(event, Mapping) and event.get("type") == "turn.completed":
                observed_turn_id = event.get("turn_id")
        invocation_turn_verified = False
        trace_error = None
        if (request.operation == HostOperation.RESUME and observed_session is not None
                and observed_session != request.identity.physical_session_id):
            trace_error = "resumed session differs"
        if exit_status is not None and observed_session and (self.native_trace_path or self.trusted_thread_reader):
            try:
                if request.operation == HostOperation.RESUME and observed_session != request.identity.physical_session_id:
                    raise ValueError("resumed session differs")
                # The launch deadline bounds admission and authentic native
                # start only.  Terminal metadata readback gets its own short
                # bounded operation after useful work has finished.
                trace_deadline = self.monotonic_clock() + 30 if not self.extended_timeout else None
                if resume_boundary is not None:
                    current_path = self._trace_path(observed_session, deadline=trace_deadline)
                    if current_path != trace_path:
                        raise ValueError("native trace path changed")
                    trace = self._resume_trace_tail(current_path, resume_boundary, resume_header)
                else:
                    current_path, trace = self._trace(observed_session, deadline=trace_deadline)
                native_lines = trace.decode("utf-8").splitlines()
                selected = _select_invocation_turn(native_lines, session_id=observed_session,
                    prompt=prompt, boundary=0,
                    started_at=started)
                if selected is None:
                    raise ValueError("native invocation turn is missing, ambiguous or incomplete")
                selected_id, turn = selected
                if observed_turn_id is not None and observed_turn_id != selected_id:
                    raise ValueError("CLI and trace turn identity differ")
                sandbox = turn.get("sandbox_policy", {})
                if sandbox.get("type") != request.requested_profile or turn.get("approval_policy") != "never":
                    raise ValueError("native requested/never permission context is unavailable")
                if request.requested_profile == "workspace-write" and self.writable_roots:
                    observed_roots = sandbox.get("writable_roots")
                    if (not isinstance(observed_roots, list)
                            or not set(self.writable_roots).issubset({os.path.realpath(value) for value in observed_roots if isinstance(value, str)})):
                        raise ValueError("native workspace-write roots do not include the owner-selected roots")
                if self.delivered_brief == {} and any(
                    (event := json.loads(line)).get("payload", {}).get("turn_id") == selected_id
                    and event.get("payload", {}).get("item", {}).get("type") == "CommandExecution"
                    for line in native_lines):
                    raise ValueError("inert initialization performed a command")
                observed_turn_id = selected_id
                observed_model = turn.get("model")
                observed_reasoning = turn.get("collaboration_mode", {}).get("settings", {}).get("reasoning_effort")
                observed_profile = _native_profile_observation(turn)["observed_profile"]
                invocation_turn_verified = True
            except Exception as exc:  # Preserve the observed session even if its host reader fails.
                observed_turn_id = None
                trace_error = str(exc)
                native_lines = []
        physical_session = observed_session
        if request.operation == HostOperation.RESUME and (
            not physical_session or physical_session != request.identity.physical_session_id
        ):
            physical_session = request.identity.physical_session_id
        identity = type(request.identity)(request.identity.logical_agent_id, physical_session)
        if trace_error is not None:
            outcome = HostOutcome.UNKNOWN
        elif exit_status == 0 and physical_session:
            outcome = HostOutcome.SUCCEEDED
        elif exit_status == 0 or exit_status is None:
            outcome = HostOutcome.UNKNOWN
        else:
            outcome = HostOutcome.FAILED
        receipt = HostReceipt(request.operation, outcome, identity, request.identity.logical_agent_id,
                              request.requested_profile, observed_runner=RUNNER_ID,
                              observed_profile=observed_profile, process_id=str(process.pid),
                              unsupported_reason=None if outcome == HostOutcome.SUCCEEDED else (
                                  "native_invocation_context_unverified" if trace_error is not None else ("codex_execution_timeout" if exit_status is None else "codex_execution_failed")))
        verification_failures = []
        native_context = _native_host_context(
            native_lines,
            request=request,
            session_id=physical_session,
            turn_id=observed_turn_id,
            observed_model=observed_model,
            observed_reasoning=observed_reasoning,
            worker_content=[],
            delivered_brief=self.delivered_brief,
            model_projection=self.model_projection, cursor_queue=self.cursor_queue,
            delivered_authorization=delivered_authorization,
            source_verifier=self.source_verifier, failure_reasons=verification_failures,
        )
        native_candidate = capture_native_cli_candidate(stdout, expected_session_id=physical_session)
        if native_context is None and self.delivered_brief:
            verification_failures.append({'code':'native_owner_join_unavailable',
                'message':trace_error or 'exact native turn, prompt, permission or task evidence unavailable'})
        evidence_text = stdout
        if native_context is not None:
            evidence_text += json.dumps(native_context, ensure_ascii=False, sort_keys=True) + "\n"
        if self.evidence_path:
            Path(self.evidence_path).write_text(evidence_text, encoding="utf-8")
        return receipt, {"command": command, "stdout": stdout, "stderr": stderr,
                         "exit_status": exit_status, "observed_model": observed_model,
                         "observed_reasoning": observed_reasoning, "observed_profile": observed_profile,
                         "host_evidence": {
                             "session_id": physical_session, "turn_id": observed_turn_id,
                             "provenance": "host_native_jsonl",
                             "process_started": True,
                             "session_created": request.operation == HostOperation.INVOKE,
                             "native_turn_started": native_turn_started,
                             "invocation_turn_verified": invocation_turn_verified,
                             "otto_host_turn_context": native_context,
                             "native_candidate": native_candidate,
                             "verification_failures": verification_failures,
                         },
                         "stdout_ref": self.evidence_path,
                         "native_receipt_ref": self.receipt_path,
                         "native_candidate": native_candidate, "verification_failures": verification_failures,
                         "delivery_state": "done" if outcome == HostOutcome.SUCCEEDED else "unknown",
                         "reconciliation": trace_error or (None if physical_session else "session unresolved"),
                         "started_at": started, "ended_at": _now()}

def capture_native_cli_candidate(text: str, *, expected_session_id: str | None) -> dict[str, Any]:
    """Retain the exact CLI carrier for reconciliation, never grant task authority.

    CLI item records do not assert a delivered brief, permissions, source proof,
    or even a turn ID in the observed version. Those facts are left unavailable.
    This function does not manufacture turn_context or host_event_ref records.
    """
    base = {"schema":"codex.native-cli-candidate.v1", "provenance":"retained_native_cli_jsonl",
            "task_bound":False, "retry_allowed":False, "turn_id":None,
            "capture_sha256":hashlib.sha256(text.encode('utf-8')).hexdigest(),
            "capture_utf8_bytes":len(text.encode('utf-8'))}
    def unsupported(reason, records=None):
        return {**base, "status":"unsupported", "unsupported_reason":reason,
                "native_records":records or []}
    if not isinstance(expected_session_id, str) or not expected_session_id:
        return unsupported('native_session_unavailable')
    if base['capture_utf8_bytes'] > 32 * 1024 * 1024:
        return unsupported('native_capture_over_budget')
    sessions=[];started=False;complete=False;pending={};seen=set();records=[];messages=[];commands=[]
    try:
        for position,raw in enumerate(text.splitlines()):
            event=json.loads(raw)
            if not isinstance(event,dict):return unsupported('native_record_not_object',records)
            kind=event.get('type')
            if kind=='thread.started':
                sessions.append(event.get('thread_id'))
                continue
            if kind=='turn.started':
                if started or complete:return unsupported('native_turn_ambiguous',records)
                started=True
                continue
            if kind=='turn.completed':
                if not started or complete or pending:return unsupported('native_turn_incomplete',records)
                complete=True
                continue
            if not started or complete:return unsupported('native_record_outside_turn',records)
            if kind not in ('item.started','item.completed'):
                return unsupported('unsupported_native_event',records)
            item=event.get('item');ident=item.get('id') if isinstance(item,dict) else None
            if not isinstance(ident,str) or not ident:return unsupported('native_item_identity_missing',records)
            if kind=='item.started':
                if ident in pending or ident in seen:return unsupported('duplicate_native_item',records)
                pending[ident]=item
                continue
            if ident in seen:return unsupported('duplicate_native_item',records)
            seen.add(ident)
            ref={'event_type':kind,'item_type':item.get('type'),'item_id':ident,
                 'record_position':position,'raw_line_sha256':hashlib.sha256(raw.encode('utf-8')).hexdigest()}
            retained={'native_record':ref,'item':item};records.append(retained)
            if item.get('type')=='command_execution':
                prior=pending.pop(ident,None)
                if (prior is None or prior.get('command')!=item.get('command')
                        or item.get('status')!='completed' or type(item.get('exit_code')) is not int
                        or not isinstance(item.get('command'),str) or not isinstance(item.get('aggregated_output'),str)
                        or 'stdout' in item or 'stderr' in item):
                    return unsupported('native_command_incomplete_or_unverifiable',records)
                body=item['aggregated_output'].encode('utf-8')
                if len(body)>1024*1024:return unsupported('native_output_over_budget',records)
                retained['aggregate_output']={'sha256':hashlib.sha256(body).hexdigest(),'utf8_bytes':len(body),
                                              'representation':'aggregated_output','completeness':'NOT_OBSERVED'}
                commands.append(retained)
            elif item.get('type')=='agent_message' and isinstance(item.get('text'),str):
                pending.pop(ident,None);messages.append(retained)
            else:return unsupported('unsupported_native_item',records)
    except (ValueError,UnicodeError):
        return unsupported('native_capture_malformed',records)
    if sessions != [expected_session_id]:return unsupported('native_session_mismatch',records)
    if not complete or pending:return unsupported('native_turn_incomplete',records)
    if not commands or not messages or records[-1] is not messages[-1]:
        return unsupported('native_final_candidate_unavailable',records)
    final=messages[-1];body=final['item']['text'].encode('utf-8')
    if not body.strip() or len(body)>1024*1024:return unsupported('native_final_candidate_over_budget_or_empty',records)
    return {**base,'status':'native_completed_unverified','session_id':sessions[0],
            'unsupported_reason':'native_owner_join_unavailable',
            'missing_joins':['turn_id','delivered_brief','permission_context','owner_source_verification'],
            'native_records':records,'commands':commands,'final_candidate':{**final,
                'text_sha256':hashlib.sha256(body).hexdigest(),'utf8_bytes':len(body),'phase_observed':False}}


def _select_admitted_turn(lines: list[str], *, session_id: str, prompt: str,
                          boundary: int, started_at: str) -> tuple[str, str] | None:
    """Correlate an exact admitted user message before its turn is terminal."""

    try:
        starts, users = {}, {}
        for index, raw in enumerate(lines):
            event = json.loads(raw)
            if not isinstance(event, Mapping):
                return None
            payload = event.get("payload", {})
            if not isinstance(payload, Mapping):
                continue
            turn = payload.get("turn_id")
            if not isinstance(turn, str) or not turn:
                continue
            if event.get("type") == "event_msg" and payload.get("type") == "task_started" and index >= boundary:
                starts.setdefault(turn, []).append((index, payload))
            if (event.get("type") == "event_msg" and payload.get("type") == "item_completed"
                    and payload.get("item", {}).get("type") == "UserMessage"):
                if payload.get("thread_id") != session_id:
                    return None
                users.setdefault(turn, []).append((index, payload["item"]))
        candidates = []
        invocation_epoch = int(datetime.fromisoformat(started_at).timestamp())
        for turn, beginnings in starts.items():
            messages = users.get(turn, [])
            if len(beginnings) != 1 or len(messages) != 1:
                continue
            start_index, start_payload = beginnings[0]
            user_index, user = messages[0]
            text = "\n".join(
                part.get("text", "") for part in user.get("content", [])
                if isinstance(part, Mapping) and part.get("type") in {"text", "Text"}
            )
            native_started = start_payload.get("started_at")
            if (not boundary <= start_index < user_index or text != prompt
                    or not isinstance(native_started, int) or isinstance(native_started, bool)
                    or native_started < invocation_epoch):
                continue
            candidates.append((turn, datetime.fromtimestamp(
                native_started, tz=timezone.utc,
            ).isoformat()))
        return candidates[0] if len(candidates) == 1 else None
    except (ValueError, TypeError, KeyError, AttributeError, json.JSONDecodeError):
        return None


def _select_invocation_turn(lines: list[str], *, session_id: str, prompt: str,
                            boundary: int, started_at: str) -> tuple[str, Mapping[str, Any]] | None:
    """Correlate a fresh exact user message with one complete host-owned turn."""
    try:
        records = [json.loads(line) for line in lines]
        starts, contexts, users, ends = {}, {}, {}, {}
        for index, event in enumerate(records):
            if not isinstance(event, Mapping):
                return None
            payload = event.get("payload", {})
            if not isinstance(payload, Mapping):
                continue
            turn = payload.get("turn_id")
            if not isinstance(turn, str):
                continue
            if event.get("type") == "event_msg" and payload.get("type") == "task_started" and index >= boundary:
                starts.setdefault(turn, []).append((index, payload))
            if event.get("type") == "turn_context":
                contexts.setdefault(turn, []).append((index, payload))
            if event.get("type") != "event_msg":
                continue
            if payload.get("type") == "task_complete":
                ends.setdefault(turn, []).append((index, payload))
            if payload.get("type") == "item_completed" and payload.get("item", {}).get("type") == "UserMessage":
                if payload.get("thread_id") != session_id:
                    return None
                users.setdefault(turn, []).append((index, payload["item"]))
        if len(starts) != 1:
            return None
        turn, beginning = next(iter(starts.items()))
        if any(len(rows) != 1 for rows in (beginning, users.get(turn, []), ends.get(turn, []))) or not contexts.get(turn):
            return None
        start, start_payload = beginning[0]
        context_index, context = contexts[turn][0]
        # Compaction can repeat the same host context within one turn. Keep
        # every occurrence bounded and require exact payload equality.
        if any(value != context for _, value in contexts[turn]):
            return None
        user_index, user = users[turn][0]
        end, end_payload = ends[turn][0]
        text = "\n".join(part.get("text", "") for part in user.get("content", [])
                         if isinstance(part, Mapping) and part.get("type") in {"text", "Text"})
        if (not (boundary <= start < context_index < user_index < end) or text != prompt
                or any(not start < index < end for index, _ in contexts[turn])):
            return None
        for index, event in enumerate(records):
            payload = event.get("payload", {})
            if (event.get("type") != "event_msg" or payload.get("type") != "item_completed"
                    or payload.get("turn_id") != turn):
                continue
            if start < index < end:
                continue
            # The provider can serialize a long-running command's completion
            # record immediately after task_complete.  It still belongs to this
            # turn when the authenticated command start preceded the task's
            # completion.  Preserve the failed/cancelled command as execution
            # history instead of discarding the entire owner join.
            item = payload.get("item", {})
            item_started = payload.get("started_at_ms")
            item_completed = payload.get("completed_at_ms")
            turn_completed = end_payload.get("completed_at")
            if (index > end and payload.get("thread_id") == session_id
                    and isinstance(item, Mapping) and item.get("type") == "CommandExecution"
                    and type(item_started) is int and type(item_completed) is int
                    and type(turn_completed) is int
                    and item_started <= item_completed
                    and item_started <= turn_completed * 1000):
                continue
            return None
        # Initial invoke has no prior session to snapshot. Its exact prompt and
        # host-issued session must also start inside this invocation boundary.
        if boundary == 0 and (not isinstance(start_payload.get("started_at"), int)
                or isinstance(start_payload["started_at"], bool)
                or start_payload["started_at"] < int(datetime.fromisoformat(started_at).timestamp())):
            return None
        return turn, context
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _sha256_hex(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) != 64:
        return None
    value = value.lower()
    return value if all(char in "0123456789abcdef" for char in value) else None


def _native_profile_observation(turn_context: Mapping[str, Any]) -> dict[str, Any]:
    """Observe an explicit host field only; never infer a requested profile.

    The captured provider currently omits this field. Supporting its exact
    string shape offline does not establish that the provider emits it.
    """
    value = turn_context.get("effective_profile")
    if value is None:
        return {"status": "unavailable", "observed_profile": None, "source": None}
    if not isinstance(value, str) or not value.strip() or value != value.strip() or "\x00" in value:
        return {"status": "malformed", "observed_profile": None, "source": "turn_context.payload.effective_profile"}
    return {"status": "observed", "observed_profile": value, "source": "turn_context.payload.effective_profile"}


def _native_permissions(turn: Mapping[str, Any], requested_profile: str) -> dict[str, Any] | None:
    """Verify a supported native sandbox without inventing effective_profile."""
    sandbox = turn.get("sandbox_policy")
    if (requested_profile not in {"read-only", "workspace-write"}
            or not isinstance(sandbox, Mapping)
            or sandbox.get("type") != requested_profile
            or turn.get("approval_policy") != "never"):
        return None
    profile = _native_profile_observation(turn)
    if profile["status"] == "malformed" or (profile["status"] == "observed" and profile["observed_profile"] != requested_profile):
        return None
    return {"sandbox_policy": dict(sandbox), "approval_policy": "never",
            "source": "turn_context.payload"}


def _exact_python_read(item: Mapping[str, Any], targets: list[str]) -> str | None:
    """Recognize only the captured single-quoted read/hash program, never run it.

    This is a local finite syntax classifier over a native command record;
    stdout and model attestations cannot grant read provenance. Arbitrary
    Python, shell expansion, extra commands and alternate wrappers stay unknown.
    """
    command = item.get("command")
    if len(targets) != 1 or not isinstance(command, list) or len(command) != 3 or command[:2] != ["/bin/zsh", "-lc"]:
        return None
    shell = command[2]
    if not isinstance(shell, str) or len(shell) > 16384:
        return None
    match = re.fullmatch(r"python3 -c '([^'\n\r]+)'", shell)
    if match is None or item.get("parsed_cmd") != [{"type": "unknown", "cmd": shell}]:
        return None
    target = targets[0]
    if not isinstance(target, str) or "\x00" in target or not Path(target).is_absolute() or os.path.normpath(target) != target:
        return None
    template = ('import hashlib,json; p=' + repr(target)
                + '; b=open(p,"rb").read(); print(json.dumps({"bytes_hex":b.hex(),'
                  '"sha256":hashlib.sha256(b).hexdigest(),"size":len(b)}))')
    try:
        if ast.dump(ast.parse(match[1])) != ast.dump(ast.parse(template)):
            return None
    except (SyntaxError, ValueError, RecursionError):
        return None
    return target


def _native_cursor_join(lines, bundle, session_id, turn_id, commands):
    """Join exact generated functions.exec calls to native nested command records."""
    binding, scripts, queue = bundle["binding"], bundle["scripts"], bundle["queue"]
    if binding["physical_session_id"] != session_id or len(commands) != 145:
        return None
    calls, outputs, seen = [], {}, set()
    for position, raw in enumerate(lines):
        event = json.loads(raw); payload = event.get("payload", {})
        if event.get("type") != "response_item" or not isinstance(payload, Mapping):
            continue
        kind = payload.get("type")
        actual_turn = payload.get("internal_chat_message_metadata_passthrough", {}).get("turn_id")
        if binding["nonce"] in str(payload.get("input", "")) and actual_turn != turn_id:
            return None
        if actual_turn != turn_id:
            continue
        if kind in {"function_call", "function_call_output"}:
            return None
        if kind == "custom_tool_call":
            if payload.get("name") != "exec" or payload.get("status") != "completed" or not isinstance(payload.get("call_id"), str) or payload["call_id"] in seen:
                return None
            seen.add(payload["call_id"])
            calls.append((position, payload, hashlib.sha256(raw.encode()).hexdigest()))
        elif kind == "custom_tool_call_output":
            ident = payload.get("call_id")
            if ident in outputs:
                return None
            outputs[ident] = (position, payload, hashlib.sha256(raw.encode()).hexdigest())
    if not calls or set(outputs) != seen:
        return None
    initialized, done, cursor, pending, prior_end = False, False, 0, None, -1
    notes, receipts = {}, []
    def substituted(code, template, marker):
        before, after = template.split(marker)
        if not code.startswith(before) or not code.endswith(after):
            raise ValueError("foreign helper bytes")
        value = json.loads(code[len(before):len(code)-len(after)])
        if not isinstance(value, str):
            raise ValueError("helper substitution must be a string")
        return value
    for start, call, call_hash in calls:
        end, output, output_hash = outputs[call["call_id"]]
        if start <= prior_end or end <= start:
            return None
        prior_end = end
        chunks = output.get("output")
        if (not isinstance(chunks, list) or len(chunks) < 2
                or any(not isinstance(x, Mapping) or x.get("type") != "input_text" or not isinstance(x.get("text"), str) for x in chunks)
                or not chunks[0]["text"].startswith("Script completed\n")):
            return None
        visible = [x["text"] for x in chunks[1:]]
        nested = [(item, ref, pos) for item, ref, pos in commands if start < pos < end]
        code = call.get("input")
        if not isinstance(code, str):
            return None
        if code == scripts["initialize"]:
            if initialized or nested or json.loads(visible[-1]) != {"status":"READY","nonce":binding["nonce"],"cursor":0,"count":145,"queue_sha256":bundle["queue_sha256"]} or len(visible) != 1:
                return None
            initialized = True
            continue
        if not initialized or done:
            return None
        if code == scripts["peek"]:
            if nested or len(visible) != 1:
                return None
            expected = {"status":"ready","nonce":binding["nonce"],"cursor":cursor,"completed_count":cursor,
                "pending_ordinal":None if pending is None else cursor+1,"pending_phase":None if pending is None else "completed",
                "next_kind":queue[cursor]["kind"] if cursor<145 else None,"receipt_withheld":True,"analytical_notes_not_evidence":notes}
            if json.loads(visible[0]) != expected:
                return None
            continue
        if code == scripts["recover"]:
            if nested or pending is None or visible != pending["visible"]:
                return None
            continue
        if 'const NOTE = ' in code:
            note = substituted(code, scripts["note"], "__NOTE_JSON__")
            if nested or pending is None or len(note) > 512 or len(visible) != 1:
                return None
            notes[str(cursor+1)] = note
            if len(json.dumps(notes, ensure_ascii=False, separators=(",",":"))) > 8000 or json.loads(visible[0]) != {"status":"NOTE_STORED_NOT_EVIDENCE","ordinal":cursor+1}:
                return None
            continue
        if code == scripts["first_step"]:
            if cursor != 0 or pending is not None or receipts:
                return None
        else:
            ack = substituted(code, scripts["next_step"], "__ACK_JSON__")
            if pending is None or ack != pending["receipt"]:
                return None
            cursor += 1; pending = None
        if cursor == 145:
            if nested or len(visible) != 1 or json.loads(visible[0]) != {"status":"DONE_145_OF_145","nonce":binding["nonce"],"queue_sha256":bundle["queue_sha256"]}:
                return None
            done = True
            continue
        if len(nested) != 1 or len(visible) != 2:
            return None
        item, ref, _ = nested[0]
        if (item.get("command") != ["/bin/zsh", "-lc", queue[cursor]["cmd"]]
                or item.get("status") != "completed" or type(item.get("exit_code")) is not int or item["exit_code"] != 0):
            return None
        body = item.get("aggregated_output") if "aggregated_output" in item else item.get("stdout", "") + item.get("stderr", "")
        receipt = json.loads(visible[1]); token = receipt.get("cursor_receipt")
        if (visible[0] != body or not isinstance(token,str) or not token.startswith("o12-cursor:"+binding["nonce"][:16]+":"+str(cursor+1)+":")
                or receipt != {"cursor_receipt":token,"ordinal":cursor+1,"next_after_ack":cursor+2,"queue_sha256":bundle["queue_sha256"]}
                or any(r["receipt"] == token for r in receipts)):
            return None
        pending = {"receipt":token,"visible":visible}
        receipts.append({"ordinal":cursor+1,"receipt":token,"command_record":ref,"helper_call_sha256":call_hash,"helper_output_sha256":output_hash})
    if not done or len(receipts) != 145 or [r["command_record"] for r in receipts] != [r for _,r,_ in commands]:
        return None
    return {**binding,"turn_id":turn_id,"queue_sha256":bundle["queue_sha256"],"command_receipts":receipts,
            "analytical_notes_not_evidence":notes,"status":"completed_native_join_not_acceptance"}


def _native_host_context(
    lines: list[str], *, request: HostRequest, session_id: str | None,
    turn_id: str | None, observed_model: str | None = None,
    observed_reasoning: str | None = None, worker_content: list[Any] | None = None,
    delivered_brief: Mapping[str, Any] | None = None,
    model_projection: Mapping[str, Any] | None = None,
    cursor_queue: list[dict[str, Any]] | None = None,
    delivered_authorization: Mapping[str, Any] | None = None,
    source_verifier: Any = None, failure_reasons: list | None = None,
) -> dict[str, Any] | None:
    """Derive evidence from host turn_context and item_completed records.

    Supports native reads and one finite, locally classified Python read. A worker
    JSON attestation, command stdout claiming targets, unrecognized command,
    incomplete result or mismatched delivered brief cannot supply evidence.
    """
    if model_projection is not None and delivered_brief.get("resource_resolution", {}).get("generation", 0) >= 11 and cursor_queue is None:
        return None
    if not session_id or not turn_id or not isinstance(delivered_brief, Mapping):
        return None
    contract = delivered_brief.get("instruction_contract", {})
    resolution = delivered_brief.get("resource_resolution", {})
    write_profile = request.requested_profile == "workspace-write"
    linked_context_read = _linked_context_read_contract(contract, request.requested_profile)
    expected_targets = contract.get("read_targets", [])
    if (contract.get("task_ref") != request.target.to_dict()
            or not isinstance(expected_targets, list)
            or (not write_profile and not linked_context_read and not expected_targets)
            or (linked_context_read and expected_targets)
            or any(not isinstance(path, str) or not Path(path).is_absolute() for path in expected_targets)):
        return None
    assignment = resolution.get("responsibility_ref")
    generation = resolution.get("generation")
    if not isinstance(assignment, Mapping) or not assignment.get("revision") or not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
        return None
    sessions, contexts, users, commands = set(), [], [], []
    command_payloads = {}
    context_positions = []
    messages, completions = [], []
    def reference(raw, payload, item=None):
        return {"event_type": payload.get("type", "turn_context"),
                "item_type": None if item is None else item.get("type"),
                "item_id": None if item is None else item.get("id"),
                "session_id": session_id, "turn_id": turn_id,
                "raw_line_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest()}
    for position, raw in enumerate(lines):
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, Mapping):
            continue
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            continue
        if event.get("type") == "session_meta":
            sessions.add(payload.get("session_id", payload.get("id")))
        if event.get("type") == "turn_context" and payload.get("turn_id") == turn_id:
            contexts.append((payload, reference(raw, {})))
            context_positions.append(position)
        if event.get("type") == "event_msg" and payload.get("type") == "task_complete" and payload.get("turn_id") == turn_id:
            completions.append((position, payload))
        if event.get("type") != "event_msg" or payload.get("type") != "item_completed" or payload.get("turn_id") != turn_id:
            continue
        if payload.get("thread_id") != session_id:
            return None
        item = payload.get("item")
        if not isinstance(item, Mapping) or not isinstance(item.get("id"), str):
            return None
        if item.get("type") == "UserMessage":
            users.append((item, reference(raw, payload, item)))
        elif item.get("type") == "CommandExecution":
            if not users:
                return None
            commands.append((item, reference(raw, payload, item), position))
            command_payloads[item["id"]] = payload
        elif item.get("type") == "AgentMessage":
            if not users:
                return None
            messages.append((item, reference(raw, payload, item), position, payload))
    if (sessions != {session_id} or not contexts or len(users) != 1
            or (not commands and not linked_context_read)):
        return None
    turn, context_ref = contexts[0]
    if any(value != turn for value, _ in contexts):
        return None
    if len(contexts) > 1 and (len(completions) != 1
            or any(position >= completions[0][0] for position in context_positions)):
        return None
    model = turn.get("model")
    reasoning = turn.get("collaboration_mode", {}).get("settings", {}).get("reasoning_effort")
    if not isinstance(model, str) or not model or not isinstance(reasoning, str) or not reasoning:
        return None
    content = users[0][0].get("content", [])
    text = "\n".join(part.get("text", "") for part in content if isinstance(part, Mapping) and part.get("type") in {"text", "Text"})
    brief_digest = _digest_json(delivered_brief)
    projection_binding = None
    cursor_binding = None
    if cursor_queue is not None:
        try:
            bundle = _cursor_bundle(delivered_brief, model_projection, delivered_authorization, cursor_queue)
            if not text.endswith(bundle["block"]):
                return None
            text = text[:-len(bundle["block"])]
            cursor_binding = _native_cursor_join(lines, bundle, session_id, turn_id, commands)
            if cursor_binding is None:
                return None
        except (ValueError, TypeError, KeyError, AttributeError):
            return None
    if model_projection is not None:
        try:
            projection_binding = _verify_model_projection(text, delivered_brief, model_projection, delivered_authorization)
        except (ValueError, TypeError):
            return None
    else:
        blocks = re.findall(r'<otto-resource-brief sha256="([a-f0-9]{64})">\s*(.*?)\s*</otto-resource-brief>', text, re.S)
        if len(blocks) != 1 or "<otto-task-projection" in text:
            return None
        try:
            actual_brief = json.loads(blocks[0][1])
        except json.JSONDecodeError:
            return None
        if actual_brief != delivered_brief or blocks[0][0] != brief_digest:
            return None
    permissions = _native_permissions(turn, request.requested_profile)
    if delivered_authorization is not None:
        if permissions is None:
            return None
        claims = re.findall(r'<otto-owner-delivery sha256="([a-f0-9]{64})">\s*(.*?)\s*</otto-owner-delivery>', text, re.S)
        if len(claims) != 1:
            return None
        try:
            if json.loads(claims[0][1]) != delivered_authorization or claims[0][0] != _digest_json(delivered_authorization):
                return None
        except json.JSONDecodeError:
            return None
    read_targets, outputs, refs = [], [], []
    local_read_classifier = False
    source_verification = None
    bounded = contract.get("source_inspection") is not None
    if bounded:
        if source_verifier is None or delivered_authorization is None or permissions is None:
            return None
        try:
            source_verification = source_verifier.verify(
                [(item, event_ref) for item, event_ref, _ in commands],
                binding={"brief_sha256": brief_digest, "assignment_ref": dict(assignment),
                         "generation": generation, "session_id": session_id, "turn_id": turn_id})
        except Exception as exc:
            if failure_reasons is not None:
                failure_reasons.append({"code":"source_verification_failed", "message":str(exc)})
            return None
        read_targets = list(expected_targets)
        outputs = [{key: item[key] for key in ("command", "cwd", "parsed_cmd", "stdout", "stderr", "aggregated_output", "status", "exit_code") if key in item}
                   for item, _, _ in commands]
        refs = [event_ref for _, event_ref, _ in commands]
    for item, event_ref, _position in ([] if bounded else commands):
        status = item.get("status")
        exit_code = item.get("exit_code")
        if linked_context_read:
            parsed = item.get("parsed_cmd")
            cwd = item.get("cwd")
            if (
                status not in {"completed", "failed"}
                or type(exit_code) is not int
                or not isinstance(item.get("stdout"), str)
                or not isinstance(item.get("command"), list)
                or not isinstance(cwd, str)
                or not isinstance(parsed, list)
                or not parsed
            ):
                return None
            cwd = unquote(urlparse(cwd).path) if cwd.startswith("file://") else cwd
            if not Path(cwd).is_absolute():
                return None
            for command in parsed:
                if isinstance(command, Mapping) and command.get("type") == "read" and isinstance(command.get("path"), str) and command["path"]:
                    path = command["path"]
                    target = os.path.normpath(path if Path(path).is_absolute() else os.path.join(cwd, path))
                    if target not in read_targets:
                        read_targets.append(target)
            outputs.append({key: item.get(key) for key in (
                "command", "cwd", "parsed_cmd", "stdout", "stderr", "aggregated_output", "status", "exit_code"
            )})
            refs.append(event_ref)
            continue
        if (status not in ({"completed", "failed"} if write_profile else {"completed"})
                or type(exit_code) is not int
                or (not write_profile and exit_code != 0)
                or not isinstance(item.get("stdout"), str)
                or not isinstance(item.get("command"), list)):
            return None
        parsed = item.get("parsed_cmd")
        cwd = item.get("cwd")
        if not isinstance(cwd, str):
            return None
        cwd = unquote(urlparse(cwd).path) if cwd.startswith("file://") else cwd
        if not Path(cwd).is_absolute() or not isinstance(parsed, list) or not parsed:
            return None
        if (request.requested_profile == "workspace-write"
                and any(not isinstance(command, Mapping) or command.get("type") != "read" for command in parsed)):
            for command in parsed:
                if isinstance(command, Mapping) and command.get("type") == "read" and isinstance(command.get("path"), str) and command["path"]:
                    path = command["path"]
                    target = os.path.normpath(path if Path(path).is_absolute() else os.path.join(cwd, path))
                    if target not in read_targets:
                        read_targets.append(target)
            outputs.append({key: item.get(key) for key in ("command", "cwd", "parsed_cmd", "stdout", "stderr", "status", "exit_code")})
            refs.append(event_ref)
            continue
        if any(not isinstance(command, Mapping) or command.get("type") != "read" for command in parsed):
            target = _exact_python_read(item, expected_targets)
            if (target is None or len(commands) != 1 or delivered_authorization is None
                    or permissions is None):
                return None
            parsed = [{"type": "read", "path": target}]
            local_read_classifier = True
        for command in parsed:
            if not isinstance(command, Mapping) or command.get("type") != "read" or not isinstance(command.get("path"), str) or not command["path"]:
                return None
            path = command["path"]
            target = os.path.normpath(path if Path(path).is_absolute() else os.path.join(cwd, path))
            if target not in read_targets:
                read_targets.append(target)
        outputs.append({key: item.get(key) for key in ("command", "cwd", "parsed_cmd", "stdout", "stderr", "status", "exit_code")})
        refs.append(event_ref)
    if not write_profile and not linked_context_read and read_targets != expected_targets:
        return None
    output = {
        "commands": outputs,
        "command_execution": {
            "status": "completed",
            "command_count": len(outputs),
            "nonzero_exit_count": sum(
                1 for item in outputs if item.get("exit_code") != 0
            ),
        },
    }
    if source_verification is not None:
        output["source_verification"] = source_verification
    final_text = []
    if messages:
        # Finite raw shape observed for the pinned Codex CLI 0.158.0 route.
        # Unknown/missing phase and non-Text artifacts are not inferred.
        if delivered_authorization is None or permissions is None or len(completions) != 1:
            return None
        finals = []
        ids = [users[0][0]["id"]] + [item["id"] for item, _, _ in commands]
        for item, event_ref, position, payload in messages:
            if (set(item) != {"type", "id", "content", "phase"}
                    or not isinstance(item["id"], str) or not item["id"].strip()
                    or not isinstance(item["phase"], str)
                    or item["phase"] not in {"commentary", "final_answer"}
                    or not isinstance(item["content"], list) or len(item["content"]) != 1
                    or not isinstance(item["content"][0], Mapping)
                    or set(item["content"][0]) != {"type", "text"}
                    or item["content"][0]["type"] != "Text"
                    or not isinstance(item["content"][0]["text"], str)
                    or type(payload.get("started_at_ms")) is not int
                    or type(payload.get("completed_at_ms")) is not int
                    or payload["started_at_ms"] > payload["completed_at_ms"]):
                return None
            ids.append(item["id"])
            if item["phase"] == "final_answer":
                finals.append((item["content"][0]["text"], event_ref, position, payload))
        if len(set(ids)) != len(ids) or len(finals) != 1:
            return None
        text, event_ref, position, final_payload = finals[0]
        completion_position, completion_payload = completions[0]
        final_started = final_payload.get("started_at_ms")
        turn_completed = completion_payload.get("completed_at")
        commands_precede_final = True
        for item, _, command_position in commands:
            if command_position < position:
                continue
            payload = command_payloads[item["id"]]
            item_started = payload.get("started_at_ms")
            item_completed = payload.get("completed_at_ms")
            if not (command_position > completion_position
                    and type(item_started) is int and type(item_completed) is int
                    and type(final_started) is int and type(turn_completed) is int
                    and item_started <= item_completed
                    and item_started <= final_started
                    and item_started <= turn_completed * 1000):
                commands_precede_final = False
                break
        if (not commands_precede_final or not position < completion_position
                or any(p > position for _, _, p, _ in messages)):
            return None
        try:
            body = text.encode("utf-8")
        except UnicodeError:
            return None
        if not text.strip() or len(body) > 1024 * 1024:
            return None
        output["final_answer"] = {
            "format": "codex-cli-0.158.0-native-final-text-v1", "phase": "final_answer",
            "text": text, "utf8_bytes": len(body), "text_sha256": hashlib.sha256(body).hexdigest(),
            "host_record": event_ref,
        }
        final_text = [text]
    if linked_context_read and not final_text:
        return None
    result_digest = _digest_json(output)
    result_ref = {"authority": "codex-host", "kind": "host.command-result", "id": session_id + ":" + turn_id, "revision": result_digest}
    host_records = {"turn_context": context_ref, "user_message": users[0][1], "commands": refs}
    if linked_context_read:
        host_records["final_answer"] = output["final_answer"]["host_record"]
    evidence = {
        "task_ref": request.target.to_dict(), "operation": request.operation.value,
        "session_id": session_id, "turn_id": turn_id,
        "provenance": ("host_final_answer/item_completed" if linked_context_read
                       else "host_command_execution/item_completed"),
        "assignment_ref": dict(assignment), "generation": generation,
        "delivered_contract_digest": _digest_json(contract), "delivered_brief_digest": brief_digest, "result_ref": result_ref,
        "result_digest": result_digest, "read_targets": read_targets,
        "host_records": host_records,
        "operation_result": {"status": "completed", "result_ref": result_ref, "result_digest": result_digest, "output": output},
    }
    if len(contexts) > 1:
        evidence["host_records"]["turn_contexts"] = [ref for _, ref in contexts]
    if projection_binding is not None:
        evidence["model_projection"] = projection_binding
    if cursor_binding is not None:
        evidence["command_cursor"] = cursor_binding
    if delivered_authorization is not None:
        evidence["owner_delivery_authorization"] = dict(delivered_authorization)
    if permissions is not None:
        evidence["native_permissions"] = {**permissions, "host_record": context_ref}
    if local_read_classifier:
        evidence["read_classifier"] = "exact-python-read-hash-v1"
    context_base = {"session_id": session_id, "turn_id": turn_id, "provenance": "host_owned_turn_context",
                    "model": model, "reasoning": reasoning, "worker_content": final_text, "task_bound_evidence": evidence}
    profile = _native_profile_observation(turn)
    if profile["status"] == "observed":
        context_base["effective_profile"] = profile["observed_profile"]
    context_digest = _digest_json(context_base)
    evidence["context_digest"] = context_digest
    evidence["evidence_digest"] = _digest_json(evidence)
    return {"type": "otto_host_turn_context", **context_base, "context_digest": context_digest}

class HerzchenHostAdapter:
    def __init__(self, port: HostPort, *, owner: str, source: str, worktree: str,
                 launcher: str, requested_model: str = "gpt-5.6-luna",
                 requested_reasoning: str = "high") -> None:
        self.port = port
        # Otto uses this finite capability marker to require the owner-bound
        # attempt gate before invoking this host transport.
        self.owner_bound = True
        self.owner, self.source, self.worktree, self.launcher = owner, source, worktree, launcher
        self.requested_model, self.requested_reasoning = requested_model, requested_reasoning

    def _packet_digest(self, request: HostRequest) -> str:
        return hashlib.sha256(request.to_json().encode()).hexdigest()

    def _envelope(self, request: HostRequest, receipt: HostReceipt, started: str,
                  *, ended: Optional[str] = None, status: Optional[str] = None,
                  delivery_state: str = "unknown", error: Optional[str] = None,
                  metadata: Optional[Mapping[str, Any]] = None) -> AdapterReceiptEnvelope:
        metadata = dict(metadata or {})
        physical = receipt.identity.physical_session_id
        envelope_started = metadata.get("started_at", started)
        envelope_ended = metadata.get("ended_at", ended)
        return AdapterReceiptEnvelope(self.owner, request.identity.logical_agent_id, physical,
            self.source, self.worktree, self._packet_digest(request), self.requested_model,
            self.requested_reasoning, request.requested_profile or "default",
            metadata.get("observed_model"), metadata.get("observed_reasoning"),
            metadata.get("observed_profile", receipt.observed_profile), self.launcher,
            receipt.observed_runner, receipt.process_id, envelope_started, envelope_ended,
            metadata.get("exit_status"), status or receipt.outcome.value,
            metadata.get("stdout_ref"), metadata.get("native_receipt_ref"), delivery_state,
            metadata.get("cursor"), metadata.get("timeout"), metadata.get("cancel"),
            metadata.get("reconciliation"), error or receipt.unsupported_reason,
            receipt.result_ref.to_json() if receipt.result_ref else None, receipt.to_dict(),
            command=tuple(metadata["command"]) if metadata.get("command") else None,
            host_evidence=metadata.get("host_evidence"),
            stdout=metadata.get("stdout"), stderr=metadata.get("stderr"),
            transport_operation=request.operation.value)

    def _reject_duplicate(self, request: HostRequest) -> None:
        """Ask the owning host binding about unresolved logical work.

        The adapter deliberately does not maintain a second session ledger. A
        binding may expose ``resolve_logical_session``; its answer is authoritative.
        """
        if request.operation not in {HostOperation.INVOKE, HostOperation.RESUME}:
            return
        resolver = getattr(self.port, "resolve_logical_session", None)
        if resolver is None or request.identity.physical_session_id is not None:
            return
        physical = resolver(request.identity.logical_agent_id)
        if physical:
            raise ContractError("unresolved logical delivery cannot create a second session")

    def execute(self, request: HostRequest) -> tuple[HostReceipt, AdapterReceiptEnvelope]:
        started = _now()
        self._reject_duplicate(request)
        metadata: Mapping[str, Any] = {}
        try:
            if not self.port.supports(request.operation):
                receipt = HostReceipt(request.operation, HostOutcome.UNSUPPORTED, request.identity,
                    request.identity.logical_agent_id, request.requested_profile,
                    unsupported_reason=f"adapter does not support {request.operation.value}")
            elif hasattr(self.port, "execute"):
                observed = self.port.execute(request)  # FND-owned transport boundary
                if isinstance(observed, tuple):
                    receipt, metadata = observed
                else:
                    receipt = observed
            else:
                receipt = HostReceipt(request.operation, HostOutcome.UNSUPPORTED, request.identity,
                    request.identity.logical_agent_id, request.requested_profile,
                    unsupported_reason="configured host has no execution binding")
        except Exception as exc:
            receipt = HostReceipt(request.operation, HostOutcome.FAILED, request.identity,
                request.identity.logical_agent_id, request.requested_profile, unsupported_reason=str(exc))
        state = metadata.get("delivery_state")
        if not state:
            state = "unknown" if receipt.outcome in {HostOutcome.UNKNOWN, HostOutcome.UNSUPPORTED} else ("done" if receipt.outcome == HostOutcome.SUCCEEDED else "unknown")
        return receipt, self._envelope(request, receipt, started, ended=_now(), delivery_state=state, metadata=metadata)

    def invoke(self, request: HostRequest): return self.execute(replace(request, operation=HostOperation.INVOKE))
    def resume(self, request: HostRequest): return self.execute(replace(request, operation=HostOperation.RESUME))
    def send(self, request: HostRequest): return self.execute(replace(request, operation=HostOperation.SEND))
    def inspect(self, request: HostRequest): return self.execute(replace(request, operation=HostOperation.INSPECT))
    def cancel(self, request: HostRequest): return self.execute(replace(request, operation=HostOperation.CANCEL))
    def wait(self, request: HostRequest): return self.execute(replace(request, operation=HostOperation.WAIT))
