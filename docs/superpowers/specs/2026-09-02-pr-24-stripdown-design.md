# PR #24 stripdown — design

**Date:** 2026-09-02
**Branch:** `claude/pr-24-stripdown`, cut from the head of PR #24
(`feature/auto-weather-and-cpdlc-requests`, commit `121b972`).

## Purpose

PR #24 arrived as three things at once: automatic weather updates, a set of new
FANS-1/A downlink requests, and some conformance fixes. Neither Hoppie's ACARS
nor SayIntentions simulates the new request types, so they would sit in the
menus doing nothing. The contributor and the maintainer agreed to remove them.

This branch keeps the automatic weather updates and the conformance fixes,
removes everything else, and repairs the bugs a review found in the code that
remains.

## Scope

### Removed

**IVAO and PilotEdge weather reports.** Sim-CPDLC supports neither network, so
`ivaoatis` and `peatis` cannot be answered. They go from `REPORT_TYPES`,
`ATIS_TYPES` and `REPORT_ORDER`, leaving METAR, TAF, short TAF and ATIS.
`ConnectionManager.send_atis_request` loses the `source` parameter that existed
only to select between them; no caller ever passed it.

**The new request types.** Heading (DM70), confirm assigned level/speed, and the
emergency messages (MAYDAY/PAN PAN, fuel and souls, diversion, cancel). None is
simulated on either supported network.

Deleted outright:

- `src/gui/dialogs/heading_request_dialog.py`
- `src/gui/dialogs/confirm_request_dialog.py`
- `src/gui/dialogs/emergency_dialog.py`
- `CpdlcSession.send_heading_request`, `send_query`, `send_emergency`,
  `send_cancel_emergency`, and the `_send_to_station` helper only they used
- `MainWindow.on_heading_request`, `on_confirm_request`, `on_declare_emergency`,
  `on_cancel_emergency`, and the `_require_station` / `_handle_request_result`
  helpers that become unreachable with them

`MainWindow._require_connection` stays: `on_weather_request` uses it.

**The reworked menu structure.** With the reduced scope a single `Requests` menu
is enough, so the `Weather` and `Emergency` menus go and their surviving items
move back. The `CTRL+P` accelerator the PR added to `PDC` goes too — it was part
of the rework, not of the weather feature.

The `Requests` menu returns to `main`'s order, with the old `ATIS` entry
replaced by the two items it grew into:

    PDC · Logon · Logoff · Altitude change · Direct to · Speed change ·
    When can we expect · Telex message ·
    Weather request (CTRL+I) · Automatic weather updates (CTRL+SHIFT+I)

### Kept

- Automatic weather updates in full: `WeatherMonitor`, `weather_parsing`,
  `WeatherDialog`, `WeatherSubscriptionsDialog`, the `WeatherReport` message
  record, and the message-list context menu that starts and stops a watch.
- METAR, TAF, short TAF and ATIS requests.
- The conformance fixes: `cpdlc_elements.py` and the full
  `DUE TO AIRCRAFT PERFORMANCE` wording; the randomised 45–75 s idle poll band;
  rescheduling after a failed poll; `set_active_polling()` no longer no-opping
  when the timer does not exist yet.

### Fixed

Six defects in the surviving code, from the review of PR #24.

| # | Defect | Fix |
|---|--------|-----|
| 1 | An exception anywhere in `on_poll_timer` after the `poll()` call skips the trailing `_schedule_next()`, so polling stops for the session while the status bar still reads "Connected". | Wrap the handler body in `try/finally` so `_schedule_next()` always runs. |
| 2 | `set_active_polling()` re-arms the one-shot timer on every call, so activity faster than the 20 s active interval starves polling entirely, and a single send can push a nearly-due poll out to a fresh 20 s. | Track the pending poll's deadline and re-arm only when it is further off than the active interval. |
| 3 | `extract_atis_letter` returns the first single letter after any marker, and the ICAO is a marker, so a D-ATIS designator (`KSFO D ATIS INFO Q`) is read as the information letter and real changes never announce. | Drop the ICAO from the marker set, leaving `INFORMATION`/`INFO`/`ATIS`. |
| 4 | `WeatherReport` is the only message type that bypasses the `@`-separator formatters, so an ATIS reaches the list and the detail pane with literal `@` characters, which NVDA reads as "at". | Add weather-specific formatters to `weather_parsing.py` and use them in `MessageManager`. |
| 5 | `WeatherDialog._sync_auto_update_checkbox` force-writes the tick box on every keystroke and report-type change, silently discarding the user's choice in both directions. | Latch that the user has touched the box and stop re-syncing once they have. |
| 6 | Weather fetches run through `_call` with `is_send=False`, so a failing inforeq increments `connection_failures` — the counter that decides the CPDLC link is dead — from a worker thread. | Give `_call` a counter selector and route inforeq failures into their own `info_failures`, outside `failure_count()`. |

**Fix 2 needs a deadline, not a flag.** `wx.Timer` cannot report how much of a
one-shot interval remains, so `_schedule_next()` records
`time.monotonic() + interval / 1000` as `_next_poll_at`, and
`set_active_polling()` re-arms only when that deadline is more than
`active_poll_interval` away. Both failure modes then disappear: repeated calls
during a busy exchange leave a pending poll alone, and an idle poll 60 s off is
still pulled forward to 20 s. An edge-triggered fix would stop the starvation
but keep delaying a nearly-due poll on the first send, which is what the
existing comment on that block already says it should not do.

**Fix 3 is a one-line change to the marker set, not a rewrite.** Removing `icao`
from `markers` is on its own sufficient: `KSFO D ATIS INFO Q` then matches at
`INFO` and yields `Q`, and the existing `EGLL ATIS INFORMATION K` cases are
unaffected because they already match on a word marker. First-match is kept.
`extract_atis_letter` keeps its `icao` parameter so no call site changes, and
its docstring loses the "airports that announce as `EGLL K`" claim, which is
what the ICAO marker served. That form cannot be told apart from a D-ATIS
designator, so it is dropped rather than guessed at; such a report falls through
to the full-text signature, the existing behaviour whenever a letter cannot be
identified.

**Fix 4 does not reuse `format_message_text`.** That helper maps `@@` to the
literal string `N/A` and strips underscores, which are CPDLC packet artifacts;
applied to an ATIS it turns `TRL 60@@WIND` into `TRL 60N/AWIND`. Weather payloads
use `@` purely as a line separator. So `weather_parsing.py` — which already owns
that knowledge, in `normalize_report` — gains two small formatters:

- `format_report_text(text)` — `@` becomes a newline, for the detail pane
- `format_report_line(text)` — `@` becomes a space and whitespace collapses,
  for the list row

Keeping the two rule sets apart means a change to CPDLC packet formatting cannot
corrupt a weather report, and vice versa.

### Out of scope

Left open deliberately, all from the same review:

- When no information letter can be identified at all, `report_signature` falls
  back to the full normalised text, which still contains the observation time,
  so an unchanged ATIS in that form announces itself on every cycle. This is the
  opposite failure to fix 3 and shares its function, but it needs a decision
  about stripping time groups that is worth taking separately.
- `check_now()` reports success even when no cycle starts.
- The weather interval is read from config without clamping to
  `MIN_/MAX_WEATHER_INTERVAL_MINUTES`.
- The `frame` fixture in `tests/conftest.py` leaks every window it creates
  (45 live top-level windows at the end of a run).
- Seven pre-existing handlers still hand-roll the block `_require_connection`
  replaces. Migrating the four older `CpdlcSession` send methods onto a shared
  helper is the same finding one layer down; `_send_to_station` is deleted here
  rather than pressed into that service, because the migration touches working
  code outside this branch's scope.

## Testing

The suite must stay green and must lose only the tests for deleted behaviour.

- `tests/test_downlink_requests.py` — drop the heading, query and emergency
  cases; keep the weather case.
- `tests/test_dialogs.py` — drop the heading, confirm and emergency dialog
  cases; keep the weather dialog cases.
- `tests/test_main_window.py` — drop the removed handlers from `MENU_HANDLERS`
  and update the menu-structure assertions to the single `Requests` menu.
- `tests/test_weather_monitor.py` — unchanged, plus new cases for fixes 3 and 5.

New tests, one per fix, each failing before its change:

1. A poll whose message callback raises still schedules the next poll.
2. Repeated `set_active_polling()` calls leave an already-pending active poll
   alone, and an idle poll further off than the active interval is still pulled
   forward to it.
3. `extract_atis_letter("KSFO D ATIS INFO Q", "KSFO")` returns `Q`, so a D-ATIS
   whose letter advances to `R` announces the change.
4. A report containing `@` and `@@` renders with line breaks and no `@`.
5. Ticking the box and then editing the ICAO preserves the tick; unticking it
   and then editing preserves the untick.
6. A failed inforeq does not change `failure_count()` or
   `should_attempt_reconnection()`.

## Delivery

Commits are ordered removal first, then fixes, so the stripdown can be read
without the repairs mixed in. The branch is left local; whether it is pushed,
opened as a PR against `main`, or offered to the contributor for
`feature/auto-weather-and-cpdlc-requests` is the maintainer's call.
