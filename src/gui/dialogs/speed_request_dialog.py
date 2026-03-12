"""
Speed request dialog for the Sim-CPDLC application.
"""

import wx


class SpeedRequestDialog(wx.Dialog):
    """Dialog for requesting a speed/Mach change."""

    def __init__(self, parent):
        wx.Dialog.__init__(
            self, parent, wx.ID_ANY, "Request Speed Change", size=(-1, -1)
        )

        vbox = wx.BoxSizer(wx.VERTICAL)

        # Speed type radio buttons
        type_label = wx.StaticText(self, label="Speed type:")
        vbox.Add(type_label, 0, wx.ALL, 5)

        self.radio_mach = wx.RadioButton(self, label="Mach", style=wx.RB_GROUP)
        self.radio_knots = wx.RadioButton(self, label="Knots")
        self.radio_mach.SetValue(True)

        vbox.Add(self.radio_mach, 0, wx.LEFT | wx.RIGHT, 10)
        vbox.Add(self.radio_knots, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Speed value
        speed_label = wx.StaticText(self, label="Speed value:")
        vbox.Add(speed_label, 0, wx.ALL, 5)
        self.speed_text = wx.TextCtrl(self)
        vbox.Add(self.speed_text, 0, wx.ALL | wx.EXPAND, 5)

        self.helper_text = wx.StaticText(
            self, label="Enter Mach number without decimal (e.g. 082 for M0.82)"
        )
        self.helper_text.SetForegroundColour(wx.Colour(100, 100, 100))
        vbox.Add(self.helper_text, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

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

        self.speed_text.Bind(wx.EVT_TEXT, self.on_text_change)
        self.radio_mach.Bind(wx.EVT_RADIOBUTTON, self._on_type_change)
        self.radio_knots.Bind(wx.EVT_RADIOBUTTON, self._on_type_change)

    def _on_type_change(self, _):
        """Update helper text when speed type changes."""
        if self.radio_mach.GetValue():
            self.helper_text.SetLabel(
                "Enter Mach number without decimal (e.g. 082 for M0.82)"
            )
        else:
            self.helper_text.SetLabel(
                "Enter speed in knots (e.g. 300)"
            )
        self.on_text_change(None)

    def on_text_change(self, _):
        """Enable OK button if speed value is valid."""
        speed = self.speed_text.GetValue().strip()
        if not speed.isdigit():
            self.ok_button.Disable()
            return

        if self.radio_mach.GetValue():
            # Mach: 2-3 digits (e.g. 82, 082)
            if 2 <= len(speed) <= 3:
                self.ok_button.Enable()
            else:
                self.ok_button.Disable()
        else:
            # Knots: 2-3 digits (e.g. 250, 300)
            if 2 <= len(speed) <= 3:
                self.ok_button.Enable()
            else:
                self.ok_button.Disable()

    def get_speed_details(self):
        """Get the speed request details.

        Returns:
            tuple: (speed, is_mach, reason) where reason is None, "WEATHER", or "PERFORMANCE"
        """
        speed = self.speed_text.GetValue().strip()
        is_mach = self.radio_mach.GetValue()

        # Pad Mach to 3 digits if needed (e.g. 82 -> 082)
        if is_mach and len(speed) == 2:
            speed = "0" + speed

        reason = None
        if self.reason_weather.GetValue():
            reason = "WEATHER"
        elif self.reason_performance.GetValue():
            reason = "PERFORMANCE"

        return speed, is_mach, reason
