## Source paths

Branch-derived lists below are Otto source paths (`src/` prefix omitted); I excluded tests unless they are themselves under `src/`. The roadmap assigns branch groups and dependencies at [astra-roadmap.md:87–101](../retro/evidence/otto-roadmap/astra-roadmap.md:87). Branch names and tips are in [BRANCH-LOG.md:5–37](../BRANCH-LOG.md:5).

- **O1 — automatic selection and `done`:** **[Inference from code search]** `herzchen/fleet/dispatch.py`, `herzchen/fleet/landing.py`, `herzchen/fleet/tools/{facade.py,rules.py}`, `otto/agents/claude_cli.py`, `herzchen/domains/work/{orchestration.py,lifecycle.py}`.

- **O2 — STAGE2CLIENT, CLIARGS, ROLEIDS, OBSOWNER, TESTPATCH:**  
  `otto/hostctl/{cli.py,service.py,config.py,register.py,serve.py}`, `otto/portfolio/{manager_journey_client.py,manager_journey_service.py,native_caller_ingress.py}`, `otto/agents/{claude_adapter.py,claude_cli.py}`.  
  Source diffs also include `otto/portfolio/tests/{test_native_caller_ingress.py,test_execution_continuity.py}`.

- **O3 — LABPIN, LANDPROOF, PL3, remaining PROCLIFE, EFFECTS:**  
  **Lab diffs:** `herzchen/domains/work/assignments.py`, `herzchen/fleet/{labs.py,landing.py,hosts/contract.py}`, `otto/agents/{codex_host_reader.py,orchestrator_route.py}`, `otto/hostctl/{adapters.py,fleet_landing.py,owner.py,product_service.py}`, `otto/portfolio/owner_bootstrap.py`.  
  **`proj/proclife` diff:** `herzchen/adapters/host.py`, `herzchen/fleet/{custody.py,hosts/__init__.py,hosts/contract.py,runner/client.py,runner/runner.py}`, `herzchen/kernel/process_identity.py`, `otto/agents/{claude_adapter.py,claude_cli.py,codex_host_reader.py,orchestrator_route.py,owner_runtime.py}`, `otto/hostctl/heavy.py`, `otto/portfolio/{execution_host.py,native_caller_ingress.py}`, `otto/runner_cli.py`.  
  **`proj/effects` diff:** `herzchen/fleet/runner/{__init__.py,effect_ledger.py,runner.py,server.py,store.py}`, `herzchen/kernel/{operations.py,store.py}`, `otto/agents/{effect_ledger.py,gateway.py,native_terminal_proof.py,owner_runtime.py}`, `otto/hostctl/{fleet_landing.py,product_service.py}`, `otto/portfolio/{__init__.py,cli.py,execution.py,execution_host.py,execution_operations.py,execution_resume.py,operating_setup.py,owner_bootstrap.py}`.

- **O4 — mandate and all-role launch gateway:** **[Inference from code search]** `herzchen/domains/work/{admission.py,assignments.py}`, `herzchen/fleet/{dispatch.py,capacity.py}`, `herzchen/kernel/limits.py`, `herzchen/usage/{accounting.py,contract.py}`, `otto/agents/{gateway.py,claude_adapter.py}`, `otto/hostctl/{service.py,serve.py}`.

- **O5 — receipts, messages, exits, monitor, supervisor:** **[Inference from code search]** `herzchen/{evidence/{commands.py,model.py},adapters/receipt.py,fleet/{file_ipc_receipts.py,landing.py,tools/{facade.py,rules.py}}}`, `otto/portfolio/{issue_loop.py,help_delivery.py,inbox.py,status.py,completion_gate.py,observability_views.py}`, `otto/attention.py`, `otto/hostctl/{serve.py,supervision.py}`.

- **O6 — PACKS, SLIM, TP3/TP6, worker capability:**  
  **`proj/packs` diff:** `herzchen/packs/{authoring.py,templates.py}`; `otto/agents/{claude_adapter.py,gateway.py,herzchen_adapter.py,host_profiles.py,orchestrator_route.py,owner_runtime.py}`; `otto/hostctl/{cli.py,config.py,portfolio_apply.py,register.py,service.py,skills.py}`; `otto/portfolio/{__init__.py,external_owner_execution.py,intake.py,manager_journey_service.py,operating_brief.py,role_context.py,run_config.py}`; plus `otto/packs/{astrid,engineering,megado,otto-profiles,otto-roles}/…`.  
  **`proj/slim` diff:** `herzchen/usage/contract.py`, `otto/{cli.py,hostctl/{cli.py,portfolio.py},portfolio/{__init__.py,advisor_context.py,advisor_host_command.py,cli.py,current_packet.py,events_candidate_proof.py,execution_operations.py,execution_resume.py,intake.py,manager_replacement.py,observability_contract.py,observability_views.py,role_context.py,show.py}`.  
  **`proj/throughput` diff:** `herzchen/fleet/{landing.py,tools/facade.py}`.

- **O7 — batch integration and user-path qualification:** **Branch-derived:** `otto/hostctl/heavy.py` (LANDBATCH); `herzchen/fleet/tools/facade.py`, `otto/hostctl/{fleet_landing.py,product_service.py}` (REALSTAGE3). DISTURB’s diff adds no `src/` paths. **[Inference from code search]** Qualification also exercises `otto/hostctl/{cli.py,service.py,serve.py}`.

- **G1 — git store and cloud adapter:** **[Inference from code search]** `herzchen/kernel/{store.py,operations.py}`, `herzchen/adapters/{host.py,receipt.py}`, `herzchen/fleet/hosts/{contract.py,codex.py,claude.py}`, `herzchen/fleet/runner/{store.py,server.py}`, `otto/hostctl/{adapters.py,service.py,serve.py}`, `otto/portfolio/execution_host.py`.

## Overlap and parallelism

The roadmap orders O2 after P3; O3 after O2; O4 after O1 and O3; O5 after O3/O4; O6 after O2/O4/O5; O7 after O1–O3 and T7; G1 after O4–O7 ([astra-roadmap.md:87–101](../retro/evidence/otto-roadmap/astra-roadmap.md:87)).

| Pair / group | Shared paths that matter | Parallel judgment |
|---|---|---|
| O1–O2 | `otto/agents/claude_cli.py` | **Inference:** avoid concurrent edits there; O1 can proceed on dispatch/landing while O2 owns its branch files. |
| O2–O3 | `otto/agents/claude_adapter.py`, `claude_cli.py`, `portfolio/native_caller_ingress.py` | O3 depends on O2; integrate O2 first. |
| O3 internal | `herzchen/fleet/hosts/contract.py`, `otto/agents/codex_host_reader.py`, `orchestrator_route.py`; proc/effects also share `owner_runtime.py`, `execution_host.py`, `fleet/runner/runner.py` | **Inference:** parallelize only exclusive files; assign shared custody/effect files to one integrator. |
| O3–O4/O5 | `otto/agents/gateway.py`, `owner_runtime.py`, `herzchen/fleet/landing.py`, `otto/hostctl/{fleet_landing.py,product_service.py}` | Integrate O3 before gateway and receipt/landing ports. |
| O4–O5–O6 | `otto/hostctl/service.py`, `serve.py`; `otto/agents/{gateway.py,claude_adapter.py}` | **Inference:** design can overlap, but changes to shared launch/service surfaces need staged integration. |
| O5–O7 | `herzchen/fleet/{landing.py,tools/facade.py}`, `otto/hostctl/{fleet_landing.py,product_service.py,serve.py}` | Qualification can be prepared earlier; integrate against the completed O5 path. |
| O6–O7 | `herzchen/fleet/tools/facade.py`, `herzchen/fleet/landing.py` | Keep worker-surface and qualification edits coordinated. |
| G1–O4–O7 | `herzchen/kernel/store.py`, `otto/hostctl/{service.py,serve.py}`, `otto/portfolio/execution_host.py` | G1 is downstream by roadmap dependency; shared authority/store semantics make earlier parallel implementation risky. |

**Hot spots (3+ roadmap items):** **[Inference, based on the branch-diff sets plus code-search scopes]** `otto/hostctl/service.py` (O2/O4/O5/O6/G1); `otto/hostctl/serve.py` (O2/O4/O5/O7/G1); `herzchen/fleet/landing.py` (O1/O3/O5/O7); `herzchen/fleet/tools/facade.py` (O1/O5/O6/O7); `otto/agents/claude_cli.py` (O1/O2/O5/O6); `otto/agents/claude_adapter.py` (O2/O3/O4/O6). Treat these as single-owner integration files.

**Inference:** the cleanest parallel work is among O6’s separate PACKS, SLIM, and throughput areas, and among O3’s exclusive branch files. O1 can start alongside O2 if `claude_cli.py` has a clear owner. Otherwise, roadmap dependencies and the hot spots call for staged integration rather than unrestricted concurrent edits.