from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def test_host_onboarding_points_to_managed_profile_resources():
    docs = (REPO / "docs" / "host-onboarding.md").read_text("utf-8")

    assert "src/otto/packs/otto-profiles/profiles.json" in docs
    assert "seven-slot model" in docs
    assert "src/otto/packs/otto-profiles/hosts.json" in docs
    assert "host qualification and launcher data" in docs
    assert "src/otto/packs/megado/skill/templates/run.<host>.json" in docs
    assert "tests/test_megado_templates.py" in docs
    assert "Add a profile to `otto/agents/host_profiles.py`" not in docs
