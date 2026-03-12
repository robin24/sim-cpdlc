"""
Weather information request dialog for the Sim-CPDLC application.
"""

import wx


class ATISDialog(wx.Dialog):
    """
    Dialog for requesting ATIS or METAR information for an airport.
    """

    def __init__(self, parent):
        """
        Initialize the weather information dialog.

        Args:
            parent: The parent window
        """
        wx.Dialog.__init__(self, parent, wx.ID_ANY, "Weather Information Request", size=(-1, -1))

        vbox = wx.BoxSizer(wx.VERTICAL)

        # Request type radio buttons
        type_label = wx.StaticText(self, label="Request type:")
        vbox.Add(type_label, 0, wx.ALL, 5)

        self.radio_atis = wx.RadioButton(self, label="ATIS", style=wx.RB_GROUP)
        self.radio_metar = wx.RadioButton(self, label="METAR")
        self.radio_atis.SetValue(True)

        vbox.Add(self.radio_atis, 0, wx.LEFT | wx.RIGHT, 10)
        vbox.Add(self.radio_metar, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

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
        Get the request details entered by the user.

        Returns:
            tuple: (icao, request_type) where request_type is "atis" or "metar"
        """
        icao = self.icao_text.GetValue().strip().upper()
        request_type = "metar" if self.radio_metar.GetValue() else "atis"
        return icao, request_type
