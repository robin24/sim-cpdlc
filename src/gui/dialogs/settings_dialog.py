"""
Settings dialog for the Sim-CPDLC application.
"""

import wx


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
    ):
        """
        Initialize the settings dialog.

        Args:
            parent: The parent window
            sayintentions_logon_code (str): The current SayIntentions logon code to display
            hoppie_logon_code (str): The current Hoppie logon code to display
            simbrief_userid (str): The current SimBrief User ID to display
            auto_check_updates (bool): Whether to automatically check for updates
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
            tuple: (sayintentions_logon_code, hoppie_logon_code, simbrief_userid, auto_check_updates)
        """
        return (
            self.sayintentions_logon_code_text.GetValue(),
            self.hoppie_logon_code_text.GetValue(),
            self.simbrief_userid_text.GetValue(),
            self.auto_check_updates_checkbox.GetValue(),
        )
