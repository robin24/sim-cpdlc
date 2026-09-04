"""
Altitude change dialog for the Sim-CPDLC application.
"""

import wx

from src.model.cpdlc_elements import (
    REASON_AIRCRAFT_PERFORMANCE,
    REASON_WEATHER,
)
from src.gui.dialogs.validation import is_flight_level, pad_three


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

        altitude_label = wx.StaticText(self, label="Requested &Altitude (FL):")
        vbox.Add(altitude_label, 0, wx.ALL, 5)
        self.altitude_text = wx.TextCtrl(self)
        self.altitude_text.SetName("Requested Altitude (FL)")
        vbox.Add(self.altitude_text, 0, wx.ALL | wx.EXPAND, 5)

        # Add a helper text for altitude format
        self.helper_text = wx.StaticText(
            self,
            label="Enter flight level, 2 or 3 digits from 10 to 600 (e.g. 350 for FL350)",
        )
        self.helper_text.SetForegroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT))
        vbox.Add(self.helper_text, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        # Reason radio buttons
        reason_label = wx.StaticText(self, label="Reason (optional):")
        vbox.Add(reason_label, 0, wx.ALL, 5)

        self.reason_none = wx.RadioButton(self, label="&None", style=wx.RB_GROUP)
        self.reason_weather = wx.RadioButton(self, label="Due to &weather")
        self.reason_performance = wx.RadioButton(self, label="Due to aircraft &performance")

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

    def _level(self):
        """The flight level as typed, without surrounding whitespace."""
        return self.altitude_text.GetValue().strip()

    def on_text_change(self, _):
        """Enable OK only for two or three ASCII digits from FL010 to FL600."""
        self.ok_button.Enable(is_flight_level(self._level()))

    def get_altitude_details(self):
        """
        Get the altitude details entered by the user.

        Returns:
            tuple: (altitude, reason) where altitude is "FL" followed by three
                digits and reason is None, "WEATHER", or "AIRCRAFT PERFORMANCE"
        """
        altitude = f"FL{pad_three(self._level())}"

        reason = None
        if self.reason_weather.GetValue():
            reason = REASON_WEATHER
        elif self.reason_performance.GetValue():
            reason = REASON_AIRCRAFT_PERFORMANCE

        return altitude, reason
