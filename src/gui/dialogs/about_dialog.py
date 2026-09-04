"""About dialog for the Sim-CPDLC application."""

import datetime
import sys

import wx
import wx.adv

from src.config import APP_VERSION, GITHUB_URL


def version_label():
    """The version as the user should report it.

    A packaged build is the release it was built from. A checkout run with
    `python app.py` carries the same number, so it says so: a bug report from
    source is a different thing from one against the installer.

    Returns:
        str: "X.Y.Z" in a packaged build, "X.Y.Z (source)" otherwise
    """
    if getattr(sys, "frozen", False):
        return APP_VERSION
    return f"{APP_VERSION} (source)"


def about_info():
    """Build the information the About box shows.

    Returns:
        wx.adv.AboutDialogInfo: Name, version, description, copyright, website
    """
    info = wx.adv.AboutDialogInfo()
    info.SetName("Sim-CPDLC")
    info.SetVersion(version_label())
    info.SetDescription("A simple CPDLC client for SayIntentions.ai and Hoppie ACARS")
    info.SetCopyright(f"Copyright (c) {datetime.date.today().year} Robin Kipp")
    info.SetWebSite(GITHUB_URL, "View on GitHub")
    return info


def show_about_dialog(parent):
    """Display information about the application.

    Args:
        parent: The parent window
    """
    wx.adv.AboutBox(about_info(), parent)
