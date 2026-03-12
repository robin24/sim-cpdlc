"""
Direct-to request dialog for the Sim-CPDLC application.
"""

import wx


class DirectRequestDialog(wx.Dialog):
    """Dialog for requesting direct-to a waypoint/fix."""

    def __init__(self, parent):
        wx.Dialog.__init__(
            self, parent, wx.ID_ANY, "Request Direct To", size=(-1, -1)
        )

        vbox = wx.BoxSizer(wx.VERTICAL)

        fix_label = wx.StaticText(self, label="Fix / Waypoint:")
        vbox.Add(fix_label, 0, wx.ALL, 5)
        self.fix_text = wx.TextCtrl(self)
        vbox.Add(self.fix_text, 0, wx.ALL | wx.EXPAND, 5)

        helper_text = wx.StaticText(
            self, label="Enter waypoint name (2-5 letters, e.g. KONOL)"
        )
        helper_text.SetForegroundColour(wx.Colour(100, 100, 100))
        vbox.Add(helper_text, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        # Reason radio buttons
        reason_label = wx.StaticText(self, label="Reason (optional):")
        vbox.Add(reason_label, 0, wx.ALL, 5)

        self.reason_none = wx.RadioButton(self, label="None", style=wx.RB_GROUP)
        self.reason_weather = wx.RadioButton(self, label="Due to weather")
        self.reason_performance = wx.RadioButton(self, label="Due to performance")

        self.reason_none.SetValue(True)

        vbox.Add(self.reason_none, 0, wx.LEFT | wx.RIGHT, 10)
        vbox.Add(self.reason_weather, 0, wx.LEFT | wx.RIGHT, 10)
        vbox.Add(self.reason_performance, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        self.ok_button = wx.Button(self, wx.ID_OK, label="OK")
        self.ok_button.Disable()
        cancel_button = wx.Button(self, wx.ID_CANCEL, label="Cancel")
        hbox.Add(self.ok_button, 1, wx.ALL, 5)
        hbox.Add(cancel_button, 1, wx.ALL, 5)

        vbox.Add(hbox, 0, wx.ALIGN_CENTER)

        self.SetSizer(vbox)
        self.Fit()

        self.fix_text.Bind(wx.EVT_TEXT, self.on_text_change)

    def on_text_change(self, _):
        """Enable OK button if fix name is valid (2-5 uppercase alpha chars)."""
        fix = self.fix_text.GetValue().strip().upper()
        if 2 <= len(fix) <= 5 and fix.isalpha():
            self.ok_button.Enable()
        else:
            self.ok_button.Disable()

    def get_direct_details(self):
        """Get the direct-to request details.

        Returns:
            tuple: (fix, reason) where reason is None, "WEATHER", or "PERFORMANCE"
        """
        fix = self.fix_text.GetValue().strip().upper()

        reason = None
        if self.reason_weather.GetValue():
            reason = "WEATHER"
        elif self.reason_performance.GetValue():
            reason = "PERFORMANCE"

        return fix, reason
