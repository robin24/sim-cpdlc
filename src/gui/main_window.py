"""Main window for the Sim-CPDLC application."""

import os
import sys
import wx
import wx.adv

from hoppie_connector import (
    CpdlcMessage,
    CpdlcResponseRequirement as RR,
    HoppieMessage,
)

from src.config import (
    SAYINTENTIONS_API_URL,
    HOPPIE_API_URL,
    DEFAULT_POLL_INTERVAL,
    ACTIVE_POLL_INTERVAL,
    INACTIVITY_TIMEOUT,
    MAX_CONNECTION_FAILURES,
    MESSAGE_SOUND_FILENAME,
    load_config,
    save_config,
)

from src.model.connection_manager import ConnectionManager
from src.model.message_manager import MessageManager
from src.model.cpdlc_session import CpdlcSession
from src.controller.polling_controller import PollingController
from src.gui.message_view import MessageView
from src.gui.dialogs import (
    ConnectDialog,
    LogonDialog,
    PDCDialog,
    AltitudeChangeDialog,
    TelexDialog,
    show_about_dialog,
)
from src.utils.update_checker import UpdateChecker
from src.gui.dialogs.settings_dialog import SettingsDialog


class MainWindow(wx.Frame):
    """Main application window for the Sim-CPDLC client."""

    def resource_path(self, relative_path):
        """Get absolute path to resource, works for dev and for PyInstaller."""
        try:
            # PyInstaller creates a temp folder and stores path in _MEIPASS
            base_path = sys._MEIPASS
        except Exception:
            base_path = os.path.abspath(".")

        return os.path.join(base_path, relative_path)

    def __init__(self, parent, title, logger):
        """Initialize the main window with UI and connection settings."""
        wx.Frame.__init__(self, parent, title=title, size=(500, 500))
        self.logger = logger
        self.logger.debug("Initializing MainWindow")

        # Initialize model components
        self.connection_manager = ConnectionManager(logger)
        self.message_manager = MessageManager(logger)
        self.cpdlc_session = CpdlcSession(logger, self.connection_manager)

        # Check if this is the first launch (config file just created)
        self._check_first_launch()

        # Initialize sound for new messages
        sound_path = self.resource_path(os.path.join("assets", MESSAGE_SOUND_FILENAME))
        if os.path.exists(sound_path):
            self.new_message_sound = wx.adv.Sound(sound_path)
        else:
            error_msg = f"Sound file not found at {sound_path}. The program will work as expected, however you will not hear a notification sound when a new CPDLC message arrives. To restore the notification sound, please quit the app and double-check that the sound file exists at the specified path."
            self.logger.warning(error_msg)
            wx.MessageBox(error_msg, "Missing Sound File", wx.OK | wx.ICON_ERROR)
            self.new_message_sound = None

        # Initialize UI
        self._init_ui()

        # Initialize update checker
        self.update_checker = UpdateChecker(self, logger)

        # Check for updates if enabled in settings
        config = load_config()
        if config.get("auto_check_updates", True):
            self.logger.debug("Auto-update check enabled, checking for updates")
            self.update_checker.check_for_updates()
        else:
            self.logger.debug("Auto-update check disabled")

        # Initialize controller
        self.polling_controller = PollingController(
            logger,
            self.connection_manager,
            self._on_message_received,
            DEFAULT_POLL_INTERVAL,
            ACTIVE_POLL_INTERVAL,
            INACTIVITY_TIMEOUT,
        )

        # Bind the close event to handle ALT+F4 and other direct close operations
        self.Bind(wx.EVT_CLOSE, self.on_close)

        self.Show(True)
        self.logger.debug("MainWindow initialization complete")

    def _init_ui(self):
        """Set up the application's user interface components."""
        # Create main panel
        self.panel = wx.Panel(self)

        # Create message view
        self.message_view = MessageView(
            self.panel, self.logger, self.message_manager, self._on_acknowledge_message
        )

        # Create status bar
        self.CreateStatusBar()
        self.SetStatusText("Not logged on.")

        # Create menu
        self._init_menu()

    def _init_menu(self):
        """Create and configure the application menu bar."""
        menu_bar = wx.MenuBar()

        # File menu
        file_menu = wx.Menu()
        self.menu_item_connect = file_menu.Append(
            wx.ID_ANY, "&Connect", "Connect to the CPDLC network"
        )
        menu_item_settings = file_menu.Append(
            wx.ID_ANY, "&Settings", "Configure application settings"
        )
        menu_item_check_updates = file_menu.Append(
            wx.ID_ANY, "Check for &Updates", "Check for new versions of the application"
        )
        menu_item_about = file_menu.Append(
            wx.ID_ABOUT, "&About", " Information about this program"
        )

        file_menu.AppendSeparator()
        menu_item_exit = file_menu.Append(wx.ID_EXIT, "E&xit", " Terminate the program")
        menu_bar.Append(file_menu, "&File")

        # Requests menu
        requests_menu = wx.Menu()
        menu_item_pdc = requests_menu.Append(
            wx.ID_ANY, "&PDC", "Request a pre-departure clearance"
        )
        menu_item_logon = requests_menu.Append(
            wx.ID_ANY, "&Logon\tCTRL+L", "Logon to a CPDLC station."
        )
        self.menu_item_logoff = requests_menu.Append(
            wx.ID_ANY, "Log&off\tCTRL+O", "Logoff from the current CPDLC station."
        )
        # Always enable both logon and logoff menu items
        menu_item_altitude_change = requests_menu.Append(
            wx.ID_ANY, "&Altitude change\tCTRL+T", "Request an altitude change."
        )
        menu_item_telex = requests_menu.Append(
            wx.ID_ANY, "Telex &message\tCTRL+M", "Send a telex message."
        )
        menu_bar.Append(requests_menu, "&Requests")

        self.SetMenuBar(menu_bar)

        # Bind menu events
        self.Bind(wx.EVT_MENU, self.on_about, menu_item_about)
        self.Bind(wx.EVT_MENU, self.on_connect_or_disconnect, self.menu_item_connect)
        self.Bind(wx.EVT_MENU, self.on_settings, menu_item_settings)
        self.Bind(wx.EVT_MENU, self.on_check_updates, menu_item_check_updates)
        self.Bind(wx.EVT_MENU, self.on_pdc_request, menu_item_pdc)
        self.Bind(wx.EVT_MENU, self.on_logon, menu_item_logon)
        self.Bind(wx.EVT_MENU, self.on_logoff, self.menu_item_logoff)
        self.Bind(wx.EVT_MENU, self.on_altitude_change, menu_item_altitude_change)
        self.Bind(wx.EVT_MENU, self.on_telex, menu_item_telex)
        self.Bind(wx.EVT_MENU, self.on_exit, menu_item_exit)

    def on_settings(self, _):
        """Display settings dialog and save any changes."""
        self.logger.debug("Opening settings dialog")

        # Load current settings
        config = load_config()
        current_sayintentions_logon_code = config.get("sayintentions_logon_code", "")
        current_hoppie_logon_code = config.get("hoppie_logon_code", "")
        current_simbrief_userid = config.get("simbrief_userid", "")
        current_auto_check_updates = config.get("auto_check_updates", True)

        dlg = SettingsDialog(
            self,
            current_sayintentions_logon_code,
            current_hoppie_logon_code,
            current_simbrief_userid,
            current_auto_check_updates,
        )
        if dlg.ShowModal() == wx.ID_OK:
            # Get the new settings
            (
                new_sayintentions_logon_code,
                new_hoppie_logon_code,
                new_simbrief_userid,
                new_auto_check_updates,
            ) = dlg.get_settings()
            self.logger.debug("Saving new settings")

            # Update the config
            config["sayintentions_logon_code"] = new_sayintentions_logon_code
            config["hoppie_logon_code"] = new_hoppie_logon_code
            config["simbrief_userid"] = new_simbrief_userid
            config["auto_check_updates"] = new_auto_check_updates
            if save_config(config):
                self.logger.info("Settings saved successfully")
                wx.MessageBox(
                    "Settings saved successfully. The new settings will be used for future operations.",
                    "Settings Saved",
                    wx.OK | wx.ICON_INFORMATION,
                )
            else:
                self.logger.error("Failed to save settings")
                wx.MessageBox(
                    "Failed to save settings. Please try again.",
                    "Error",
                    wx.OK | wx.ICON_ERROR,
                )
        else:
            self.logger.debug("Settings dialog cancelled")

        dlg.Destroy()

    def on_check_updates(self, _):
        """Manually check for updates."""
        self.logger.debug("Manually checking for updates")
        self.update_checker.check_for_updates(auto_check=False)

    def on_about(self, _):
        """Display information about the application."""
        show_about_dialog(self)

    def on_connect_or_disconnect(self, _):
        """Toggle connection state based on current status."""
        if not self.connection_manager.is_connected():
            # Connect
            self.on_connect()
        else:
            # Disconnect
            self.on_disconnect()

    def on_connect(self):
        """Establish connection to the CPDLC network."""
        self.logger.debug("Opening connection dialog")
        dlg = ConnectDialog(self)
        if dlg.ShowModal() == wx.ID_OK:
            callsign, logon_code, network_type = dlg.get_connection_details()

            if self.connection_manager.connect(callsign, logon_code, network_type):
                # Start polling
                self.polling_controller.start(self)

                # Set callsign in session
                self.cpdlc_session.set_callsign(callsign)

                # Update UI
                self.SetStatusText(f"Connected as {callsign}.")
                self.menu_item_connect.SetItemLabel("&Disconnect")
                self.menu_item_connect.SetHelp("Disconnect from the CPDLC network")

                # Add system message
                self._add_custom_message(f"Connected as {callsign}", "SYSTEM")
            else:
                wx.MessageBox(
                    "Connection failed. Please check your callsign and logon code.",
                    "Error",
                    wx.OK | wx.ICON_ERROR,
                )

        dlg.Destroy()

    def on_disconnect(self):
        """Disconnect from the CPDLC network."""
        if not self.connection_manager.is_connected():
            return

        # Check if logged on to a station
        if self.cpdlc_session.is_logged_on():
            # Confirm disconnect with warning about active logon
            confirm_message = f"You are currently logged on to {self.cpdlc_session.get_current_station()}. If you disconnect, you will be logged off from this station.\n\nAre you sure you want to disconnect from the CPDLC network?"
        else:
            # Standard confirmation
            confirm_message = (
                "Are you sure you want to disconnect from the CPDLC network?"
            )

        # Confirm disconnect
        if (
            wx.MessageBox(
                confirm_message,
                "Confirm Disconnect",
                wx.YES_NO | wx.ICON_QUESTION,
            )
            != wx.YES
        ):
            self.logger.debug("Disconnect cancelled by user")
            return

        self.logger.info("Disconnecting from CPDLC network")

        # If logged on to a station, send logoff message first
        if self.cpdlc_session.is_logged_on():
            success, message = self.cpdlc_session.send_logoff_message()
            if success and message:
                self._add_custom_message(message)
            self.polling_controller.set_active_polling()

            # Small delay to allow the message to be sent
            wx.MilliSleep(500)  # 500ms delay

        # Stop polling
        self.polling_controller.stop()

        # Disconnect
        self.connection_manager.disconnect()

        # Update UI
        self.menu_item_connect.SetItemLabel("&Connect")
        self.menu_item_connect.SetHelp("Connect to the CPDLC network")
        self.SetStatusText("Disconnected from CPDLC network.")

        # Add system message
        self._add_custom_message("Disconnected from CPDLC network", "SYSTEM")

    def on_logon(self, _):
        """Initiate logon to a CPDLC station."""
        # Check if connected to the network
        if not self.connection_manager.is_connected():
            wx.MessageBox(
                "You must be connected to the CPDLC network to log on to a station.",
                "Not Connected",
                wx.OK | wx.ICON_INFORMATION,
            )
            return

        self.logger.debug("Opening logon dialog")
        dlg = LogonDialog(self)
        if dlg.ShowModal() == wx.ID_OK:
            station = dlg.get_logon_details()

            # Validate station name is exactly 4 characters
            if len(station) != 4:
                wx.MessageBox(
                    "Station name must be exactly 4 characters long.",
                    "Invalid Station Name",
                    wx.OK | wx.ICON_ERROR,
                )
                dlg.Destroy()
                return

            success, message = self.cpdlc_session.logon(station)
            if success:
                # Add custom message only if a message was returned from the session
                if message:
                    self._add_custom_message(message)

                # Update UI to show pending logon status
                self.SetStatusText(f"Pending logon to {station}.")

                # Set active polling
                self.polling_controller.set_active_polling()
            else:
                wx.MessageBox(
                    f"Failed to send logon request to {station}.",
                    "Error",
                    wx.OK | wx.ICON_ERROR,
                )

        dlg.Destroy()

    def on_logoff(self, _):
        """Initiate logoff from current CPDLC station."""
        if not self.cpdlc_session.is_logged_on():
            wx.MessageBox(
                "You are not currently logged on to any station.",
                "Not Logged On",
                wx.OK | wx.ICON_INFORMATION,
            )
            return

        # Confirm logoff
        station = self.cpdlc_session.get_current_station()
        if (
            wx.MessageBox(
                f"Are you sure you want to log off from {station}?",
                "Confirm Logoff",
                wx.YES_NO | wx.ICON_QUESTION,
            )
            != wx.YES
        ):
            self.logger.debug("Logoff cancelled by user")
            return

        success, message = self.cpdlc_session.logoff()
        if success:
            if message:
                self._add_custom_message(message)

            # Update UI
            self.SetStatusText(f"Logged off from {station}")

            # Set active polling
            self.polling_controller.set_active_polling()
        else:
            wx.MessageBox(
                f"Failed to send logoff message to {station}.",
                "Error",
                wx.OK | wx.ICON_ERROR,
            )

    def on_altitude_change(self, _):
        """Send altitude change request to current station."""
        # Check if connected and logged on
        if not self.connection_manager.is_connected():
            wx.MessageBox(
                "You must be connected to the CPDLC network to request an altitude change.",
                "Not Connected",
                wx.OK | wx.ICON_INFORMATION,
            )
            return

        if not self.cpdlc_session.is_logged_on():
            wx.MessageBox(
                "You must be logged on to a station to request an altitude change.",
                "Not Logged On",
                wx.OK | wx.ICON_INFORMATION,
            )
            return

        self.logger.debug("Opening altitude change dialog")
        dlg = AltitudeChangeDialog(self)
        if dlg.ShowModal() == wx.ID_OK:
            altitude, reason, is_climb = dlg.get_altitude_details()

            success, message = self.cpdlc_session.send_altitude_change_request(
                altitude, is_climb, reason
            )
            if success:
                if message:
                    self._add_custom_message(message)

                # Set active polling
                self.polling_controller.set_active_polling()
            else:
                wx.MessageBox(
                    "Failed to send altitude change request.",
                    "Error",
                    wx.OK | wx.ICON_ERROR,
                )

        dlg.Destroy()

    def get_current_station(self):
        """Get the current station from the CPDLC session.

        Returns:
            str: The current station or empty string if not logged on
        """
        return (
            self.cpdlc_session.get_current_station()
            if self.cpdlc_session.is_logged_on()
            else ""
        )

    def on_telex(self, _):
        """Send a telex message to specified recipient."""
        # Check if connected to the network
        if not self.connection_manager.is_connected():
            wx.MessageBox(
                "You must be connected to the CPDLC network to send a telex message.",
                "Not Connected",
                wx.OK | wx.ICON_INFORMATION,
            )
            return

        self.logger.debug("Opening telex dialog")
        dlg = TelexDialog(self)
        if dlg.ShowModal() == wx.ID_OK:
            recipient, message = dlg.get_telex_details()

            success, returned_message = self.cpdlc_session.send_telex(
                recipient, message
            )
            if success:
                if returned_message:
                    self._add_custom_message(returned_message)
            else:
                wx.MessageBox(
                    f"Failed to send telex message to {recipient}.",
                    "Error",
                    wx.OK | wx.ICON_ERROR,
                )

        dlg.Destroy()

    def on_pdc_request(self, _):
        """Request a pre-departure clearance from departure airport."""
        # Check if connected to the network
        if not self.connection_manager.is_connected():
            wx.MessageBox(
                "You must be connected to the CPDLC network to request a PDC.",
                "Not Connected",
                wx.OK | wx.ICON_INFORMATION,
            )
            return

        self.logger.debug("Opening PDC request dialog")
        dlg = PDCDialog(self)
        if dlg.ShowModal() == wx.ID_OK:
            (
                origin_icao,
                destination_icao,
                aircraft_code,
                stand_designator,
                atis_code,
            ) = dlg.get_pdc_details()

            success, message = self.cpdlc_session.send_pdc_request(
                origin_icao,
                destination_icao,
                aircraft_code,
                stand_designator,
                atis_code,
            )
            if success:
                if message:
                    self._add_custom_message(message)

                # Set active polling
                self.polling_controller.set_active_polling()
            else:
                wx.MessageBox(
                    f"Failed to send PDC request to {origin_icao}.",
                    "Error",
                    wx.OK | wx.ICON_ERROR,
                )

        dlg.Destroy()

    def _add_custom_message(self, text, sender=None):
        """Add a custom message to the message list.

        Args:
            text: Message text
            sender: Optional sender name (defaults to current callsign)
        """
        if sender is None:
            sender = self.cpdlc_session.get_callsign()

        message_id = self.message_manager.add_custom_message(text, sender)
        self.message_view.add_message(message_id)

        # Don't play sound for outgoing messages (from user's callsign) or system messages
        # Sound should only play for incoming messages, which are handled in _on_message_received

    def _on_message_received(self, message):
        """Handle received messages from the network.

        Args:
            message: The received message
        """
        # Add to message manager
        message_id = self.message_manager.add_message(message)
        if message_id >= 0:
            # Add to view
            self.message_view.add_message(message_id)

            # Play sound for new messages
            self._play_message_sound()

            # Check for special messages that affect CPDLC session state
            if hasattr(message, "get_packet_content") and hasattr(
                message, "get_from_name"
            ):
                content = message.get_packet_content()
                sender = message.get_from_name()

                # Check for LOGON ACCEPTED message
                if "LOGON ACCEPTED" in content:
                    # Handle automatic handovers or explicit logon acceptance
                    self.cpdlc_session.handle_logon_accepted(sender)
                    # Update UI
                    self.SetStatusText(f"Logged on to {sender}.")
                    self.logger.info(f"Logon accepted by {sender}")

                # Check for LOGOFF message from station
                elif (
                    "LOGOFF" in content
                    and sender == self.cpdlc_session.get_current_station()
                ):
                    self.cpdlc_session.handle_station_logoff(sender)
                    # Update UI
                    self.SetStatusText(f"Logged off from {sender}")
                    self.logger.info(f"Received LOGOFF from {sender}")

    def _on_acknowledge_message(self, message, response):
        """Handle message acknowledgement.

        Args:
            message: The message being acknowledged
            response: The response text
        """
        sender = message.get_from_name()
        min_value = message.get_min()

        success, returned_message = self.cpdlc_session.send_acknowledgement(
            sender, min_value, response
        )
        if success:
            # Mark as acknowledged
            self.message_manager.mark_acknowledged(message)

            # Add custom message only if a message was returned from the session
            if returned_message:
                self._add_custom_message(returned_message)

            # Set active polling
            self.polling_controller.set_active_polling()

    def _play_message_sound(self):
        """Play sound notification for new messages."""
        if self.new_message_sound:
            self.new_message_sound.Play(wx.adv.SOUND_ASYNC)
            self.logger.debug("Played message notification sound")

    def on_close(self, event):
        """Handle application close event and perform cleanup."""
        self.logger.info("Application close event triggered")

        # If connected, show confirmation dialog
        if self.connection_manager.is_connected():
            if not self._confirm_exit(event):
                return

            self.logger.info("Exit confirmed, performing clean disconnect")

            # If logged on to a station, send logoff message first
            if self.cpdlc_session.is_logged_on():
                success, message = self.cpdlc_session.send_logoff_message()
                if success and message:
                    self._add_custom_message(message)

            # Stop polling
            self.polling_controller.stop()

        self.logger.info("Application shutting down")
        event.Skip()  # Allow the window to close

    def _confirm_exit(self, event):
        """Show exit confirmation dialog based on connection state.

        Returns:
            bool: True if exit confirmed, False otherwise
        """
        # Prepare confirmation message based on connection state
        if self.cpdlc_session.is_logged_on():
            station = self.cpdlc_session.get_current_station()
            confirm_message = f"You are currently connected to the CPDLC network and logged on to {station}.\n\nAre you sure you want to exit the application? You will be logged off from the station."
        else:
            confirm_message = "You are currently connected to the CPDLC network.\n\nAre you sure you want to exit the application?"

        # Show confirmation dialog
        if (
            wx.MessageBox(
                confirm_message,
                "Confirm Exit",
                wx.YES_NO | wx.ICON_QUESTION,
            )
            != wx.YES
        ):
            self.logger.debug("Exit cancelled by user")
            event.Veto()  # Prevent the window from closing
            return False

        return True

    def _check_first_launch(self):
        """Check if this is the first launch and prompt for settings if needed."""
        import os
        from src.config import CONFIG_FILE, load_config, save_config, DEFAULT_CONFIG

        # Check if config file exists
        config_file_exists = os.path.exists(CONFIG_FILE)

        # If config file doesn't exist, this is the first launch
        if not config_file_exists:
            self.logger.info("First launch detected - creating config file")

            # Create the config file with empty values
            config = DEFAULT_CONFIG.copy()
            save_config(config)

            # Show alert dialog
            dlg = wx.MessageDialog(
                self,
                "Welcome to Sim-CPDLC!\n\n"
                "It looks like this is your first time running the application. "
                "Would you like to set up your logon codes and SimBrief user ID now?\n\n"
                "These settings are required for connecting to CPDLC networks and retrieving SimBrief flight plans.",
                "Welcome to Sim-CPDLC",
                wx.YES_NO | wx.ICON_INFORMATION,
            )

            result = dlg.ShowModal()
            dlg.Destroy()

            if result == wx.ID_YES:
                self.logger.debug("User chose to set up settings on first launch")
                # Open the settings dialog
                wx.CallAfter(self.on_settings, None)
            else:
                self.logger.debug("User chose not to set up settings on first launch")
                # Continue with normal UI presentation

    def on_exit(self, _):
        """Handle exit menu selection by closing the window."""
        self.logger.info("Exit menu selected")
        self.Close()  # This will trigger on_close
