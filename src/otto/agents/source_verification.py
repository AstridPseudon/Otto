"""Finite, independent owner observations. Never supplies native execution facts."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import os
import re
from pathlib import Path
import selectors
import shlex
import subprocess
import time

SCHEMA = "otto.bounded-source-inspection.v1"
FILE_CAP = 2 * 1024 * 1024
OUTPUT_CAP = 1024 * 1024
TOTAL_CAP = 16 * OUTPUT_CAP

class SourceVerificationError(ValueError):
    pass

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def finite(value, cap):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= cap:
        raise SourceVerificationError("invalid finite occurrence budget")
    return value

T01_EXTENDED_TIMEOUTS = {"inert_seconds":120,"delivery_seconds":4500,"total_seconds":4620}
DEFAULT_TIMEOUTS = {"inert_seconds":120,"delivery_seconds":1800,"total_seconds":1920}

def t01_task_ref(ref):
    return isinstance(ref, dict) and all(ref.get(k) == v for k,v in {
        "authority":"o01-worker-readiness-operational-pending-d7", "kind":"work.task",
        "id":"task-02ce5a517090e99c5335f62a3e75"}.items())

def t01_timeout_scope(scope):
    return (isinstance(scope, dict) and t01_task_ref(scope.get("task_ref"))
        and type(scope.get("generation")) is int and scope["generation"] == 12
        and scope.get("principal") == "worker_normal" and scope.get("profile") == "read-only"
        and scope.get("requested_model") == "gpt-6-luna" and scope.get("requested_reasoning") == "xhigh"
        and isinstance(scope.get("project_ref"), dict)
        and all(scope["project_ref"].get(k) == v for k,v in {"authority":"o01-worker-readiness-operational-pending-d7",
            "kind":"work.project","id":"project-1f94173efd5ad5811c329af6f459"}.items()))

def t01_timeout_brief(brief):
    if not isinstance(brief, dict): return False
    snapshot = brief.get("context", {}).get("canonical_snapshot", {})
    scope = {**snapshot,"task_ref":brief.get("instruction_contract", {}).get("task_ref"),
        "project_ref":brief.get("context", {}).get("project_state", {}).get("project", {}).get("ref"),
        "profile":"read-only","requested_model":"gpt-6-luna","requested_reasoning":"xhigh"}
    return (t01_timeout_scope(scope) and brief.get("resource_resolution", {}).get("generation") == 12
        and brief.get("instruction_contract", {}).get("source_inspection", {}).get("timeouts") == T01_EXTENDED_TIMEOUTS
        and brief["instruction_contract"]["source_inspection"].get("manifest_sha256") == "9d72c9b3efa302900a37cd279829285b823f70e57bc7e15d744570d05c7f45fe")

def inspection_contract(value, *, task_ref=None):
    if not isinstance(value, dict) or set(value) != {"schema", "manifest_sha256", "timeouts"} or value["schema"] != SCHEMA:
        raise SourceVerificationError("unsupported source inspection contract")
    h = value["manifest_sha256"]
    if not isinstance(h, str) or len(h) != 64 or any(c not in "0123456789abcdef" for c in h):
        raise SourceVerificationError("missing admitted manifest digest")
    t = value["timeouts"]
    if not isinstance(t, dict) or set(t) != {"inert_seconds", "delivery_seconds", "total_seconds"}:
        raise SourceVerificationError("missing finite stage budgets")
    extended = t == T01_EXTENDED_TIMEOUTS and t01_task_ref(task_ref)
    caps = T01_EXTENDED_TIMEOUTS if extended else DEFAULT_TIMEOUTS
    for key, cap in caps.items():
        finite(t[key], cap)
    return deepcopy(value)

def controlled_environment():
    # No inherited Git/rg/shell/helper configuration, credentials or PATH.
    return {"PATH": "/usr/bin:/bin", "HOME": "/dev/null", "LC_ALL": "C", "LANG": "C",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_COUNT": "3",
            "GIT_CONFIG_KEY_0": "core.hooksPath", "GIT_CONFIG_VALUE_0": "/dev/null",
            "GIT_CONFIG_KEY_1": "core.fsmonitor", "GIT_CONFIG_VALUE_1": "false",
            "GIT_CONFIG_KEY_2": "core.untrackedCache", "GIT_CONFIG_VALUE_2": "false"}

def capture(argv, cwd, deadline, *, clock=time.monotonic):
    """Bound each pipe while reading; no shell, normalization or unbounded drain."""
    if deadline <= clock():
        raise SourceVerificationError("owner verification deadline exhausted")
    p = subprocess.Popen(argv, cwd=cwd, env=controlled_environment(), stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
    output = {"stdout": bytearray(), "stderr": bytearray()}
    try:
        with selectors.DefaultSelector() as sel:
            for name in output:
                pipe = getattr(p, name); os.set_blocking(pipe.fileno(), False)
                sel.register(pipe, selectors.EVENT_READ, name)
            while sel.get_map():
                remaining = deadline - clock()
                if remaining <= 0:
                    raise SourceVerificationError("owner verification timeout")
                ready = sel.select(remaining)
                if not ready:
                    raise SourceVerificationError("owner verification timeout")
                for key, _ in ready:
                    data = os.read(key.fileobj.fileno(), 65536)
                    if not data:
                        sel.unregister(key.fileobj); continue
                    output[key.data].extend(data)
                    if sum(map(len, output.values())) > OUTPUT_CAP:
                        raise SourceVerificationError("owner output cap exceeded")
            remaining = deadline - clock()
            if remaining <= 0:
                raise SourceVerificationError("owner verification deadline exhausted")
            code = p.wait(timeout=remaining)
        return {"stdout": bytes(output["stdout"]).decode("utf-8", errors="strict"),
                "stderr": bytes(output["stderr"]).decode("utf-8", errors="strict"), "exit_code": code}
    except (subprocess.TimeoutExpired, UnicodeError) as exc:
        raise SourceVerificationError("owner capture timeout or non-UTF8 output") from exc
    finally:
        if p.poll() is None:
            p.kill()
            remaining = min(2.0, max(0.0, deadline - clock()))
            try:
                p.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                pass  # Unknown process release; never a successful result.
        p.stdout.close(); p.stderr.close()

def decode_command(command):
    # CLI JSON uses a shell-quoted string; decode only its exact existing wrapper.
    # The inner grammar below is unchanged and still rejects composition/regex.
    if isinstance(command, str):
        if len(command.encode()) > 16384:
            raise SourceVerificationError("native command exceeds byte bound")
        try:
            command = shlex.split(command, posix=True)
        except ValueError as exc:
            raise SourceVerificationError("invalid native argv representation") from exc
        if command[:2] != ["/bin/zsh", "-lc"] or len(command) != 3:
            raise SourceVerificationError("unsupported native argv representation")
    if not isinstance(command, list) or not command or any(not isinstance(x, str) or not x or "\x00" in x for x in command):
        raise SourceVerificationError("missing exact native argv")
    if sum(len(x.encode()) for x in command) > 16384:
        raise SourceVerificationError("native command exceeds byte bound")
    if command[:2] != ["/bin/zsh", "-lc"]:
        return command
    if len(command) != 3 or len(command[2]) > 16384:
        raise SourceVerificationError("unsupported native shell wrapper")
    text = command[2]; quote = None; escaped = False
    for c in text:
        if escaped:
            escaped = False; continue
        if quote == "'":
            if c == "'": quote = None
            continue
        if c == "\\":
            escaped = True; continue
        if quote == '"':
            if c == '"': quote = None
            elif c in "$`": raise SourceVerificationError("shell expansion is forbidden")
            continue
        if c in "'\"": quote = c
        elif c in "$`;|&<>()*?[]{}~\n\r":
            raise SourceVerificationError("shell composition or expansion is forbidden")
    if quote or escaped:
        raise SourceVerificationError("incomplete shell quotation")
    try:
        return shlex.split(text, posix=True)
    except ValueError as exc:
        raise SourceVerificationError("invalid shell quotation") from exc

class SourceVerifierFactory:
    """An owner-injected immutable admission, never constructed from worker text."""
    def __init__(self, manifest, *, runner=capture, clock=time.monotonic):
        self._manifest = deepcopy(manifest)
        if not isinstance(manifest, dict) or set(manifest) != {"schema", "roots", "files", "tools"} or manifest["schema"] != "otto.source-admission.v1":
            raise SourceVerificationError("unsupported owner admission")
        if not isinstance(manifest["roots"], list) or len(manifest["roots"]) != 7:
            raise SourceVerificationError("exact seven roots required")
        if set(manifest["tools"]) != {"cat", "git", "rg"}:
            raise SourceVerificationError("three exact tool pins required")
        self.runner, self.clock = runner, clock

    def __call__(self, *, brief, deadline):
        spec = inspection_contract(brief["instruction_contract"]["source_inspection"], task_ref=brief["instruction_contract"].get("task_ref"))
        if spec["timeouts"] == T01_EXTENDED_TIMEOUTS and not t01_timeout_brief(brief):
            raise SourceVerificationError("extended timeout requires exact generation12 T01 brief")
        if spec["manifest_sha256"] != digest(self._manifest):
            raise SourceVerificationError("owner admission does not match delivered brief")
        return SourceVerifier(self._manifest, brief, deadline, runner=self.runner, clock=self.clock)

class SourceVerifier:
    def __init__(self, manifest, brief, deadline, *, runner, clock):
        self.manifest, self.brief = deepcopy(manifest), deepcopy(brief)
        self.deadline, self.runner, self.clock = deadline, runner, clock
        self.roots = [self.normal(x["path"]) for x in manifest["roots"]]
        if len(set(self.roots)) != 7:
            raise SourceVerificationError("duplicate admitted root")
        self.files = {self.normal(x["path"]): x["sha256"] for x in manifest["files"]}
        if len(self.files) != len(manifest["files"]):
            raise SourceVerificationError("duplicate admitted file")
        self.tools = deepcopy(manifest["tools"])
        self.baseline = None; self.receipt = None; self.used_files = {}; self.consumed = False

    def remaining(self):
        if self.clock() >= self.deadline:
            raise SourceVerificationError("occurrence deadline exhausted")

    @staticmethod
    def normal(path):
        if not isinstance(path, str) or not Path(path).is_absolute() or ".." in Path(path).parts or str(Path(path)) != path:
            raise SourceVerificationError("path must be absolute and normalized")
        return path

    def resolved(self, path, *, exact_allowed=True):
        self.remaining(); path = self.normal(path)
        real = str(Path(path).resolve(strict=True))
        admitted = any(Path(real).is_relative_to(Path(r)) and Path(path).is_relative_to(Path(r)) for r in self.roots)
        if not admitted and not (exact_allowed and path in self.files and real == path):
            raise SourceVerificationError("foreign path or symlink escape")
        if not Path(real).is_file() and not Path(real).is_dir():
            raise SourceVerificationError("nonregular source scope")
        return real

    def file_pin(self, path):
        self.remaining(); p = Path(path)
        if not p.is_file() or p.stat().st_size > FILE_CAP:
            raise SourceVerificationError("source file unavailable or above 2MiB")
        with p.open('rb') as stream: data = stream.read(FILE_CAP + 1)
        if len(data) > FILE_CAP:
            raise SourceVerificationError("source file grew past bound")
        return {"path": str(p), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}

    def run(self, argv, cwd):
        self.remaining()
        result = self.runner(argv, cwd, self.deadline, clock=self.clock)
        self.remaining()
        if (not isinstance(result, dict) or set(result) != {"stdout", "stderr", "exit_code"}
                or not isinstance(result["stdout"], str) or not isinstance(result["stderr"], str) or type(result["exit_code"]) is not int
                or len(result["stdout"].encode()) + len(result["stderr"].encode()) > OUTPUT_CAP):
            raise SourceVerificationError("owner output missing or exceeds cap")
        return result

    def identities(self):
        tools = {}
        for name, pin in self.tools.items():
            path = self.normal(pin["path"]); self.remaining()
            # Tool binaries have their own identity bound, not the source file cap.
            if not Path(path).is_file():
                raise SourceVerificationError("owner tool is not a regular file")
            h = hashlib.sha256()
            with open(path, 'rb') as stream:
                while chunk := stream.read(1024 * 1024): self.remaining(); h.update(chunk)
            if h.hexdigest() != pin["sha256"]:
                raise SourceVerificationError("pinned owner tool changed")
            tools[name] = {"path": str(Path(path).resolve(strict=True)), "sha256": h.hexdigest()}
        roots = []
        for row in self.manifest["roots"]:
            root = row["path"]
            if str(Path(root).resolve(strict=True)) != root:
                raise SourceVerificationError("admitted root changed or is a symlink")
            git_dir = Path(root) / '.git'
            metadata = {}
            if not git_dir.is_dir():
                raise SourceVerificationError("indirect Git metadata requires explicit admission")
            for path in [git_dir / 'config', git_dir / 'config.worktree', git_dir / 'info/exclude',
                         Path(root) / '.gitignore', Path(root) / '.ignore', Path(root) / '.rgignore']:
                if path.exists():
                    if path.is_symlink(): raise SourceVerificationError("symlinked root configuration")
                    metadata[str(path)] = self.file_pin(str(path))
                    if path.name in {'config', 'config.worktree'} and re.search(r'(?im)^\s*\[\s*include(?:if)?(?:\s|\])', path.read_text()):
                        raise SourceVerificationError("external Git configuration include is not admitted")
            prefix = [self.tools["git"]["path"], "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", root]
            head = self.run(prefix + ["rev-parse", "HEAD"], root)
            status = self.run(prefix + ["status", "--porcelain=v1", "--untracked-files=all"], root)
            if head != {"stdout": row["head"] + "\n", "stderr": "", "exit_code": 0} or status != {"stdout": row["status_porcelain"], "stderr": "", "exit_code": 0}:
                raise SourceVerificationError("admitted root HEAD/dirty state changed")
            roots.append({**row, "configuration": metadata})
        files = [self.file_pin(self.resolved(p)) for p in self.files]
        if any(row["sha256"] != self.files[row["path"]] for row in files):
            raise SourceVerificationError("admitted input changed")
        return {"roots": roots, "files": files, "tools": tools, "environment_sha256": digest(controlled_environment())}

    def begin(self):
        if self.baseline is not None:
            raise SourceVerificationError("source verifier is one-occurrence only")
        self.baseline = self.identities()

    def classify(self, item):
        argv = decode_command(item.get("command"))
        if not argv:
            raise SourceVerificationError("empty command")
        name = next((name for name, pin in self.tools.items() if argv[0] in {name, pin["path"]}), None)
        if name is None:
            raise SourceVerificationError("unadmitted executable")
        cwd = item.get("cwd")
        if isinstance(cwd, str) and cwd.startswith('file://'):
            from urllib.parse import unquote, urlparse
            cwd = unquote(urlparse(cwd).path)
        self.resolved(cwd, exact_allowed=False)
        scopes = []
        if name == 'cat' and len(argv) == 3 and argv[1] == '--':
            scopes = [self.resolved(argv[2])]
            self.file_pin(scopes[0])
        elif name == 'git' and argv[1:5] == ['--no-optional-locks', '-c', 'core.fsmonitor=false', '-C'] and len(argv) in {8, 9}:
            if argv[5] not in self.roots or argv[6:] not in [['rev-parse', 'HEAD'], ['status', '--porcelain=v1', '--untracked-files=all']]:
                raise SourceVerificationError("unsupported Git query")
            scopes = [self.resolved(argv[5], exact_allowed=False)]
        elif name == 'rg' and argv[1:7] == ['--no-config', '--color=never', '--no-heading', '--with-filename', '-n', '-F']:
            i = 7; tokens = []
            # Native and owner executions need deterministic file traversal to
            # compare complete bytes. Preserve legacy grammar and admit only
            # this exact additional form; never reorder captured output.
            if argv[i:i + 2] == ['--sort', 'path']:
                i += 2
            while i + 1 < len(argv) and argv[i] == '-e':
                tokens.append(argv[i + 1]); i += 2
            if not 1 <= len(tokens) <= 8 or any(not t or len(t) > 256 or '\n' in t or '\x00' in t for t in tokens) or i >= len(argv) or argv[i] != '--' or not argv[i + 1:]:
                raise SourceVerificationError("unsupported literal query")
            scopes = [self.resolved(p, exact_allowed=False) for p in argv[i + 1:]]
        else:
            raise SourceVerificationError("unsupported command grammar")
        return name, argv, cwd, scopes

    def snapshot(self, scopes):
        files = {}
        for scope in scopes:
            p = Path(scope)
            ancestor = p.parent
            while any(ancestor.is_relative_to(Path(root)) for root in self.roots):
                for name in ('.gitignore', '.ignore', '.rgignore'):
                    config = ancestor / name
                    if config.exists(): files[self.resolved(str(config))] = self.file_pin(self.resolved(str(config)))
                ancestor = ancestor.parent
            candidates = [p] if p.is_file() else p.rglob('*')
            for candidate in candidates:
                self.remaining()
                if '.git' in candidate.relative_to(p if p.is_dir() else p.parent).parts:
                    continue
                resolved = self.resolved(str(candidate))
                if candidate.is_file(): files[resolved] = self.file_pin(resolved)
                elif not candidate.is_dir(): raise SourceVerificationError("nonregular source entry")
        return files

    def verify(self, commands, *, binding):
        if self.baseline is None or self.consumed or not 1 <= len(commands) <= 256:
            raise SourceVerificationError("uninitialized, consumed or over-budget verification")
        self.consumed = True
        resolution = self.brief['resource_resolution']
        if (binding.get('brief_sha256') != digest(self.brief)
                or binding.get('assignment_ref') != resolution['responsibility_ref']
                or binding.get('generation') != resolution['generation']
                or not binding.get('session_id') or not binding.get('turn_id')):
            raise SourceVerificationError("source verification recipient binding changed")
        if self.identities() != self.baseline:
            raise SourceVerificationError("source identity changed during native delivery")
        results = []; total = 0; reads = []
        for item, event_ref in commands:
            aggregate = 'aggregated_output' in item
            split = 'stdout' in item or 'stderr' in item
            if (item.get('status') != 'completed' or not (aggregate or split)
                    or (aggregate and not isinstance(item.get('aggregated_output'), str))
                    or (split and (not isinstance(item.get('stdout'), str) or not isinstance(item.get('stderr'), str)))
                    or (aggregate and split and (item.get('stderr') != ''
                        or item.get('aggregated_output') != item.get('stdout')))
                    or type(item.get('exit_code')) is not int
                    or event_ref.get('session_id') != binding['session_id'] or event_ref.get('turn_id') != binding['turn_id']):
                raise SourceVerificationError("native comparable output or identity missing")
            name, argv, cwd, scopes = self.classify(item)
            before = {} if name == 'git' else self.snapshot(scopes)
            owner_argv = [self.tools[name]['path'], *argv[1:]]
            if name == 'cat': owner_argv[2] = scopes[0]
            if name == 'rg': owner_argv[owner_argv.index('--') + 1:] = scopes
            result = self.run(owner_argv, cwd)
            if aggregate:
                # No native stream split is inferred. Independent complete owner
                # capture can compare aggregate bytes only when stream order is
                # unambiguous. Both nonempty streams require unsupported status.
                if result['stdout'] and result['stderr']:
                    raise SourceVerificationError("aggregate stream order is unverifiable")
                comparable = (result['exit_code'] == item['exit_code']
                              and result['stdout'] + result['stderr'] == item['aggregated_output']
                              and (not split or result == {key: item[key] for key in result}))
                native_output = {'representation':'aggregated_output',
                    'sha256':hashlib.sha256(item['aggregated_output'].encode()).hexdigest(),
                    'utf8_bytes':len(item['aggregated_output'].encode())}
                if split:
                    native_output.update(
                        representation='matching_aggregate_and_separate_streams',
                        stdout_sha256=hashlib.sha256(item['stdout'].encode()).hexdigest(),
                        stderr_sha256=hashlib.sha256(item['stderr'].encode()).hexdigest())
            else:
                comparable = result == {key:item[key] for key in result}
                native_output = {'representation':'separate_streams'}
            if result['exit_code'] not in ({0, 1} if name == 'rg' else {0}) or not comparable:
                raise SourceVerificationError("native output differs from complete owner query")
            size = len(result['stdout'].encode()) + len(result['stderr'].encode()); total += size
            if total > TOTAL_CAP:
                raise SourceVerificationError("occurrence output cap exceeded")
            after = {} if name == 'git' else self.snapshot(scopes)
            if before != after:
                raise SourceVerificationError("source changed during verification")
            self.used_files.update(before)
            if name == 'cat':
                reads.extend(p for p in scopes if p not in reads)
            results.append({'native_record': event_ref, 'native_command': item['command'], 'argv': argv,
                            'owner_argv': owner_argv, 'cwd': cwd, 'resolved_scope': scopes,
                            'exit_code': result['exit_code'], 'stdout_sha256': hashlib.sha256(result['stdout'].encode()).hexdigest(),
                            'stderr_sha256': hashlib.sha256(result['stderr'].encode()).hexdigest(), 'retained_bytes': size,
                            'source_files': list(before.values()), 'complete_owner_capture': True, 'native_output':native_output})
        evidence_sizes = [len(json.dumps(row, ensure_ascii=False).encode()) + row['retained_bytes'] for row in results]
        if any(size > OUTPUT_CAP for size in evidence_sizes) or sum(evidence_sizes) > TOTAL_CAP:
            raise SourceVerificationError('accepted evidence byte budget exceeded')
        required = self.brief['instruction_contract'].get('read_targets', [])
        if not all(self.resolved(p) in reads for p in required):
            raise SourceVerificationError("required exact contract input was not read")
        self.receipt = {'schema': SCHEMA, 'provenance': 'independent_owner_source_verification',
                        'native_capture_completeness': 'NOT_OBSERVED', 'native_child_environment': 'NOT_OBSERVED',
                        'binding': deepcopy(binding), 'manifest_sha256': digest(self.manifest),
                        'source_identity_sha256': digest(self.baseline), 'commands': results, 'retained_bytes': total}
        self.recheck(self.receipt)
        return deepcopy(self.receipt)

    def recheck(self, receipt):
        if self.receipt is None or receipt != self.receipt or self.identities() != self.baseline:
            raise SourceVerificationError("owner source proof missing, forged or stale")
        for path, pin in self.used_files.items():
            if self.file_pin(self.resolved(path)) != pin:
                raise SourceVerificationError("used source changed before result publication")
        return True
