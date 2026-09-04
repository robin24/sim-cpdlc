"""The update check: the checker reports an outcome off the GUI thread, and
the window's prompt waits for open dialogs and never closes the app (audit M-5)."""

import webbrowser

import requests
import wx

from src.config import APP_VERSION
from src.model.cpdlc_session import CpdlcSession
from src.model.message_manager import MessageManager
from src.utils.update_checker import UpdateChecker, UpdateOutcome
from tests.support import FakeClock, FakeConnectionManager, inline_worker, make_main_window


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


def check(logger, monkeypatch, payload=None, error=None):
    """Run one check against a faked GitHub and return its outcome."""

    def get(url, timeout=None):
        if error is not None:
            raise error
        return FakeResponse(payload)

    monkeypatch.setattr(requests, "get", get)
    worker = inline_worker(logger)
    outcomes = []
    UpdateChecker(logger, worker).check(outcomes.append)
    assert outcomes == [], "the lookup must not run on the calling thread"
    worker.run_pending()
    return outcomes[0]


# --- the checker --------------------------------------------------------------


def test_a_newer_release_is_reported(logger, monkeypatch):
    outcome = check(
        logger, monkeypatch, {"tag_name": "v99.0.0", "html_url": "https://example.invalid/release"}
    )

    assert (outcome.latest, outcome.url, outcome.newer, outcome.error) == (
        "99.0.0",
        "https://example.invalid/release",
        True,
        None,
    )


def test_the_running_version_is_not_newer_than_itself(logger, monkeypatch):
    outcome = check(logger, monkeypatch, {"tag_name": f"v{APP_VERSION}", "html_url": "u"})

    assert (outcome.latest, outcome.newer) == (APP_VERSION, False)


def test_a_failed_lookup_is_reported_not_raised(logger, monkeypatch):
    outcome = check(logger, monkeypatch, error=requests.ConnectionError("offline"))

    assert (outcome.latest, outcome.newer) == (None, False)
    assert "offline" in outcome.error


# --- the window's prompt ------------------------------------------------------


def build(logger):
    session = CpdlcSession(
        logger, FakeConnectionManager(), clock=FakeClock(), worker=inline_worker(logger)
    )
    return make_main_window(logger, session, MessageManager(logger))


NEWER = UpdateOutcome(latest="99.0.0", url="https://example.invalid/release", newer=True)


def test_the_update_prompt_waits_for_an_open_dialog(logger, message_boxes):
    """It used to pop over whatever was open and could close the app from
    under it; now it waits until no dialog is open."""
    window = build(logger)
    window._modal_depth = 1
    # Declining the prompt keeps this test on the deferral; the release page
    # is what the next test is about.
    message_boxes.answer = wx.NO

    window._on_auto_update_check(NEWER)

    assert message_boxes.calls == []
    assert window.pending_update is NEWER

    window._modal_depth = 0
    window._flush_deferred()

    assert message_boxes.captions == ["Update Available"]
    assert "Open the release page in your browser?" in message_boxes.calls[0][0]
    assert window.pending_update is None


def test_saying_yes_opens_the_release_page_and_nothing_else(logger, message_boxes, monkeypatch):
    opened = []
    monkeypatch.setattr(webbrowser, "open", opened.append)
    window = build(logger)
    message_boxes.answer = wx.YES

    window._on_manual_update_check(NEWER)

    assert opened == ["https://example.invalid/release"]
    assert message_boxes.captions == ["Update Available"]
    assert window.status_texts[-1] == "Version 99.0.0 is available."


def test_a_manual_check_reports_when_there_is_nothing_new(logger, message_boxes):
    window = build(logger)

    window._on_manual_update_check(UpdateOutcome(latest=APP_VERSION, url="u", newer=False))

    assert message_boxes.captions == ["No Updates Available"]
    assert window.status_texts[-1] == f"You are running the latest version ({APP_VERSION})."


def test_a_manual_check_reports_a_failed_lookup(logger, message_boxes):
    window = build(logger)

    window._on_manual_update_check(UpdateOutcome(error="offline"))

    assert message_boxes.captions == ["Update Check Failed"]
    assert window.status_texts[-1] == "Update check failed."


def test_a_manual_check_resolves_the_checking_status_line(logger):
    """The status bar is what a screen-reader user queries; "Checking for
    updates..." must not outlive the check."""
    window = build(logger)
    window.on_check_updates(None)
    assert window.status_texts[-1] == "Checking for updates..."

    window.worker.run_pending()

    assert window.status_texts[-1] != "Checking for updates..."


def test_an_automatic_check_stays_silent_when_there_is_nothing_new(logger, message_boxes):
    window = build(logger)

    window._on_auto_update_check(UpdateOutcome(latest=APP_VERSION, newer=False))

    assert message_boxes.calls == []


def test_a_message_box_counts_as_an_open_dialog_while_it_shows(logger, monkeypatch):
    window = build(logger)
    depths = []

    def recording(message, caption="Message", style=wx.OK, *args, **kwargs):
        depths.append(window._modal_depth)
        return wx.OK

    monkeypatch.setattr(wx, "MessageBox", recording)

    window._message_box("Hello", "Test")

    assert depths == [1]
    assert window._modal_depth == 0
