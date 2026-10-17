"""The unentered ORC packet prototype must not remain an advertised route."""

from pathlib import Path

import otto.portfolio as portfolio


def test_unentered_orc_packet_modules_and_exports_are_retired():
    package_dir = Path(portfolio.__file__).parent
    assert not (package_dir / "current_packet.py").exists()
    assert not (package_dir / "execution_resume.py").exists()
    for name in ("ExecutionResumeError", "execute_selected_packet", "packet_digest"):
        assert name not in portfolio.__all__
        assert not hasattr(portfolio, name)
