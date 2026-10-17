from scripts.slim_ledger import (
    BASELINE_LINES,
    BASELINE_MODULES,
    BASELINE_REVISION,
    DELETION_TARGET,
    current_portfolio_totals,
    generate,
)


def test_slim_ledger_records_baseline_callers_and_deletion_budget():
    ledger = generate()
    current_lines, current_modules = current_portfolio_totals()
    assert f"Immutable baseline at `{BASELINE_REVISION}`: **{BASELINE_LINES:,} lines** across **{BASELINE_MODULES} top-level modules**" in ledger
    assert f"Current checkout top-level portfolio: **{current_lines:,} lines** across **{current_modules} modules**" in ledger
    assert f"**{DELETION_TARGET:,} lines**" in ledger
    assert "production importers" in ledger
    assert "test importers" in ledger
    assert "dynamic production refs" in ledger
    assert "dynamic test refs" in ledger
    assert "Installed root commands from `build_client_parser()`" in ledger
    installed, injected = ledger.split("## Injected `otto` verbs", 1) if "## Injected `otto` verbs" in ledger else (ledger, "")
    assert "`ask`, `help`, `open`, `read`, `release`, `retire`, `save`, `show`, `status`, `wait`" in installed
    assert "`complete-task`" not in installed.split("## Module inventory", 1)[0]
    assert "`complete-task`" in injected.split("## Module inventory", 1)[0]
    # A populated example proves caller locations are recorded rather than just
    # emitting headings and summary counts.
    assert "`src/otto/portfolio/cli.py:" in ledger
    assert "`src/otto/portfolio/__init__.py:" in ledger
    assert "## SL9 measured deletion candidates" in ledger
    assert "manager_journey_service.py` | " in ledger
    assert "observability_contract.py` |" not in ledger.split("## SL9 measured deletion candidates", 1)[1]
    assert "advisor_context.py` |" not in ledger.split("## SL9 measured deletion candidates", 1)[1]
