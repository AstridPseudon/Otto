"""Suggested effect commands preserve the exact JSON argument through a shell."""
from contextlib import redirect_stdout
from io import StringIO
import json
import re
import shlex
from types import SimpleNamespace
from unittest import TestCase

from herzchen.contracts import AuthenticatedActor, ResourceRef
from herzchen.kernel import OperationRecord, OperationRequest, OperationState
from herzchen.fleet.runner.runner import Runner
from otto.portfolio import cli


class EffectCommandQuotingTests(TestCase):
    def setUp(self):
        self.effect_ref = ResourceRef("owner", "effect", 'held_"native"_turn')
        request = OperationRequest(
            "fixture.native-turn", "v1", ResourceRef("owner", "adapter", "fixture"),
            AuthenticatedActor("owner", "requester", "credential"), self.effect_ref.id,
            "a" * 64, {"turn_id": "turn-7"},
        )
        self.record = OperationRecord(
            ResourceRef("owner", "operation", self.effect_ref.id, "rev-2"), request,
            OperationState.UNKNOWN, {}, None, 2,
        )

    def test_effect_read_next_action_shell_parses_to_exact_json_reference(self):
        output = StringIO()
        with redirect_stdout(output):
            cli.main(["effects", "read", "--effect-ref", json.dumps(self.effect_ref.to_dict())],
                     effect_manager=_Manager(self.record))
        response = json.loads(output.getvalue())
        suggested = _command(response["next_action"])
        args = shlex.split(suggested)
        self.assertEqual(args[:3], ["otto", "effects", "resolve"])
        self.assertEqual(json.loads(args[args.index("--effect-ref") + 1]), self.effect_ref.to_dict())

    def test_runner_unknown_guidance_shell_parses_to_exact_json_reference(self):
        runner = Runner.__new__(Runner)
        runner._effect_ledger = _Manager(self.record)
        response = runner._unknown_effect_guidance({"state": "unknown", "run_id": self.effect_ref.id})
        suggested = _command(response["next_action"])
        args = shlex.split(suggested)
        self.assertEqual(args[:3], ["otto", "effects", "read"])
        self.assertEqual(json.loads(args[args.index("--effect-ref") + 1]), self.effect_ref.to_dict())


def _command(action):
    match = re.search(r"`([^`]*)`", action)
    if match is None:
        raise AssertionError("next_action did not include a command")
    return match.group(1)


class _Manager:
    def __init__(self, record):
        self.record = record

    def get(self, key):
        return self.record if key == self.record.effect_ref.id else None

    def matches(self, sealed_record, effect):
        return effect is self.record
