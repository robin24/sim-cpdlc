"""
Settings dialog for the Sim-CPDLC application.
"""

import wx

from src.config import (
    DEFAULT_WEATHER_INTERVAL_MINUTES,
    MAX_WEATHER_INTERVAL_MINUTES,
    MIN_WEATHER_INTERVAL_MINUTES,
)


class SettingsDialog(wx.Dialog):
    """
    Dialog for configuring application settings.
    """

    def __init__(
        self,
        parent,
        sayintentions_logon_code="",
        hoppie_logon_code="",
        simbrief_userid="",
        auto_check_updates=True,
        auto_tune_com1=True,
        weather_update_interval=DEFAULT_WEATHER_INTERVAL_MINUTES,
    ):
        """
        Initialize the settings dialog.

        Args:
            parent: The parent window
            sayintentions_logon_code (str): The current SayIntentions logon code to display
            hoppie_logon_code (str): The current Hoppie logon code to display
            simbrief_userid (str): The current SimBrief User ID to display
            auto_check_updates (bool): Whether to automatically check for updates
            auto_tune_com1 (bool): Whether to auto-tune COM1 standby
            weather_update_interval (int): Minutes between automatic weather checks
        """
        wx.Dialog.__init__(self, parent, wx.ID_ANY, "Settings", size=(-1, -1))

        vbox = wx.BoxSizer(wx.VERTICAL)

        # SayIntentions Logon code field
        sayintentions_logon_code_label = wx.StaticText(
            self, label="SayIntentions Logon code:"
        )
        vbox.Add(sayintentions_logon_code_label, 0, wx.ALL, 5)
        self.sayintentions_logon_code_text = wx.TextCtrl(self)
        self.sayintentions_logon_code_text.SetValue(sayintentions_logon_code)
        vbox.Add(self.sayintentions_logon_code_text, 0, wx.ALL | wx.EXPAND, 5)

        # Help text for SayIntentions logon code
        sayintentions_help_text = wx.StaticText(
            self,
            label="This logon code will be used for all connections to the SayIntentions.ai ACARS.\n"
            "You will not need to enter it in the Connect dialog.",
        )
        vbox.Add(sayintentions_help_text, 0, wx.ALL, 5)

        # Add a separator
        vbox.Add(wx.StaticLine(self), 0, wx.EXPAND | wx.ALL, 5)

        # Hoppie Logon code field
        hoppie_logon_code_label = wx.StaticText(self, label="Hoppie Logon code:")
        vbox.Add(hoppie_logon_code_label, 0, wx.ALL, 5)
        self.hoppie_logon_code_text = wx.TextCtrl(self)
        self.hoppie_logon_code_text.SetValue(hoppie_logon_code)
        vbox.Add(self.hoppie_logon_code_text, 0, wx.ALL | wx.EXPAND, 5)

        # Help text for Hoppie logon code
        hoppie_help_text = wx.StaticText(
            self,
            label="This logon code will be used for all connections to the Hoppie.nl ACARS.\n"
            "You will not need to enter it in the Connect dialog.",
        )
        vbox.Add(hoppie_help_text, 0, wx.ALL, 5)

        # Add a separator
        vbox.Add(wx.StaticLine(self), 0, wx.EXPAND | wx.ALL, 5)

        # SimBrief User ID field
        simbrief_label = wx.StaticText(self, label="SimBrief User ID:")
        vbox.Add(simbrief_label, 0, wx.ALL, 5)
        self.simbrief_userid_text = wx.TextCtrl(self)
        self.simbrief_userid_text.SetValue(simbrief_userid)
        vbox.Add(self.simbrief_userid_text, 0, wx.ALL | wx.EXPAND, 5)

        # Help text for SimBrief User ID
        simbrief_help_text = wx.StaticText(
            self,
            label="Enter your SimBrief User ID to fetch your flight plans.\n"
            "You can find this in your SimBrief account settings.",
        )
        vbox.Add(simbrief_help_text, 0, wx.ALL, 5)

        # Add a separator
        vbox.Add(wx.StaticLine(self), 0, wx.EXPAND | wx.ALL, 5)

        # Auto-update checkbox
        self.auto_check_updates_checkbox = wx.CheckBox(
            self, label="Automatically check for updates"
        )
        self.auto_check_updates_checkbox.SetValue(auto_check_updates)
        vbox.Add(self.auto_check_updates_checkbox, 0, wx.ALL, 5)

        # Help text for auto-update
        auto_update_help_text = wx.StaticText(
            self,
            label="When enabled, the application will check for updates when it starts.\n"
            "You can always check for updates manually from the File menu.",
        )
        vbox.Add(auto_update_help_text, 0, wx.ALL, 5)

        # Add a separator
        vbox.Add(wx.StaticLine(self), 0, wx.EXPAND | wx.ALL, 5)

        # Auto-tune COM1 checkbox
        self.auto_tune_com1_checkbox = wx.CheckBox(
            self, label="Auto-tune COM1 standby on CONTACT/MONITOR"
        )
        self.auto_tune_com1_checkbox.SetValue(auto_tune_com1)
        vbox.Add(self.auto_tune_com1_checkbox, 0, wx.ALL, 5)

        # Help text for auto-tune COM1
        auto_tune_help_text = wx.StaticText(
            self,
            label="When enabled, receiving a CONTACT or MONITOR instruction will\n"
            "automatically set the frequency as COM1 standby in MSFS via SimConnect.",
        )
        vbox.Add(auto_tune_help_text, 0, wx.ALL, 5)

        # Add a separator
        vbox.Add(wx.StaticLine(self), 0, wx.EXPAND | wx.ALL, 5)

        # Automatic weather update interval
        weather_interval_label = wx.StaticText(
            self, label="Automatic weather update interval (minutes):"
        )
        vbox.Add(weather_interval_label, 0, wx.ALL, 5)
        self.weather_interval_spin = wx.SpinCtrl(
            self,
            min=MIN_WEATHER_INTERVAL_MINUTES,
            max=MAX_WEATHER_INTERVAL_MINUTES,
            initial=weather_update_interval,
        )
        self.weather_interval_spin.SetName("Automatic weather update interval in minutes")
        vbox.Add(self.weather_interval_spin, 0, wx.ALL, 5)

        weather_interval_help_text = wx.StaticText(
            self,
            label="How often reports you have asked to keep updated are requested\n"
            "again. Shorter intervals put more load on the ACARS network, so\n"
            "only lower this if you are watching an ATIS that changes often.",
        )
        vbox.Add(weather_interval_help_text, 0, wx.ALL, 5)

        # Buttons
        hbox = wx.BoxSizer(wx.HORIZONTAL)
        self.ok_button = wx.Button(self, wx.ID_OK, label="Save")
        cancel_button = wx.Button(self, wx.ID_CANCEL, label="Cancel")
        hbox.Add(self.ok_button, 1, wx.ALL, 5)
        hbox.Add(cancel_button, 1, wx.ALL, 5)

        vbox.Add(hbox, 0, wx.ALIGN_CENTER)

        self.SetSizer(vbox)
        self.Fit()

    def get_settings(self):
        """
        Get the settings entered by the user.

        Returns:
            tuple: (sayintentions_logon_code, hoppie_logon_code, simbrief_userid,
                   auto_check_updates, auto_tune_com1, weather_update_interval)
        """
        return (
            self.sayintentions_logon_code_text.GetValue().strip(),
            self.hoppie_logon_code_text.GetValue().strip(),
            self.simbrief_userid_text.GetValue().strip(),
            self.auto_check_updates_checkbox.GetValue(),
            self.auto_tune_com1_checkbox.GetValue(),
            self.weather_interval_spin.GetValue(),
        )
