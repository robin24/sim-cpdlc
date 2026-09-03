"""Shared test doubles and builders for the sim-cpdlc test suite.

These are helpers, not fixtures: import them explicitly with
`from tests.support import ...`. Fixtures live in conftest.py.
"""

from hoppie_connector import CpdlcMessage, CpdlcResponseRequirement as RR

from src.config import DEFAULT_CONFIG, save_config

CLIENT_CALLSIGN = "DLH123"


def uplink(
    sender, min_value, text="CLIMB TO AND MAINTAIN FL360", rr=RR.WILCO_UNABLE, mrn=None
):
    """Build an uplink CpdlcMessage as it would arrive from a station.

    Args:
        sender: Station sending the message
        min_value: The station's own message number (MIN)
        text: Message element text
        rr: Response requirement
        mrn: Message reference number, the MIN of our message this one
            answers. Every real LOGON ACCEPTED carries one.
    """
    return CpdlcMessage(sender, CLIENT_CALLSIGN, min_value, rr, text, mrn)


class FakeConnectionManager:
    """Stands in for ConnectionManager, recording frames instead of transmitting.

    ConnectionManager is the network boundary and is injected into CpdlcSession,
    so this is the intended seam rather than a mock of code under test.

    Args:
        connected: What is_connected() reports
        raise_with: An exception every send raises instead of recording, for
            exercising the failure paths
    """

    def __init__(self, connected=True, raise_with=None):
        self._connected = connected
        self.raise_with = raise_with
        self.sent = []
        self.telexes = []
        self.info_requests = []

    def is_connected(self):
        return self._connected

    def send_cpdlc(self, recipient, min_value, response_type, message, mrn=None):
        if self.raise_with is not None:
            raise self.raise_with
        self.sent.append((recipient, min_value, response_type, message, mrn))

    def send_telex(self, recipient, message):
        if self.raise_with is not None:
            raise self.raise_with
        self.telexes.append((recipient, message))

    def send_info_request(self, info_type, icao):
        if self.raise_with is not None:
            raise self.raise_with
        self.info_requests.append((info_type, icao))
        return f"{icao} REPORT FOR {info_type}"


class RecordingMessageView:
    """Captures the message IDs the window pushes into the list view."""

    def __init__(self):
        self.added = []

    def add_message(self, message_id):
        self.added.append(message_id)


class FakePollingController:
    """Records polling-rate changes without owning a wx.Timer."""

    def __init__(self):
        self.active_calls = 0

    def set_active_polling(self):
        self.active_calls += 1


class FakeSimConnectManager:
    """Records the frequencies the window tries to tune, never touching a simulator.

    Args:
        result: What connect() and set_com1_standby_mhz() report back
    """

    def __init__(self, result=True):
        self.result = result
        self.tuned = []

    def connect(self):
        return self.result

    def disconnect(self):
        pass

    def set_com1_standby_mhz(self, frequency_mhz):
        self.tuned.append(frequency_mhz)
        return self.result


def make_main_window(logger, cpdlc_session, message_manager, config=None, simconnect=None):
    """Build a MainWindow whose wx.Frame half is never initialised.

    MainWindow.__init__ opens dialogs, loads sounds and starts an update check,
    none of which a unit test should trigger. Allocating the instance and wiring
    only the collaborators the message path touches lets the real
    _on_message_received / _on_acknowledge_message code run unmodified.

    Args:
        logger: Test logger
        cpdlc_session: The CpdlcSession the window should drive
        message_manager: The MessageManager the window should fill
        config: Overrides written to the (isolated) config file, so the
            window's own load_config() calls see them. None leaves the
            defaults in place.
        simconnect: A FakeSimConnectManager; a fresh one when None
    """
    from src.gui.main_window import MainWindow

    if config is not None:
        assert save_config({**DEFAULT_CONFIG, **config}), "could not write test config"

    window = MainWindow.__new__(MainWindow)
    window.logger = logger
    window.cpdlc_session = cpdlc_session
    window.message_manager = message_manager
    window.message_view = RecordingMessageView()
    window.polling_controller = FakePollingController()
    window.simconnect_manager = (
        simconnect if simconnect is not None else FakeSimConnectManager()
    )
    window.new_message_sound = None
    window.status_texts = []
    # Instance attribute shadows wx.Frame.SetStatusText, which would need a
    # live C++ frame behind it.
    window.SetStatusText = window.status_texts.append
    return window
