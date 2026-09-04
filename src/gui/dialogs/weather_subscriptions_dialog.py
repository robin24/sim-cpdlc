"""
Automatic weather updates management dialog for the Sim-CPDLC application.
"""

import time

import wx

from src.utils.weather_parsing import report_type_label


class WeatherSubscriptionsDialog(wx.Dialog):
    """
    Dialog listing the reports being kept up to date, with controls to stop
    individual subscriptions or check them all immediately.
    """

    def __init__(self, parent, weather_monitor, on_stop):
        """
        Initialize the subscriptions dialog.

        Args:
            parent: The parent window
            weather_monitor: The WeatherMonitor whose subscriptions are listed
            on_stop: Callable(icao, info_type) that stops one report's updates
                and tells the pilot; the window's helper, so a stop from here
                reads the same as one from the report's context menu
        """
        wx.Dialog.__init__(
            self, parent, wx.ID_ANY, "Automatic Weather Updates", size=(-1, -1)
        )

        self.weather_monitor = weather_monitor
        self._stop_updates = on_stop
        self._keys = []

        vbox = wx.BoxSizer(wx.VERTICAL)

        list_label = wx.StaticText(self, label="Reports being kept up to date:")
        vbox.Add(list_label, 0, wx.ALL, 5)

        self.subscription_list = wx.ListBox(self, choices=[])
        self.subscription_list.SetName("Reports being kept up to date")
        vbox.Add(self.subscription_list, 1, wx.ALL | wx.EXPAND, 5)

        interval_minutes = max(1, round(weather_monitor.interval_ms / 60000))
        plural = "" if interval_minutes == 1 else "s"
        self.interval_text = wx.StaticText(
            self,
            label=f"Each report is checked every {interval_minutes} minute{plural}. "
            "Change this in File, Settings.",
        )
        vbox.Add(self.interval_text, 0, wx.ALL, 5)

        button_box = wx.BoxSizer(wx.HORIZONTAL)
        self.check_button = wx.Button(self, wx.ID_ANY, label="Check &now")
        self.stop_button = wx.Button(self, wx.ID_ANY, label="&Stop updating")
        self.stop_all_button = wx.Button(self, wx.ID_ANY, label="Stop &all")
        close_button = wx.Button(self, wx.ID_CANCEL, label="&Close")

        button_box.Add(self.check_button, 1, wx.ALL, 5)
        button_box.Add(self.stop_button, 1, wx.ALL, 5)
        button_box.Add(self.stop_all_button, 1, wx.ALL, 5)
        button_box.Add(close_button, 1, wx.ALL, 5)

        vbox.Add(button_box, 0, wx.ALIGN_CENTER)

        self.SetSizer(vbox)
        self.SetMinSize((520, 320))
        self.Fit()

        self.check_button.Bind(wx.EVT_BUTTON, self.on_check_now)
        self.stop_button.Bind(wx.EVT_BUTTON, self.on_stop)
        self.stop_all_button.Bind(wx.EVT_BUTTON, self.on_stop_all)
        self.subscription_list.Bind(wx.EVT_LISTBOX, self._update_button_state)

        self._refresh()
        self._stop_listening = weather_monitor.subscribe_to_changes(self._refresh)

    def Destroy(self):
        """Stop following the monitor before wx tears the list down."""
        self._stop_listening()
        return super().Destroy()

    def _format_entry(self, subscription):
        """Build the list entry text for one subscription.

        Args:
            subscription: A WeatherSubscription

        Returns:
            str: Text describing the subscription and its last update
        """
        label = report_type_label(subscription.info_type)

        if subscription.last_update:
            checked = time.strftime("%H:%M", time.localtime(subscription.last_update))
            status = f"last checked {checked}"
        else:
            status = "not yet checked"

        return f"{label} {subscription.icao}, {status}"

    def _refresh(self):
        """Rebuild the list from the monitor, keeping the selected report if it is still there."""
        selected = self.subscription_list.GetSelection()
        selected_key = self._keys[selected] if 0 <= selected < len(self._keys) else None

        subscriptions = self.weather_monitor.get_subscriptions()
        self._keys = [s.key for s in subscriptions]
        self.subscription_list.Set([self._format_entry(s) for s in subscriptions])

        if subscriptions:
            index = self._keys.index(selected_key) if selected_key in self._keys else 0
            self.subscription_list.SetSelection(index)

        self._update_button_state(None)

    def _update_button_state(self, _):
        """Enable or disable buttons based on what is selected."""
        has_items = self.subscription_list.GetCount() > 0
        has_selection = self.subscription_list.GetSelection() != wx.NOT_FOUND

        self.check_button.Enable(has_items)
        self.stop_all_button.Enable(has_items)
        self.stop_button.Enable(has_items and has_selection)

    def on_check_now(self, _):
        """Run an update cycle straight away, if one can start."""
        if self.weather_monitor.check_now():
            message = (
                "Checking all subscribed reports now. You will be notified of "
                "any that have changed."
            )
        else:
            message = (
                "Could not check just now: either a check is already running, "
                "or you are not connected to the network. Nothing has been "
                "requested."
            )

        wx.MessageBox(message, "Automatic Weather Updates", wx.OK | wx.ICON_INFORMATION)

    def on_stop(self, _):
        """Stop updating the selected report, through the window so it is announced."""
        index = self.subscription_list.GetSelection()
        if index == wx.NOT_FOUND or index >= len(self._keys):
            return

        icao, info_type = self._keys[index]
        self._stop_updates(icao, info_type)

    def on_stop_all(self, _):
        """Stop updating every report, after confirming."""
        if not self._keys:
            return

        if (
            wx.MessageBox(
                "Stop automatic updates for all reports?",
                "Confirm",
                wx.YES_NO | wx.ICON_QUESTION,
            )
            != wx.YES
        ):
            return

        # The monitor's notification rebuilds self._keys as each report goes,
        # so iterate over a copy.
        for icao, info_type in list(self._keys):
            self._stop_updates(icao, info_type)
