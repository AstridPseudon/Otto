"""Connected Frame intent fixture. Source/test content, not canonical adoption."""
from herzchen.contracts import ReferenceBinding

# Name, kind, reading parent, summary, responsibility/tradeoff sketch.
PAGES = (
    ("frame", "product", None, "Creators finish recoverable collaborative media projects across devices.",
     "## Promise\nA creator can start on desktop, review in the browser and continue after a disconnect.\n\n## Deliberate tradeoff\nPreserve user intent and explain conflicts even when immediate consistency is unavailable."),
    ("creation", "area", "frame", "Make and preview a project with predictable local feedback.",
     "Own the creation loop from source media to timeline to preview. A fast preview may differ from final output; make that approximation visible. Keep editing independent of render scheduling."),
    ("collaboration", "area", "frame", "Share intent without concealing concurrent work or recovery choices.",
     "Own exchange and conflict presentation. Reconciliation produces alternatives instead of silently discarding a local draft. Offline permission revocation remains an open boundary."),
    ("web", "repository", "collaboration", "Browser review and lightweight collaborative editing.",
     "Present project intent, review comments and reconciliation choices. Delegate durable journal semantics to model/sync. Trade browser portability against offline storage limits."),
    ("desktop", "repository", "creation", "Durable disconnected editing and local media access.",
     "Own local working copies, recovery UI and device integration. The desktop app presents conflicts but does not invent a second project model. Budget disk use explicitly."),
    ("model", "repository", "creation", "Portable project operations, identities and deterministic interpretation.",
     "Own operation identity, timeline types and migration boundaries. Stable operation IDs survive replay across repositories. A small shared contract avoids hiding UI-specific choices in the model."),
    ("sync", "repository", "collaboration", "Exchange operations and reconcile divergent replicas.",
     "Own delivery acknowledgements and reconciliation boundaries. Transport retries reuse operation IDs. Reconciliation returns candidate alternatives; the user chooses consequential conflicts."),
    ("media", "repository", "creation", "Preview and render media with explicit resource budgets.",
     "Own decoding, media references and render evaluation. Keep canonical project intent independent of codec details. Low-resolution previews trade fidelity for timely feedback."),
    ("agents", "repository", "collaboration", "Agents propose attributed edits within current authorized scope.",
     "Own agent session orchestration and bounded context delivery. Proposed architecture is advisory; current tasks and Direction govern effects. Preserve exact observations and recoverable proposals."),
    ("api", "repository", "collaboration", "Authenticated access and durable platform capabilities.",
     "Own authorization checks, shared resource APIs and revocation. Avoid granting access merely because a reference was shared. Decide the disconnected revocation boundary with desktop/sync owners."),
    ("offline", "concept", "collaboration", "Recover disconnected work and reconcile without silent loss.",
     "## Principle\nP-preserve: retain recoverable user intent.\n\n## Transition\nA recovery copy is useful before the complete operation journal exists.\n\n## Open tension\nImmediate remote revocation and disconnected editing require a visible reconciliation boundary."),
    ("operation-identity", "concept", "creation", "Replay has stable logical operation identity across replicas.",
     "An operation ID names user intent independently of network attempts. Deduplicate transport retry, preserve causal context and avoid equating physical attempts with logical edits. Define conflict presentation separately."),
    ("journal", "subsystem", "collaboration", "Journal, reconciliation and conflict presentation form distinct boundaries.",
     "The journal records stable operation IDs and dependencies. Reconciliation computes candidate state from replicas; presentation explains alternatives without replacing the working copy. Sync/model own semantics; desktop/web own consequential user choice."),
    ("preview", "subsystem", "creation", "Incremental preview evaluates project intent within local budgets.",
     "Model changes invalidate affected media evaluation. The media engine schedules bounded decode/render work; desktop/web present preview fidelity. Prefer reusable references over copying project state into render jobs."),
)


def frame_nodes(definition, refs):
    def binding(name):
        return ReferenceBinding(refs[name], "current").to_dict()

    nodes = {}
    for name, kind, parent, summary, body in PAGES:
        nodes[name] = {
            "schema": "vision.node.v1", "definition": definition, "kind": kind,
            "title": "Frame" if name == "frame" else name.replace("-", " ").title(),
            "summary": summary, "body_markdown": body, "maturity": "proposed",
            "as_of": "2026-10-11", "horizon": {"label": "next year", "target_range": "2027"},
            "navigation_parent": binding(parent) if parent else None,
            "applies_to": [], "relationships": [], "sources": [], "work_refs": [],
            "repository": {"key": name, "locator": "frame/" + name} if kind == "repository" else None,
            "members": [binding(member[0]) for member in PAGES if member[0] != "frame"] if name == "frame" else None,
        }
    for name, repositories in {
        "offline": ("desktop", "sync", "model"), "operation-identity": ("model", "sync", "agents"),
        "journal": ("sync", "model", "desktop", "web"), "preview": ("media", "model", "desktop", "web"),
    }.items():
        nodes[name]["applies_to"] = [binding(repo) for repo in repositories]
    nodes["offline"]["relationships"] = [
        {"id": "operations", "relation": "depends_on", "target": binding("operation-identity")},
        {"id": "reconciliation", "relation": "refines", "target": binding("journal")},
        {"id": "access", "relation": "in_tension_with", "target": binding("api"),
         "note": "Offline work and immediate remote access revocation need an explicit boundary."},
    ]
    return nodes
