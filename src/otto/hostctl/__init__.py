"""Host-neutral Otto installation: one agent CLI host, its own isolated owner.

``ottoctl`` (``otto.hostctl.cli``) initialises a host's Store and root
orchestrator, reads identity and context through the owner's external
context route, registers Megado run bundles as pending projects and dry-runs
role admission. See docs/host-onboarding.md.
"""
