# Cold worker UX trace

Trace time: about 4 minutes, from reading the worker-facing facade and tool schemas through mapping the successful path and refusal recovery.

## Available verbs and successful path

The worker-facing surface has three verbs: `task`, `check`, and `done`. The listing is token-scoped and exposes each tool's name, kind, description, and declared argument names. The assignment is carried by the token; it is not a worker argument.

1. Call `tools/list` with the assigned token and choose an available tool.
2. Call `task` with a JSON object containing only declared arguments to perform the work.
3. Call `check` with its declared arguments to get feedback. A successful check is recorded in the feedback ledger and explicitly reports `accepted: false`.
4. Address feedback, then call `done` to submit. A successful `done` reports `submitted: true` and `accepted: false`.

The surface stays at four MCP tools (list plus the three worker verbs); this change only adds guidance to refusal replies.

## Refusal recovery, before and after

Before: the facade returned `ok: false`, an error code, and a short detail. For an unknown or revoked token, an unavailable tool, or bad arguments, the worker had no indicated next step and had to infer how to recover.

After: those refusals include `next_action` with a case-specific instruction:

- Unknown, stale, or revoked token: use the current assignment token; ask the owner to issue a replacement if it was revoked or lost.
- Tool unavailable to this role: call `tools/list` with the token and choose a listed tool.
- Arguments are not a mapping: send a JSON object matching the selected schema.
- Undeclared argument: remove it and use only fields listed by `tools/list`.
- Non-JSON value: replace it with JSON data.

## Friction found

`call(..., args=None)` is normalized to an empty argument object, so `None` does not exercise the “arguments must be a mapping” refusal. The focused regression test uses a list to reach that branch. The tool listing provides field names but no argument types or required/optional markers, so its schema guidance is limited to declared names and JSON shape.
