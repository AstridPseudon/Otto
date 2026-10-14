# Project onboarding

Use the installed Otto entrypoint and its `onboarding` route to start one
ordinary draft:

```sh
python -m otto.portfolio.cli help --format text
python -m otto.portfolio.cli onboarding create \
  --actor OWNER \
  --request-id onboarding-create-1 \
  --title "A useful idea" \
  --brief "The short brief that explains what to explore."
```

The route requires a non-blank title and brief. It optionally accepts bounded
UTF-8 supporting files, an existing predecessor reference for later queue-after
work, and an owner-adopted blank/template resource. The default is the existing
blank pending project path.

The result contains a canonical `project_ref`, a stable logical
`workspace.locator`, the current EDT projection, and the brief's DAT document
membership at `brief.md`. The physical checkout path is session-scoped and is
not the workspace identity. Reopen the same project with a fresh request key:

```sh
python -m otto.portfolio.cli onboarding find \
  --actor OWNER --project-ref 'PROJECT_REF_JSON'
python -m otto.portfolio.cli onboarding reopen \
  --actor OWNER --request-id onboarding-reopen-1 \
  --project-ref 'PROJECT_REF_JSON'
```

Creation is a finite composition over the existing owner-backed pending
ProjectSheet, DAT document/link, and EDT checkout ports. It does not create a
Store, local authoritative project folder, task, role, pool, schedule, provider
call, or activation. The generic default-orchestrator route remains a separate
explicit compatibility operation; this entry uses live inert owner authoring.

If the exact authenticated owner binding is not installed, the command returns
`binding.state=missing` and an actionable next action. The read-only `find`
operation additionally requires the host-issued finite project-read grant.
Do not substitute a filesystem bootstrap, controller script, Store path, or
another actor's credentials.

Exploration, executable planning, review, queue-after, and activation remain
document or later lifecycle work. Use the existing check-in/release and
recovery commands for the returned EDT projection; a successful create or
reopen is not task acceptance or execution readiness.
