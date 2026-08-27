"""
Heading request dialog for the Sim-CPDLC application.

A heading request is one of the downlink types VATSIM controller clients
handle directly, alongside level, direct-to and speed requests.
"""

import wx


class HeadingRequestDialog(wx.Dialog):
    """Dialog for requesting a heading."""

    def __init__(self, parent):
        """
        Initialize the heading request dialog.

        Args:
            parent: The parent window
        """
        wx.Dialog.__init__(self, parent, wx.ID_ANY, "Heading Request", size=(-1, -1))

        vbox = wx.BoxSizer(wx.VERTICAL)

        degrees_label = wx.StaticText(self, label="Heading in d&egrees:")
        vbox.Add(degrees_label, 0, wx.ALL, 5)
        self.degrees_text = wx.TextCtrl(self)
        self.degrees_text.SetName("Heading in degrees")
        vbox.Add(self.degrees_text, 0, wx.ALL | wx.EXPAND, 5)

        helper_text = wx.StaticText(self, label="One to three digits, e.g. 270")
        vbox.Add(helper_text, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        self.ok_button = wx.Button(self, wx.ID_OK, label="OK")
        self.ok_button.Disable()
        cancel_button = wx.Button(self, wx.ID_CANCEL, label="Cancel")
        hbox.Add(self.ok_button, 1, wx.ALL, 5)
        hbox.Add(cancel_button, 1, wx.ALL, 5)

        vbox.Add(hbox, 0, wx.ALIGN_CENTER)

        self.SetSizer(vbox)
        self.Fit()

        self.degrees_text.Bind(wx.EVT_TEXT, self._on_value_change)

    def _on_value_change(self, _):
        """Enable OK once the heading is a plausible value."""
        degrees = self.degrees_text.GetValue().strip()
        self.ok_button.Enable(degrees.isdigit() and 1 <= int(degrees) <= 360)

    def get_heading(self):
        """
        Get the requested heading.

        Returns:
            str: The heading as three digits, e.g. "070"
        """
        return self.degrees_text.GetValue().strip().zfill(3)
