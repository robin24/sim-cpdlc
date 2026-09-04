"""
When-can-we-expect dialog for the Sim-CPDLC application.
"""

import wx

from src.gui.dialogs.validation import (
    FLIGHT_LEVEL,
    KNOTS,
    MACH,
    is_flight_level,
    matches,
    pad_three,
)


class WhenCanWeDialog(wx.Dialog):
    """Dialog for sending 'WHEN CAN WE EXPECT' inquiries."""

    # Message types and the rule their value must match; None means no value.
    MESSAGE_TYPES = [
        ("HIGHER LEVEL", None),
        ("LOWER LEVEL", None),
        ("BACK ON ROUTE", None),
        ("CLIMB TO FL", FLIGHT_LEVEL),
        ("DESCENT TO FL", FLIGHT_LEVEL),
        ("Mach", MACH),
        ("Speed (knots)", KNOTS),
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
        self.helper_text.SetForegroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT))
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
        label, rule = self.MESSAGE_TYPES[idx]

        if rule is not None:
            self.value_label.Show()
            self.value_text.Show()
            self.helper_text.Show()

            if "FL" in label:
                self.helper_text.SetLabel(
                    "Enter flight level, 2 or 3 digits from 10 to 600 (e.g. 350)"
                )
            elif label == "Mach":
                self.helper_text.SetLabel("Enter Mach without decimal (e.g. 082)")
            else:
                self.helper_text.SetLabel("Enter speed in knots, 3 digits (e.g. 300)")

            self._on_value_change(None)
        else:
            self.value_label.Hide()
            self.value_text.Hide()
            self.helper_text.Hide()
            self.ok_button.Enable()

        self.Fit()

    def _value(self):
        """The value as typed, without surrounding whitespace."""
        return self.value_text.GetValue().strip()

    def _on_value_change(self, _):
        """Enable OK when the value fits the selected type's rule."""
        label, rule = self.MESSAGE_TYPES[self._get_selected_index()]

        if rule is None:
            self.ok_button.Enable()
            return

        # FLIGHT_LEVEL and MACH are both r"\d{2,3}": CPython folds equal
        # string literals in the same module into one object, so "rule is
        # FLIGHT_LEVEL" would also be true for the Mach rule. Dispatch on the
        # label instead, as _on_type_change and get_message_text already do.
        value = self._value()
        if "FL" in label:
            ok = is_flight_level(value)
        else:
            ok = matches(rule, value)
        self.ok_button.Enable(ok)

    def get_message_text(self):
        """Build the full WHEN CAN WE EXPECT message text.

        Returns:
            str: The complete message text
        """
        label, rule = self.MESSAGE_TYPES[self._get_selected_index()]

        if rule is None:
            return f"WHEN CAN WE EXPECT {label}"

        value = self._value()

        if "FL" in label:
            # CLIMB TO FL / DESCENT TO FL
            return f"WHEN CAN WE EXPECT {label}{pad_three(value)}"
        elif label == "Mach":
            return f"WHEN CAN WE EXPECT M{pad_three(value)}"
        else:
            # Speed in knots
            return f"WHEN CAN WE EXPECT {value}K"
