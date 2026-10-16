"""Tests for the product-neutral tool facade core in herzchen.fleet.tools."""

import pytest

from herzchen.fleet.tools import (
    CHECK,
    DONE,
    KINDS,
    TASK,
    Acceptance,
    AcceptanceError,
    FeedbackLedger,
    OwnerPort,
    ToolFacade,
    ToolRuleError,
    ToolSpec,
    TokenBook,
)

# --- core: tokens, facade, check-versus-done

ROLE = "worker"
TASK_TOOL = "task_run"
CHECK_TOOL = "run_check"
DONE_TOOL = "submit"
TASK_OP = "do_task"
CHECK_OP = "run_check_op"
DONE_OP = "submit_op"

CANNED = {
    TASK_OP: {"status": "started", "accepted": True, "acceptance": "yes"},
    CHECK_OP: {"run_id": "run-1", "commit": "c1", "ok": True, "accepted": True},
    DONE_OP: {"submitted": True, "counts_as_acceptance": True},
}


class FakeOwner(OwnerPort):
    """Records every call and returns canned replies. An exception value is raised instead."""

    def __init__(self, replies=None):
        self.replies = dict(CANNED if replies is None else replies)
        self.calls = []

    def call(self, operation, assignment, args, *, feedback):
        self.calls.append(
            {"operation": operation, "assignment": assignment, "args": dict(args), "feedback": feedback}
        )
        reply = self.replies[operation]
        if isinstance(reply, Exception):
            raise reply
        return reply


def _tools():
    return [
        ToolSpec(name=TASK_TOOL, kind=TASK, operation=TASK_OP, args=("title",), description="Do the work"),
        ToolSpec(name=CHECK_TOOL, kind=CHECK, operation=CHECK_OP, args=("suite",), description="Check the work"),
        ToolSpec(name=DONE_TOOL, kind=DONE, operation=DONE_OP, description="Submit for review"),
    ]


def _facade(owner=None, book=None, ledger=None, roles=None):
    owner = owner if owner is not None else FakeOwner()
    book = book if book is not None else TokenBook()
    ledger = ledger if ledger is not None else FeedbackLedger()
    roles = roles if roles is not None else {ROLE: (TASK_TOOL, CHECK_TOOL, DONE_TOOL)}
    facade = ToolFacade(_tools(), roles, owner, book, ledger)
    return facade, book, ledger, owner


def test_token_scoped_to_assignment():
    facade, book, _ledger, owner = _facade()
    t1 = book.issue("a1", ROLE)
    t2 = book.issue("a2", ROLE)

    smuggled = facade.call(t1, TASK_TOOL, {"assignment": "a2", "title": "x"})
    assert smuggled["ok"] is False and smuggled["error"] == "bad_args"
    not_json = facade.call(t1, TASK_TOOL, {"title": object()})
    assert not_json["ok"] is False and not_json["error"] == "bad_args"
    assert owner.calls == []

    reply = facade.call(t1, TASK_TOOL, {"title": "x"})
    assert reply["ok"] is True and reply["kind"] == "task"
    assert owner.calls[-1]["assignment"] == "a1"

    facade.call(t2, TASK_TOOL, {"title": "y"})
    assert owner.calls[-1]["assignment"] == "a2"

    book.issue("a1", ROLE)
    old = facade.call(t1, TASK_TOOL, {"title": "z"})
    assert old == {"ok": False, "error": "unauthorized", "detail": "unknown token"}

    book.revoke("a2")
    assert facade.call(t2, TASK_TOOL, {"title": "z"})["error"] == "unauthorized"

    for forged in ("forged-token", "", None, 42):
        assert facade.call(forged, TASK_TOOL, {"title": "z"})["error"] == "unauthorized"

    assert book.live() == frozenset({"a1"})
    assert t1 not in repr(book)
    assert t2 not in repr(book)
    assert t1 not in repr(vars(book))


def test_worker_check_never_counts_as_acceptance():
    facade, book, ledger, owner = _facade()
    token = book.issue("a1", ROLE)
    acceptance = Acceptance(ledger)

    reply = facade.call(token, CHECK_TOOL, {"suite": "unit"})
    assert reply["ok"] is True and reply["kind"] == "check"
    assert reply["feedback"] is True and reply["accepted"] is False
    assert "accepted" not in reply["result"]
    assert "acceptance" not in reply["result"]
    assert owner.calls[-1]["feedback"] is True

    [entry] = ledger.entries("a1")
    assert entry["kind"] == "feedback"
    assert entry["counts_as_acceptance"] is False

    with pytest.raises(AcceptanceError):
        acceptance.record("a1", "c1", {"run_id": "run-1", "commit": "c1", "ok": True})
    assert acceptance.accepted("a1", "c1") is False

    acceptance.record("a1", "c1", {"run_id": "run-9", "commit": "c1", "ok": True})
    assert acceptance.accepted("a1", "c1") is True
    assert acceptance.accepted("a1", "c2") is False

    with pytest.raises(AcceptanceError):
        acceptance.record("a1", "c2", {"run_id": "run-10", "commit": "c1", "ok": True})
    with pytest.raises(AcceptanceError):
        acceptance.record("a1", "c2", {"run_id": "run-11", "commit": "c2", "ok": False})
    assert acceptance.accepted("a1", "c2") is False

    done = facade.call(token, DONE_TOOL, {})
    assert done["ok"] is True and done["kind"] == "done"
    assert done["submitted"] is True and done["accepted"] is False
    assert "accepted" not in done["result"]
    assert "counts_as_acceptance" not in done["result"]

    other = book.issue("a3", ROLE)
    facade.call(other, DONE_TOOL, {})
    assert acceptance.accepted("a3", "c1") is False


def test_role_limits_tools():
    facade, book, _ledger, owner = _facade(roles={"limited": (TASK_TOOL,)})
    token = book.issue("a1", "limited")

    assert facade.listing(token) == [
        {"name": TASK_TOOL, "kind": TASK, "description": "Do the work", "args": ["title"]}
    ]
    assert facade.call(token, CHECK_TOOL, {"suite": "unit"})["error"] == "forbidden"
    assert facade.call(token, DONE_TOOL, {})["error"] == "forbidden"
    assert facade.call(token, "no_such_tool", {})["error"] == "forbidden"
    assert owner.calls == []
    assert facade.call(token, TASK_TOOL, {"title": "ok"})["ok"] is True

    full, full_book, _, _ = _facade()
    full_token = full_book.issue("a2", ROLE)
    assert [spec["name"] for spec in full.listing(full_token)] == [TASK_TOOL, CHECK_TOOL, DONE_TOOL]

    with pytest.raises(ToolRuleError):
        _facade(roles={ROLE: ("missing_tool",)})


def test_toolspec_rejects_reserved_args():
    for reserved in ("assignment", "token", "role", "feedback", "accepted", "acceptance"):
        with pytest.raises(ToolRuleError):
            ToolSpec(name="t", kind=TASK, operation="op", args=(reserved,))
    with pytest.raises(ToolRuleError):
        ToolSpec(name="t", kind="boss", operation="op")
    with pytest.raises(ToolRuleError):
        ToolSpec(name="Bad Name", kind=TASK, operation="op")
    assert KINDS == (TASK, CHECK, DONE)


def test_owner_failure_is_generic():
    owner = FakeOwner({TASK_OP: RuntimeError("secret-token-xyz")})
    facade, book, _ledger, _ = _facade(owner=owner)
    token = book.issue("a1", ROLE)

    reply = facade.call(token, TASK_TOOL, {"title": "x"})
    assert reply == {"ok": False, "error": "owner_unavailable", "detail": "RuntimeError"}
    assert "secret-token-xyz" not in repr(reply)
    assert token not in repr(reply)
