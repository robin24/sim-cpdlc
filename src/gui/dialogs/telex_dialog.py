"""
Telex dialog for the Sim-CPDLC application.
"""

import wx


class TelexDialog(wx.Dialog):
    """
    Dialog for sending a telex message.
    """

    def __init__(self, parent):
        """
        Initialize the telex dialog.

        Args:
            parent: The parent window
        """
        wx.Dialog.__init__(self, parent, wx.ID_ANY, "Telex", size=(400, 300))

        vbox = wx.BoxSizer(wx.VERTICAL)

        recipient_label = wx.StaticText(self, label="To:")
        vbox.Add(recipient_label, 0, wx.ALL, 5)
        self.recipient_text = wx.TextCtrl(self)
        # Use the get_current_station method from MainWindow
        self.recipient_text.SetValue(parent.get_current_station())
        vbox.Add(self.recipient_text, 0, wx.ALL | wx.EXPAND, 5)

        message_label = wx.StaticText(self, label="Message:")
        vbox.Add(message_label, 0, wx.ALL, 5)
        self.message_text = wx.TextCtrl(self, style=wx.TE_MULTILINE, size=(-1, 100))
        vbox.Add(self.message_text, 1, wx.ALL | wx.EXPAND, 5)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        self.ok_button = wx.Button(self, wx.ID_OK, label="OK")
        self.ok_button.Disable()
        cancel_button = wx.Button(self, wx.ID_CANCEL, label="Cancel")
        hbox.Add(self.ok_button, 1, wx.ALL, 5)
        hbox.Add(cancel_button, 1, wx.ALL, 5)

        vbox.Add(hbox, 0, wx.ALIGN_CENTER)

        self.SetSizer(vbox)

        self.Fit()

        self.recipient_text.Bind(wx.EVT_TEXT, self.on_text_change)
        self.message_text.Bind(wx.EVT_TEXT, self.on_text_change)

    def on_text_change(self, _):
        """
        Enable the OK button if both recipient and message are provided.
        """
        if (
            self.recipient_text.GetValue().strip()
            and self.message_text.GetValue().strip()
        ):
            self.ok_button.Enable()
        else:
            self.ok_button.Disable()

    def get_telex_details(self):
        """
        Get the telex details entered by the user.

        Returns:
            tuple: (recipient, message)
        """
        return (
            self.recipient_text.GetValue().upper(),
            self.message_text.GetValue().upper(),
        )
