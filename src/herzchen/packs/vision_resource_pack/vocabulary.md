# Vision vocabulary

Vision describes intended product and architecture structure in ordinary DAT
documents. A `product` is the collection root; `area`, `repository`, and
`subsystem` refine its reading structure. A `concept` is cross-cutting intent;
`design-decision` records a proposed tradeoff or unresolved choice.

`navigation_parent` is the single reading parent. It is not a semantic edge.
`members` is the root collection roster and is the only collection membership
source. `applies_to` attaches a concept or other node to repository
descriptions. Typed relationships are `refines`, `contributes_to`,
`depends_on`, `in_tension_with`, and `supersedes`.

Vision content is advisory. It does not describe observed implementation,
current Direction, authorized tasks, grants, or actor identity. A resource
definition validates content; it never grants access, launches a provider,
executes code, or creates storage.
