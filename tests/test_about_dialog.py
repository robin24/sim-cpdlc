"""The About box: the version a user reports, and the copyright year."""

import datetime
import sys

from src.config import APP_VERSION
from src.gui.dialogs import about_dialog


def test_a_source_checkout_says_so(monkeypatch):
    """Bug reports from `python app.py` used to carry a bare version that
    looked like a release (audit M-10)."""
    monkeypatch.delattr(sys, "frozen", raising=False)

    assert about_dialog.version_label() == f"{APP_VERSION} (source)"


def test_a_packaged_build_shows_the_release_number(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    assert about_dialog.version_label() == APP_VERSION


def test_the_about_box_carries_the_label_and_this_years_copyright(wx_app, monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)

    info = about_dialog.about_info()

    assert info.GetVersion() == f"{APP_VERSION} (source)"
    assert info.GetCopyright() == f"Copyright (c) {datetime.date.today().year} Robin Kipp"
