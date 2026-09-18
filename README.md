# Otto

Otto is a small, owner-bound coordination layer for agent work. It turns a
request into a bounded operation, keeps responsibility and evidence explicit,
and hands durable state to the canonical Herzchen owner. The central idea is
simple: a prompt is not authority, a queued request is not proof of execution,
and a completed model turn is not the same thing as completed work.

## Philosophy

- **One owner, one source of truth.** Otto does not create a second database,
  scheduler, queue, or receipt system. Herzchen owns durable identities,
  assignments, revisions, transactions, receipts, and events.
- **Finite boundaries.** Host adapters and owner ports expose only the
  operations a caller is allowed to use. Unsupported capabilities stay
  visible as unsupported instead of becoming local no-ops or synthetic passes.
- **Evidence before claims.** Every admitted action carries a logical request
  key, scoped assignment and generation, pinned inputs, and an observable
  result. Unknown, stale, replayed, and rejected outcomes remain distinct.
- **Progress is reversible.** Source publication, merge, package release,
  installation, deployment, and project closure are separate decisions. A
  partial result names what happened and what still needs an owner.

## Approach

Otto validates a typed request, checks the current owner and assignment fence,
and delegates transport to an injected host adapter. The adapter may invoke or
resume a native agent, but Otto does not own that process or pretend that it can
inspect capabilities the adapter does not provide. On the durable path,
`PortfolioOwnerBootstrap` connects Otto to Herzchen's public command and read
ports. Consumer code receives finite serialized operations; it never receives a
database connection, raw SQL writer, or private event store.

The portfolio layer composes that boundary into a few focused workflows:

- current action packets and safe continuation/resume;
- manager inbox and readiness/reconciliation views;
- responsibility assignments, guarded completion, and evidence reports;
- attention and due-record continuity;
- repository candidate, source-set, merge, publication, and deployment records.

## Repository structure

```text
src/otto/agents/       host responsibility gateway and attempt capture
src/otto/portfolio/    owner binding, inbox, packets, intake, and workflows
src/otto/engineering/  repository and release-record boundary
src/otto/attention.py  due obligations and attention continuity
profiles/otto/         operating guidance for bounded handoffs and custody
tests/otto/            focused contract, replay, fence, and continuity tests
```

## Development

Run the focused suite with the source tree and a compatible Herzchen runtime
available:

```bash
PYTHONPATH=src:<herzchen-site-packages> python -m pytest -q tests/otto
```

Build a wheel without pulling dependencies into the environment:

```bash
python -m pip wheel . --no-deps --no-build-isolation -w dist
```

Before a release, verify the source commit/tree, package hash, installed import
origins, owner receipts, and remote revision separately. A passing test suite
does not by itself prove host delivery, publication, installation, or project
closure.
