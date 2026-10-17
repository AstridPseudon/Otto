import contextlib
import io
import json
from types import SimpleNamespace
from unittest.mock import patch

from herzchen.fleet.runner.client import RunnerUnavailable
from otto import runner_cli


def test_submit_transport_failure_exposes_key_for_exact_retry():
    requests = []

    class Client:
        def __init__(self, fail):
            self.fail = fail

        def call(self, request):
            requests.append(dict(request))
            if self.fail:
                raise RunnerUnavailable("reply lost")
            return {"ok": True, "run_id": "run-1"}

    args = SimpleNamespace(argv=["/bin/true"], cwd=None, weight=1, task="untasked",
                           purpose=None, max_minutes=None, request_id=None, wait=False)
    out = io.StringIO()
    with patch.object(runner_cli.uuid, "uuid4", return_value=SimpleNamespace(hex="retryable-key")), \
            contextlib.redirect_stdout(out):
        code = runner_cli._submit(args, Client(fail=True))
    failure = json.loads(out.getvalue())
    assert code == runner_cli.EXIT_UNREACHABLE
    assert failure["request_id"] == "retryable-key"

    args.request_id = failure["request_id"]
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        retry_code = runner_cli._submit(args, Client(fail=False))
    assert retry_code == 0
    assert requests[0]["request_id"] == requests[1]["request_id"] == "retryable-key"
