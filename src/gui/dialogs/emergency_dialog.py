"""
Emergency declaration dialog for the Sim-CPDLC application.
"""

import re

import wx

_FUEL_TIME = re.compile(r"^([01][0-9]|2[0-3])[0-5][0-9]$")


class EmergencyDialog(wx.Dialog):
    """
    Dialog for declaring a MAYDAY or PAN PAN over CPDLC.

    Sends the urgency or distress element, optionally followed by the fuel and
    souls on board report and a diversion, as separate elements of one message.
    """

    def __init__(self, parent):
        """
        Initialize the emergency dialog.

        Args:
            parent: The parent window
        """
        wx.Dialog.__init__(self, parent, wx.ID_ANY, "Declare Emergency", size=(-1, -1))

        vbox = wx.BoxSizer(wx.VERTICAL)

        type_label = wx.StaticText(self, label="Emergency &type:")
        vbox.Add(type_label, 0, wx.ALL, 5)

        self.pan_radio = wx.RadioButton(
            self, label="PAN PAN, urgency", style=wx.RB_GROUP
        )
        self.mayday_radio = wx.RadioButton(self, label="MAYDAY, distress")
        self.pan_radio.SetValue(True)

        vbox.Add(self.pan_radio, 0, wx.LEFT | wx.RIGHT, 10)
        vbox.Add(self.mayday_radio, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        fuel_label = wx.StaticText(self, label="&Fuel remaining (optional):")
        vbox.Add(fuel_label, 0, wx.ALL, 5)
        self.fuel_text = wx.TextCtrl(self)
        self.fuel_text.SetName("Fuel remaining")
        vbox.Add(self.fuel_text, 0, wx.ALL | wx.EXPAND, 5)

        fuel_help = wx.StaticText(
            self, label="Hours and minutes as four digits, e.g. 0230 for 2 hours 30"
        )
        vbox.Add(fuel_help, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        souls_label = wx.StaticText(self, label="&Souls on board (optional):")
        vbox.Add(souls_label, 0, wx.ALL, 5)
        self.souls_text = wx.TextCtrl(self)
        self.souls_text.SetName("Souls on board")
        vbox.Add(self.souls_text, 0, wx.ALL | wx.EXPAND, 5)

        souls_help = wx.StaticText(
            self,
            label="Fuel and souls are reported together, so enter both or neither.",
        )
        vbox.Add(souls_help, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        diverting_label = wx.StaticText(self, label="&Diverting to (optional):")
        vbox.Add(diverting_label, 0, wx.ALL, 5)
        self.diverting_text = wx.TextCtrl(self)
        self.diverting_text.SetName("Diverting to")
        vbox.Add(self.diverting_text, 0, wx.ALL | wx.EXPAND, 5)

        via_label = wx.StaticText(self, label="Di&verting via (optional):")
        vbox.Add(via_label, 0, wx.ALL, 5)
        self.via_text = wx.TextCtrl(self)
        self.via_text.SetName("Diverting via")
        vbox.Add(self.via_text, 0, wx.ALL | wx.EXPAND, 5)

        details_label = wx.StaticText(self, label="Further de&tail (optional):")
        vbox.Add(details_label, 0, wx.ALL, 5)
        self.details_text = wx.TextCtrl(self)
        self.details_text.SetName("Further detail")
        vbox.Add(self.details_text, 0, wx.ALL | wx.EXPAND, 5)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        self.ok_button = wx.Button(self, wx.ID_OK, label="Send")
        cancel_button = wx.Button(self, wx.ID_CANCEL, label="Cancel")
        hbox.Add(self.ok_button, 1, wx.ALL, 5)
        hbox.Add(cancel_button, 1, wx.ALL, 5)

        vbox.Add(hbox, 0, wx.ALIGN_CENTER)

        self.SetSizer(vbox)
        self.Fit()

        self.fuel_text.Bind(wx.EVT_TEXT, self._on_value_change)
        self.souls_text.Bind(wx.EVT_TEXT, self._on_value_change)

    def _on_value_change(self, _):
        """Enable Send unless the optional fuel/souls pair is half-filled."""
        fuel = self.fuel_text.GetValue().strip()
        souls = self.souls_text.GetValue().strip()

        if not fuel and not souls:
            self.ok_button.Enable(True)
            return

        valid = (
            bool(_FUEL_TIME.match(fuel))
            and souls.isdigit()
            and 1 <= int(souls) <= 999
        )
        self.ok_button.Enable(valid)

    def get_emergency_details(self):
        """
        Get the emergency details entered by the user.

        Returns:
            tuple: (is_mayday, fuel_remaining, souls_on_board, diverting_to,
                   via_route, free_text)
        """
        fuel = self.fuel_text.GetValue().strip()
        souls = self.souls_text.GetValue().strip()

        return (
            self.mayday_radio.GetValue(),
            fuel or None,
            souls or None,
            self.diverting_text.GetValue().strip().upper() or None,
            self.via_text.GetValue().strip().upper() or None,
            self.details_text.GetValue().strip().upper() or None,
        )
