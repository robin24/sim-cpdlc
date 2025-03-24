"""
Pre-Departure Clearance (PDC) dialog for the Sim-CPDLC application.
"""

import wx
import logging
from src.config import load_config
from src.utils.simbrief import get_latest_ofp


class PDCDialog(wx.Dialog):
    """
    Dialog for requesting a pre-departure clearance.
    """

    def __init__(self, parent):
        """
        Initialize the PDC dialog.

        Args:
            parent: The parent window
        """
        wx.Dialog.__init__(self, parent, wx.ID_ANY, "Request PDC", size=(-1, -1))
        self.logger = logging.getLogger("Sim-CPDLC")

        # Load config to get SimBrief User ID
        config = load_config()
        simbrief_userid = config.get("simbrief_userid", "")

        vbox = wx.BoxSizer(wx.VERTICAL)

        origin_icao_label = wx.StaticText(self, label="Departure ICAO:")
        vbox.Add(origin_icao_label, 0, wx.ALL, 5)
        self.origin_icao_text = wx.TextCtrl(self)
        vbox.Add(self.origin_icao_text, 0, wx.ALL | wx.EXPAND, 5)

        destination_icao_label = wx.StaticText(self, label="Destination ICAO:")
        vbox.Add(destination_icao_label, 0, wx.ALL, 5)
        self.destination_icao_text = wx.TextCtrl(self)
        vbox.Add(self.destination_icao_text, 0, wx.ALL | wx.EXPAND, 5)

        aircraft_label = wx.StaticText(self, label="Aircraft code:")
        vbox.Add(aircraft_label, 0, wx.ALL, 5)
        self.aircraft_text = wx.TextCtrl(self)
        vbox.Add(self.aircraft_text, 0, wx.ALL | wx.EXPAND, 5)

        # Try to populate fields from SimBrief if a user ID is available
        if simbrief_userid:
            self.logger.debug(
                f"Attempting to fetch SimBrief OFP for user ID: {simbrief_userid}"
            )
            try:
                ofp_data = get_latest_ofp(simbrief_userid)
                if ofp_data:
                    # Extract departure ICAO
                    origin = ofp_data.get("origin", {})
                    origin_icao = origin.get("icao_code", "")
                    if origin_icao:
                        self.logger.info(
                            f"Found departure ICAO in SimBrief OFP: {origin_icao}"
                        )
                        self.origin_icao_text.SetValue(origin_icao)
                    else:
                        self.logger.warning(
                            "Could not extract departure ICAO from SimBrief OFP"
                        )

                    # Extract destination ICAO
                    destination = ofp_data.get("destination", {})
                    destination_icao = destination.get("icao_code", "")
                    if destination_icao:
                        self.logger.info(
                            f"Found destination ICAO in SimBrief OFP: {destination_icao}"
                        )
                        self.destination_icao_text.SetValue(destination_icao)
                    else:
                        self.logger.warning(
                            "Could not extract destination ICAO from SimBrief OFP"
                        )

                    # Extract aircraft code
                    aircraft = ofp_data.get("aircraft", {})
                    aircraft_icao = aircraft.get("icao_code", "")
                    if aircraft_icao:
                        self.logger.info(
                            f"Found aircraft ICAO in SimBrief OFP: {aircraft_icao}"
                        )
                        self.aircraft_text.SetValue(aircraft_icao)
                    else:
                        self.logger.warning(
                            "Could not extract aircraft ICAO from SimBrief OFP"
                        )
                else:
                    self.logger.warning("Failed to fetch SimBrief OFP data")
            except Exception as e:
                self.logger.error(f"Error fetching SimBrief OFP: {str(e)}")

        stand_label = wx.StaticText(self, label="Stand number:")
        vbox.Add(stand_label, 0, wx.ALL, 5)
        self.stand_text = wx.TextCtrl(self)
        vbox.Add(self.stand_text, 0, wx.ALL | wx.EXPAND, 5)

        atis_label = wx.StaticText(self, label="ATIS:")
        vbox.Add(atis_label, 0, wx.ALL, 5)
        self.atis_text = wx.TextCtrl(self)
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

    def on_text_change(self, _):
        """
        Enable the OK button if all fields are provided.
        """
        if (
            self.origin_icao_text.GetValue().strip()
            and self.destination_icao_text.GetValue().strip()
            and self.aircraft_text.GetValue().strip()
            and self.stand_text.GetValue().strip()
            and self.atis_text.GetValue().strip()
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
            self.origin_icao_text.GetValue().upper(),
            self.destination_icao_text.GetValue().upper(),
            self.aircraft_text.GetValue().upper(),
            self.stand_text.GetValue(),
            self.atis_text.GetValue().upper(),
        )
