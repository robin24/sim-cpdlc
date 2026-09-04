"""The manual tools under tools/ stay importable and refuse to guess."""

import importlib


def test_the_simbrief_probe_refuses_to_run_without_a_user_id(monkeypatch, capsys):
    """It used to carry a hard-coded id and write the owner's flight plan into
    src/ (audit L-20)."""
    probe = importlib.import_module("tools.simbrief_probe")
    monkeypatch.delenv("SIMBRIEF_USERID", raising=False)

    assert probe.main() == 2
    assert "SIMBRIEF_USERID" in capsys.readouterr().err
