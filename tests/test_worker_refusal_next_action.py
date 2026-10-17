"""Worker-facing facade refusals explain the practical recovery step."""

from herzchen.fleet.tools import CHECK, DONE, TASK, FeedbackLedger, ToolFacade, ToolSpec, TokenBook


class Owner:
    def call(self, operation, assignment, args, *, feedback):
        return {"ok": True}


def _facade():
    tools = (
        ToolSpec("task", TASK, "task", args=("title",)),
        ToolSpec("check", CHECK, "check"),
        ToolSpec("done", DONE, "done"),
    )
    book = TokenBook()
    token = book.issue("assignment-1", "worker")
    facade = ToolFacade(tools, {"worker": ("task", "check", "done")}, Owner(), book, FeedbackLedger())
    return facade, book, token


def test_invalid_or_revoked_assignment_tokens_say_how_to_recover():
    facade, book, token = _facade()
    expected = "Use the current token for this assignment; ask the owner to issue a replacement if it was revoked or lost."

    assert facade.listing("unknown-token")["next_action"] == expected
    assert facade.call("unknown-token", "task", {"title": "work"})["next_action"] == expected
    book.issue("assignment-1", "worker")
    assert facade.call(token, "task", {"title": "work"})["next_action"] == expected


def test_unavailable_tool_says_to_choose_from_the_workers_listing():
    facade, _book, token = _facade()

    refusal = facade.call(token, "not_for_this_worker", {})

    assert refusal["next_action"] == "Call tools/list with this token and choose one of the tools listed for your role."


def test_bad_argument_refusals_explain_schema_and_json_recovery():
    facade, _book, token = _facade()

    cases = (
        (["title", "work"], "Send arguments as a JSON object matching the selected tool's args schema."),
        ({"extra": "value"}, "Remove undeclared fields; use only arguments listed by tools/list."),
        ({"title": object()}, "Replace the value with JSON data, such as a string, number, boolean, null, array, or object."),
    )
    for args, expected in cases:
        refusal = facade.call(token, "task", args)
        assert refusal["error"] == "bad_args"
        assert refusal["next_action"] == expected
