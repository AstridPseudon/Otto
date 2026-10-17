from pathlib import Path


REPORT = Path(__file__).parents[1] / ".project" / "after.md"


def test_after_report_distinguishes_evidence_and_deletions():
    text = REPORT.read_text()
    assert "3,394 s" in text and "2,301 s" in text and "1,300 s" in text
    assert "not CPU time" in text
    assert "No sealed runner records or accepted-task runs are available" in text
    assert "`/usr/bin/true`" in text
    assert "TP2 is blocked" in text and "TP4 is blocked" in text
    assert "The landing/staging gate was not run" in text
    assert "TP1 | +126/-0" in text
    assert "TP3 | +100/-0" in text
    assert "TP6 | +114/-8" in text
    assert "No source deletion is justified" in text
    assert "test runtimes are correctness evidence only" in text
