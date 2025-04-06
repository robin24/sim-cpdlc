"""
Dialog modules for the Sim-CPDLC application.
"""

from src.gui.dialogs.connect_dialog import ConnectDialog
from src.gui.dialogs.logon_dialog import LogonDialog
from src.gui.dialogs.pdc_dialog import PDCDialog
from src.gui.dialogs.altitude_change_dialog import AltitudeChangeDialog
from src.gui.dialogs.telex_dialog import TelexDialog
from src.gui.dialogs.settings_dialog import SettingsDialog
from src.gui.dialogs.about_dialog import show_about_dialog

__all__ = [
    "ConnectDialog",
    "LogonDialog",
    "PDCDialog",
    "AltitudeChangeDialog",
    "TelexDialog",
    "SettingsDialog",
    "show_about_dialog",
]
