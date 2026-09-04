"""Main window for the Sim-CPDLC application."""

import functools
import os
import re
import sys
import wx
import wx.adv

from hoppie_connector import (
    CpdlcMessage,
    CpdlcResponseRequirement as RR,
    HoppieError,
    HoppieMessage,
)

from src.config import (
    DEFAULT_POLL_INTERVAL,
    ACTIVE_POLL_INTERVAL,
    INACTIVITY_TIMEOUT,
    MESSAGE_SOUND_FILENAME,
    weather_interval_minutes,
    load_config,
    save_config,
)

from src.model.connection_manager import ConnectionManager
from src.model.message_manager import MessageManager
from src.model.cpdlc_session import CpdlcSession
from src.model.weather_monitor import WeatherMonitor
from src.controller.polling_controller import PollingController
from src.model.network_worker import NetworkWorker, PRIORITY_LINK
from src.controller.link_state import LinkState
from src.gui.message_view import MessageView
from src.gui.dialogs import (
    ConnectDialog,
    LogonDialog,
    PDCDialog,
    AltitudeChangeDialog,
    TelexDialog,
    WeatherDialog,
    WeatherSubscriptionsDialog,
    DirectRequestDialog,
    SpeedRequestDialog,
    WhenCanWeDialog,
    show_about_dialog,
)
from src.utils.weather_parsing import report_type_label
from src.utils.update_checker import UpdateChecker
from src.utils.simconnect_manager import SimConnectManager
from src.utils.frequency_parser import extract_contact_frequency
from src.gui.dialogs.settings_dialog import SettingsDialog

# A HANDOVER names the next station as a 4-letter code; the @ separators the
# networks wrap it in have been flattened to spaces by then.
HANDOVER_PATTERN = re.compile(r"^HANDOVER\s+([A-Z]{4})$")


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

        # One thread for every network call, so the GUI thread never waits on
        # the network and every result comes back through the event loop.
        self.worker = NetworkWorker(logger)

        # Initialize model components
        self.connection_manager = ConnectionManager(logger)
        self.message_manager = MessageManager(logger)
        self.cpdlc_session = CpdlcSession(logger, self.connection_manager, worker=self.worker)
        self.simconnect_manager = SimConnectManager()

        # Check if this is the first launch (config file just created)
        self._check_first_launch()

        # Initialize sound for new messages
        sound_path = self.resource_path(os.path.join("assets", MESSAGE_SOUND_FILENAME))
        if os.path.exists(sound_path):
            self.new_message_sound = wx.adv.Sound(sound_path)
        else:
            error_msg = f"Sound file not found at {sound_path}. The program will work as expected, however you will not hear a notification sound when a new CPDLC message arrives. To restore the notification sound, please quit the app and double-check that the sound file exists at the specified path."
            self.logger.warning(error_msg)
            wx.MessageBox(error_msg, "Missing Sound File", wx.OK | wx.ICON_WARNING)
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
            link_callback=self._on_link_change,
            unreadable_callback=self._on_unreadable_messages,
            tick_callback=self._on_poll_tick,
            worker=self.worker,
        )
        # message_id -> response text queued but not yet reported, so a second
        # answer to the same uplink is refused until the first has gone out
        # (or failed).
        self._responses_in_flight = {}
        # True while a connect or disconnect job is out; every handler that
        # needs the connection refuses until it reports.
        self._link_busy = False
        # Named once per episode; reset to False whenever the link recovers.
        self._callsign_clash_announced = False

        # Initialize automatic weather updates
        interval_minutes = weather_interval_minutes(config)
        self.weather_monitor = WeatherMonitor(
            logger,
            self.connection_manager,
            self._on_weather_update,
            self._on_weather_error,
            interval_ms=interval_minutes * 60000,
            worker=self.worker,
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
            self.panel,
            self.logger,
            self.message_manager,
            self._on_acknowledge_message,
            self.cpdlc_session.is_answerable_sender,
            self._on_toggle_weather_updates,
            self._is_weather_watched,
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
            wx.ID_ABOUT, "&About", "Information about this program"
        )

        file_menu.AppendSeparator()
        menu_item_exit = file_menu.Append(wx.ID_EXIT, "E&xit", "Terminate the program")
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
        menu_item_direct = requests_menu.Append(
            wx.ID_ANY, "&Direct to\tCTRL+D", "Request direct to a waypoint."
        )
        menu_item_speed = requests_menu.Append(
            wx.ID_ANY, "&Speed change\tCTRL+S", "Request a speed/Mach change."
        )
        menu_item_when = requests_menu.Append(
            wx.ID_ANY, "&When can we expect\tCTRL+W", "Send a when-can-we-expect inquiry."
        )
        menu_item_telex = requests_menu.Append(
            wx.ID_ANY, "Telex &message\tCTRL+M", "Send a telex message."
        )
        menu_item_weather = requests_menu.Append(
            wx.ID_ANY,
            "AT&IS and Weather request\tCTRL+I",
            "Request a METAR, TAF or ATIS for an airport.",
        )
        menu_item_weather_subs = requests_menu.Append(
            wx.ID_ANY,
            "A&utomatic weather updates\tCTRL+SHIFT+I",
            "Show and manage the reports being kept up to date.",
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
        self.Bind(wx.EVT_MENU, self.on_direct_request, menu_item_direct)
        self.Bind(wx.EVT_MENU, self.on_speed_request, menu_item_speed)
        self.Bind(wx.EVT_MENU, self.on_when_can_we_expect, menu_item_when)
        self.Bind(wx.EVT_MENU, self.on_telex, menu_item_telex)
        self.Bind(wx.EVT_MENU, self.on_weather_request, menu_item_weather)
        self.Bind(
            wx.EVT_MENU, self.on_weather_subscriptions, menu_item_weather_subs
        )
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
        current_auto_tune_com1 = config.get("auto_tune_com1", True)
        current_weather_interval = weather_interval_minutes(config)

        dlg = SettingsDialog(
            self,
            current_sayintentions_logon_code,
            current_hoppie_logon_code,
            current_simbrief_userid,
            current_auto_check_updates,
            current_auto_tune_com1,
            current_weather_interval,
        )
        if dlg.ShowModal() == wx.ID_OK:
            # Get the new settings
            (
                new_sayintentions_logon_code,
                new_hoppie_logon_code,
                new_simbrief_userid,
                new_auto_check_updates,
                new_auto_tune_com1,
                new_weather_interval,
            ) = dlg.get_settings()
            self.logger.debug("Saving new settings")

            # Update the config
            config["sayintentions_logon_code"] = new_sayintentions_logon_code
            config["hoppie_logon_code"] = new_hoppie_logon_code
            config["simbrief_userid"] = new_simbrief_userid
            config["auto_check_updates"] = new_auto_check_updates
            config["auto_tune_com1"] = new_auto_tune_com1
            config["weather_update_interval"] = new_weather_interval
            self.weather_monitor.set_interval(new_weather_interval * 60000)
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
        """Ask for the connection details and connect on the worker."""
        self.logger.debug("Opening connection dialog")
        dlg = ConnectDialog(self)
        if dlg.ShowModal() == wx.ID_OK:
            callsign, logon_code, network_type = dlg.get_connection_details()
            self._begin_connect(callsign, logon_code, network_type)

        dlg.Destroy()

    def _begin_connect(self, callsign, logon_code, network_type):
        """Submit the connection attempt; the menu item stays disabled until it reports.

        Args:
            callsign: Aircraft callsign
            logon_code: CPDLC logon code
            network_type: "sayintentions" or "hoppie"
        """
        self.menu_item_connect.Enable(False)
        self._link_busy = True
        self.SetStatusText(f"Connecting as {callsign}...")
        self.worker.submit(
            "connect",
            lambda: self.connection_manager.connect(callsign, logon_code, network_type),
            functools.partial(self._on_connect_result, callsign, network_type),
            PRIORITY_LINK,
        )

    def _on_connect_result(self, callsign, network_type, result):
        """Finish a connection attempt. Runs on the GUI thread.

        Args:
            callsign: The callsign the attempt was made with
            network_type: The network it was made on
            result: The worker's JobResult
        """
        self.menu_item_connect.Enable(True)
        self._link_busy = False
        if not result.ok:
            self.SetStatusText("Not connected.")
            wx.MessageBox(
                f"Connection failed: {result.error}",
                "Error",
                wx.OK | wx.ICON_ERROR,
            )
            return

        # Start polling and automatic weather updates
        self.polling_controller.start(self)
        self.weather_monitor.start(self)

        # Hand the identity to the session; a different callsign or
        # network starts a clean dialogue, the same one keeps the logon
        self.cpdlc_session.begin_session(callsign, network_type)

        # Update UI
        self.SetStatusText(f"Connected as {callsign}.")
        self.menu_item_connect.SetItemLabel("&Disconnect")
        self.menu_item_connect.SetHelp("Disconnect from the CPDLC network")

        # Add system message
        self._add_custom_message(f"Connected as {callsign}", "SYSTEM")

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
        self.menu_item_connect.Enable(False)
        self._link_busy = True
        self.SetStatusText("Disconnecting...")
        self._end_dialogue()

        # Stop polling and automatic weather updates
        self.polling_controller.stop()
        self.weather_monitor.stop()
        self.weather_monitor.clear()

        # The LOGOFF queued by _end_dialogue runs at a higher priority than
        # this, so the connection is only closed once it has gone out.
        self.worker.submit(
            "disconnect", self.connection_manager.disconnect, self._on_disconnected, PRIORITY_LINK
        )

    def _on_disconnected(self, result):
        """Finish a disconnect once the LOGOFF has had its turn. Runs on the GUI thread.

        Args:
            result: The worker's JobResult (disconnect() cannot fail)
        """
        # Anything still queued belonged to the old session.
        self.worker.new_generation()
        # Their results were just dropped with the generation.
        self._responses_in_flight.clear()
        # Belt and braces: nothing queued during the disconnect may leave a dialogue behind.
        self.cpdlc_session.reset()

        # Update UI
        self.menu_item_connect.Enable(True)
        self._link_busy = False
        self.menu_item_connect.SetItemLabel("&Connect")
        self.menu_item_connect.SetHelp("Connect to the CPDLC network")
        self.SetStatusText("Disconnected from CPDLC network.")

        # Add system message
        self._add_custom_message("Disconnected from CPDLC network", "SYSTEM")

    def on_logon(self, _):
        """Initiate logon to a CPDLC station."""
        if not self._require_connection("log on to a station"):
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

            previous = self.cpdlc_session.get_current_station()
            self.SetStatusText(f"Logging on to {station}...")
            queued = self.cpdlc_session.logon(
                station,
                functools.partial(self._on_logon_frame, station),
                on_logoff_done=functools.partial(
                    self._on_prelogon_logoff, previous, station
                ),
            )
            if not queued:
                wx.MessageBox(
                    f"Failed to send logon request to {station}.",
                    "Error",
                    wx.OK | wx.ICON_ERROR,
                )

        dlg.Destroy()

    def _on_logon_frame(self, station, success, text_or_error):
        """Report the REQUEST LOGON of a manual logon. Runs on the GUI thread.

        Args:
            station: The station being logged on to
            success: Whether the frame went out
            text_or_error: The frame text, or the error text
        """
        if success:
            self._add_custom_message(text_or_error)
            self.polling_controller.set_active_polling()
            self.SetStatusText(f"Pending logon to {station}.")
            return

        error_detail = f": {text_or_error}" if text_or_error else ""
        self.SetStatusText(f"Could not log on to {station}.")
        wx.MessageBox(
            f"Failed to send logon request to {station}{error_detail}.",
            "Error",
            wx.OK | wx.ICON_ERROR,
        )

    def _on_prelogon_logoff(self, previous, station, success, text_or_error):
        """Report the LOGOFF that a logon while logged on sends first. Runs on the GUI thread.

        Args:
            previous: The station the LOGOFF went to
            station: The station being logged on to next
            success: Whether the frame went out
            text_or_error: The frame text, or the error text
        """
        if success:
            self._add_custom_message(text_or_error)
            return

        error_detail = f": {text_or_error}" if text_or_error else ""
        self.logger.warning(f"Could not send LOGOFF to {previous}{error_detail}")
        self.SetStatusText(f"Could not send LOGOFF to {previous}.")
        wx.MessageBox(
            f"Failed to send LOGOFF to {previous}{error_detail}. The logon to {station} goes ahead.",
            "Error",
            wx.OK | wx.ICON_ERROR,
        )

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

        self.SetStatusText(f"Sending LOGOFF to {station}...")
        if not self.cpdlc_session.logoff(functools.partial(self._on_logoff_frame, station)):
            wx.MessageBox(
                f"Failed to send logoff message to {station}.",
                "Error",
                wx.OK | wx.ICON_ERROR,
            )

    def _on_logoff_frame(self, station, success, text_or_error, quiet=False):
        """Report the outcome of a LOGOFF. Runs on the GUI thread.

        Args:
            station: The station the LOGOFF went to
            success: Whether the frame went out
            text_or_error: The frame text, or the error text
            quiet: True on disconnect and exit, where a failure gets a SYSTEM
                row rather than a dialog and the status bar is left alone
        """
        if success:
            self._add_custom_message(text_or_error)
            if not quiet:
                self.SetStatusText(f"Logged off from {station}.")
            return

        error_detail = f": {text_or_error}" if text_or_error else ""
        self.logger.warning(f"Could not send LOGOFF to {station}{error_detail}")
        if quiet:
            self._add_custom_message(
                f"Could not send LOGOFF to {station}{error_detail}", "SYSTEM"
            )
        else:
            self.SetStatusText(f"Could not send LOGOFF to {station}.")
            wx.MessageBox(
                f"Failed to send logoff message to {station}{error_detail}.",
                "Error",
                wx.OK | wx.ICON_ERROR,
            )

    def _end_dialogue(self):
        """Queue the LOGOFF for the current station, if any, then forget the dialogue.

        The session is reset at once, whether or not the LOGOFF gets through:
        after a disconnect the app must not believe it is still logged on
        (audit M-1). A LOGOFF that could not be sent gets a SYSTEM row when
        its result comes back, so the pilot knows the station was not told.
        """
        if self.cpdlc_session.is_logged_on():
            station = self.cpdlc_session.get_current_station()
            self.cpdlc_session.logoff(
                functools.partial(self._on_logoff_frame, station, quiet=True)
            )

        self.cpdlc_session.reset()

    def on_altitude_change(self, _):
        """Send altitude change request to current station."""
        # Check if connected and logged on
        if not self._require_connection("request an altitude change"):
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
            altitude, reason = dlg.get_altitude_details()

            what = "altitude change request"
            self.SetStatusText(f"Sending {what}...")
            if not self.cpdlc_session.send_altitude_change_request(
                altitude, reason, self._send_callback(what)
            ):
                wx.MessageBox(f"Failed to send {what}.", "Error", wx.OK | wx.ICON_ERROR)

        dlg.Destroy()

    def on_direct_request(self, _):
        """Send a direct-to waypoint request."""
        if not self._require_connection("send a request"):
            return

        if not self.cpdlc_session.is_logged_on():
            wx.MessageBox(
                "You must be logged on to a station to send a request.",
                "Not Logged On",
                wx.OK | wx.ICON_INFORMATION,
            )
            return

        dlg = DirectRequestDialog(self)
        if dlg.ShowModal() == wx.ID_OK:
            fix, reason = dlg.get_direct_details()

            what = "direct request"
            self.SetStatusText(f"Sending {what}...")
            if not self.cpdlc_session.send_direct_request(
                fix, reason, self._send_callback(what)
            ):
                wx.MessageBox(f"Failed to send {what}.", "Error", wx.OK | wx.ICON_ERROR)

        dlg.Destroy()

    def on_speed_request(self, _):
        """Send a speed/Mach change request."""
        if not self._require_connection("send a request"):
            return

        if not self.cpdlc_session.is_logged_on():
            wx.MessageBox(
                "You must be logged on to a station to send a request.",
                "Not Logged On",
                wx.OK | wx.ICON_INFORMATION,
            )
            return

        dlg = SpeedRequestDialog(self)
        if dlg.ShowModal() == wx.ID_OK:
            speed, is_mach, reason = dlg.get_speed_details()

            what = "speed request"
            self.SetStatusText(f"Sending {what}...")
            if not self.cpdlc_session.send_speed_request(
                speed, is_mach, reason, self._send_callback(what)
            ):
                wx.MessageBox(f"Failed to send {what}.", "Error", wx.OK | wx.ICON_ERROR)

        dlg.Destroy()

    def on_when_can_we_expect(self, _):
        """Send a when-can-we-expect inquiry."""
        if not self._require_connection("send a request"):
            return

        if not self.cpdlc_session.is_logged_on():
            wx.MessageBox(
                "You must be logged on to a station to send a request.",
                "Not Logged On",
                wx.OK | wx.ICON_INFORMATION,
            )
            return

        dlg = WhenCanWeDialog(self)
        if dlg.ShowModal() == wx.ID_OK:
            message_text = dlg.get_message_text()

            what = "request"
            self.SetStatusText(f"Sending {what}...")
            if not self.cpdlc_session.send_when_can_we_expect(
                message_text, self._send_callback(what)
            ):
                wx.MessageBox(f"Failed to send {what}.", "Error", wx.OK | wx.ICON_ERROR)

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
        if not self._require_connection("send a telex message"):
            return

        self.logger.debug("Opening telex dialog")
        dlg = TelexDialog(self)
        if dlg.ShowModal() == wx.ID_OK:
            recipient, message = dlg.get_telex_details()

            what = f"telex message to {recipient}"
            self.SetStatusText(f"Sending {what}...")
            if not self.cpdlc_session.send_telex(
                recipient, message, self._send_callback(what)
            ):
                wx.MessageBox(f"Failed to send {what}.", "Error", wx.OK | wx.ICON_ERROR)

        dlg.Destroy()

    def _require_connection(self, action):
        """Check we are connected, telling the user if we are not.

        Args:
            action: What the user was trying to do, for the message text

        Returns:
            bool: True if connected
        """
        if self.connection_manager.is_connected() and not self._link_busy:
            return True

        wx.MessageBox(
            f"You must be connected to the CPDLC network to {action}.",
            "Not Connected",
            wx.OK | wx.ICON_INFORMATION,
        )
        return False

    def _send_callback(self, what):
        """Build the on_done for a downlink: echo it and speed up polling, or
        say why it failed.

        Args:
            what: The request as the failure dialog names it, e.g.
                "altitude change request"
        """

        def done(success, text_or_error):
            if success:
                self._add_custom_message(text_or_error)
                self.SetStatusText(f"Sent {text_or_error}.")
                self.polling_controller.set_active_polling()
                return

            error_detail = f": {text_or_error}" if text_or_error else ""
            self.SetStatusText(f"Could not send {what}.")
            wx.MessageBox(
                f"Failed to send {what}{error_detail}.",
                "Error",
                wx.OK | wx.ICON_ERROR,
            )

        return done

    def on_weather_request(self, _):
        """Request a METAR, TAF or ATIS, optionally keeping it up to date."""
        if not self._require_connection("request weather information"):
            return

        self.logger.debug("Opening weather information request dialog")

        dlg = WeatherDialog(self, is_watched=self._is_weather_watched)

        if dlg.ShowModal() == wx.ID_OK:
            icao, info_type, auto_update = dlg.get_weather_details()

            label = report_type_label(info_type)
            was_watched = self.weather_monitor.is_subscribed(icao, info_type)

            # Unchecking the box is how the user stops updates, so act on it
            # whether or not this request succeeds.
            if was_watched and not auto_update:
                self.weather_monitor.unsubscribe(icao, info_type)
                self._add_custom_message(
                    f"Stopped automatic updates for {label} {icao}", "SYSTEM"
                )

            self.SetStatusText(f"Requesting {label} for {icao}...")
            queued = self.cpdlc_session.request_weather(
                info_type,
                icao,
                lambda success, result: self._on_weather_requested(
                    success, result, icao, info_type, auto_update, was_watched
                ),
            )
            if not queued:
                wx.MessageBox(
                    f"Failed to retrieve {label} for {icao}: not connected.",
                    "Error",
                    wx.OK | wx.ICON_ERROR,
                )

        dlg.Destroy()

    def _on_weather_requested(self, success, result, icao, info_type, auto_update, was_watched):
        """Show a requested report, or say why it did not come. Runs on the GUI thread.

        Args:
            success: Whether the report arrived
            result: The report text, or the error text
            icao: Airport ICAO code
            info_type: Report type key
            auto_update: Whether the pilot asked to keep the report updated
            was_watched: Whether it was already being watched when asked
        """
        label = report_type_label(info_type)
        if not success:
            error_detail = f": {result}" if result else ""
            self.SetStatusText(f"Could not retrieve {label} for {icao}.")
            wx.MessageBox(
                f"Failed to retrieve {label} for {icao}{error_detail}.",
                "Error",
                wx.OK | wx.ICON_ERROR,
            )
            return

        self._add_weather_message(result, icao, info_type)
        self.SetStatusText(f"{label} for {icao} received.")

        # Only start watching a report we know we can actually fetch.
        if auto_update:
            self.weather_monitor.subscribe(icao, info_type, initial_text=result)
            if not was_watched:
                self._add_custom_message(
                    f"Now watching {label} {icao} for changes", "SYSTEM"
                )

    def on_weather_subscriptions(self, _):
        """Show and manage the reports being kept up to date."""
        if self.weather_monitor.count() == 0:
            wx.MessageBox(
                "No reports are being kept up to date. Check "
                "'Keep this report updated automatically' when you request a "
                "METAR, TAF or ATIS to start watching one.",
                "Automatic Weather Updates",
                wx.OK | wx.ICON_INFORMATION,
            )
            return

        dlg = WeatherSubscriptionsDialog(self, self.weather_monitor)
        dlg.ShowModal()
        dlg.Destroy()

    def _on_weather_update(self, subscription, text, description):
        """Announce a weather report that has changed.

        Args:
            subscription: The WeatherSubscription that changed
            text: The new report text
            description: A short description of the new report
        """
        self._add_weather_message(
            text, subscription.icao, subscription.info_type, play_sound=True
        )
        self.SetStatusText(f"New {description}")

    def _on_weather_error(self, subscription, error):
        """Report that automatic updates have been given up on.

        Args:
            subscription: The WeatherSubscription that was dropped
            error: The last error description
        """
        self._add_custom_message(
            f"Stopped automatic updates for {subscription.describe()}: {error}",
            "SYSTEM",
        )

    def _defer(self, callback, *args, **kwargs):
        """Run a callback on the next pass of the event loop.

        A modal dialog opened from inside a timer tick nests an event loop under
        the handler, and the next tick then runs inside it; deferring keeps
        every tick short.
        """
        wx.CallAfter(callback, *args, **kwargs)

    def _on_link_change(self, old_state, new_state, reason):
        """Announce the link transitions the status bar alone would hide.

        NVDA does not announce status bar changes on its own, so losing the
        link, getting it back and a rejected logon code each get a SYSTEM row
        and the notification sound. A degraded link (one or two failed polls)
        only changes the status bar, except that a callsign already in use is
        named once per episode so the pilot can look for the other client.

        Args:
            old_state: The LinkState before the transition
            new_state: The LinkState after it
            reason: The poll's reason text, None on recovery
        """
        if new_state == LinkState.CONNECTED:
            # The episode is over either way; the next clash, if any, is a
            # new one and deserves its own row.
            self._callsign_clash_announced = False

        if new_state == LinkState.LOST:
            # Automatic weather updates are a re-request on a timer, and every
            # failed attempt spends part of their five-strikes budget. A link
            # that is already down must not also burn through that budget.
            self.weather_monitor.stop()
            self._add_custom_message("Connection lost, retrying", "SYSTEM", play_sound=True)
        elif new_state == LinkState.CONNECTED and old_state == LinkState.LOST:
            self.weather_monitor.start(self)
            self._add_custom_message("Connection restored", "SYSTEM", play_sound=True)
        elif new_state == LinkState.FATAL:
            self._on_fatal_link_error(reason)

        if (
            new_state in (LinkState.DEGRADED, LinkState.LOST)
            and reason
            and "callsign already in use" in reason.lower()
            and not self._callsign_clash_announced
        ):
            # In addition to the LOST row above, not instead of it: a clash
            # can be the very reason the link went down.
            self._callsign_clash_announced = True
            self._add_custom_message(
                "Connection problem: callsign already in use", "SYSTEM"
            )

    def _on_fatal_link_error(self, reason):
        """Tear the connection down after the server rejected the logon code.

        Args:
            reason: The server's reason text
        """
        self.logger.error(f"Disconnecting after a fatal link error: {reason}")
        self.polling_controller.stop()
        # Nothing queued for this session may run or report now.
        self.worker.new_generation()
        # Their results were just dropped with the generation.
        self._responses_in_flight.clear()
        self.weather_monitor.stop()
        self.weather_monitor.clear()
        self.connection_manager.disconnect()
        self.cpdlc_session.reset()
        self.menu_item_connect.SetItemLabel("&Connect")
        self.menu_item_connect.SetHelp("Connect to the CPDLC network")
        self.SetStatusText("Disconnected: logon code rejected.")
        self._add_custom_message(
            "Disconnected: the server rejected the logon code", "SYSTEM", play_sound=True
        )
        self._defer(
            wx.MessageBox,
            "The server rejected the logon code. Check it under File > Settings, "
            "then connect again.",
            "Logon Code Rejected",
            wx.OK | wx.ICON_ERROR,
        )

    def _on_unreadable_messages(self, unreadable):
        """Tell the pilot about uplinks that arrived but could not be decoded.

        The server has already marked them delivered, so the controller will
        be waiting for a response the pilot never saw. The raw packet is shown
        so it can be read out or asked about by voice.

        Args:
            unreadable: List of UnreadableMessage records from one poll
        """
        for item in unreadable:
            self._add_custom_message(
                f"Unreadable message from {item.sender}: {item.raw}",
                "SYSTEM",
                play_sound=True,
            )

    def _on_poll_tick(self):
        """Housekeeping on the poll clock: give up on a logon nobody answered."""
        station = self.cpdlc_session.expire_pending()
        if station:
            self.SetStatusText(f"Logon to {station} not answered.")
            self._add_custom_message(f"Logon to {station} not answered", "SYSTEM")

    def on_pdc_request(self, _):
        """Request a pre-departure clearance from departure airport."""
        # Check if connected to the network
        if not self._require_connection("request a PDC"):
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

            what = f"PDC request to {origin_icao}"
            self.SetStatusText(f"Sending {what}...")
            if not self.cpdlc_session.send_pdc_request(
                origin_icao,
                destination_icao,
                aircraft_code,
                stand_designator,
                atis_code,
                self._send_callback(what),
            ):
                wx.MessageBox(f"Failed to send {what}.", "Error", wx.OK | wx.ICON_ERROR)

        dlg.Destroy()

    def _add_weather_message(self, text, icao, info_type, play_sound=False):
        """Add a weather report to the message list.

        Tagging the report with its airport and type lets the context menu on
        it start or stop automatic updates without retyping anything.

        Args:
            text: The report text
            icao: Airport ICAO code
            info_type: Report type key
            play_sound: Whether to play the notification sound. Off for a
                report the pilot just asked for, which is already on their
                screen; on for an automatic update, which arrives unprompted.
        """
        message_id = self.message_manager.add_weather_message(text, icao, info_type)
        self.message_view.add_message(message_id)

        if play_sound:
            self._play_message_sound()

    def _is_weather_watched(self, icao, info_type):
        """Check whether a report is being kept up to date.

        Args:
            icao: Airport ICAO code
            info_type: Report type key

        Returns:
            bool: True if the report is being watched
        """
        return self.weather_monitor.is_subscribed(icao, info_type)

    def _on_toggle_weather_updates(self, icao, info_type, text=None):
        """Start or stop automatic updates for a report.

        Args:
            icao: Airport ICAO code
            info_type: Report type key
            text: The report already on screen, if any. Seeding the new
                subscription with it stops the next check announcing a report
                the pilot is looking at as though it were new.
        """
        label = report_type_label(info_type)

        if self.weather_monitor.is_subscribed(icao, info_type):
            self.weather_monitor.unsubscribe(icao, info_type)
            self._add_custom_message(
                f"Stopped automatic updates for {label} {icao}", "SYSTEM"
            )
            self.SetStatusText(f"Stopped watching {label} {icao}.")
            return

        self.weather_monitor.subscribe(icao, info_type, initial_text=text)
        self._add_custom_message(
            f"Now watching {label} {icao} for changes", "SYSTEM"
        )
        self.SetStatusText(f"Watching {label} {icao}.")

    def _add_custom_message(self, text, sender=None, play_sound=False):
        """Add a custom message to the message list.

        Args:
            text: Message text
            sender: Optional sender name (defaults to current callsign)
            play_sound: Whether to play the notification sound. Off for
                outgoing and system messages, on for information that arrives
                from the network such as weather reports.
        """
        if sender is None:
            sender = self.cpdlc_session.get_callsign()

        message_id = self.message_manager.add_custom_message(text, sender)
        self.message_view.add_message(message_id)

        if play_sound:
            self._play_message_sound()

    def _on_message_received(self, message):
        """Handle received messages from the network.

        Only a CPDLC message can change session state or tune the radio.
        Telex, progress and ADS-C messages are shown and nothing else, so a
        telex reading LOGON ACCEPTED cannot log the aircraft on (audit L-2).

        Args:
            message: The received message
        """
        text = None
        if isinstance(message, CpdlcMessage):
            text = self._protocol_text(message)
            # Protocol noise, hidden before it reaches the list
            if text.startswith("CURRENT ATC UNIT") or text.startswith("CURRENT ATS UNIT"):
                self.logger.debug(f"Hiding protocol message: {text}")
                return

        message_id = self.message_manager.add_message(message)
        if message_id < 0:
            return

        self.message_view.add_message(message_id)
        self._play_message_sound()

        if text is not None:
            self._handle_session_uplink(message, text)

    @staticmethod
    def _protocol_text(message):
        """A CPDLC message element with its @ separators flattened to spaces."""
        return " ".join(message.get_message().replace("@", " ").split())

    def _handle_session_uplink(self, message, text):
        """Apply a CPDLC uplink to the session, then tune the radio if it asks.

        Args:
            message: The CpdlcMessage, already in the list
            text: Its element text as returned by _protocol_text
        """
        session = self.cpdlc_session
        sender = message.get_from_name()
        mrn = message.get_mrn()

        if text.startswith("LOGON ACCEPTED"):
            # Only report the logon if the session actually accepted it; a
            # stale acceptance from a previously contacted station is ignored
            # and must not be announced as success.
            if session.handle_logon_accepted(sender, mrn=mrn):
                self.SetStatusText(f"Logged on to {sender}.")
                self.logger.info(f"Logon accepted by {sender}")
        elif text.startswith("LOGON REJECTED") or (text == "UNABLE" and mrn is not None):
            # An UNABLE is only a rejection when it answers the REQUEST LOGON;
            # the session checks the station and the MRN.
            if session.handle_logon_rejected(sender, mrn=mrn):
                self.SetStatusText(f"Logon to {sender} rejected.")
                self._add_custom_message(f"Logon to {sender} rejected", "SYSTEM")
        elif sender == session.get_current_station():
            match = HANDOVER_PATTERN.match(text)
            if match:
                self._follow_handover(sender, match.group(1))
            elif text == "LOGOFF":
                session.handle_station_logoff(sender)
                self.SetStatusText(f"Logged off from {sender}.")
                self.logger.info(f"Received LOGOFF from {sender}")

        # The station that handed the aircraft over may still send the CONTACT
        # for the next frequency, so any answerable sender may tune the radio.
        if session.is_answerable_sender(sender):
            self._auto_tune(text)

    def _follow_handover(self, sender, new_station):
        """Log on to the station a HANDOVER names.

        Args:
            sender: The station handing over (the current station)
            new_station: The station to log on to
        """
        self.logger.info(f"Handover detected from {sender} to {new_station}")
        self.SetStatusText(f"Logged off from {sender}.")
        self._add_custom_message(f"Logging on to {new_station}", "SYSTEM")

        queued = self.cpdlc_session.handle_handover(
            sender, new_station, functools.partial(self._on_handover_logon, new_station)
        )
        if not queued:
            self.logger.error(f"Failed to send logon request to {new_station} during handover")
            self._add_custom_message(
                f"Failed to logon to {new_station} during handover", "SYSTEM"
            )

    def _on_handover_logon(self, new_station, success, text_or_error):
        """Report the REQUEST LOGON a handover sent. Runs on the GUI thread.

        Args:
            new_station: The station being logged on to
            success: Whether the frame went out
            text_or_error: The frame text, or the error text
        """
        if success:
            self._add_custom_message(text_or_error)
            self.SetStatusText(f"Pending logon to {new_station}.")
            self.polling_controller.set_active_polling()
            return

        error_detail = f": {text_or_error}" if text_or_error else ""
        self.logger.error(
            f"Failed to send logon request to {new_station} during handover{error_detail}"
        )
        self._add_custom_message(
            f"Failed to logon to {new_station} during handover{error_detail}",
            "SYSTEM",
        )

    def _auto_tune(self, text):
        """Put a CONTACT/MONITOR frequency into the COM1 standby, if enabled.

        Args:
            text: The uplink's element text as returned by _protocol_text
        """
        config = load_config()
        if not config.get("auto_tune_com1", True):
            return

        freq = extract_contact_frequency(text)
        if freq is None:
            return

        self.logger.info(f"CONTACT/MONITOR frequency detected: {freq:.3f} MHz")
        if self.simconnect_manager.set_com1_standby_mhz(freq):
            self.logger.info(f"COM1 standby set to {freq:.3f} MHz")
        else:
            self.logger.warning("Could not set COM1 standby (SimConnect unavailable)")
            self.SetStatusText(f"Auto-tune failed \u2014 set {freq:.3f} manually")

    def _on_acknowledge_message(self, message_id: int, response: str):
        """Queue a response to an uplink.

        Args:
            message_id: The ID of the message being acknowledged
            response: The response text
        """
        addressing = self.message_manager.get_cpdlc_addressing(message_id)
        if addressing is None:
            self.logger.warning(f"Cannot acknowledge unknown message ID {message_id}")
            self.SetStatusText("Could not send response: message unavailable.")
            return

        sender, min_value = addressing

        pending = self._responses_in_flight.get(message_id)
        if pending is not None:
            self.logger.info(
                f"{response} for message ID {message_id} not queued: {pending} is already on its way"
            )
            self.SetStatusText(f"{response} not sent: {pending} is already on its way for this message.")
            return

        self.SetStatusText(f"Sending {response}...")
        # Claim the message before queueing, and give it back if the send was
        # refused; _on_acknowledgement_sent releases it once the frame reports.
        self._responses_in_flight[message_id] = response
        queued = self.cpdlc_session.send_acknowledgement(
            sender,
            min_value,
            response,
            functools.partial(self._on_acknowledgement_sent, message_id, response),
        )
        if not queued:
            self._responses_in_flight.pop(message_id, None)
            wx.MessageBox(
                "Failed to send acknowledgement: not connected.",
                "Error",
                wx.OK | wx.ICON_ERROR,
            )

    def _on_acknowledgement_sent(self, message_id, response, success, text_or_error):
        """Retire and echo a response once it has gone out. Runs on the GUI thread.

        Args:
            message_id: The ID of the message that was answered
            response: The response text
            success: Whether the frame went out
            text_or_error: The frame text, or the error text
        """
        self._responses_in_flight.pop(message_id, None)
        if success:
            # MessageManager decides whether this response retires the message;
            # STANDBY is sent but leaves it answerable.
            self.message_manager.mark_acknowledged(message_id, response)
            self._add_custom_message(text_or_error)
            self.SetStatusText(f"Sent {response}.")
            self.polling_controller.set_active_polling()
            return

        error_detail = f": {text_or_error}" if text_or_error else ""
        self.SetStatusText(f"Could not send {response}.")
        wx.MessageBox(
            f"Failed to send acknowledgement{error_detail}.",
            "Error",
            wx.OK | wx.ICON_ERROR,
        )

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
            self._end_dialogue()

            # Stop polling
            self.polling_controller.stop()

        self.weather_monitor.shutdown()
        self.simconnect_manager.disconnect()
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
