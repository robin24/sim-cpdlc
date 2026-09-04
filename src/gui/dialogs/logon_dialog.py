"""
Logon dialog for the Sim-CPDLC application.
"""

import wx

from src.gui.dialogs.validation import STATION, matches


class LogonDialog(wx.Dialog):
    """
    Dialog for logging on to a CPDLC station.
    """

    def __init__(self, parent):
        """
        Initialize the logon dialog.

        Args:
            parent: The parent window
        """
        wx.Dialog.__init__(self, parent, wx.ID_ANY, "Logon", size=(-1, -1))

        vbox = wx.BoxSizer(wx.VERTICAL)

        station_label = wx.StaticText(self, label="&Station:")
        vbox.Add(station_label, 0, wx.ALL, 5)
        self.station_text = wx.TextCtrl(self)
        self.station_text.SetName("Station")
        vbox.Add(self.station_text, 0, wx.ALL | wx.EXPAND, 5)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        self.ok_button = wx.Button(self, wx.ID_OK, label="OK")
        self.ok_button.Disable()
        cancel_button = wx.Button(self, wx.ID_CANCEL, label="Cancel")
        hbox.Add(self.ok_button, 1, wx.ALL, 5)
        hbox.Add(cancel_button, 1, wx.ALL, 5)

        vbox.Add(hbox, 0, wx.ALIGN_CENTER)

        self.SetSizer(vbox)

        self.Fit()

        self.station_text.Bind(wx.EVT_TEXT, self.on_text_change)

    def _station(self):
        """The station as it would be sent: stripped and upper-cased."""
        return self.station_text.GetValue().strip().upper()

    def on_text_change(self, _):
        """Enable OK only for a station name the network accepts."""
        self.ok_button.Enable(matches(STATION, self._station()))

    def get_logon_details(self):
        """
        Get the logon details entered by the user.

        Returns:
            str: The station name, stripped and upper-cased
        """
        return self._station()
