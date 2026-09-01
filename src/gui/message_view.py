"""Message view component for the CPDLC client."""

import wx

from src.model.message_manager import MessageManager


class MessageView:
    """Handles display and interaction with CPDLC messages."""

    def __init__(
        self,
        parent,
        logger,
        message_manager: MessageManager,
        on_acknowledge,
        get_current_station,
    ):
        """Initialize the message view.

        Args:
            parent: Parent panel
            logger: Application logger
            message_manager: Message manager instance
            on_acknowledge: Callback for message acknowledgement
            get_current_station: Callable returning the station currently
                logged on, used to scope responses to the live dialogue
        """
        self.parent = parent
        self.logger = logger
        self.message_manager = message_manager
        self.on_acknowledge = on_acknowledge
        self.get_current_station = get_current_station

        self._init_ui()

    def _init_ui(self):
        """Initialize the UI components."""
        # Create a horizontal box sizer
        hbox = wx.BoxSizer(wx.HORIZONTAL)

        # Create message list
        # LC_SINGLE_SEL keeps GetFirstSelected() unambiguous: with multiple
        # rows selected it returns the lowest-indexed one, which need not be
        # the row the user is looking at or right-clicked.
        self.message_list = wx.ListCtrl(
            self.parent, style=wx.LC_REPORT | wx.LC_SINGLE_SEL
        )
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

        # needs_acknowledgement resolves the ID itself and rejects anything
        # that is not an unanswered CPDLC message from the current station.
        self.logger.debug(f"Checking message ID={message_id}")
        needs_ack, responses = self.message_manager.needs_acknowledgement(
            message_id, self.get_current_station()
        )

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
                lambda event, resp=response, mid=message_id: self._handle_acknowledge(
                    mid, resp
                ),
                menu_item,
            )

        self.parent.PopupMenu(menu)

        for menu_item in menu_items:
            self.parent.Unbind(wx.EVT_MENU, id=menu_item.GetId())

        menu.Destroy()

    def _handle_acknowledge(self, message_id: int, response: str):
        """Handle acknowledgement of a message.

        Args:
            message_id: The ID of the message to acknowledge
            response: The response text
        """
        if self.on_acknowledge:
            self.on_acknowledge(message_id, response)
