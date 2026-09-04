"""Shared test doubles and builders for the sim-cpdlc test suite.

These are helpers, not fixtures: import them explicitly with
`from tests.support import ...`. Fixtures live in conftest.py.
"""

import wx

from hoppie_connector import CpdlcMessage, CpdlcResponseRequirement as RR, HoppieError

from src.config import DEFAULT_CONFIG, load_config, save_config
from src.model.connection_manager import PollResult
from src.model.network_worker import NetworkWorker
from src.utils.update_checker import UpdateChecker

CLIENT_CALLSIGN = "DLH123"


def mnemonic(label):
    """Return the access-key letter a wx label declares with '&', if any.

    wx escapes a literal ampersand as "&&", which is not a mnemonic.

    Args:
        label: A wx item, menu or control label, e.g. "&Connect" or "Log&off\tCTRL+O".

    Returns:
        str: The upper-cased mnemonic letter, or None if the label declares
            none.
    """
    index = 0
    while index < len(label) - 1:
        if label[index] == "&":
            if label[index + 1] == "&":
                index += 2
                continue
            return label[index + 1].upper()
        index += 1
    return None


def colliding_mnemonics(labels):
    """Group labels by mnemonic letter, keeping only letters more than one claims.

    Args:
        labels: Iterable of wx item, menu or control labels.

    Returns:
        dict: {letter: [label, ...]} for every letter two or more labels
            declare as their mnemonic.
    """
    by_letter = {}
    for label in labels:
        letter = mnemonic(label)
        if letter is not None:
            by_letter.setdefault(letter, []).append(label)
    return {letter: found for letter, found in by_letter.items() if len(found) > 1}


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


class InlineWorker(NetworkWorker):
    """A NetworkWorker with no thread, for tests.

    Jobs run when the test calls run_pending(), on the test's own thread, and
    each result is handed straight to its callback. A callback that raises is
    re-raised once the queue has drained: in the application wx.CallAfter
    only schedules the callback, so its exception surfaces later in the event
    loop rather than inside the worker, and a test must see it the same way.
    Pacing is simulated on a FakeClock, so no test waits on a real sleep.
    """

    def __init__(self, logger):
        self.errors = []
        self.clock = FakeClock()
        super().__init__(
            logger,
            dispatch=self._dispatch_inline,
            start_thread=False,
            clock=self.clock,
            sleep=self.clock.advance,
        )

    def _dispatch_inline(self, fn, *args):
        try:
            fn(*args)
        except Exception as exc:
            self.errors.append(exc)
            raise

    def run_pending(self):
        super().run_pending()
        if self.errors:
            error = self.errors[0]
            self.errors.clear()
            raise error


def inline_worker(logger):
    """A NetworkWorker with no thread: submit, run_pending(), assert."""
    return InlineWorker(logger)


class FakeConnectionManager:
    """Stands in for ConnectionManager, recording frames instead of transmitting.

    ConnectionManager is the network boundary and is injected into CpdlcSession,
    so this is the intended seam rather than a mock of code under test.

    Args:
        connected: What is_connected() reports
        raise_with: An exception every send raises instead of recording, for
            exercising the failure paths
        connect_error: An exception connect() raises instead of connecting
    """

    def __init__(self, connected=True, raise_with=None, connect_error=None):
        self._connected = connected
        self.raise_with = raise_with
        self.connect_error = connect_error
        self.sent = []
        self.telexes = []
        self.info_requests = []
        self.poll_results = []
        self.disconnected = False
        self.connected_as = None

    def is_connected(self):
        return self._connected

    def connect(self, callsign, logon_code, network_type):
        if self.connect_error is not None:
            raise self.connect_error
        self._connected = True
        self.connected_as = (callsign, network_type)

    def disconnect(self):
        self._connected = False
        self.disconnected = True

    def send_cpdlc(self, recipient, min_value, response_type, message, mrn=None):
        if not self._connected:
            raise HoppieError("Not connected")
        if self.raise_with is not None:
            raise self.raise_with
        self.sent.append((recipient, min_value, response_type, message, mrn))

    def send_telex(self, recipient, message):
        if not self._connected:
            raise HoppieError("Not connected")
        if self.raise_with is not None:
            raise self.raise_with
        self.telexes.append((recipient, message))

    def send_info_request(self, info_type, icao):
        if not self._connected:
            raise HoppieError("Not connected")
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
        tune_results: Answers for successive set_com1_standby_mhz() calls,
            consumed in order; `result` once they run out
    """

    def __init__(self, result=True, tune_results=None):
        self.result = result
        self.tune_results = list(tune_results or [])
        self.tuned = []
        self.connects = 0
        self.disconnects = 0
        self.connected = False

    def connect(self):
        self.connects += 1
        self.connected = self.result
        return self.result

    def is_connected(self):
        return self.connected

    def disconnect(self):
        self.disconnects += 1
        self.connected = False

    def set_com1_standby_mhz(self, frequency_mhz):
        self.tuned.append(frequency_mhz)
        if self.tune_results:
            return self.tune_results.pop(0)
        return self.result


class FakeWeatherMonitor:
    """Records the lifecycle calls and subscriptions the window makes on the weather monitor."""

    def __init__(self):
        self.stopped = False
        self.cleared = False
        self.started = False
        self.shut_down = False
        self.subscriptions = {}

    def start(self, parent_window):
        self.started = True

    def stop(self):
        self.stopped = True

    def clear(self):
        self.cleared = True
        self.subscriptions.clear()

    def shutdown(self):
        self.shut_down = True

    def subscribe(self, icao, info_type, initial_text=None):
        self.subscriptions[(icao.upper(), info_type)] = initial_text

    def unsubscribe(self, icao, info_type):
        return self.subscriptions.pop((icao.upper(), info_type), None) is not None

    def is_subscribed(self, icao, info_type):
        return (icao.upper(), info_type) in self.subscriptions

    def count(self):
        return len(self.subscriptions)


class FakeMenuItem:
    """Records the label, help text and enabled state the window sets on a menu item."""

    def __init__(self, label="&Disconnect"):
        self.label = label
        self.help = ""
        self.enabled = True

    def SetItemLabel(self, label):
        self.label = label

    def SetHelp(self, text):
        self.help = text

    def Enable(self, enable=True):
        self.enabled = enable

    def IsEnabled(self):
        return self.enabled


class FakeSound:
    """Counts the notification chimes instead of playing them."""

    def __init__(self):
        self.played = 0

    def Play(self, flags=0):
        self.played += 1
        return True


class FakeCloseEvent:
    """Stands in for the wx.CloseEvent on_close receives.

    Args:
        can_veto: What CanVeto() reports; False for a forced close (Windows
            ending the session), which cannot be cancelled
    """

    def __init__(self, can_veto=True):
        self.skipped = False
        self.vetoed = False
        self.can_veto = can_veto

    def Skip(self):
        self.skipped = True

    def Veto(self):
        self.vetoed = True

    def CanVeto(self):
        return self.can_veto


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

    The window's deferred callbacks run synchronously, since there is no event
    loop; a queued send runs when the test calls window.worker.run_pending().
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
    window.worker = cpdlc_session.worker
    window.polling_controller = FakePollingController()
    window.weather_monitor = FakeWeatherMonitor()
    window.menu_item_connect = FakeMenuItem()
    window.simconnect_manager = (
        simconnect if simconnect is not None else FakeSimConnectManager()
    )
    window.new_message_sound = FakeSound()
    # wx.CallAfter needs a running wx.App; run deferred callbacks at once.
    window._defer = lambda callback, *args, **kwargs: callback(*args, **kwargs)
    window._responses_in_flight = {}
    window._link_busy = False
    window._callsign_clash_announced = False
    window._modal_depth = 0
    window.pending_update = None
    window._auto_tune_com1 = load_config().get("auto_tune_com1", True)
    window._simconnect_reconnecting = False
    window._pending_tune = None
    window.update_checker = UpdateChecker(logger, window.worker)
    window.status_texts = []
    # Instance attribute shadows wx.Frame.SetStatusText, which would need a
    # live C++ frame behind it.
    window.SetStatusText = window.status_texts.append
    return window
