"""The manual tools under tools/ stay importable and refuse to guess."""

import importlib
import logging


def test_the_simbrief_probe_refuses_to_run_without_a_user_id(monkeypatch, capsys):
    """It used to carry a hard-coded id and write the owner's flight plan into
    src/ (audit L-20)."""
    probe = importlib.import_module("tools.simbrief_probe")
    monkeypatch.delenv("SIMBRIEF_USERID", raising=False)

    assert probe.main() == 2
    assert "SIMBRIEF_USERID" in capsys.readouterr().err


def test_main_leaves_the_root_logger_alone(monkeypatch):
    """main() used to call logging.basicConfig() itself, which reconfigures
    process-wide logging the first time anything calls it -- including a
    caller that already owns its own logging setup, like this test suite
    calling main() in-process (audit finding, pkg6 review).

    basicConfig() is a documented no-op once the root logger already has a
    handler, and pytest's own logging plugin gives the root logger handlers
    before any test body runs -- so a plain before/after snapshot of pytest's
    incidental state can never observe this bug. Start from a handler-less
    root instead, the state a fresh, unconfigured caller would actually see,
    and restore it via monkeypatch so the rest of the session is unaffected
    either way.
    """
    probe = importlib.import_module("tools.simbrief_probe")
    monkeypatch.delenv("SIMBRIEF_USERID", raising=False)
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", [])
    monkeypatch.setattr(root, "level", logging.WARNING)

    probe.main()

    assert root.level == logging.WARNING
    assert root.handlers == []
