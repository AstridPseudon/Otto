from scripts.slim_ledger import BASELINE_LINES, DELETION_TARGET, generate


def test_slim_ledger_records_baseline_callers_and_deletion_budget():
    ledger = generate()
    assert f"**{BASELINE_LINES:,} lines**" in ledger
    assert "**99 modules**" in ledger
    assert f"**{DELETION_TARGET:,} lines**" in ledger
    assert "production importers" in ledger
    assert "test importers" in ledger
    assert "dynamic production refs" in ledger
    assert "dynamic test refs" in ledger
    # A populated example proves caller locations are recorded rather than just
    # emitting headings and summary counts.
    assert "`src/otto/portfolio/cli.py:" in ledger
    assert "## SL9 measured deletion candidates" in ledger
    assert "inbox.py` | 1,415" in ledger
