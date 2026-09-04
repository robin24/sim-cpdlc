"""
Connect dialog for the Sim-CPDLC application.
"""

import wx
import logging
from src.config import load_config


class ConnectDialog(wx.Dialog):
    """
    Dialog for connecting to the CPDLC network with callsign and logon code.
    """

    def __init__(self, parent, fetch_simbrief=None):
        """
        Initialize the connect dialog.

        Args:
            parent: The parent window
            fetch_simbrief: Callable(on_done) that fetches the latest SimBrief
                flight plan off the GUI thread and calls on_done(ofp_or_None)
                on it; returns False when no SimBrief id is configured. None
                skips the fetch. The dialog opens at once either way and fills
                the callsign in when the plan arrives.
        """
        wx.Dialog.__init__(self, parent, wx.ID_ANY, "Connect", size=(-1, -1))
        self.logger = logging.getLogger("Sim-CPDLC")
        self._alive = True

        # Load config to get saved logon codes
        config = load_config()
        self.saved_sayintentions_logon_code = config.get("sayintentions_logon_code", "")
        self.saved_hoppie_logon_code = config.get("hoppie_logon_code", "")

        vbox = wx.BoxSizer(wx.VERTICAL)

        # Radio buttons for network selection
        self.network_radio_box = wx.RadioBox(
            self,
            label="Network",
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

        vbox.Add(self.callsign_text, 0, wx.ALL | wx.EXPAND, 5)

        # The flight plan arrives after the dialog is open; this line says
        # where it stands so a screen-reader user is not left guessing.
        self.simbrief_status = wx.StaticText(self, label="")
        vbox.Add(self.simbrief_status, 0, wx.ALL, 5)

        # Logon code field - create controls but manage visibility later
        self.logon_code_label = wx.StaticText(self, label="Logon code:")
        vbox.Add(self.logon_code_label, 0, wx.ALL, 5)
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

        # Update logon code field visibility based on initial network selection
        self.update_logon_code_visibility()

        # Check if fields are valid on initialization
        self.on_text_change(None)

        if fetch_simbrief is not None and fetch_simbrief(self._on_simbrief):
            self.simbrief_status.SetLabel("Fetching SimBrief flight plan...")

    def _on_simbrief(self, ofp_data):
        """Fill the callsign in from the flight plan, if the dialog is still open.

        Args:
            ofp_data: The SimBrief OFP dict, or None when the fetch failed
        """
        if not self._alive:
            return

        # The callsign is airline code plus flight number, e.g. "WAT2088".
        atc = (ofp_data or {}).get("atc") or {}
        callsign = atc.get("callsign", "")
        if callsign:
            self.logger.info(f"Found callsign in SimBrief OFP: {callsign}")
            self.callsign_text.SetValue(callsign)
            self.simbrief_status.SetLabel("Callsign taken from your SimBrief flight plan.")
        elif not ofp_data:
            # Nothing came back: the network, the account or the ID is at fault.
            self.logger.warning("Could not fetch flight plan from SimBrief")
            self.simbrief_status.SetLabel("Could not fetch flight plan from SimBrief.")
        else:
            # The plan is there but says nothing about the callsign, which the
            # pilot fixes in SimBrief rather than by fetching again.
            self.logger.warning("SimBrief OFP has no callsign")
            self.simbrief_status.SetLabel("Your SimBrief flight plan has no callsign.")

        self.on_text_change(None)
        self.Layout()
        self.Fit()

    def Destroy(self):
        """Forget the dialog before wx does, so a late SimBrief answer is ignored."""
        self._alive = False
        return super().Destroy()

    def update_logon_code_visibility(self):
        """
        Update the visibility of the logon code field based on the selected network.
        Hide the field if a logon code exists for the selected network.
        """
        selection = self.network_radio_box.GetSelection()

        # Check if a logon code exists for the selected network
        has_logon_code = False
        if selection == 0 and self.saved_sayintentions_logon_code:  # SayIntentions
            has_logon_code = True
        elif selection == 1 and self.saved_hoppie_logon_code:  # Hoppie
            has_logon_code = True

        # Show or hide the logon code field based on whether a logon code exists
        self.logon_code_label.Show(not has_logon_code)
        self.logon_code_text.Show(not has_logon_code)

        # Refresh the layout to account for the visibility change
        self.Layout()
        self.Fit()

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

        # Update logon code field visibility
        self.update_logon_code_visibility()

        # Update button state
        self.on_text_change(None)

    def on_text_change(self, _):
        """
        Enable the OK button if required fields are valid.
        If logon code field is visible, both callsign and logon code must be valid.
        If logon code field is hidden, only callsign needs to be valid.
        """
        callsign_valid = bool(self.callsign_text.GetValue().strip())

        # Check if logon code field is visible
        if self.logon_code_text.IsShown():
            # If visible, both callsign and logon code must be valid
            logon_code_valid = bool(self.logon_code_text.GetValue().strip())
            if callsign_valid and logon_code_valid:
                self.ok_button.Enable()
            else:
                self.ok_button.Disable()
        else:
            # If hidden, only callsign needs to be valid
            if callsign_valid:
                self.ok_button.Enable()
            else:
                self.ok_button.Disable()

    def get_connection_details(self):
        """
        Get the connection details entered by the user.

        Returns:
            tuple: (callsign, logon_code, network_type)
        """
        callsign = self.callsign_text.GetValue().strip().upper()
        selection = self.network_radio_box.GetSelection()

        # Determine network type
        network_type = "sayintentions" if selection == 0 else "hoppie"

        # Get the appropriate logon code
        # If the logon code field is hidden, use the saved code from config
        if not self.logon_code_text.IsShown():
            if selection == 0:  # SayIntentions
                logon_code = self.saved_sayintentions_logon_code
            else:  # Hoppie
                logon_code = self.saved_hoppie_logon_code
        else:
            # Otherwise use the value entered in the field
            logon_code = self.logon_code_text.GetValue().strip()

        return callsign, logon_code, network_type
