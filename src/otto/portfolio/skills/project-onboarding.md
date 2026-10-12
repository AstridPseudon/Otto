# Project onboarding

This is the installed, user-facing route for starting one ordinary Otto
project. It composes existing owner-authenticated Work, DAT and EDT operations;
it is guidance, not a second state store or a new lifecycle engine.

## Start from installed help

Use the exact command and private descriptor issued by the host for your own
finite onboarding journey. The maintained authenticated caller is:

```sh
python -m otto.portfolio.onboarding_bound_cli --connection ISSUED_PRIVATE_DESCRIPTOR \
  --request-json '{"operation":"help"}'
python -m otto.portfolio.onboarding_bound_cli --connection ISSUED_PRIVATE_DESCRIPTOR \
  --request-json '{"operation":"cli","argv":["onboarding","create","--request-id","onboarding-create-1","--title","A useful idea","--brief","A short exploration brief"]}'
```

The host issues this finite consumer facade over its existing owner and
serialized lane using `issue_bound_onboarding_tool`. It fixes the current root
assignment, generation, actor, project reader and allowed operations. The
private descriptor is a bearer capability; keep it private and return only
receipt refs and exact readbacks. A manager must not borrow a root descriptor.
An absent descriptor is unavailable authentication; the caller cannot mint one.

Draft creation is inert: no task, role, pool, Due record or provider effect.
This issuance supports title and brief only; template claims are unavailable.
Use its `whoami`, exact returned project/session refs, `save`, `release` and
`onboarding find/reopen` commands to resume the same draft. Stable operation
keys reconcile original effects; changed input and stale sessions are refused.

The generic `otto.portfolio.cli.main` remains an injected host API and help
surface. Running its module by itself does not authenticate. The production
protected owner-authoring ingress remains a distinct admitted root route for
`project-authoring`, `document-authoring`, `project-queue` and owner context.
Its own role supplies the current locator; no caller should construct or copy
a protected envelope or controller script. Disposable connected qualification
loads this installed client and actual owner ports in one tiny fixture; it
does not enroll or activate a production project or call a provider.

The physical checkout path is session-scoped; the canonical project reference
and logical workspace locator are the identity. Do not create a replacement
`.otto/runs` folder when an EDT session is interrupted.

## Connected cold journey

The caller receives only installed help, an authenticated owner capability,
the title/brief and any deliberately selected files or predecessor. It then:

1. creates or reopens the same pending project and saves exploration, plan and
   review as documents;
2. imports/checks in selected files using the existing bounded per-document
   composition, retaining progress and child receipts for interruption,
   changed-input replay, path collision and stale-base conflicts;
3. reads current role identity and adopted context with the installed
   `whoami`/`effective-context` route, then reads setup/readiness and the current
   manager/root destination;
4. uses the owner-authenticated queue-after composition and its one canonical
   queue locator, without editing a second ordered list;
5. waits for genuine predecessor terminal readback before explicit activation,
   then keeps setup activation, dispatch and `finish-project` closeout distinct.

Every stage preserves the same project identity and reports partial or unknown
effects honestly. A lost response is reconciled through its original handle;
it is never replayed with a new key. No caller step opens Store or requires private
controller imports.

## Preparation/proposal preflight

Before an effect, resolve and retain:

- the current canonical required scope and its `_digest`;
- one actual runnable selected configuration and its adopted resource pins;
- the original candidate, source and evidence references/hashes when present;
- an operation-specific unique backup path; and
- the exact missing-stage resume state.

Compare top-level and nested proposal sources and the candidate before debit.
Reject malformed or refused proposals without rewriting a verdict or forcing a
PASS. Preserve custody, adoption, native identity, budgets and immutable
history. Bounded artifact reads use the installed `read-artifact` contract with
`--offset 0 --max-bytes 4096`; an empty artifact inventory is unavailable
evidence, not success. Local key/hash/path repair is not part of recovery.

## Current guidance and supersession

Use the current role introduction for the exact installed command and resource
pins, [identity and directions](references/identity-and-directions.md) for
caller context, [manager guidance](references/manager.md) for current manager
and root coordination, [recovery](recovery/SKILL.md) for interrupted work,
`operating-setup --operation read` for readiness, and `finish-project` for
closeout. Existing historical `queued-transition.md`, old proposal or
folder-format pages, and controller-specific examples are retained evidence
only. They are superseded by this installed route and must not be used as a
second queue, root binding, or recovery authority.

Installation or skill discovery does not adopt resources into an existing
assignment. The owner must expose the selected resource/command pins and
current authenticated route; source-only examples cannot establish installed
behavior.
