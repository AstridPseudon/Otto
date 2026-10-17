# H35 cold-agent UX trace

Two fresh Luna agents received only this checkout path and the same four
prompts: where to implement a third `HostKind`, how to register/admit it, which
focused checks to run, and what needs the gate. Neither could see this task
brief or the project conversation. Times are the agents' reported elapsed
minutes, rounded to about two minutes.

## Baseline

- Time: about 2 minutes.
- Host extension point: correct. Located a `HostKind` implementation beside
  the existing implementations and `REGISTRY` in
  `src/herzchen/fleet/hosts/__init__.py`.
- Registration/admission: correct. Distinguished the fleet registry from
  Otto admission, and found the pinned adapter, capability, profile, and
  template steps.
- Focused checks: correct. Found `tests/test_host_contract.py`, the Otto
  hostctl/template checks, and Claude binding/admission examples.
- Gate: correct. Identified native launcher/fence proof and live owner journey
  as evidence beyond offline fixtures; live behavior remains unverified until
  a real journey.
- UX finding: the answers were accurate, but the contributor route was spread
  across the extension instructions and project tasklist. The distinction
  between registering a fleet kind and admitting it through Otto was not
  called out as a quick navigation step.

## After documentation update

- Time: about 2 minutes.
- Host extension point: correct, with direct references to `HostKind`, the new
  sibling module, and the registry in `docs/host-onboarding.md`'s contributor
  map.
- Registration/admission: correct. Explicitly separated fleet registration
  from `ottoctl service admit-host`, and identified the Otto config, service,
  adapter, profile, native verifier, and template paths.
- Focused checks: correct. Identified the contract test, four Otto wiring
  tests, and host-specific Claude binding/admission tests.
- Gate: correct. Identified native launcher/write-fence probing, owner or
  staging journeys, and sandbox checks requiring `sandbox-exec`, `ps`, or a
  staging owner; recorded that unavailable checks are `needs the gate`.

## Change made

Added the concise contributor map and gate boundary to
`docs/host-onboarding.md`. The first attempt did not give an incorrect answer;
the update makes the extension path and gate limits immediately scannable
without relying on the project tasklist.
