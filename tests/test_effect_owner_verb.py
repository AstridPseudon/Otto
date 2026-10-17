"""Owner command lane passes an authenticated resolver to exact effect settlement."""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from herzchen.contracts import AuthenticatedActor, ResourceRef
from herzchen.kernel import OperationRecord, OperationRequest, OperationState
from otto.portfolio import cli


class EffectOwnerVerbTests(TestCase):
    def test_resolve_uses_authenticated_owner_actor_and_minted_key(self):
        actor = AuthenticatedActor("owner", "otto-owner", "owner-credential")
        effect_ref = ResourceRef("owner", "effect", "held-native-turn")
        request = OperationRequest(
            "otto.native-turn", "v1", ResourceRef("owner", "adapter", "native-turn"),
            AuthenticatedActor("owner", "requester", "requester-credential"),
            effect_ref.id, "a" * 64, {"turn_id": "turn-7"},
        )
        held = OperationRecord(ResourceRef("owner", "operation", effect_ref.id, "rev-2"), request,
                               OperationState.UNKNOWN, {}, None, 2)
        manager = _Manager(held)
        session = SimpleNamespace(
            store=object(), portfolio=object(),
            owner=SimpleNamespace(owner_actor=actor),
        )
        argv = ["effects", "resolve", "--effect-ref", json.dumps(effect_ref.to_dict()),
                "--state", "committed", "--evidence-key", "exact-terminal-proof"]

        with patch.object(cli, "OperationManager", return_value=manager):
            output = cli.owner_verb(argv, session=session, home=Path("/tmp"))

        self.assertEqual(manager.resolver, actor)
        self.assertTrue(manager.transition_key.startswith("otto-effects-resolve:"))
        self.assertEqual(output["outcome"], "resolved")
        self.assertEqual(output["effect_ref"], effect_ref.to_dict())
        self.assertEqual(output["state"], "committed")


class _Manager:
    def __init__(self, held):
        self.held = held
        self.resolver = None
        self.transition_key = None

    def get(self, key):
        return self.held if key == self.held.effect_ref.id else None

    def resolve_unknown(self, record, state, result, **kwargs):
        self.resolver = kwargs["resolver"]
        self.transition_key = kwargs["transition_key"]
        if not isinstance(self.resolver, AuthenticatedActor):
            raise TypeError("resolver must be AuthenticatedActor")
        return OperationRecord(record.operation_ref, record.request, state, result, None, record.version + 1)
