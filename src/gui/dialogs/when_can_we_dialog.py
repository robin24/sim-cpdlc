"""
When-can-we-expect dialog for the Sim-CPDLC application.
"""

import wx


class WhenCanWeDialog(wx.Dialog):
    """Dialog for sending 'WHEN CAN WE EXPECT' inquiries."""

    # Message types and whether they need a value field
    MESSAGE_TYPES = [
        ("HIGHER LEVEL", False),
        ("LOWER LEVEL", False),
        ("BACK ON ROUTE", False),
        ("CLIMB TO FL", True),
        ("DESCENT TO FL", True),
        ("Mach", True),
        ("Speed (knots)", True),
    ]

    def __init__(self, parent):
        wx.Dialog.__init__(
            self, parent, wx.ID_ANY, "When Can We Expect", size=(-1, -1)
        )

        vbox = wx.BoxSizer(wx.VERTICAL)

        type_label = wx.StaticText(self, label="Request type:")
        vbox.Add(type_label, 0, wx.ALL, 5)

        self.radios = []
        for i, (label, _) in enumerate(self.MESSAGE_TYPES):
            style = wx.RB_GROUP if i == 0 else 0
            radio = wx.RadioButton(self, label=label, style=style)
            vbox.Add(radio, 0, wx.LEFT | wx.RIGHT, 10)
            radio.Bind(wx.EVT_RADIOBUTTON, self._on_type_change)
            self.radios.append(radio)

        self.radios[0].SetValue(True)

        # Value field (shown only for types that need it)
        vbox.Add((0, 5))
        self.value_label = wx.StaticText(self, label="Value:")
        vbox.Add(self.value_label, 0, wx.ALL, 5)
        self.value_text = wx.TextCtrl(self)
        vbox.Add(self.value_text, 0, wx.ALL | wx.EXPAND, 5)

        self.helper_text = wx.StaticText(self, label="")
        self.helper_text.SetForegroundColour(wx.Colour(100, 100, 100))
        vbox.Add(self.helper_text, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        # Initially hide value fields (first option doesn't need them)
        self.value_label.Hide()
        self.value_text.Hide()
        self.helper_text.Hide()

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        self.ok_button = wx.Button(self, wx.ID_OK, label="OK")
        cancel_button = wx.Button(self, wx.ID_CANCEL, label="Cancel")
        hbox.Add(self.ok_button, 1, wx.ALL, 5)
        hbox.Add(cancel_button, 1, wx.ALL, 5)

        vbox.Add(hbox, 0, wx.ALIGN_CENTER)

        self.SetSizer(vbox)
        self.Fit()

        self.value_text.Bind(wx.EVT_TEXT, self._on_value_change)

    def _get_selected_index(self):
        for i, radio in enumerate(self.radios):
            if radio.GetValue():
                return i
        return 0

    def _on_type_change(self, _):
        """Show/hide value field based on selected type."""
        idx = self._get_selected_index()
        _, needs_value = self.MESSAGE_TYPES[idx]

        if needs_value:
            self.value_label.Show()
            self.value_text.Show()
            self.helper_text.Show()

            label = self.MESSAGE_TYPES[idx][0]
            if "FL" in label:
                self.helper_text.SetLabel("Enter flight level (e.g. 350)")
            elif label == "Mach":
                self.helper_text.SetLabel("Enter Mach without decimal (e.g. 082)")
            else:
                self.helper_text.SetLabel("Enter speed in knots (e.g. 300)")

            self._on_value_change(None)
        else:
            self.value_label.Hide()
            self.value_text.Hide()
            self.helper_text.Hide()
            self.ok_button.Enable()

        self.Fit()

    def _on_value_change(self, _):
        """Validate value field."""
        idx = self._get_selected_index()
        _, needs_value = self.MESSAGE_TYPES[idx]

        if not needs_value:
            self.ok_button.Enable()
            return

        value = self.value_text.GetValue().strip()
        if value.isdigit() and 2 <= len(value) <= 3:
            self.ok_button.Enable()
        else:
            self.ok_button.Disable()

    def get_message_text(self):
        """Build the full WHEN CAN WE EXPECT message text.

        Returns:
            str: The complete message text
        """
        idx = self._get_selected_index()
        label, needs_value = self.MESSAGE_TYPES[idx]

        if not needs_value:
            return f"WHEN CAN WE EXPECT {label}"

        value = self.value_text.GetValue().strip()

        if "FL" in label:
            # CLIMB TO FL / DESCENT TO FL
            return f"WHEN CAN WE EXPECT {label}{value}"
        elif label == "Mach":
            if len(value) == 2:
                value = "0" + value
            return f"WHEN CAN WE EXPECT M{value}"
        else:
            # Speed in knots
            return f"WHEN CAN WE EXPECT {value}K"
