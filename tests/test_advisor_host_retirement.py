"""The unreferenced paused-host adoption prototype is retired."""
from pathlib import Path


def test_paused_host_prototype_files_are_absent():
    root = Path(__file__).resolve().parents[1]
    assert not (root / "src/otto/portfolio/advisor_host_command.py").exists()
    assert not (root / "tests/test_manager_advisor_paused_host.py").exists()
