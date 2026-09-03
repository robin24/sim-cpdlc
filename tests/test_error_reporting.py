"""The last-resort exception reporter: log first, one deferred dialog at a time.

A fault that repeats on every poll tick used to open a new modal dialog inside
the previous one, because the dialog was shown synchronously from the failing
handler and timers keep firing under a modal loop.
"""

import sys
import threading

import wx

from src.error_reporting import ExceptionReporter


def test_a_report_logs_and_defers_its_dialog(logger, wx_app, message_boxes):
    reporter = ExceptionReporter(logger)

    reporter.report(RuntimeError, RuntimeError("boom"), None, "main thread")

    assert message_boxes.calls == [], "the dialog must not open inside the failing handler"
    wx_app.ProcessPendingEvents()
    assert message_boxes.captions == ["Unexpected Error"]
    assert "RuntimeError: boom" in message_boxes.calls[0][0]


def test_a_report_while_the_dialog_is_open_only_logs(logger, wx_app, monkeypatch):
    reporter = ExceptionReporter(logger)
    shown = []

    def message_box(text, *args, **kwargs):
        shown.append(text)
        if len(shown) == 1:
            # A timer tick fails again under the open dialog.
            reporter._show_dialog("second")
        return wx.OK

    monkeypatch.setattr(wx, "MessageBox", message_box)

    reporter._show_dialog("first")

    assert shown == ["first"]
    assert reporter._dialog_open is False


def test_a_report_with_no_application_running_is_logged_only(logger, message_boxes):
    """Background threads can outlive the wx.App; wx.CallAfter would raise."""
    assert wx.GetApp() is None
    reporter = ExceptionReporter(logger)

    reporter.report(RuntimeError, RuntimeError("late"), None, "background thread")

    assert message_boxes.calls == []


def test_install_routes_both_hooks_to_the_reporter(logger, monkeypatch):
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    reporter = ExceptionReporter(logger)

    reporter.install()

    assert sys.excepthook == reporter.handle_uncaught
    assert threading.excepthook == reporter.handle_thread
