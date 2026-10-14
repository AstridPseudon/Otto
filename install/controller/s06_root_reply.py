"""Run-local manual reply ingress: root-owned stdin grants exact payloads.

This is a bounded host adapter, not universal caller authentication or an
automatic production transport. Reader thread never reads or mutates Store.
Canonical checks run only on the existing serialized ExecutionHost lane.
"""
import hashlib
import json
import os
from pathlib import Path
import threading

FIELDS = {'command', 'request_key', 'issue_id', 'authority_source', 'response', 'proposed_solution', 'next_action'}
MAX_BYTES = 16384

def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()

def checked_request(value):
    if not isinstance(value, dict) or set(value) != FIELDS or value['command'] != 'respond-help':
        raise PermissionError('root stdin accepts only exact respond-help fields; no actor or routing overrides')
    if any(not isinstance(value[k], str) or not value[k].strip() or '\x00' in value[k] for k in FIELDS):
        raise ValueError('root response fields must be nonempty text')
    if len(encoded(value)) > MAX_BYTES:
        raise ValueError('root response exceeds bounded ingress size')
    return json.loads(encoded(value))

class RootStdinReply:
    def __init__(self, *, binding, authenticated_actor, delivery, portfolio, directory):
        self.binding = json.loads(encoded(binding))
        self.actor = authenticated_actor
        self.delivery, self.portfolio = delivery, portfolio
        self.directory = Path(directory)
        self.grants = {}
        self.lock = threading.Lock()

    def publish(self, envelope):
        """Only root-owned stdin calls this; validates syntax, never Store."""
        if not isinstance(envelope, dict) or set(envelope) != {'schema', 'binding', 'request'}:
            raise PermissionError('root envelope fields differ')
        if envelope['schema'] != 'otto.run-local.root-stdin-reply.v1' or envelope['binding'] != self.binding:
            raise PermissionError('root grant requires the exact adopted recipient binding')
        request = checked_request(envelope['request'])
        raw = encoded(request)
        token = hashlib.sha256(b'otto-root-stdin-reply-v1\0' + raw).hexdigest()
        path = self.directory / ('request-' + token + '.json')
        response = path.with_name('response-' + token + '.json')
        self.directory.mkdir(exist_ok=True)
        with self.lock:
            if path.exists() and json.loads(path.read_text()) != request:
                raise RuntimeError('retained root reply request identity differs')
            self.grants[hashlib.sha256(raw).hexdigest()] = self.binding
            if not path.exists() and not response.exists():
                temporary = path.with_name('.' + path.name + '.root-publish')
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
                try:
                    with os.fdopen(fd, 'wb') as stream:
                        stream.write(raw + b'\n'); stream.flush(); os.fsync(stream.fileno())
                    os.replace(temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)
        return {'outcome': 'root-granted', 'request_id': token, 'request_path': str(path),
                'response_path': str(response), 'provider_called': False,
                'canonical_response_recorded': False, 'transport': 'existing-file-ipc',
                'replayed_transport': response.exists(), 'grant_sha256': hashlib.sha256(raw).hexdigest()}

    def authorize(self, request):
        """Called by maintained installer on owner lane before effects."""
        request = checked_request(request)
        with self.lock:
            grant = self.grants.get(hashlib.sha256(encoded(request)).hexdigest())
        if grant != self.binding:
            raise PermissionError('manager IPC cannot authorize a recipient reply; exact root stdin grant missing')
        self.delivery.describe(self.binding['project_ref'])
        assignment = self.delivery.current_supervisor(self.binding['project_ref'])
        if (assignment.principal != self.actor.actor or self.actor.authority != self.binding['project_ref']['authority']):
            raise PermissionError('root actor differs from current bound recipient')
        loop = self.portfolio._issue_loop()
        issue = next((i for i in loop.read_issues(project_ref=self.binding['project_ref'])['issues']
                      if i['issue_id'] == request['issue_id']), None)
        if issue is None or issue['purpose'] != 'operational_help':
            raise PermissionError('root reply must target an actual operational help issue in the bound project')
        exact = any(v.get('state') == 'intent' and v.get('recipient_assignment_ref') == self.binding['assignment_ref']
                    and v.get('recipient_generation') == self.binding['generation']
                    and v.get('recipient_principal') == self.binding['principal']
                    and v.get('recipient_conversation') == self.binding['conversation_ref']['native_id']
                    and v.get('message', {}).get('type') == 'issue'
                    for v in issue['deliveries'])
        if not exact:
            raise PermissionError('actual help intent lacks the exact current recipient generation and conversation')
        return self.actor

    def serve_stdin(self, stream, emit):
        while True:
            line = stream.readline(MAX_BYTES + 2)
            if not line: return
            try:
                if len(line.encode()) > MAX_BYTES or not line.endswith('\n'):
                    raise ValueError('root stdin requires one bounded complete JSON line')
                receipt = self.publish(json.loads(line))
                emit({'root_reply_ingress': receipt})
            except Exception as error:
                emit({'root_reply_ingress': {'outcome': 'rejected', 'provider_called': False,
                     'error': str(error), 'canonical_response_recorded': False}})
