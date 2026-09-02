"""
Weather information request dialog for the Sim-CPDLC application.
"""

import wx

from src.utils.weather_parsing import REPORT_TYPES

# Order the report types are offered in, most commonly used first. ATIS leads
# because it is what most requests are for.
REPORT_ORDER = ("vatatis", "metar", "taf", "shorttaf")

AUTO_UPDATE_HELP = (
    "When ticked, the report is requested again periodically and you are\n"
    "notified only when it actually changes. Untick it to stop updates, or\n"
    "use the context menu on any weather report in the message list."
)


class WeatherDialog(wx.Dialog):
    """
    Dialog for requesting a METAR, TAF or ATIS for an airport, optionally
    keeping it up to date automatically.
    """

    def __init__(self, parent, default_type="vatatis", is_watched=None):
        """
        Initialize the weather information dialog.

        Args:
            parent: The parent window
            default_type: Report type key to preselect
            is_watched: Callable(icao, info_type) returning whether that report
                is already being kept up to date. The tick box mirrors it, so it
                always shows the real state and can be used to turn updates off
                as well as on.
        """
        self.is_watched = is_watched
        wx.Dialog.__init__(
            self, parent, wx.ID_ANY, "Weather Information Request", size=(-1, -1)
        )

        vbox = wx.BoxSizer(wx.VERTICAL)

        type_label = wx.StaticText(self, label="&Report type:")
        vbox.Add(type_label, 0, wx.ALL, 5)

        self.type_choice = wx.Choice(
            self, choices=[REPORT_TYPES[key][0] for key in REPORT_ORDER]
        )
        self.type_choice.SetName("Report type")
        if default_type in REPORT_ORDER:
            self.type_choice.SetSelection(REPORT_ORDER.index(default_type))
        else:
            self.type_choice.SetSelection(0)
        vbox.Add(self.type_choice, 0, wx.ALL | wx.EXPAND, 5)

        icao_label = wx.StaticText(self, label="Airport &ICAO code:")
        vbox.Add(icao_label, 0, wx.ALL, 5)
        self.icao_text = wx.TextCtrl(self)
        self.icao_text.SetName("Airport ICAO code")
        vbox.Add(self.icao_text, 0, wx.ALL | wx.EXPAND, 5)

        self.auto_update_checkbox = wx.CheckBox(
            self, label="&Keep this report updated automatically"
        )
        vbox.Add(self.auto_update_checkbox, 0, wx.ALL, 5)

        auto_help_text = wx.StaticText(self, label=AUTO_UPDATE_HELP)
        vbox.Add(auto_help_text, 0, wx.ALL, 5)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        self.ok_button = wx.Button(self, wx.ID_OK, label="OK")
        self.ok_button.Disable()
        cancel_button = wx.Button(self, wx.ID_CANCEL, label="Cancel")
        hbox.Add(self.ok_button, 1, wx.ALL, 5)
        hbox.Add(cancel_button, 1, wx.ALL, 5)

        vbox.Add(hbox, 0, wx.ALIGN_CENTER)

        self.SetSizer(vbox)
        self.Fit()

        self.icao_text.Bind(wx.EVT_TEXT, self.on_text_change)
        self.type_choice.Bind(wx.EVT_CHOICE, self.on_text_change)

        self._sync_auto_update_checkbox()

    def on_text_change(self, _):
        """
        Enable the OK button if ICAO code is exactly 4 characters, and keep the
        tick box showing whether that report is currently being watched.
        """
        if len(self.icao_text.GetValue().strip()) == 4:
            self.ok_button.Enable()
        else:
            self.ok_button.Disable()

        self._sync_auto_update_checkbox()

    def _sync_auto_update_checkbox(self):
        """Point the tick box at whatever airport and report type are showing."""
        if not self.is_watched:
            return

        icao, info_type, _ = self.get_weather_details()
        watched = bool(icao) and self.is_watched(icao, info_type)

        if self.auto_update_checkbox.GetValue() != watched:
            self.auto_update_checkbox.SetValue(watched)

    def get_weather_details(self):
        """
        Get the request details entered by the user.

        Returns:
            tuple: (icao, info_type, auto_update) where auto_update is the state
                  the user wants: True to keep the report updated, False to stop.
        """
        icao = self.icao_text.GetValue().strip().upper()
        info_type = REPORT_ORDER[max(self.type_choice.GetSelection(), 0)]
        return icao, info_type, self.auto_update_checkbox.GetValue()
