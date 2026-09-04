"""
Pre-Departure Clearance (PDC) dialog for the Sim-CPDLC application.
"""

import wx
import logging


class PDCDialog(wx.Dialog):
    """
    Dialog for requesting a pre-departure clearance.
    """

    def __init__(self, parent, fetch_simbrief=None):
        """
        Initialize the PDC dialog.

        Args:
            parent: The parent window
            fetch_simbrief: Callable(on_done) that fetches the latest SimBrief
                flight plan off the GUI thread and calls on_done(ofp_or_None)
                on it; returns False when no SimBrief id is configured. None
                skips the fetch. The dialog opens at once either way and fills
                the airports and aircraft in when the plan arrives.
        """
        wx.Dialog.__init__(self, parent, wx.ID_ANY, "Request PDC", size=(-1, -1))
        self.logger = logging.getLogger("Sim-CPDLC")
        self._alive = True

        vbox = wx.BoxSizer(wx.VERTICAL)

        origin_icao_label = wx.StaticText(self, label="&Departure ICAO:")
        vbox.Add(origin_icao_label, 0, wx.ALL, 5)
        self.origin_icao_text = wx.TextCtrl(self)
        self.origin_icao_text.SetName("Departure ICAO")
        vbox.Add(self.origin_icao_text, 0, wx.ALL | wx.EXPAND, 5)

        destination_icao_label = wx.StaticText(self, label="Des&tination ICAO:")
        vbox.Add(destination_icao_label, 0, wx.ALL, 5)
        self.destination_icao_text = wx.TextCtrl(self)
        self.destination_icao_text.SetName("Destination ICAO")
        vbox.Add(self.destination_icao_text, 0, wx.ALL | wx.EXPAND, 5)

        aircraft_label = wx.StaticText(self, label="Aircraft &code:")
        vbox.Add(aircraft_label, 0, wx.ALL, 5)
        self.aircraft_text = wx.TextCtrl(self)
        self.aircraft_text.SetName("Aircraft code")
        vbox.Add(self.aircraft_text, 0, wx.ALL | wx.EXPAND, 5)

        # The flight plan arrives after the dialog is open; this line says
        # where it stands so a screen-reader user is not left guessing.
        self.simbrief_status = wx.StaticText(self, label="")
        vbox.Add(self.simbrief_status, 0, wx.ALL, 5)

        stand_label = wx.StaticText(self, label="&Stand number:")
        vbox.Add(stand_label, 0, wx.ALL, 5)
        self.stand_text = wx.TextCtrl(self)
        self.stand_text.SetName("Stand number")
        vbox.Add(self.stand_text, 0, wx.ALL | wx.EXPAND, 5)

        atis_label = wx.StaticText(self, label="&ATIS:")
        vbox.Add(atis_label, 0, wx.ALL, 5)
        self.atis_text = wx.TextCtrl(self)
        self.atis_text.SetName("ATIS")
        vbox.Add(self.atis_text, 0, wx.ALL | wx.EXPAND, 5)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        self.ok_button = wx.Button(self, wx.ID_OK, label="OK")
        self.ok_button.Disable()
        cancel_button = wx.Button(self, wx.ID_CANCEL, label="Cancel")
        hbox.Add(self.ok_button, 1, wx.ALL, 5)
        hbox.Add(cancel_button, 1, wx.ALL, 5)

        vbox.Add(hbox, 0, wx.ALIGN_CENTER)

        self.SetSizer(vbox)

        self.Fit()

        self.origin_icao_text.Bind(wx.EVT_TEXT, self.on_text_change)
        self.destination_icao_text.Bind(wx.EVT_TEXT, self.on_text_change)
        self.aircraft_text.Bind(wx.EVT_TEXT, self.on_text_change)
        self.stand_text.Bind(wx.EVT_TEXT, self.on_text_change)
        self.atis_text.Bind(wx.EVT_TEXT, self.on_text_change)

        if fetch_simbrief is not None and fetch_simbrief(self._on_simbrief):
            self.simbrief_status.SetLabel("Fetching SimBrief flight plan...")

    def _on_simbrief(self, ofp_data):
        """Fill the airports and aircraft in from the flight plan, if the dialog is still open.

        Args:
            ofp_data: The SimBrief OFP dict, or None when the fetch failed
        """
        if not self._alive:
            return

        if not ofp_data:
            self.logger.warning("Could not fetch flight plan from SimBrief")
            self.simbrief_status.SetLabel("Could not fetch flight plan from SimBrief.")
        else:
            filled = 0
            for field, key in (
                (self.origin_icao_text, "origin"),
                (self.destination_icao_text, "destination"),
                (self.aircraft_text, "aircraft"),
            ):
                value = (ofp_data.get(key) or {}).get("icao_code", "")
                if value:
                    self.logger.info(f"Found {key} ICAO in SimBrief OFP: {value}")
                    field.SetValue(value)
                    filled += 1
                else:
                    self.logger.warning(f"Could not extract {key} ICAO from SimBrief OFP")

            if filled:
                self.simbrief_status.SetLabel("Flight plan loaded from SimBrief.")
            else:
                self.simbrief_status.SetLabel("Could not read the flight plan from SimBrief.")

        # Every path above only sets the label; the re-layout has to happen
        # once, here, or the dialog keeps the size Fit() computed for the
        # empty label and the new text runs past the right edge.
        self.on_text_change(None)
        self.Layout()
        self.Fit()

    def Destroy(self):
        """Forget the dialog before wx does, so a late SimBrief answer is ignored."""
        self._alive = False
        return super().Destroy()

    def on_text_change(self, _):
        """
        Enable the OK button if all fields are provided and ICAO codes are 4 chars.
        """
        origin = self.origin_icao_text.GetValue().strip()
        dest = self.destination_icao_text.GetValue().strip()
        aircraft = self.aircraft_text.GetValue().strip()
        stand = self.stand_text.GetValue().strip()
        atis = self.atis_text.GetValue().strip()

        if (
            len(origin) == 4
            and len(dest) == 4
            and aircraft
            and stand
            and atis
        ):
            self.ok_button.Enable()
        else:
            self.ok_button.Disable()

    def get_pdc_details(self):
        """
        Get the PDC details entered by the user.

        Returns:
            tuple: (origin_icao, destination_icao, aircraft_code, stand_designator, atis_code)
        """
        return (
            self.origin_icao_text.GetValue().strip().upper(),
            self.destination_icao_text.GetValue().strip().upper(),
            self.aircraft_text.GetValue().strip().upper(),
            self.stand_text.GetValue().strip(),
            self.atis_text.GetValue().strip().upper(),
        )
