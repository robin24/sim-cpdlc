"""
ATIS request dialog for the Sim-CPDLC application.
"""

import wx


class ATISDialog(wx.Dialog):
    """
    Dialog for requesting ATIS information for an airport.
    """

    def __init__(self, parent):
        """
        Initialize the ATIS dialog.

        Args:
            parent: The parent window
        """
        wx.Dialog.__init__(self, parent, wx.ID_ANY, "ATIS Request", size=(-1, -1))

        vbox = wx.BoxSizer(wx.VERTICAL)

        icao_label = wx.StaticText(self, label="Airport ICAO code:")
        vbox.Add(icao_label, 0, wx.ALL, 5)
        self.icao_text = wx.TextCtrl(self)
        vbox.Add(self.icao_text, 0, wx.ALL | wx.EXPAND, 5)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        self.ok_button = wx.Button(self, wx.ID_OK, label="OK")
        self.ok_button.Disable()
        cancel_button = wx.Button(self, wx.ID_CANCEL, label="Cancel")
        hbox.Add(self.ok_button, 1, wx.ALL, 5)
        hbox.Add(cancel_button, 1, wx.ALL, 5)

        vbox.Add(hbox, 0, wx.ALIGN_CENTER)

        self.SetSizer(vbox)

        self.Fit()

        self.icao_text.Bind(wx.EVT_TEXT, self.on_text_change)

    def on_text_change(self, _):
        """
        Enable the OK button if ICAO code is exactly 4 characters.
        """
        if len(self.icao_text.GetValue().strip()) == 4:
            self.ok_button.Enable()
        else:
            self.ok_button.Disable()

    def get_atis_details(self):
        """
        Get the ATIS request details entered by the user.

        Returns:
            str: The airport ICAO code in uppercase
        """
        return self.icao_text.GetValue().strip().upper()
