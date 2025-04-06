"""About dialog for the Sim-CPDLC application."""

import wx
import wx.adv

from src.config import APP_VERSION, GITHUB_URL


def show_about_dialog(parent):
    """Display information about the application.

    Args:
        parent: The parent window
    """
    info = wx.adv.AboutDialogInfo()
    info.SetName("Sim-CPDLC")
    info.SetVersion(APP_VERSION)
    info.SetDescription("A simple CPDLC client for SayIntentions.ai and Hoppie ACARS")
    info.SetCopyright("Copyright (c) 2025 Robin Kipp")
    info.SetWebSite(GITHUB_URL, "View on GitHub")

    wx.adv.AboutBox(info)
