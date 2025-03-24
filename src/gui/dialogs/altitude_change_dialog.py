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

        # Add radio buttons for climb/descent selection
        direction_label = wx.StaticText(self, label="Direction:")
        vbox.Add(direction_label, 0, wx.ALL, 5)

        # Create a horizontal box for the radio buttons
        direction_hbox = wx.BoxSizer(wx.HORIZONTAL)
        self.climb_radio = wx.RadioButton(self, label="Climb", style=wx.RB_GROUP)
        self.descent_radio = wx.RadioButton(self, label="Descent")
        direction_hbox.Add(self.climb_radio, 0, wx.RIGHT, 10)
        direction_hbox.Add(self.descent_radio, 0, wx.LEFT, 10)
        vbox.Add(direction_hbox, 0, wx.ALL, 5)

        # By default, select climb
        self.climb_radio.SetValue(True)

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

        reason_label = wx.StaticText(self, label="Reason (optional):")
        vbox.Add(reason_label, 0, wx.ALL, 5)
        self.reason_text = wx.TextCtrl(self, style=wx.TE_MULTILINE, size=(-1, 60))
        vbox.Add(self.reason_text, 0, wx.ALL | wx.EXPAND, 5)

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
            if altitude and int(altitude) > 0:
                self.ok_button.Enable()
            else:
                self.ok_button.Disable()
        except ValueError:
            # Not a valid number
            self.ok_button.Disable()

    def get_altitude_details(self):
        """
        Get the altitude details entered by the user.

        Returns:
            tuple: (altitude, reason, is_climb)
        """
        altitude = self.altitude_text.GetValue().strip()
        reason = self.reason_text.GetValue().strip()
        is_climb = self.climb_radio.GetValue()

        # Format altitude as FL followed by the number
        if altitude:
            altitude = f"FL{altitude}"

        return altitude, reason, is_climb
