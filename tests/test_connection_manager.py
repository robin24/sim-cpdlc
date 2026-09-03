"""Tests for the hoppie_connector boundary in ConnectionManager.

These cover the failure modes that used to leave a request silently doing
nothing: the library raises a mix of builtin ConnectionError, requests
exceptions and bare ValueError/TypeError, and only HoppieError is caught
anywhere above this layer.

The HTTP layer is the seam. Faking requests.get/post rather than the connector
itself keeps the library's own validators and response parsers in the path, so
these tests fail if hoppie_connector changes what it raises.
"""

import logging

import pytest
import requests
from hoppie_connector import HoppieConnector, HoppieError

from src.config import HOPPIE_API_URL, SAYINTENTIONS_API_URL
from src.model.connection_manager import (
    ConnectionManager,
    install_request_timeout,
    redact,
)

LOGON = "SUPERSECRET123"


class FakeResponse:
    """Enough of requests.Response for both hoppie_connector and our own GETs."""

    def __init__(self, body="ok", status_code=200):
        self.status_code = status_code
        self.reason = "Bad Gateway" if status_code >= 400 else "OK"
        self.text = body
        self.content = body.encode("ascii", "replace")
        self.elapsed = 0.1

    @property
    def ok(self):
        return self.status_code < 400

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError(f"{self.status_code} Server Error")


def responder(body="ok", status_code=200, raises=None):
    """Build a stand-in for requests.get/post."""

    def _request(url, **kwargs):
        if raises is not None:
            raise raises
        return FakeResponse(body, status_code)

    return _request


def serving(monkeypatch, *args, **kwargs):
    """Point both requests.get and requests.post at one fake responder."""
    handler = responder(*args, **kwargs)
    monkeypatch.setattr(requests, "get", handler)
    monkeypatch.setattr(requests, "post", handler)


@pytest.fixture
def manager(logger):
    return ConnectionManager(logger)


def connected(logger, monkeypatch, callsign="DLH123"):
    """A manager that has completed a successful connect()."""
    serving(monkeypatch, "ok")
    cm = ConnectionManager(logger)
    cm.connect(callsign, LOGON, "hoppie")
    return cm


# --- the silent-failure class -------------------------------------------------


@pytest.mark.parametrize(
    "recipient, message, expected",
    [
        ("EDDF", "WIND 270°/25KT", "non-ASCII"),
        ("EDDF", "A" * 221, "too long"),
        ("EDDF ", "HELLO", "Invalid TO station name"),
    ],
    ids=["non-ascii-body", "over-220-chars", "recipient-with-trailing-space"],
)
def test_message_validation_failures_surface_as_hoppie_error(
    logger, monkeypatch, recipient, message, expected
):
    """hoppie_connector raises bare ValueError for these, and nothing above
    this layer catches ValueError. Before they were converted, a telex with a
    degree sign in it did nothing at all: no message, no dialog, no log line."""
    cm = connected(logger, monkeypatch)

    with pytest.raises(HoppieError):
        cm.send_telex(recipient, message)


def test_a_bad_http_status_surfaces_as_hoppie_error(logger, monkeypatch):
    """hoppie_connector raises the builtin ConnectionError for a non-OK status."""
    cm = connected(logger, monkeypatch)
    serving(monkeypatch, "", status_code=502)

    with pytest.raises(HoppieError):
        cm.send_telex("EDDF", "HELLO")


def test_an_unparseable_body_surfaces_as_hoppie_error(logger, monkeypatch):
    """A captive portal answers 200 with HTML, so response.ok is True and the
    library's parser raises ValueError instead."""
    cm = connected(logger, monkeypatch)
    serving(monkeypatch, "<html>Login required</html>")

    with pytest.raises(HoppieError):
        cm.send_telex("EDDF", "HELLO")


def test_a_local_os_error_is_not_disguised_as_a_network_failure(logger, monkeypatch):
    """A CA bundle missing from a packaged build raises OSError from inside
    requests. Converting it would send the client into a reconnect loop against
    a problem retrying cannot fix, so it must stay a programming error."""
    cm = connected(logger, monkeypatch)
    serving(monkeypatch, raises=FileNotFoundError(2, "No such file", "cacert.pem"))

    with pytest.raises(FileNotFoundError):
        cm.send_telex("EDDF", "HELLO")

    assert cm.send_failures == 0


# --- credential handling ------------------------------------------------------


def test_redact_removes_the_logon_code():
    text = f"url: /acars/system/connect.html?logon={LOGON}&from=DLH123&type=poll"

    scrubbed = redact(text)

    assert LOGON not in scrubbed
    assert "<redacted>" in scrubbed
    assert "from=DLH123" in scrubbed


def test_the_logon_code_never_reaches_the_error_text(logger, monkeypatch):
    """requests embeds the full request URL in its exception messages, and that
    URL carries the logon code. This error text is written to the log file and
    shown in a dialog."""
    serving(
        monkeypatch,
        raises=requests.exceptions.ConnectionError(
            "HTTPSConnectionPool(host='www.hoppie.nl', port=443): Max retries "
            f"exceeded with url: /acars/system/connect.html?logon={LOGON}&type=poll"
        ),
    )
    cm = ConnectionManager(logger)

    with pytest.raises(HoppieError) as caught:
        cm.connect("DLH123", LOGON, "hoppie")

    assert LOGON not in str(caught.value)


def test_both_api_urls_use_https():
    """The logon code travels as a query parameter on every request."""
    assert HOPPIE_API_URL.startswith("https://")
    assert SAYINTENTIONS_API_URL.startswith("https://")


# --- connect and reconnect actually verify the link ---------------------------


def test_connect_succeeds_against_a_healthy_server(logger, monkeypatch):
    cm = connected(logger, monkeypatch)

    assert cm.is_connected()
    assert cm.callsign == "DLH123"


def test_connect_fails_when_the_server_is_down(logger, monkeypatch):
    """HoppieConnector's constructor performs no I/O, so without a real round
    trip connect() reported success against any server and any logon code."""
    serving(monkeypatch, "", status_code=502)
    cm = ConnectionManager(logger)

    with pytest.raises(HoppieError):
        cm.connect("DLH123", LOGON, "hoppie")

    assert cm.is_connected() is False


def test_connect_rejects_a_callsign_the_library_cannot_send_with(logger, monkeypatch):
    """A hyphenated registration fails the library's ^[A-Z0-9]{3,8}$ check. It
    used to connect cleanly and then fail silently on every subsequent send."""
    serving(monkeypatch, "ok")
    cm = ConnectionManager(logger)

    with pytest.raises(HoppieError):
        cm.connect("D-AIBL", LOGON, "hoppie")

    assert cm.is_connected() is False


def test_reconnection_reports_failure_when_the_server_is_still_down(
    logger, monkeypatch
):
    """Rebuilding the connector alone always 'succeeded', so a dead link
    produced an endless cycle of false 'Reconnection successful' log lines."""
    cm = connected(logger, monkeypatch)
    serving(monkeypatch, "", status_code=502)

    assert cm.attempt_reconnection() is False
    assert cm.is_connected() is False


def test_reconnection_succeeds_once_the_server_recovers(logger, monkeypatch):
    cm = connected(logger, monkeypatch)
    cm.connection_failures = 3

    assert cm.attempt_reconnection() is True
    assert cm.connection_failures == 0


# --- failure counting drives reconnection -------------------------------------


def test_transport_failures_during_polling_reach_the_threshold(logger, monkeypatch):
    cm = connected(logger, monkeypatch)
    serving(monkeypatch, "", status_code=502)

    for _ in range(cm.max_connection_failures):
        cm.poll()

    assert cm.should_attempt_reconnection() is True


def test_an_unparseable_poll_response_also_counts(logger, monkeypatch):
    """This failure is not a transport error, so _call does not count it. If
    poll() did not count it either, the reconnection logic would never run and
    the client would poll a dead endpoint forever."""
    cm = connected(logger, monkeypatch)
    serving(monkeypatch, "<html>Login required</html>")

    for _ in range(cm.max_connection_failures):
        cm.poll()

    assert cm.should_attempt_reconnection() is True


def test_poll_reports_failure_without_raising(logger, monkeypatch):
    cm = connected(logger, monkeypatch)
    serving(monkeypatch, "", status_code=502)

    assert cm.poll() == (None, None)
    assert cm.poll_failed() is True


def test_a_successful_poll_clears_the_failure_state(logger, monkeypatch):
    cm = connected(logger, monkeypatch)
    serving(monkeypatch, "", status_code=502)
    cm.poll()

    serving(monkeypatch, "ok")
    cm.poll()

    assert cm.poll_failed() is False


def test_send_failures_survive_a_successful_poll(logger, monkeypatch):
    """Proxies routinely pass GETs and block POSTs. Polls kept resetting the
    shared counter, so a link that could not send anything never reconnected."""
    cm = connected(logger, monkeypatch)

    for _ in range(cm.max_connection_failures):
        monkeypatch.setattr(requests, "post", responder("", status_code=502))
        with pytest.raises(HoppieError):
            cm.send_telex("EDDF", "HELLO")
        monkeypatch.setattr(requests, "get", responder("ok"))
        cm.poll()

    assert cm.should_attempt_reconnection() is True


def test_a_rejected_message_is_not_counted_as_a_link_failure(logger, monkeypatch):
    """The server was reachable and answered; the message was simply invalid."""
    cm = connected(logger, monkeypatch)

    with pytest.raises(HoppieError):
        cm.send_telex("EDDF", "A" * 221)

    assert cm.send_failures == 0
    assert cm.should_attempt_reconnection() is False


# --- session state ------------------------------------------------------------


def test_disconnect_clears_everything_connect_set(logger, monkeypatch):
    """Stale credentials let a later reconnection resurrect the previous
    session under the previous callsign, on the previous network."""
    cm = connected(logger, monkeypatch)
    cm.connection_failures = 3

    cm.disconnect()

    assert cm.callsign == ""
    assert cm.logon_code == ""
    assert cm.network_type is None
    assert cm.should_attempt_reconnection() is False


def test_no_reconnection_without_a_live_connection(logger):
    """should_attempt_reconnection() guarded on the credentials alone, which
    outlive a disconnect."""
    cm = ConnectionManager(logger)
    cm.callsign, cm.logon_code = "DLH123", LOGON
    cm.connection_failures = 99

    assert cm.should_attempt_reconnection() is False


def test_api_url_follows_the_selected_network(logger):
    cm = ConnectionManager(logger)

    assert cm._api_url("hoppie") == HOPPIE_API_URL
    assert cm._api_url("sayintentions") == SAYINTENTIONS_API_URL


# --- information requests -----------------------------------------------------


@pytest.mark.parametrize("kind", ["metar", "vatatis"])
def test_an_information_request_unwraps_the_server_envelope(
    logger, monkeypatch, kind
):
    cm = connected(logger, monkeypatch)
    serving(monkeypatch, "ok {server info {EDDF 121250Z 27010KT CAVOK}}")

    assert cm.send_info_request(kind, "EDDF") == "EDDF 121250Z 27010KT CAVOK"


@pytest.mark.parametrize("kind", ["metar", "vatatis"])
def test_an_information_request_reports_a_server_error(logger, monkeypatch, kind):
    cm = connected(logger, monkeypatch)
    serving(monkeypatch, "error {invalid logon}")

    with pytest.raises(HoppieError):
        cm.send_info_request(kind, "EDDF")


def test_an_information_request_sends_a_timeout(logger, monkeypatch):
    """These are the one place the app builds its own request, so the timeout
    is ours to pass."""
    seen = {}

    def _get(url, params=None, timeout=None):
        seen["timeout"] = timeout
        return FakeResponse("ok {server info {EDDF 121250Z}}")

    cm = connected(logger, monkeypatch)
    monkeypatch.setattr(requests, "get", _get)
    cm.send_info_request("metar", "EDDF")

    assert seen["timeout"] is not None


def test_an_information_request_requires_a_connection(logger):
    cm = ConnectionManager(logger)

    with pytest.raises(HoppieError):
        cm.send_info_request("metar", "EDDF")


def test_a_failing_weather_request_does_not_trip_reconnection(logger, monkeypatch):
    """Weather is auxiliary. Three timed-out fetches used to spend the whole
    CPDLC failure budget, so the next failed poll tore down a working link."""
    cm = connected(logger, monkeypatch)
    serving(monkeypatch, raises=requests.exceptions.Timeout("timed out"))

    for icao in ("EGLL", "EGKK", "EGSS"):
        with pytest.raises(HoppieError):
            cm.send_info_request("metar", icao)

    assert cm.info_failures == 3
    assert cm.failure_count() == 0
    assert cm.poll_failed() is False
    assert cm.should_attempt_reconnection() is False


def test_a_weather_request_that_recovers_clears_its_own_count(logger, monkeypatch):
    cm = connected(logger, monkeypatch)
    serving(monkeypatch, raises=requests.exceptions.Timeout("timed out"))
    with pytest.raises(HoppieError):
        cm.send_info_request("metar", "EGLL")

    serving(monkeypatch, "ok {server info {EGLL 261150Z 24010KT}}")
    cm.send_info_request("metar", "EGLL")

    assert cm.info_failures == 0


# --- request timeout ----------------------------------------------------------


def test_install_request_timeout_supplies_a_default(monkeypatch):
    """hoppie_connector passes no timeout and offers no hook to supply one, so
    a server that accepts the connection and goes silent blocked forever.
    socket.setdefaulttimeout() does not help: requests explicitly calls
    sock.settimeout(None) when given no timeout."""
    seen = {}

    def _request(url, **kwargs):
        seen.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(requests, "get", _request)
    monkeypatch.setattr(requests, "post", _request)
    install_request_timeout(7)

    requests.get("https://example.invalid/")
    assert seen["timeout"] == 7

    seen.clear()
    requests.post("https://example.invalid/")
    assert seen["timeout"] == 7


def test_an_explicit_timeout_still_wins(monkeypatch):
    seen = {}

    def _request(url, **kwargs):
        seen.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(requests, "get", _request)
    monkeypatch.setattr(requests, "post", _request)
    install_request_timeout(7)

    requests.get("https://example.invalid/", timeout=1)

    assert seen["timeout"] == 1
