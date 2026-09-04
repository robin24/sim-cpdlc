"""
Telex dialog for the Sim-CPDLC application.
"""

import wx

from src.gui.dialogs.validation import matches

# The ACARS free-text limit, enforced by hoppie_connector's TelexMessage, which
# also rejects any non-ASCII character. Checking here means the pilot hears
# about it while typing rather than as a send failure.
TELEX_MAX_CHARACTERS = 220
# hoppie_connector's station-name rule, applied to the recipient.
RECIPIENT = r"[A-Z0-9]{3,8}"


class TelexDialog(wx.Dialog):
    """
    Dialog for sending a telex message.
    """

    def __init__(self, parent, recipient):
        """
        Initialize the telex dialog.

        Args:
            parent: The parent window
            recipient: The station to address by default; the current
                station, or "" when not logged on
        """
        wx.Dialog.__init__(self, parent, wx.ID_ANY, "Telex", size=(-1, -1))

        vbox = wx.BoxSizer(wx.VERTICAL)

        recipient_label = wx.StaticText(self, label="To:")
        vbox.Add(recipient_label, 0, wx.ALL, 5)
        self.recipient_text = wx.TextCtrl(self)
        self.recipient_text.SetValue(recipient)
        vbox.Add(self.recipient_text, 0, wx.ALL | wx.EXPAND, 5)

        message_label = wx.StaticText(self, label="Message:")
        vbox.Add(message_label, 0, wx.ALL, 5)
        self.message_text = wx.TextCtrl(self, style=wx.TE_MULTILINE, size=(-1, 100))
        vbox.Add(self.message_text, 1, wx.ALL | wx.EXPAND, 5)

        # Read by screen readers on request; says why OK is disabled. Created
        # with the longest label this dialog ever shows so Fit() below sizes
        # the dialog to hold it; on_text_change(None) at the end of __init__
        # resets the text to the real (much shorter) starting count.
        self.counter_text = wx.StaticText(
            self,
            label=f"{TELEX_MAX_CHARACTERS} / {TELEX_MAX_CHARACTERS} characters. "
            "Only plain ASCII text can be sent.",
        )
        vbox.Add(self.counter_text, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        self.ok_button = wx.Button(self, wx.ID_OK, label="OK")
        cancel_button = wx.Button(self, wx.ID_CANCEL, label="Cancel")
        hbox.Add(self.ok_button, 1, wx.ALL, 5)
        hbox.Add(cancel_button, 1, wx.ALL, 5)

        vbox.Add(hbox, 0, wx.ALIGN_CENTER)

        self.SetSizer(vbox)

        self.Fit()

        self.recipient_text.Bind(wx.EVT_TEXT, self.on_text_change)
        self.message_text.Bind(wx.EVT_TEXT, self.on_text_change)
        self.on_text_change(None)

    def _recipient(self):
        """The recipient as it would be sent: stripped and upper-cased."""
        return self.recipient_text.GetValue().strip().upper()

    def _message(self):
        """The message as it would be sent: stripped and upper-cased."""
        return self.message_text.GetValue().strip().upper()

    def on_text_change(self, _):
        """Update the character count and enable OK only for a sendable telex."""
        message = self._message()
        count = f"{len(message)} / {TELEX_MAX_CHARACTERS} characters"
        message_ok = bool(message)

        if len(message) > TELEX_MAX_CHARACTERS:
            count += f". Too long by {len(message) - TELEX_MAX_CHARACTERS}."
            message_ok = False
        elif not message.isascii():
            count += ". Only plain ASCII text can be sent."
            message_ok = False

        self.counter_text.SetLabel(count)
        self.ok_button.Enable(message_ok and matches(RECIPIENT, self._recipient()))

    def get_telex_details(self):
        """
        Get the telex details entered by the user.

        Returns:
            tuple: (recipient, message), both stripped and upper-cased
        """
        return self._recipient(), self._message()
