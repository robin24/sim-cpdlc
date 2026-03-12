"""
Altitude change dialog for the Sim-CPDLC application.
"""

import wx


class AltitudeChangeDialog(wx.Dialog):
    """
    Dialog for requesting an altitude change.
    """

    def __init__(self, parent):
        """
        Initialize the altitude change dialog.

        Args:
            parent: The parent window
        """
        wx.Dialog.__init__(
            self, parent, wx.ID_ANY, "Request Altitude Change", size=(-1, -1)
        )

        vbox = wx.BoxSizer(wx.VERTICAL)

        altitude_label = wx.StaticText(self, label="Requested Altitude (FL):")
        vbox.Add(altitude_label, 0, wx.ALL, 5)
        self.altitude_text = wx.TextCtrl(self)
        vbox.Add(self.altitude_text, 0, wx.ALL | wx.EXPAND, 5)

        # Add a helper text for altitude format
        helper_text = wx.StaticText(
            self, label="Enter flight level without 'FL' prefix (e.g., 350 for FL350)"
        )
        helper_text.SetForegroundColour(wx.Colour(100, 100, 100))  # Gray color
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

        self.altitude_text.Bind(wx.EVT_TEXT, self.on_text_change)

    def on_text_change(self, _):
        """
        Enable the OK button if altitude is provided and is a valid number.
        """
        # Only enable the OK button if altitude is provided and is a valid number
        altitude = self.altitude_text.GetValue().strip()
        try:
            fl = int(altitude) if altitude else 0
            if 10 <= fl <= 600:
                self.ok_button.Enable()
            else:
                self.ok_button.Disable()
        except ValueError:
            self.ok_button.Disable()

    def get_altitude_details(self):
        """
        Get the altitude details entered by the user.

        Returns:
            tuple: (altitude, reason) where reason is None, "WEATHER", or "PERFORMANCE"
        """
        altitude = self.altitude_text.GetValue().strip()

        # Format altitude as FL followed by the number
        if altitude:
            altitude = f"FL{altitude}"

        reason = None
        if self.reason_weather.GetValue():
            reason = "WEATHER"
        elif self.reason_performance.GetValue():
            reason = "PERFORMANCE"

        return altitude, reason
