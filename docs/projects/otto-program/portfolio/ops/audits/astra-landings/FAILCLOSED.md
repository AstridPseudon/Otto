DEFECTS — the digest and relative-path fixes work by inspection, but operator refusal remains incomplete.

Reviewed merge `28408ce` against current `canon/main` (`eb9b6cd`); verified the Luna agents’ findings directly. No tests or Otto commands were run.

1. **Orchestrated creation still substitutes the owner for a missing operator.**  
   Compose `PortfolioOwnerBootstrap` with valid portfolio/root-assignment refs and `operator_actor=None`, then request pending creation. Dispatch bypasses `_operator()` at `src/otto/portfolio/herzchen_binding.py:456`; `_create_orchestrated_project` calls orchestration unguarded at `:534`. Bootstrap passes the missing operator through (`src/otto/portfolio/owner_bootstrap.py:728`), and orchestration substitutes `actor` (`src/herzchen/domains/work/orchestration.py:187`) and persists it as creator (`:461`). Template and create-and-open routes reach the same bypass. This remains on current main.
   
   **Fix — normal:** require the operator before invoking orchestration in `herzchen_binding.py`. Test the real orchestrated pending, template, and create-and-open routes with no operator: each must refuse without creating a project. Keep a configured-operator success case.

2. **Non-orchestrated create-and-open reports a saved project that was never created and consumes the request key.**  
   The new operator check runs inside the creation callback (`src/otto/portfolio/owner_bootstrap.py:479`). Authoring first persists the scope, actor reservation, and receipt (`src/herzchen/authoring/sessions.py:768`), then catches the missing-operator exception as a materialization failure (`:800`). It returns `saved_project_edit_not_opened` with the planned project reference supplied at `owner_bootstrap.py:546`, although no project exists. After configuring an operator, retrying the same key takes the prior-receipt path instead of creating it (`sessions.py:745`). This remains on current main.
   
   **Fix — normal:** resolve the operator before calling `authoring.create_and_open` at `owner_bootstrap.py:534`, then reuse it in the callback. Test refusal with no project, authoring reservation, or request receipt; supplying the operator and retrying the same key must succeed.

The acceptance tests are incomplete: `tests/test_operator_admission.py:114` checks private guards and raw folder import, but does not exercise every modified creation branch. Add missing-operator cases for ordinary pending creation, transfer import, template creation, and new-project save alongside the regressions above.

The legacy-stamp test (`tests/test_operator_admission.py:106`) and relative-exec test (`tests/test_host_contract.py:238`) would fail against the parent implementation by inspection. Their assertions are behavioral, not comparisons against the implementation’s own result; neither patches the guarded product method nor waits on a timer. No substantiated over-engineering finding.