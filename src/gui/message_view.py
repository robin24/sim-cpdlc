"""Message view component for the CPDLC client."""

import wx

from hoppie_connector import HoppieMessage, CpdlcMessage
from src.model.message_manager import MessageManager, WeatherReport


class MessageView:
    """Handles display and interaction with CPDLC messages."""

    def __init__(
        self,
        parent,
        logger,
        message_manager: MessageManager,
        on_acknowledge=None,
        on_toggle_weather_updates=None,
        is_weather_watched=None,
    ):
        """Initialize the message view.

        Args:
            parent: Parent panel
            logger: Application logger
            message_manager: Message manager instance
            on_acknowledge: Callback for message acknowledgement
            on_toggle_weather_updates: Callback(icao, info_type) to start or
                stop automatic updates for a weather report
            is_weather_watched: Callable(icao, info_type) returning whether a
                report is currently being kept up to date
        """
        self.parent = parent
        self.logger = logger
        self.message_manager = message_manager
        self.on_acknowledge = on_acknowledge
        self.on_toggle_weather_updates = on_toggle_weather_updates
        self.is_weather_watched = is_weather_watched

        self._init_ui()

    def _init_ui(self):
        """Initialize the UI components."""
        # Create a horizontal box sizer
        hbox = wx.BoxSizer(wx.HORIZONTAL)

        # Create message list
        self.message_list = wx.ListCtrl(self.parent, style=wx.LC_REPORT)
        self.message_list.InsertColumn(0, "Sender", width=-1)
        self.message_list.InsertColumn(1, "Message", width=-1)
        self.message_list.SetToolTip("Messages received from the CPDLC network.")
        hbox.Add(self.message_list, 1, wx.ALL, 5)

        # Create message detail view
        self.message_detail = wx.TextCtrl(
            self.parent, style=wx.TE_MULTILINE | wx.TE_READONLY
        )
        hbox.Add(self.message_detail, 1, wx.ALL, 5)

        # Set the sizer for the parent panel
        self.parent.SetSizer(hbox)

        # Bind events
        self.message_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_message_selected)
        self.message_list.Bind(wx.EVT_CONTEXT_MENU, self.on_context_menu)

    def add_message(self, message_id: int):
        """Add a message to the list view.

        Args:
            message_id: The message ID to add
        """
        sender, display_text = self.message_manager.get_message_display_text(message_id)
        if not sender:
            return

        index = self.message_list.InsertItem(self.message_list.GetItemCount(), sender)
        self.message_list.SetItem(index, 1, display_text)
        self.message_list.SetItemData(index, message_id)

    def clear(self):
        """Clear all messages from the view."""
        self.message_list.DeleteAllItems()
        self.message_detail.Clear()

    def on_message_selected(self, event):
        """Handle message selection in the list.

        Args:
            event: The event object
        """
        selected_index = event.GetIndex()
        if 0 <= selected_index < self.message_list.GetItemCount():
            message_id = self.message_list.GetItemData(selected_index)

            self.logger.debug(f"Message selected: ID={message_id}")

            # Get the detailed text for the message
            detail_text = self.message_manager.get_message_detail_text(message_id)
            self.message_detail.SetValue(detail_text)

    def on_context_menu(self, event):
        """Show context menu for message responses.

        Args:
            event: The event object
        """
        selected_index = self.message_list.GetFirstSelected()
        if selected_index == -1:
            self.logger.debug("Context menu requested but no message selected")
            return

        message_id = self.message_list.GetItemData(selected_index)
        message = self.message_manager.get_message(message_id)

        # Weather reports get their own menu, so automatic updates can be
        # started or stopped from the report itself.
        if isinstance(message, WeatherReport):
            self._show_weather_menu(message)
            return

        if not isinstance(message, HoppieMessage):
            self.logger.debug(f"Selected item (ID={message_id}) is not a HoppieMessage")
            return

        self.logger.debug(f"Checking message: {message}")
        needs_ack, responses = self.message_manager.needs_acknowledgement(message)

        if not needs_ack:
            self.logger.debug(
                "Message does not need acknowledgement, no context menu shown"
            )
            return

        self.logger.debug(f"Showing context menu with responses: {responses}")
        menu = wx.Menu()

        menu_items = []
        for response in responses:
            menu_item = menu.Append(wx.ID_ANY, f"Respond: {response}")
            menu_items.append(menu_item)
            self.parent.Bind(
                wx.EVT_MENU,
                lambda event, resp=response, msg=message: self._handle_acknowledge(
                    msg, resp
                ),
                menu_item,
            )

        self.parent.PopupMenu(menu)

        for menu_item in menu_items:
            self.parent.Unbind(wx.EVT_MENU, id=menu_item.GetId())

        menu.Destroy()

    def _show_weather_menu(self, report: WeatherReport):
        """Show the context menu for a weather report.

        Args:
            report: The selected WeatherReport
        """
        if not self.on_toggle_weather_updates:
            return

        watched = bool(
            self.is_weather_watched
            and self.is_weather_watched(report.icao, report.info_type)
        )

        label = (
            f"Stop automatic updates for {report.label} {report.icao}"
            if watched
            else f"Start automatic updates for {report.label} {report.icao}"
        )
        self.logger.debug(f"Showing weather context menu: {label}")

        menu = wx.Menu()
        menu_item = menu.Append(wx.ID_ANY, label)
        self.parent.Bind(
            wx.EVT_MENU,
            lambda event, r=report: self.on_toggle_weather_updates(
                r.icao, r.info_type
            ),
            menu_item,
        )

        self.parent.PopupMenu(menu)

        self.parent.Unbind(wx.EVT_MENU, id=menu_item.GetId())
        menu.Destroy()

    def _handle_acknowledge(self, message: CpdlcMessage, response: str):
        """Handle acknowledgement of a message.

        Args:
            message: The message to acknowledge
            response: The response text
        """
        if self.on_acknowledge:
            self.on_acknowledge(message, response)
