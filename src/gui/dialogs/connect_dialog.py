"""
Connect dialog for the Sim-CPDLC application.
"""

import wx
import logging
from src.config import load_config
from src.utils.simbrief import get_latest_ofp


class ConnectDialog(wx.Dialog):
    """
    Dialog for connecting to the CPDLC network with callsign and logon code.
    """

    def __init__(self, parent):
        """
        Initialize the connect dialog.

        Args:
            parent: The parent window
        """
        wx.Dialog.__init__(self, parent, wx.ID_ANY, "Connect", size=(-1, -1))
        self.logger = logging.getLogger("Sim-CPDLC")

        # Load config to get saved logon codes and SimBrief User ID
        config = load_config()
        self.saved_sayintentions_logon_code = config.get("sayintentions_logon_code", "")
        self.saved_hoppie_logon_code = config.get("hoppie_logon_code", "")
        simbrief_userid = config.get("simbrief_userid", "")

        vbox = wx.BoxSizer(wx.VERTICAL)

        # Network selection
        network_label = wx.StaticText(self, label="Select Network:")
        vbox.Add(network_label, 0, wx.ALL, 5)

        # Radio buttons for network selection
        self.network_radio_box = wx.RadioBox(
            self,
            label="",
            choices=["SayIntentions ACARS", "Hoppie ACARS"],
            majorDimension=1,
            style=wx.RA_SPECIFY_COLS,
        )
        vbox.Add(self.network_radio_box, 0, wx.ALL | wx.EXPAND, 5)

        # Bind the radio box selection event
        self.network_radio_box.Bind(wx.EVT_RADIOBOX, self.on_network_selection)

        # Callsign field
        callsign_label = wx.StaticText(self, label="Callsign:")
        vbox.Add(callsign_label, 0, wx.ALL, 5)
        self.callsign_text = wx.TextCtrl(self)

        # Try to populate callsign from SimBrief if a user ID is available
        if simbrief_userid:
            self.logger.debug(
                f"Attempting to fetch SimBrief OFP for user ID: {simbrief_userid}"
            )
            try:
                ofp_data = get_latest_ofp(simbrief_userid)
                if ofp_data:
                    # Extract callsign from OFP data
                    # The callsign is typically stored as airline code + flight number
                    # For example: "WAT2088" = "WAT" (airline) + "2088" (flight number)
                    atc = ofp_data.get("atc", {})
                    callsign = atc.get("callsign", "")

                    if callsign:
                        self.logger.info(f"Found callsign in SimBrief OFP: {callsign}")
                        self.callsign_text.SetValue(callsign)
                    else:
                        self.logger.warning(
                            "Could not extract callsign from SimBrief OFP"
                        )
                else:
                    self.logger.warning("Failed to fetch SimBrief OFP data")
            except Exception as e:
                self.logger.error(f"Error fetching SimBrief OFP: {str(e)}")

        vbox.Add(self.callsign_text, 0, wx.ALL | wx.EXPAND, 5)

        # Logon code field - always show it, but populate based on selection
        logon_code_label = wx.StaticText(self, label="Logon code:")
        vbox.Add(logon_code_label, 0, wx.ALL, 5)
        self.logon_code_text = wx.TextCtrl(self)
        vbox.Add(self.logon_code_text, 0, wx.ALL | wx.EXPAND, 5)

        # Set initial logon code based on default selection (SayIntentions)
        if self.saved_sayintentions_logon_code:
            self.logon_code_text.SetValue(self.saved_sayintentions_logon_code)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        self.ok_button = wx.Button(self, wx.ID_OK, label="OK")
        self.ok_button.Disable()
        cancel_button = wx.Button(self, wx.ID_CANCEL, label="Cancel")
        hbox.Add(self.ok_button, 1, wx.ALL, 5)
        hbox.Add(cancel_button, 1, wx.ALL, 5)

        vbox.Add(hbox, 0, wx.ALIGN_CENTER)

        self.SetSizer(vbox)

        self.Fit()

        # Bind events
        self.callsign_text.Bind(wx.EVT_TEXT, self.on_text_change)
        self.logon_code_text.Bind(wx.EVT_TEXT, self.on_text_change)

        # Check if fields are valid on initialization
        self.on_text_change(None)

    def on_network_selection(self, event):
        """
        Handle network selection change.
        Update the logon code field with the saved code for the selected network.
        """
        selection = self.network_radio_box.GetSelection()

        if selection == 0:  # SayIntentions
            self.logon_code_text.SetValue(self.saved_sayintentions_logon_code)
        else:  # Hoppie
            self.logon_code_text.SetValue(self.saved_hoppie_logon_code)

        # Update button state
        self.on_text_change(None)

    def on_text_change(self, _):
        """
        Enable the OK button if both callsign and logon code are provided.
        """
        callsign_valid = bool(self.callsign_text.GetValue().strip())
        logon_code_valid = bool(self.logon_code_text.GetValue().strip())

        if callsign_valid and logon_code_valid:
            self.ok_button.Enable()
        else:
            self.ok_button.Disable()

    def get_connection_details(self):
        """
        Get the connection details entered by the user.

        Returns:
            tuple: (callsign, logon_code, network_type)
        """
        callsign = self.callsign_text.GetValue().upper()
        logon_code = self.logon_code_text.GetValue()

        # Get selected network (0 = SayIntentions, 1 = Hoppie)
        network_type = (
            "sayintentions" if self.network_radio_box.GetSelection() == 0 else "hoppie"
        )

        return callsign, logon_code, network_type
