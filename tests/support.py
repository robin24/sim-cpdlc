"""Shared test doubles and builders for the sim-cpdlc test suite.

These are helpers, not fixtures: import them explicitly with
`from tests.support import ...`. Fixtures live in conftest.py.
"""

import wx

from hoppie_connector import CpdlcMessage, CpdlcResponseRequirement as RR

from src.config import DEFAULT_CONFIG, save_config
from src.model.connection_manager import PollResult
from src.model.network_worker import NetworkWorker

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


def answerable(*stations):
    """A sender predicate that answers True for exactly these stations.

    Stands in for CpdlcSession.is_answerable_sender where no session is
    involved; answerable() with no stations means nobody is logged on.
    """
    return lambda sender: sender in stations


def inline_worker(logger):
    """A NetworkWorker with no thread.

    Jobs run when the test calls run_pending(), on the test's own thread, and
    each result is handed straight to its callback, so a test drives the
    asynchronous path deterministically: submit, run_pending(), assert.
    """
    return NetworkWorker(logger, dispatch=lambda fn, *args: fn(*args), start_thread=False)


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
        self.poll_results = []
        self.disconnected = False
        self.connected_as = None

    def is_connected(self):
        return self._connected

    def connect(self, callsign, logon_code, network_type):
        self._connected = True
        self.connected_as = (callsign, network_type)

    def disconnect(self):
        self._connected = False
        self.disconnected = True

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

    def poll(self):
        """Serve the next scripted PollResult, or a clean empty poll."""
        if self.poll_results:
            return self.poll_results.pop(0)
        return PollResult(ok=True)


class RecordingMessageView:
    """Captures the message IDs the window pushes into the list view."""

    def __init__(self):
        self.added = []

    def add_message(self, message_id):
        self.added.append(message_id)


class FakePollingController:
    """Records polling-rate changes and stops without owning a wx.Timer."""

    def __init__(self):
        self.active_calls = 0
        self.stopped = False
        self.started = False

    def start(self, parent_window):
        self.started = True

    def set_active_polling(self):
        self.active_calls += 1

    def stop(self):
        self.stopped = True


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


class FakeWeatherMonitor:
    """Records the lifecycle calls the window makes on the weather monitor."""

    def __init__(self):
        self.stopped = False
        self.cleared = False
        self.started = False
        self.shut_down = False

    def start(self, parent_window):
        self.started = True

    def stop(self):
        self.stopped = True

    def clear(self):
        self.cleared = True

    def shutdown(self):
        self.shut_down = True


class FakeMenuItem:
    """Records the label and help text the window sets on a menu item."""

    def __init__(self, label="&Disconnect"):
        self.label = label
        self.help = ""

    def SetItemLabel(self, label):
        self.label = label

    def SetHelp(self, text):
        self.help = text


class FakeSound:
    """Counts the notification chimes instead of playing them."""

    def __init__(self):
        self.played = 0

    def Play(self, flags=0):
        self.played += 1
        return True


class FakeCallLater:
    """Stands in for a wx.CallLater handle, recording whether it was cancelled."""

    def __init__(self):
        self.stopped = False

    def Stop(self):
        self.stopped = True


class FakeCloseEvent:
    """Stands in for the wx.CloseEvent on_close receives."""

    def __init__(self):
        self.skipped = False
        self.vetoed = False

    def Skip(self):
        self.skipped = True

    def Veto(self):
        self.vetoed = True


class FakeClock:
    """A monotonic clock the test moves by hand, for the session's time windows.

    Args:
        now: The starting reading, in seconds
    """

    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class MessageBoxes:
    """Records wx.MessageBox calls and answers them without showing anything."""

    def __init__(self):
        self.calls = []
        self.answer = wx.YES

    def __call__(self, message, caption="Message", style=wx.OK, *args, **kwargs):
        self.calls.append((message, caption, style))
        return self.answer

    @property
    def captions(self):
        return [caption for _, caption, _ in self.calls]


class MessageDialogs:
    """Stands in for wx.MessageDialog: records the request, answers without showing.

    The default answer is wx.ID_NO because the first-launch prompt reacts to
    ID_YES by scheduling the real Settings dialog through wx.CallAfter.
    """

    class _Dialog:
        def __init__(self, recorder):
            self._recorder = recorder

        def ShowModal(self):
            return self._recorder.answer

        def Destroy(self):
            return True

    def __init__(self):
        self.calls = []
        self.answer = wx.ID_NO

    def __call__(self, parent, message, caption="Message", style=wx.OK, *args, **kwargs):
        self.calls.append((message, caption, style))
        return self._Dialog(self)

    @property
    def captions(self):
        return [caption for _, caption, _ in self.calls]


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

    The window's deferred and delayed callbacks (`_defer`, `_retry_later`) run
    or are recorded synchronously, since there is no event loop.
    """
    from src.gui.main_window import MainWindow

    if config is not None:
        assert save_config({**DEFAULT_CONFIG, **config}), "could not write test config"

    window = MainWindow.__new__(MainWindow)
    window.logger = logger
    window.cpdlc_session = cpdlc_session
    window.message_manager = message_manager
    window.message_view = RecordingMessageView()
    window.connection_manager = cpdlc_session.connection_manager
    window.polling_controller = FakePollingController()
    window.weather_monitor = FakeWeatherMonitor()
    window.menu_item_connect = FakeMenuItem()
    window.simconnect_manager = (
        simconnect if simconnect is not None else FakeSimConnectManager()
    )
    window.new_message_sound = FakeSound()
    # wx.CallAfter needs a running wx.App; run deferred callbacks at once.
    window._defer = lambda callback, *args, **kwargs: callback(*args, **kwargs)
    # wx.CallLater needs a running wx.App; record delayed callbacks instead.
    window.retries = []
    window._pending_retry = None

    def _retry_later(delay_ms, callback, *args):
        window.retries.append((delay_ms, callback, args))
        window._pending_retry = FakeCallLater()

    window._retry_later = _retry_later
    window._callsign_clash_announced = False
    window.status_texts = []
    # Instance attribute shadows wx.Frame.SetStatusText, which would need a
    # live C++ frame behind it.
    window.SetStatusText = window.status_texts.append
    return window
