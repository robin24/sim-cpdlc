"""
Confirm-assigned dialog for the Sim-CPDLC application.

Asks the station to confirm what the aircraft has been assigned. SayIntentions
lists confirm altitude and confirm speed among the requests its ATC acts on.
"""

import wx

# (label, message text)
CONFIRM_TYPES = (
    ("Assigned level", "CONFIRM ASSIGNED LEVEL"),
    ("Assigned speed", "CONFIRM ASSIGNED SPEED"),
)


class ConfirmRequestDialog(wx.Dialog):
    """Dialog for asking the station to confirm an assigned clearance."""

    def __init__(self, parent):
        """
        Initialize the confirm request dialog.

        Args:
            parent: The parent window
        """
        wx.Dialog.__init__(self, parent, wx.ID_ANY, "Confirm Assigned", size=(-1, -1))

        vbox = wx.BoxSizer(wx.VERTICAL)

        type_label = wx.StaticText(self, label="Ask the station to confirm:")
        vbox.Add(type_label, 0, wx.ALL, 5)

        self.type_choice = wx.Choice(
            self, choices=[entry[0] for entry in CONFIRM_TYPES]
        )
        self.type_choice.SetName("Ask the station to confirm")
        self.type_choice.SetSelection(0)
        vbox.Add(self.type_choice, 0, wx.ALL | wx.EXPAND, 5)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        self.ok_button = wx.Button(self, wx.ID_OK, label="OK")
        cancel_button = wx.Button(self, wx.ID_CANCEL, label="Cancel")
        hbox.Add(self.ok_button, 1, wx.ALL, 5)
        hbox.Add(cancel_button, 1, wx.ALL, 5)

        vbox.Add(hbox, 0, wx.ALIGN_CENTER)

        self.SetSizer(vbox)
        self.Fit()

    def get_message(self):
        """
        Get the query text.

        Returns:
            str: The message text, e.g. "CONFIRM ASSIGNED LEVEL"
        """
        return CONFIRM_TYPES[max(self.type_choice.GetSelection(), 0)][1]
