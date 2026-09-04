"""
Direct-to request dialog for the Sim-CPDLC application.
"""

import wx

from src.model.cpdlc_elements import (
    REASON_AIRCRAFT_PERFORMANCE,
    REASON_WEATHER,
)
from src.gui.dialogs.validation import FIX, matches


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

        self.helper_text = wx.StaticText(
            self, label="2-7 letters or digits, e.g. KONOL or 55N020W"
        )
        self.helper_text.SetForegroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT))
        vbox.Add(self.helper_text, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        # Reason radio buttons
        reason_label = wx.StaticText(self, label="Reason (optional):")
        vbox.Add(reason_label, 0, wx.ALL, 5)

        self.reason_none = wx.RadioButton(self, label="None", style=wx.RB_GROUP)
        self.reason_weather = wx.RadioButton(self, label="Due to weather")
        self.reason_performance = wx.RadioButton(self, label="Due to aircraft performance")

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

    def _fix(self):
        """The fix as it would be sent: stripped and upper-cased."""
        return self.fix_text.GetValue().strip().upper()

    def on_text_change(self, _):
        """Enable OK only for 2-7 ASCII letters or digits."""
        self.ok_button.Enable(matches(FIX, self._fix()))

    def get_direct_details(self):
        """Get the direct-to request details.

        Returns:
            tuple: (fix, reason) where reason is None, "WEATHER", or "AIRCRAFT PERFORMANCE"
        """
        fix = self._fix()

        reason = None
        if self.reason_weather.GetValue():
            reason = REASON_WEATHER
        elif self.reason_performance.GetValue():
            reason = REASON_AIRCRAFT_PERFORMANCE

        return fix, reason
