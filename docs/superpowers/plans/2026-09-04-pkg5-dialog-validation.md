# Package 5: Dialog Validation and Feedback — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every dialog refuses input the network would reject, hands back exactly the text it validated, and the window's feedback (settings, weather subscriptions, list layout, message text, radio tuning, handovers) says what actually happened.

**Architecture:** The request dialogs share one ASCII validation helper (`src/gui/dialogs/validation.py`) and return stripped, zero-padded values; the Telex dialog counts characters; the settings, connect and PDC getters strip; `on_settings` applies runtime changes only after the file was written; `resource_path` becomes a module-level function anchored on the source tree; `message_formatting` treats `@@` as one separator and collapses spaces; `MessageView` fits its columns; `WeatherMonitor` gains change listeners that the subscriptions dialog uses to stay current, and the window announces every stop the same way; the frequency parser accepts a bare frequency and the HANDOVER pattern tolerates `@` and trailing text.

**Tech Stack:** Python 3.12+, wxPython 4.2.5, hoppie-connector 0.2.1, `re` from the standard library, pytest 9.1.1 with pytest-timeout.

## Global Constraints

- Run every command with `C:\Claude\sim-cpdlc\.claude\worktrees\review-25-ceb148\.venv\Scripts\python.exe` (below `$PY`; in Git Bash `PY=/c/Claude/sim-cpdlc/.claude/worktrees/review-25-ceb148/.venv/Scripts/python.exe`). Run the suite from the worktree root as `$PY -m pytest -q -p no:cacheprovider`. Baseline before this plan: 390 passed. The suite must be green at the end of every task.
- Work on branch `claude/pkg5-dialogs`, cut from `main` at `ceda363`, in the worktree `C:\Claude\sim-cpdlc\.claude\worktrees\pkg5-dialogs`. Never touch `C:\Claude\sim-cpdlc` itself.
- Test-driven: every task writes its failing tests first, runs them to see them fail for the expected reason, then implements. Tests must never reach the network, the real config file, SimBrief, the simulator or a modal dialog (the autouse fixtures in `tests/conftest.py` enforce this; keep using `tests.support` doubles). Dialogs are built on the `frame` fixture and destroyed through the `dialog` fixture.
- Files this package may change: `src/gui/dialogs/validation.py` (new), `src/gui/dialogs/logon_dialog.py`, `src/gui/dialogs/altitude_change_dialog.py`, `src/gui/dialogs/direct_request_dialog.py`, `src/gui/dialogs/speed_request_dialog.py`, `src/gui/dialogs/when_can_we_dialog.py`, `src/gui/dialogs/telex_dialog.py`, `src/gui/dialogs/settings_dialog.py`, `src/gui/dialogs/connect_dialog.py`, `src/gui/dialogs/pdc_dialog.py`, `src/gui/dialogs/weather_subscriptions_dialog.py`, `src/gui/main_window.py`, `src/gui/message_view.py`, `src/model/weather_monitor.py`, `src/utils/message_formatting.py`, `src/utils/frequency_parser.py`, and anything under `tests/`. Nothing else under `src/` changes.
- Validation is ASCII-only: a rule matches when `text.isascii() and re.fullmatch(rule, text, re.ASCII)`. Rules (from the spec): station `[A-Z0-9]{4}`; flight level `\d{2,3}`, zero-padded to three (`FL050`); Mach `\d{2,3}`, zero-padded to three (`082`); knots `\d{3}`; fix `[A-Z0-9]{2,7}`; telex recipient `[A-Z0-9]{3,8}`; telex message at most 220 characters, ASCII only. Every getter returns stripped text, upper-cased where it was upper-cased before.
- Exact user-facing strings: direct-to helper text `2-7 letters or digits, e.g. KONOL or 55N020W`; knots helper text `Enter speed in knots, 3 digits (e.g. 300)`; telex counter `"{n} / 220 characters"`, followed by `". Too long by {n-220}."` over the limit or `". Only plain ASCII text can be sent."` for non-ASCII text; settings confirmation `Settings saved. The weather interval applies now; logon codes apply to the next connection.` with caption `Settings Saved`; stop of automatic updates: SYSTEM row `Stopped automatic updates for {label} {icao}` and status text `Stopped watching {label} {icao}.` (unchanged wording, now from one helper).
- Exact patterns: frequency `(?:CONTACT|MONITOR)\s+(?:.+?\s+)?(?:ON\s+)?(\d{3}\.\d{1,3})(?:\s*MHZ)?` with `re.IGNORECASE | re.DOTALL`; HANDOVER `^HANDOVER\s+@?([A-Z]{4})\b`.
- Commit messages: imperative sentence subject, body, trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. Git prints CRLF warnings on this machine; they are harmless. Write files with LF endings.
- Spec: `docs/superpowers/specs/2026-09-03-audit-fixes-design.md`, section "Package 5: dialog validation and feedback". Audit: `docs/audit/2026-09-03-codebase-audit.md` (M-8, L-7, L-10, L-11, L-12, L-16, L-17).

## Deviations from the spec (decided while planning; the spec's "Package 5" section is otherwise followed)

1. **`resource_path` anchors on the source tree, not on `sys.argv[0]`.** The spec suggested `os.path.dirname(os.path.abspath(sys.argv[0]))`; under pytest and `python -m` launches `sys.argv[0]` is not `app.py`, so every window the suite builds would lose its sound. The base is the directory two levels above `src/gui/main_window.py` (the one holding `app.py`, `src/` and `assets/`), and `sys._MEIPASS` in a frozen build.
2. **The Telex recipient is validated as a station name** (`[A-Z0-9]{3,8}`, hoppie_connector's rule) before OK enables. The spec only asked for stripping; the audit's M-8 example ("EDDF " rejected at send time as "Invalid TO station name") is exactly this field.
3. **The HANDOVER pattern ends in a word boundary**: `^HANDOVER\s+@?([A-Z]{4})\b` instead of `^HANDOVER\s+@?([A-Z]{4})@?`. Trailing text is still allowed, but `HANDOVER EDGGX` is no longer read as a handover to EDGG.
4. **"Stop all" in the subscriptions dialog hands each report to `on_stop` in list order** (one SYSTEM row per report) instead of calling `WeatherMonitor.clear()`, so all stop paths say the same thing.
5. **The Telex counter carries a reason when the text disables OK.** A disabled button explains nothing to a screen-reader user; the suffixes are fixed in Global Constraints.

## Design notes

- **`src/gui/dialogs/validation.py`** holds the rules and two helpers: `matches(rule, text) -> bool` and `pad_three(text) -> str` (`str.zfill(3)`). Dialogs read their field through a private accessor that strips (and upper-cases where the value is upper-cased), validate that value in `on_text_change`, and return the same value from the getter, so what was validated is what is sent.
- **Change listeners on `WeatherMonitor`.** `subscribe_to_changes(callback) -> stop_listening` registers a zero-argument callable and returns a callable that removes it (idempotent). `_notify_changed()` runs after: a new subscription; a removal by `unsubscribe`, `clear`, or the drop after `MAX_CONSECUTIVE_ERRORS`; and a successful check (`last_update` changed, whether or not the report text changed). Failed checks short of the limit notify nothing. A listener that raises is logged with `logger.exception` and removed, so a dialog wx has already destroyed cannot break the update cycle.
- **Column fitting.** `MessageView._fit_columns()` sets the Sender column to the wider of `LIST_AUTOSIZE` (widest row) and `LIST_AUTOSIZE_USEHEADER` (header text), then gives the Message column the client width that is left, never less than `MIN_MESSAGE_COLUMN_WIDTH = 200`. It runs after every `add_message`, after `clear`, once at construction and on the list's `EVT_SIZE`.
- **`_stop_weather_updates(icao, info_type)`** on the window unsubscribes and produces the SYSTEM row and status text. The context-menu toggle's stop branch and the subscriptions dialog both call it. The weather request dialog's uncheck path in `on_weather_request` is left as it is: its status text is immediately replaced by "Requesting ...".

---

### Task 1: Request dialogs validate ASCII input and return stripped, padded values

**Files:**
- Create: `src/gui/dialogs/validation.py`
- Modify: `src/gui/dialogs/logon_dialog.py`, `src/gui/dialogs/altitude_change_dialog.py`, `src/gui/dialogs/direct_request_dialog.py`, `src/gui/dialogs/speed_request_dialog.py`, `src/gui/dialogs/when_can_we_dialog.py`, `src/gui/main_window.py:513-521` (the duplicate length check in `on_logon`), `tests/conftest.py` (the `dialog` fixture moves here), `tests/test_dialogs.py:13-25` (fixture removed), `tests/README.md`
- Test: `tests/test_request_dialogs.py` (new)

**Interfaces:**
- Consumes: nothing new.
- Produces: `src.gui.dialogs.validation` with `STATION`, `FLIGHT_LEVEL`, `MACH`, `KNOTS`, `FIX` (regex strings), `matches(rule, text) -> bool`, `pad_three(text) -> str`. `DirectRequestDialog.helper_text` and `SpeedRequestDialog.helper_text` are attributes. The `dialog` fixture lives in `tests/conftest.py` and is used by Tasks 2, 3 and 6. `WhenCanWeDialog.MESSAGE_TYPES` becomes a list of `(label, rule_or_None)`.

- [ ] **Step 1: Move the `dialog` fixture to `tests/conftest.py`**

Cut lines 13-25 of `tests/test_dialogs.py` (the `@pytest.fixture def dialog(frame): ...` block) and append this to `tests/conftest.py` after the `frame` fixture:

```python
@pytest.fixture
def dialog(frame):
    """Builds a dialog on the shared frame and destroys it, whatever the test does to it.

    Usage: ``instance = dialog(SomeDialog, *constructor_args)``.
    """
    built = []

    def build(factory, *args, **kwargs):
        instance = factory(frame, *args, **kwargs)
        built.append(instance)
        return instance

    yield build
    for instance in built:
        instance.Destroy()
```

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_dialogs.py`
Expected: all pass (the fixture is found through conftest).

- [ ] **Step 2: Write the failing tests**

Create `tests/test_request_dialogs.py`:

```python
"""What each request dialog lets through its OK button, and what it hands back.

hoppie_connector validates at send time with messages the pilot cannot act on
("invalid characters", "Invalid TO station name"), so the OK button has to be
the gate, and the getter has to return exactly the text that was validated:
stripped, upper-cased and zero-padded.
"""

import pytest
import wx

from src.gui.dialogs import (
    AltitudeChangeDialog,
    DirectRequestDialog,
    LogonDialog,
    SpeedRequestDialog,
    WhenCanWeDialog,
)
from src.model.cpdlc_elements import REASON_WEATHER

# Passes str.isdigit() and int(), but is not ASCII and the network rejects it.
ARABIC_INDIC_350 = "\u0663\u0665\u0660"
ARABIC_INDIC_82 = "\u0668\u0662"


def select(radio):
    """Pick a radio button the way a user does, so the bound handler runs."""
    radio.SetValue(True)
    event = wx.CommandEvent(wx.EVT_RADIOBUTTON.typeId, radio.GetId())
    event.SetEventObject(radio)
    radio.GetEventHandler().ProcessEvent(event)


# --- logon --------------------------------------------------------------------


@pytest.mark.parametrize(
    "typed, enabled",
    [
        ("EDDF", True),
        ("eddf", True),
        (" EDDF ", True),
        ("KZ7X", True),
        ("EDD", False),
        ("EDDFX", False),
        ("ED F", False),
        ("ED-F", False),
        ("\u00c9DDF", False),
        ("", False),
    ],
)
def test_logon_accepts_exactly_four_letters_or_digits(dialog, typed, enabled):
    logon = dialog(LogonDialog)

    logon.station_text.SetValue(typed)

    assert logon.ok_button.IsEnabled() is enabled


def test_logon_returns_the_station_stripped_and_upper_cased(dialog):
    """"EDDF " passed the old length check and failed at send time."""
    logon = dialog(LogonDialog)

    logon.station_text.SetValue(" eddf ")

    assert logon.get_logon_details() == "EDDF"


# --- altitude -----------------------------------------------------------------


@pytest.mark.parametrize(
    "typed, enabled",
    [
        ("350", True),
        ("50", True),
        (" 350 ", True),
        ("5", False),
        ("3500", False),
        ("+350", False),
        ("3_50", False),
        ("35.0", False),
        (ARABIC_INDIC_350, False),
        ("", False),
    ],
)
def test_altitude_accepts_two_or_three_ascii_digits(dialog, typed, enabled):
    """int() took "3_50" and "+350", which went out as REQUEST FL3_50."""
    altitude = dialog(AltitudeChangeDialog)

    altitude.altitude_text.SetValue(typed)

    assert altitude.ok_button.IsEnabled() is enabled


def test_altitude_is_returned_as_a_padded_flight_level(dialog):
    altitude = dialog(AltitudeChangeDialog)

    altitude.altitude_text.SetValue(" 50 ")

    assert altitude.get_altitude_details() == ("FL050", None)


def test_altitude_carries_the_chosen_reason(dialog):
    altitude = dialog(AltitudeChangeDialog)
    altitude.altitude_text.SetValue("350")

    select(altitude.reason_weather)

    assert altitude.get_altitude_details() == ("FL350", REASON_WEATHER)


# --- direct to ----------------------------------------------------------------


@pytest.mark.parametrize(
    "typed, enabled",
    [
        ("KONOL", True),
        ("konol", True),
        (" KONOL ", True),
        ("55N020W", True),
        ("5530N", True),
        ("DF", True),
        ("K", False),
        ("ABCDEFGH", False),
        ("KON-OL", False),
        ("KON OL", False),
        ("\u00c5BCD", False),
        ("", False),
    ],
)
def test_direct_to_accepts_two_to_seven_letters_or_digits(dialog, typed, enabled):
    """Oceanic fixes such as 55N020W were refused by the letters-only rule."""
    direct = dialog(DirectRequestDialog)

    direct.fix_text.SetValue(typed)

    assert direct.ok_button.IsEnabled() is enabled


def test_direct_to_returns_the_fix_stripped_and_upper_cased(dialog):
    direct = dialog(DirectRequestDialog)

    direct.fix_text.SetValue(" 55n020w ")

    assert direct.get_direct_details() == ("55N020W", None)


def test_direct_to_helper_text_names_the_rule(dialog):
    direct = dialog(DirectRequestDialog)

    assert direct.helper_text.GetLabel() == "2-7 letters or digits, e.g. KONOL or 55N020W"


# --- speed --------------------------------------------------------------------


@pytest.mark.parametrize(
    "typed, enabled",
    [
        ("82", True),
        ("082", True),
        (" 82 ", True),
        ("8", False),
        ("0820", False),
        ("0.82", False),
        (ARABIC_INDIC_82, False),
        ("", False),
    ],
)
def test_mach_accepts_two_or_three_ascii_digits(dialog, typed, enabled):
    speed = dialog(SpeedRequestDialog)

    speed.speed_text.SetValue(typed)

    assert speed.ok_button.IsEnabled() is enabled


@pytest.mark.parametrize(
    "typed, enabled",
    [
        ("300", True),
        ("250", True),
        ("30", False),
        ("3000", False),
        ("+300", False),
        ("", False),
    ],
)
def test_knots_need_exactly_three_ascii_digits(dialog, typed, enabled):
    """The knots branch used to be a copy of the Mach branch, so M820 went out."""
    speed = dialog(SpeedRequestDialog)
    select(speed.radio_knots)

    speed.speed_text.SetValue(typed)

    assert speed.ok_button.IsEnabled() is enabled


def test_switching_the_speed_type_re_checks_the_value(dialog):
    speed = dialog(SpeedRequestDialog)
    speed.speed_text.SetValue("82")
    assert speed.ok_button.IsEnabled() is True

    select(speed.radio_knots)

    assert speed.ok_button.IsEnabled() is False
    assert speed.helper_text.GetLabel() == "Enter speed in knots, 3 digits (e.g. 300)"


def test_mach_is_returned_padded_to_three_digits(dialog):
    speed = dialog(SpeedRequestDialog)

    speed.speed_text.SetValue(" 82 ")

    assert speed.get_speed_details() == ("082", True, None)


def test_knots_are_returned_as_typed(dialog):
    speed = dialog(SpeedRequestDialog)
    select(speed.radio_knots)

    speed.speed_text.SetValue("300")

    assert speed.get_speed_details() == ("300", False, None)


# --- when can we expect -------------------------------------------------------


def test_a_request_without_a_value_is_ready_at_once(dialog):
    when = dialog(WhenCanWeDialog)

    assert when.ok_button.IsEnabled() is True
    assert when.value_text.IsShown() is False
    assert when.get_message_text() == "WHEN CAN WE EXPECT HIGHER LEVEL"


def test_choosing_a_type_with_a_value_shows_the_field_and_waits_for_it(dialog):
    when = dialog(WhenCanWeDialog)

    select(when.radios[3])

    assert when.value_text.IsShown() is True
    assert when.ok_button.IsEnabled() is False


@pytest.mark.parametrize(
    "index, typed, enabled, text",
    [
        (3, "50", True, "WHEN CAN WE EXPECT CLIMB TO FL050"),
        (3, " 350 ", True, "WHEN CAN WE EXPECT CLIMB TO FL350"),
        (3, "5", False, None),
        (3, "+350", False, None),
        (4, "100", True, "WHEN CAN WE EXPECT DESCENT TO FL100"),
        (4, ARABIC_INDIC_350, False, None),
        (5, "82", True, "WHEN CAN WE EXPECT M082"),
        (5, "0820", False, None),
        (6, "300", True, "WHEN CAN WE EXPECT 300K"),
        (6, "30", False, None),
    ],
)
def test_a_request_with_a_value_applies_the_rule_for_its_type(dialog, index, typed, enabled, text):
    when = dialog(WhenCanWeDialog)
    select(when.radios[index])

    when.value_text.SetValue(typed)

    assert when.ok_button.IsEnabled() is enabled
    if enabled:
        assert when.get_message_text() == text
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_request_dialogs.py`
Expected: failures such as `assert True is False` for `" EDDF "` / `"KZ7X"` / `"55N020W"` / `"30"` (knots), `AttributeError: 'DirectRequestDialog' object has no attribute 'helper_text'`, and `("FL50", None) != ("FL050", None)`.

- [ ] **Step 4: Create the validation helper**

Create `src/gui/dialogs/validation.py`:

```python
"""Input rules shared by the request dialogs.

Every rule is ASCII-only: str.isdigit() and a bare \\d accept digits from other
scripts, and int() accepts "3_50" and "+350", all of which hoppie_connector
rejects at send time with a message the pilot cannot act on. Matching here
makes the OK button the only gate, and the getters return the very text that
was matched.
"""

import re

# A CPDLC station: four letters or digits.
STATION = r"[A-Z0-9]{4}"
# A flight level typed without the FL prefix; two digits are zero-padded.
FLIGHT_LEVEL = r"\d{2,3}"
# A Mach number typed without the decimal point; two digits are zero-padded.
MACH = r"\d{2,3}"
# An indicated airspeed in knots.
KNOTS = r"\d{3}"
# A fix, waypoint or navaid, including lat/long forms such as 55N020W.
FIX = r"[A-Z0-9]{2,7}"


def matches(rule, text):
    """Return True when text is ASCII and matches the rule in full."""
    return text.isascii() and re.fullmatch(rule, text, re.ASCII) is not None


def pad_three(text):
    """Zero-pad a validated number to three digits (50 -> 050)."""
    return text.zfill(3)
```

- [ ] **Step 5: Rework `LogonDialog`**

In `src/gui/dialogs/logon_dialog.py` add `from src.gui.dialogs.validation import STATION, matches` after `import wx`, and replace `on_text_change` and `get_logon_details` with:

```python
    def _station(self):
        """The station as it would be sent: stripped and upper-cased."""
        return self.station_text.GetValue().strip().upper()

    def on_text_change(self, _):
        """Enable OK only for a station name the network accepts."""
        self.ok_button.Enable(matches(STATION, self._station()))

    def get_logon_details(self):
        """
        Get the logon details entered by the user.

        Returns:
            str: The station name, stripped and upper-cased
        """
        return self._station()
```

- [ ] **Step 6: Rework `AltitudeChangeDialog`**

In `src/gui/dialogs/altitude_change_dialog.py` add `from src.gui.dialogs.validation import FLIGHT_LEVEL, matches, pad_three` below the `cpdlc_elements` import, and replace `on_text_change` and `get_altitude_details` with:

```python
    def _level(self):
        """The flight level as typed, without surrounding whitespace."""
        return self.altitude_text.GetValue().strip()

    def on_text_change(self, _):
        """Enable OK only for two or three ASCII digits."""
        self.ok_button.Enable(matches(FLIGHT_LEVEL, self._level()))

    def get_altitude_details(self):
        """
        Get the altitude details entered by the user.

        Returns:
            tuple: (altitude, reason) where altitude is "FL" followed by three
                digits and reason is None, "WEATHER", or "AIRCRAFT PERFORMANCE"
        """
        altitude = f"FL{pad_three(self._level())}"

        reason = None
        if self.reason_weather.GetValue():
            reason = REASON_WEATHER
        elif self.reason_performance.GetValue():
            reason = REASON_AIRCRAFT_PERFORMANCE

        return altitude, reason
```

- [ ] **Step 7: Rework `DirectRequestDialog`**

In `src/gui/dialogs/direct_request_dialog.py` add `from src.gui.dialogs.validation import FIX, matches` below the `cpdlc_elements` import; make the helper an attribute with the new text:

```python
        self.helper_text = wx.StaticText(
            self, label="2-7 letters or digits, e.g. KONOL or 55N020W"
        )
        self.helper_text.SetForegroundColour(wx.Colour(100, 100, 100))
        vbox.Add(self.helper_text, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
```

and replace `on_text_change` and the first lines of `get_direct_details`:

```python
    def _fix(self):
        """The fix as it would be sent: stripped and upper-cased."""
        return self.fix_text.GetValue().strip().upper()

    def on_text_change(self, _):
        """Enable OK only for 2-7 ASCII letters or digits."""
        self.ok_button.Enable(matches(FIX, self._fix()))

    def get_direct_details(self):
        """Get the direct-to request details.

        Returns:
            tuple: (fix, reason) where reason is None, "WEATHER", or "AIRCRAFT PERFORMANCE"
        """
        fix = self._fix()
```

(the reason lines and the `return fix, reason` stay as they are).

- [ ] **Step 8: Rework `SpeedRequestDialog`**

In `src/gui/dialogs/speed_request_dialog.py` add `from src.gui.dialogs.validation import KNOTS, MACH, matches, pad_three` below the `cpdlc_elements` import; change the knots helper text in `_on_type_change` to `"Enter speed in knots, 3 digits (e.g. 300)"`; replace `on_text_change` and `get_speed_details` with:

```python
    def _rule(self):
        """The validation rule for the selected speed type."""
        return MACH if self.radio_mach.GetValue() else KNOTS

    def _speed(self):
        """The speed as typed, without surrounding whitespace."""
        return self.speed_text.GetValue().strip()

    def on_text_change(self, _):
        """Enable OK only for a value that fits the selected speed type."""
        self.ok_button.Enable(matches(self._rule(), self._speed()))

    def get_speed_details(self):
        """Get the speed request details.

        Returns:
            tuple: (speed, is_mach, reason) where speed is three digits and
                reason is None, "WEATHER", or "AIRCRAFT PERFORMANCE"
        """
        speed = self._speed()
        is_mach = self.radio_mach.GetValue()

        if is_mach:
            speed = pad_three(speed)

        reason = None
        if self.reason_weather.GetValue():
            reason = REASON_WEATHER
        elif self.reason_performance.GetValue():
            reason = REASON_AIRCRAFT_PERFORMANCE

        return speed, is_mach, reason
```

- [ ] **Step 9: Rework `WhenCanWeDialog`**

In `src/gui/dialogs/when_can_we_dialog.py` add `from src.gui.dialogs.validation import FLIGHT_LEVEL, KNOTS, MACH, matches, pad_three` after `import wx`, and replace the class body up to `__init__` plus `_on_type_change`, `_on_value_change` and `get_message_text`:

```python
    # Message types and the rule their value must match; None means no value.
    MESSAGE_TYPES = [
        ("HIGHER LEVEL", None),
        ("LOWER LEVEL", None),
        ("BACK ON ROUTE", None),
        ("CLIMB TO FL", FLIGHT_LEVEL),
        ("DESCENT TO FL", FLIGHT_LEVEL),
        ("Mach", MACH),
        ("Speed (knots)", KNOTS),
    ]
```

```python
    def _on_type_change(self, _):
        """Show/hide value field based on selected type."""
        idx = self._get_selected_index()
        label, rule = self.MESSAGE_TYPES[idx]

        if rule is not None:
            self.value_label.Show()
            self.value_text.Show()
            self.helper_text.Show()

            if "FL" in label:
                self.helper_text.SetLabel("Enter flight level, 2 or 3 digits (e.g. 350)")
            elif label == "Mach":
                self.helper_text.SetLabel("Enter Mach without decimal (e.g. 082)")
            else:
                self.helper_text.SetLabel("Enter speed in knots, 3 digits (e.g. 300)")

            self._on_value_change(None)
        else:
            self.value_label.Hide()
            self.value_text.Hide()
            self.helper_text.Hide()
            self.ok_button.Enable()

        self.Fit()

    def _value(self):
        """The value as typed, without surrounding whitespace."""
        return self.value_text.GetValue().strip()

    def _on_value_change(self, _):
        """Enable OK when the value fits the selected type's rule."""
        _, rule = self.MESSAGE_TYPES[self._get_selected_index()]

        if rule is None:
            self.ok_button.Enable()
            return

        self.ok_button.Enable(matches(rule, self._value()))

    def get_message_text(self):
        """Build the full WHEN CAN WE EXPECT message text.

        Returns:
            str: The complete message text
        """
        label, rule = self.MESSAGE_TYPES[self._get_selected_index()]

        if rule is None:
            return f"WHEN CAN WE EXPECT {label}"

        value = self._value()

        if "FL" in label:
            # CLIMB TO FL / DESCENT TO FL
            return f"WHEN CAN WE EXPECT {label}{pad_three(value)}"
        elif label == "Mach":
            return f"WHEN CAN WE EXPECT M{pad_three(value)}"
        else:
            # Speed in knots
            return f"WHEN CAN WE EXPECT {value}K"
```

The `for i, (label, _) in enumerate(self.MESSAGE_TYPES)` loop in `__init__` keeps working with the new tuples.

- [ ] **Step 10: Drop the duplicate length check in `on_logon`**

In `src/gui/main_window.py`, inside `on_logon`, delete these lines (the dialog now guarantees the shape):

```python
            # Validate station name is exactly 4 characters
            if len(station) != 4:
                self._message_box(
                    "Station name must be exactly 4 characters long.",
                    "Invalid Station Name",
                    wx.OK | wx.ICON_ERROR,
                )
                return
```

Run `grep -rn "exactly 4 characters" src tests` — expected: no matches remain.

- [ ] **Step 11: Run the new tests and the suite**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_request_dialogs.py`
Expected: all pass.

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: 390 + the new tests pass, 0 failures.

- [ ] **Step 12: Update `tests/README.md`**

Add a row, keeping the table's alphabetical order:

```markdown
| `test_request_dialogs.py` | The OK-button rules and the returned values of the logon, altitude, direct-to, speed and when-can-we dialogs |
```

- [ ] **Step 13: Commit**

```bash
git add src/gui/dialogs/validation.py src/gui/dialogs/logon_dialog.py src/gui/dialogs/altitude_change_dialog.py src/gui/dialogs/direct_request_dialog.py src/gui/dialogs/speed_request_dialog.py src/gui/dialogs/when_can_we_dialog.py src/gui/main_window.py tests/conftest.py tests/test_dialogs.py tests/test_request_dialogs.py tests/README.md
git commit -m "Validate request dialog input on ASCII rules and return what was validated"
```

(body: which rules, why ASCII-only, that the getters now return the validated text and the window's length check went; trailer as in Global Constraints.)

---

### Task 2: The Telex dialog counts characters and refuses what the network would

**Files:**
- Modify: `src/gui/dialogs/telex_dialog.py`, `tests/README.md`
- Test: `tests/test_request_dialogs.py` (append a telex section)

**Interfaces:**
- Consumes: `src.gui.dialogs.validation.matches` (Task 1); the `dialog` fixture in `tests/conftest.py` (Task 1).
- Produces: `TelexDialog.counter_text` (a `wx.StaticText`), module constants `TELEX_MAX_CHARACTERS = 220` and `RECIPIENT = r"[A-Z0-9]{3,8}"` in `telex_dialog.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_request_dialogs.py` (add `TelexDialog` to the `src.gui.dialogs` import):

```python
# --- telex --------------------------------------------------------------------


@pytest.fixture
def telex(dialog, frame):
    """A Telex dialog whose parent window claims to be logged on to EDDF."""
    frame.get_current_station = lambda: "EDDF"
    return dialog(TelexDialog)


def test_the_recipient_starts_as_the_current_station(telex):
    assert telex.recipient_text.GetValue() == "EDDF"
    assert telex.counter_text.GetLabel() == "0 / 220 characters"
    assert telex.ok_button.IsEnabled() is False


def test_the_counter_follows_the_message(telex):
    telex.message_text.SetValue("REQUEST OCEANIC CLEARANCE")

    assert telex.counter_text.GetLabel() == "25 / 220 characters"
    assert telex.ok_button.IsEnabled() is True


def test_a_message_at_the_limit_is_allowed(telex):
    telex.message_text.SetValue("A" * 220)

    assert telex.counter_text.GetLabel() == "220 / 220 characters"
    assert telex.ok_button.IsEnabled() is True


def test_a_message_over_the_limit_is_refused_with_the_overrun(telex):
    """The limit used to surface only after OK, as a send failure."""
    telex.message_text.SetValue("A" * 221)

    assert telex.counter_text.GetLabel() == "221 / 220 characters. Too long by 1."
    assert telex.ok_button.IsEnabled() is False


def test_non_ascii_text_is_refused_with_a_reason(telex):
    telex.message_text.SetValue("GR\u00dcSSE AUS FRANKFURT")

    assert telex.counter_text.GetLabel() == (
        "20 / 220 characters. Only plain ASCII text can be sent."
    )
    assert telex.ok_button.IsEnabled() is False


@pytest.mark.parametrize(
    "recipient, enabled",
    [
        ("EDDF", True),
        (" eddf ", True),
        ("EDDFZQZX", True),
        ("ED", False),
        ("EDDFZQZXA", False),
        ("ED DF", False),
        ("", False),
    ],
)
def test_the_recipient_must_be_a_station_name(telex, recipient, enabled):
    telex.message_text.SetValue("HELLO")

    telex.recipient_text.SetValue(recipient)

    assert telex.ok_button.IsEnabled() is enabled


def test_the_telex_is_returned_stripped_and_upper_cased(telex):
    telex.recipient_text.SetValue(" eddf ")
    telex.message_text.SetValue("  request oceanic clearance \n")

    assert telex.get_telex_details() == ("EDDF", "REQUEST OCEANIC CLEARANCE")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_request_dialogs.py -k telex`
Expected: `AttributeError: 'TelexDialog' object has no attribute 'counter_text'` and `("EDDF ", ...) != ("EDDF", ...)`-style failures.

- [ ] **Step 3: Rework `TelexDialog`**

Replace `src/gui/dialogs/telex_dialog.py` with:

```python
"""
Telex dialog for the Sim-CPDLC application.
"""

import wx

from src.gui.dialogs.validation import matches

# The ACARS free-text limit, enforced by hoppie_connector's TelexMessage, which
# also rejects any non-ASCII character. Checking here means the pilot hears
# about it while typing rather than as a send failure.
TELEX_MAX_CHARACTERS = 220
# hoppie_connector's station-name rule, applied to the recipient.
RECIPIENT = r"[A-Z0-9]{3,8}"


class TelexDialog(wx.Dialog):
    """
    Dialog for sending a telex message.
    """

    def __init__(self, parent):
        """
        Initialize the telex dialog.

        Args:
            parent: The parent window; its get_current_station() fills the
                recipient in
        """
        wx.Dialog.__init__(self, parent, wx.ID_ANY, "Telex", size=(-1, -1))

        vbox = wx.BoxSizer(wx.VERTICAL)

        recipient_label = wx.StaticText(self, label="To:")
        vbox.Add(recipient_label, 0, wx.ALL, 5)
        self.recipient_text = wx.TextCtrl(self)
        self.recipient_text.SetValue(parent.get_current_station())
        vbox.Add(self.recipient_text, 0, wx.ALL | wx.EXPAND, 5)

        message_label = wx.StaticText(self, label="Message:")
        vbox.Add(message_label, 0, wx.ALL, 5)
        self.message_text = wx.TextCtrl(self, style=wx.TE_MULTILINE, size=(-1, 100))
        vbox.Add(self.message_text, 1, wx.ALL | wx.EXPAND, 5)

        # Read by screen readers on request; says why OK is disabled.
        self.counter_text = wx.StaticText(self, label="")
        vbox.Add(self.counter_text, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        self.ok_button = wx.Button(self, wx.ID_OK, label="OK")
        cancel_button = wx.Button(self, wx.ID_CANCEL, label="Cancel")
        hbox.Add(self.ok_button, 1, wx.ALL, 5)
        hbox.Add(cancel_button, 1, wx.ALL, 5)

        vbox.Add(hbox, 0, wx.ALIGN_CENTER)

        self.SetSizer(vbox)

        self.Fit()

        self.recipient_text.Bind(wx.EVT_TEXT, self.on_text_change)
        self.message_text.Bind(wx.EVT_TEXT, self.on_text_change)
        self.on_text_change(None)

    def _recipient(self):
        """The recipient as it would be sent: stripped and upper-cased."""
        return self.recipient_text.GetValue().strip().upper()

    def _message(self):
        """The message as it would be sent: stripped and upper-cased."""
        return self.message_text.GetValue().strip().upper()

    def on_text_change(self, _):
        """Update the character count and enable OK only for a sendable telex."""
        message = self._message()
        count = f"{len(message)} / {TELEX_MAX_CHARACTERS} characters"
        message_ok = bool(message)

        if len(message) > TELEX_MAX_CHARACTERS:
            count += f". Too long by {len(message) - TELEX_MAX_CHARACTERS}."
            message_ok = False
        elif not message.isascii():
            count += ". Only plain ASCII text can be sent."
            message_ok = False

        self.counter_text.SetLabel(count)
        self.ok_button.Enable(message_ok and matches(RECIPIENT, self._recipient()))

    def get_telex_details(self):
        """
        Get the telex details entered by the user.

        Returns:
            tuple: (recipient, message), both stripped and upper-cased
        """
        return self._recipient(), self._message()
```

- [ ] **Step 4: Run the tests and the suite**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_request_dialogs.py`
Expected: all pass.

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 5: Update `tests/README.md`**

Change the `test_request_dialogs.py` row to:

```markdown
| `test_request_dialogs.py` | The OK-button rules and the returned values of the logon, altitude, direct-to, speed, when-can-we and telex dialogs, including the telex character count |
```

- [ ] **Step 6: Commit**

```bash
git add src/gui/dialogs/telex_dialog.py tests/test_request_dialogs.py tests/README.md
git commit -m "Count telex characters and refuse what the network would reject"
```

---

### Task 3: Settings, Connect and PDC hand back stripped fields; settings apply only once saved

**Files:**
- Modify: `src/gui/dialogs/settings_dialog.py:171-186`, `src/gui/dialogs/connect_dialog.py:201-226`, `src/gui/dialogs/pdc_dialog.py:149-162`, `src/gui/main_window.py:316-338` (`on_settings`), `tests/README.md`
- Test: `tests/test_dialogs.py`, `tests/test_main_window.py`

**Interfaces:**
- Consumes: the `dialog` fixture (Task 1); `RecordingFetch` and `FakeSettingsDialog` already in the test modules.
- Produces: nothing new for later tasks.

- [ ] **Step 1: Write the failing dialog tests**

Append to `tests/test_dialogs.py` (extend its import to `from src.gui.dialogs import ConnectDialog, PDCDialog, SettingsDialog, WeatherDialog`):

```python
# --- the getters return what was validated -----------------------------------


def test_settings_are_returned_without_surrounding_whitespace(dialog):
    """A logon code saved with a trailing space failed every later connection."""
    settings = dialog(SettingsDialog)
    settings.sayintentions_logon_code_text.SetValue(" si-code ")
    settings.hoppie_logon_code_text.SetValue("hoppie-code\t")
    settings.simbrief_userid_text.SetValue(" 123456 ")

    assert settings.get_settings()[:3] == ("si-code", "hoppie-code", "123456")


def test_connection_details_are_returned_stripped(dialog):
    connect = dialog(ConnectDialog, fetch_simbrief=RecordingFetch(configured=False))
    connect.callsign_text.SetValue(" dlh123 ")
    connect.logon_code_text.SetValue(" secret ")

    callsign, logon_code, _ = connect.get_connection_details()

    assert (callsign, logon_code) == ("DLH123", "secret")


def test_pdc_details_are_returned_stripped(dialog):
    pdc = dialog(PDCDialog, fetch_simbrief=RecordingFetch(configured=False))
    pdc.origin_icao_text.SetValue(" eddf ")
    pdc.destination_icao_text.SetValue("egll ")
    pdc.aircraft_text.SetValue(" a320")
    pdc.stand_text.SetValue(" A12 ")
    pdc.atis_text.SetValue(" k ")

    assert pdc.get_pdc_details() == ("EDDF", "EGLL", "A320", "A12", "K")
```

- [ ] **Step 2: Write the failing window tests**

In `tests/test_main_window.py`, change `FakeSettingsDialog.get_settings` to return `("", "", "", False, False, 7)` and its docstring to `"""Stands in for SettingsDialog: answers OK with auto-tune off and a 7-minute weather interval."""`, then append after `test_saving_settings_refreshes_the_auto_tune_cache`:

```python
def test_saved_settings_apply_the_weather_interval_at_once(window, monkeypatch, message_boxes):
    monkeypatch.setattr(mw, "SettingsDialog", FakeSettingsDialog)

    window.on_settings(None)

    assert window.weather_monitor.interval_ms == 7 * 60000
    assert message_boxes.calls[-1][:2] == (
        "Settings saved. The weather interval applies now; logon codes apply to the next connection.",
        "Settings Saved",
    )


def test_a_failed_save_changes_nothing(window, monkeypatch, message_boxes):
    """The session and the file must agree: a setting the file did not take
    is not applied for the rest of the session either."""
    monkeypatch.setattr(mw, "SettingsDialog", FakeSettingsDialog)
    monkeypatch.setattr(mw, "save_config", lambda config: False)
    interval_before = window.weather_monitor.interval_ms

    window.on_settings(None)

    assert window.weather_monitor.interval_ms == interval_before
    assert window._auto_tune_com1 is True
    assert message_boxes.captions[-1] == "Error"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_dialogs.py tests/test_main_window.py -k "stripped or whitespace or settings or failed_save"`
Expected: the three getter tests fail on whitespace (`("si-code ", ...)`), the interval test fails on the message text, and `test_a_failed_save_changes_nothing` fails with `interval_ms == 420000` (applied before the save).

- [ ] **Step 4: Strip in the three getters**

`src/gui/dialogs/settings_dialog.py`, `get_settings`:

```python
        return (
            self.sayintentions_logon_code_text.GetValue().strip(),
            self.hoppie_logon_code_text.GetValue().strip(),
            self.simbrief_userid_text.GetValue().strip(),
            self.auto_check_updates_checkbox.GetValue(),
            self.auto_tune_com1_checkbox.GetValue(),
            self.weather_interval_spin.GetValue(),
        )
```

`src/gui/dialogs/connect_dialog.py`, `get_connection_details`: `callsign = self.callsign_text.GetValue().strip().upper()` and, in the else branch, `logon_code = self.logon_code_text.GetValue().strip()`.

`src/gui/dialogs/pdc_dialog.py`, `get_pdc_details`:

```python
        return (
            self.origin_icao_text.GetValue().strip().upper(),
            self.destination_icao_text.GetValue().strip().upper(),
            self.aircraft_text.GetValue().strip().upper(),
            self.stand_text.GetValue().strip(),
            self.atis_text.GetValue().strip().upper(),
        )
```

- [ ] **Step 5: Apply settings only inside the success branch**

In `src/gui/main_window.py`, `on_settings`, delete the line `self.weather_monitor.set_interval(new_weather_interval * 60000)` that precedes `if save_config(config):` and make the success branch:

```python
            if save_config(config):
                self.weather_monitor.set_interval(new_weather_interval * 60000)
                self._auto_tune_com1 = new_auto_tune_com1
                self.logger.info("Settings saved successfully")
                self._message_box(
                    "Settings saved. The weather interval applies now; "
                    "logon codes apply to the next connection.",
                    "Settings Saved",
                    wx.OK | wx.ICON_INFORMATION,
                )
```

The failure branch stays as it is.

- [ ] **Step 6: Run the tests and the suite**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_dialogs.py tests/test_main_window.py`
Expected: all pass.

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 7: Update `tests/README.md`**

```markdown
| `test_dialogs.py` | The weather request dialog's validation; the Connect and PDC dialogs filling in from SimBrief; the Settings, Connect and PDC getters returning stripped fields |
| `test_main_window.py` | The real window: menu bindings, message list, weather toggles, settings |
```

- [ ] **Step 8: Commit**

```bash
git add src/gui/dialogs/settings_dialog.py src/gui/dialogs/connect_dialog.py src/gui/dialogs/pdc_dialog.py src/gui/main_window.py tests/test_dialogs.py tests/test_main_window.py tests/README.md
git commit -m "Strip the settings and connection fields, and apply settings only once saved"
```

---

### Task 4: Bundled files are found from any working directory

**Files:**
- Modify: `src/gui/main_window.py:62-70` (the `resource_path` method becomes a module-level function) and `:95` (its caller)
- Test: `tests/test_main_window.py`

**Interfaces:**
- Produces: `src.gui.main_window.resource_path(relative_path) -> str` (module-level; the method is removed).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_main_window.py` (add `import os` and extend the config import to `from src.config import DEFAULT_CONFIG, MESSAGE_SOUND_FILENAME, save_config`):

```python
# --- bundled files -------------------------------------------------------------


def test_the_sound_is_found_from_any_working_directory(monkeypatch, tmp_path):
    """python C:\\...\\app.py run from another folder used to warn that the
    sound was missing, because the lookup went through the working directory."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delattr(sys, "frozen", raising=False)

    path = mw.resource_path(os.path.join("assets", MESSAGE_SOUND_FILENAME))

    assert os.path.isfile(path)


def test_a_frozen_build_looks_in_the_unpacked_bundle(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert mw.resource_path("assets/message.wav") == os.path.join(
        str(tmp_path), "assets/message.wav"
    )


def test_the_window_loads_its_sound_from_another_working_directory(build_window, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    window = build_window()

    assert window.new_message_sound is not None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_main_window.py -k "working_directory or frozen_build"`
Expected: `AttributeError: module 'src.gui.main_window' has no attribute 'resource_path'` for the first two; the third fails with `None is not None` (and a recorded "sound file not found" message box).

- [ ] **Step 3: Make `resource_path` a module-level function**

In `src/gui/main_window.py` add `from pathlib import Path` to the standard-library imports, delete the `resource_path` method from `MainWindow` (lines 62-70), and add below `HANDOVER_PATTERN`:

```python
# The directory that holds app.py, src/ and assets/: two levels above this
# file. A frozen build unpacks the same layout into sys._MEIPASS.
_SOURCE_ROOT = str(Path(__file__).resolve().parents[2])


def resource_path(relative_path):
    """Absolute path of a bundled file, in a checkout or a PyInstaller build.

    The working directory plays no part: a checkout started from another
    folder used to lose its notification sound and warn about it on every
    start.

    Args:
        relative_path: Path below the source root, e.g. "assets/message.wav"

    Returns:
        str: The absolute path
    """
    if getattr(sys, "frozen", False):
        base_path = getattr(sys, "_MEIPASS", _SOURCE_ROOT)
    else:
        base_path = _SOURCE_ROOT
    return os.path.join(base_path, relative_path)
```

Change the caller in `__init__` to `sound_path = resource_path(os.path.join("assets", MESSAGE_SOUND_FILENAME))`.

Run `grep -rn "resource_path" src tests` — expected: the function, its caller and the new tests only.

- [ ] **Step 4: Run the tests and the suite**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_main_window.py`
Expected: all pass.

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/gui/main_window.py tests/test_main_window.py
git commit -m "Find bundled files from the source tree, not the working directory"
```

---

### Task 5: A doubled separator is one separator, and the list columns fit

**Files:**
- Modify: `src/utils/message_formatting.py:20-41`, `src/gui/message_view.py:49-96`, `tests/README.md`
- Test: `tests/test_message_formatting.py`, `tests/test_message_view.py`

**Interfaces:**
- Produces: `MessageView._fit_columns()`, `MessageView._on_list_size(event)`, module constant `MIN_MESSAGE_COLUMN_WIDTH = 200` in `message_view.py`.

- [ ] **Step 1: Write the failing formatting tests**

Append to `tests/test_message_formatting.py`:

```python
def test_a_doubled_separator_is_just_a_separator():
    """"@@" used to become "N/A" glued to its neighbours, which a screen
    reader read as "FL360N slash AREPORT"."""
    assert format_message_text("CLIMB TO AND MAINTAIN @FL360@@REPORT LEVEL") == (
        "CLIMB TO AND MAINTAIN\nFL360\nREPORT LEVEL"
    )
    assert format_list_text("CLIMB TO AND MAINTAIN @FL360@@REPORT LEVEL") == (
        "CLIMB TO AND MAINTAIN FL360 REPORT LEVEL"
    )


def test_the_list_row_has_single_spaces_and_no_line_breaks():
    assert format_list_text("CONTACT  MAASTRICHT@\n132.850@ .") == "CONTACT MAASTRICHT 132.850 ."
```

- [ ] **Step 2: Write the failing view tests**

Append to `tests/test_message_view.py`:

```python
# --- column layout -------------------------------------------------------------


def test_the_message_column_takes_the_width_the_sender_column_leaves(panel, logger):
    """Both columns were autosized once, while the list was still empty."""
    view = MessageView(panel, logger, MessageManager(logger), None, answerable())
    lst = view.message_list
    lst.SetSize((600, 200))

    view._fit_columns()

    assert lst.GetColumnWidth(0) > 0
    assert lst.GetColumnWidth(1) == lst.GetClientSize().width - lst.GetColumnWidth(0)


def test_a_resize_refits_the_columns(panel, logger):
    view = MessageView(panel, logger, MessageManager(logger), None, answerable())
    lst = view.message_list
    lst.SetSize((600, 200))
    view._fit_columns()
    narrow = lst.GetColumnWidth(1)

    lst.SetSize((900, 200))
    event = wx.SizeEvent(lst.GetSize(), lst.GetId())
    event.SetEventObject(lst)
    lst.GetEventHandler().ProcessEvent(event)

    assert lst.GetColumnWidth(1) > narrow
    assert lst.GetColumnWidth(1) == lst.GetClientSize().width - lst.GetColumnWidth(0)


def test_a_long_sender_widens_its_column(panel, logger):
    manager = MessageManager(logger)
    view = build_view(panel, logger, manager, STATION)
    lst = view.message_list
    lst.SetSize((600, 200))
    view._fit_columns()
    before = lst.GetColumnWidth(0)

    view.add_message(manager.add_message(uplink("WWWWWWWW", 4)))

    assert lst.GetColumnWidth(0) > before
    assert lst.GetColumnWidth(1) == lst.GetClientSize().width - lst.GetColumnWidth(0)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_message_formatting.py tests/test_message_view.py -k "separator or single_spaces or column"`
Expected: the formatting tests fail with `N/A` in the output; the view tests fail with `AttributeError: 'MessageView' object has no attribute '_fit_columns'`.

- [ ] **Step 4: Rework the two formatting functions**

In `src/utils/message_formatting.py` replace `format_list_text` with:

```python
def format_list_text(text):
    """Format message text for compact list display."""
    if not text or not isinstance(text, str):
        return text

    # "@" separates the fields of a CPDLC element and "_" pads them. In a
    # one-line summary a separator becomes a space, and runs of separators
    # ("@@", "@ @") collapse with the surrounding whitespace and line breaks.
    return " ".join(text.replace("_", "").replace("@", " ").split())
```

and in `format_message_text` delete the two lines

```python
        # Replace @@ with N/A before splitting on single @
        text = text.replace("@@", "N/A")
```

(the loop already skips the empty segment a doubled `@` produces). Update the comment above `segments = text.split("@")` to `# Split on the field separators; an empty segment ("@@") is skipped below`.

- [ ] **Step 5: Fit the columns in `MessageView`**

In `src/gui/message_view.py` add below the imports:

```python
# The Message column never shrinks below this, so a narrow window scrolls
# sideways instead of truncating every row.
MIN_MESSAGE_COLUMN_WIDTH = 200
```

In `_init_ui` replace the two `InsertColumn` lines and add the binding and the first fit:

```python
        self.message_list.InsertColumn(0, "Sender")
        self.message_list.InsertColumn(1, "Message")
        self.message_list.SetToolTip("Messages received from the CPDLC network.")
        hbox.Add(self.message_list, 1, wx.ALL, 5)
```

and after the existing `Bind` calls:

```python
        self.message_list.Bind(wx.EVT_SIZE, self._on_list_size)
        self._fit_columns()
```

Add the two methods after `clear`:

```python
    def _fit_columns(self):
        """Size the Sender column to its content and give the Message column the rest.

        A column autosized once, while the list is still empty, stays a few
        characters wide for the rest of the session.
        """
        lst = self.message_list
        lst.SetColumnWidth(0, wx.LIST_AUTOSIZE)
        by_content = lst.GetColumnWidth(0)
        lst.SetColumnWidth(0, wx.LIST_AUTOSIZE_USEHEADER)
        sender_width = max(by_content, lst.GetColumnWidth(0))
        lst.SetColumnWidth(0, sender_width)

        remaining = lst.GetClientSize().width - sender_width
        lst.SetColumnWidth(1, max(remaining, MIN_MESSAGE_COLUMN_WIDTH))

    def _on_list_size(self, event):
        """Re-fit the columns whenever the list is resized."""
        event.Skip()
        self._fit_columns()
```

Call `self._fit_columns()` as the last line of both `add_message` (after `SetItemData`) and `clear`.

- [ ] **Step 6: Run the tests and the suite**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_message_formatting.py tests/test_message_view.py`
Expected: all pass.

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 7: Update `tests/README.md`**

```markdown
| `test_message_formatting.py` | Packet prefix stripping and the list and detail text, including doubled separators |
| `test_message_view.py` | The message list, its column layout and its response context menu |
```

- [ ] **Step 8: Commit**

```bash
git add src/utils/message_formatting.py src/gui/message_view.py tests/test_message_formatting.py tests/test_message_view.py tests/README.md
git commit -m "Treat a doubled separator as one and fit the message list columns"
```

---

### Task 6: Every stop of automatic weather updates is announced, and the dialog follows the monitor

**Files:**
- Modify: `src/model/weather_monitor.py`, `src/gui/dialogs/weather_subscriptions_dialog.py`, `src/gui/main_window.py` (`on_weather_subscriptions`, `_on_toggle_weather_updates`, new `_stop_weather_updates`), `tests/README.md`
- Test: `tests/test_weather_monitor.py`, `tests/test_weather_subscriptions_dialog.py` (new), `tests/test_main_window.py`

**Interfaces:**
- Consumes: the `dialog` fixture (Task 1); `ScriptedConnection`, `deliver` and `inline_worker` already used in `tests/test_weather_monitor.py`.
- Produces: `WeatherMonitor.subscribe_to_changes(callback) -> stop_listening` (both zero-argument callables), `WeatherMonitor._notify_changed()`, `WeatherMonitor._listeners` (list); `WeatherSubscriptionsDialog(parent, weather_monitor, on_stop)` where `on_stop(icao, info_type)`; `MainWindow._stop_weather_updates(icao, info_type)`.

- [ ] **Step 1: Write the failing monitor tests**

Append to `tests/test_weather_monitor.py` (extend its import to `from src.model.weather_monitor import MAX_CONSECUTIVE_ERRORS, WeatherMonitor`):

```python
# --- change listeners ----------------------------------------------------------


def test_listeners_hear_the_subscription_list_change(logger, frame):
    monitor = WeatherMonitor(logger, ScriptedConnection(), worker=inline_worker(logger))
    monitor._parent = frame
    counts = []
    stop_listening = monitor.subscribe_to_changes(lambda: counts.append(monitor.count()))

    monitor.subscribe("EGLL", "vatatis")
    monitor.subscribe("EGLL", "vatatis")  # already watched: nothing changed
    monitor.unsubscribe("EGLL", "vatatis")
    monitor.unsubscribe("EGLL", "vatatis")  # already gone: nothing changed
    monitor.subscribe("EGKK", "metar")
    monitor.clear()
    monitor.clear()  # already empty: nothing changed

    assert counts == [1, 0, 1, 0]

    stop_listening()
    stop_listening()  # a second call is harmless
    monitor.subscribe("EGLL", "vatatis")
    assert counts == [1, 0, 1, 0]


def test_listeners_hear_a_successful_check_and_a_dropped_subscription(logger, frame):
    """The dialog shows "last checked" and lists dropped reports until told
    otherwise, so both events have to reach it. Failed checks short of the
    limit change nothing it shows."""
    monitor = WeatherMonitor(logger, ScriptedConnection(), worker=inline_worker(logger))
    monitor._parent = frame
    monitor.subscribe("EGLL", "metar")
    changes = []
    monitor.subscribe_to_changes(lambda: changes.append(monitor.count()))

    monitor._on_result("EGLL", "metar", "EGLL 261150Z 24010KT Q1013", None)
    assert changes == [1]

    for _ in range(MAX_CONSECUTIVE_ERRORS - 1):
        monitor._on_result("EGLL", "metar", None, "timeout")
    assert changes == [1]

    monitor._on_result("EGLL", "metar", None, "timeout")
    assert changes == [1, 0]


def test_a_listener_that_raises_is_dropped_and_the_others_still_run(logger, frame):
    """A dialog wx has already destroyed raises from its list; that must not
    break the update cycle for the rest of the session."""
    monitor = WeatherMonitor(logger, ScriptedConnection(), worker=inline_worker(logger))
    monitor._parent = frame
    heard = []

    def broken():
        raise RuntimeError("wrapped C++ object has been deleted")

    monitor.subscribe_to_changes(broken)
    monitor.subscribe_to_changes(lambda: heard.append(monitor.count()))

    monitor.subscribe("EGLL", "vatatis")
    monitor.unsubscribe("EGLL", "vatatis")

    assert heard == [1, 0]
```

- [ ] **Step 2: Write the failing dialog tests**

Create `tests/test_weather_subscriptions_dialog.py`:

```python
"""The Automatic Weather Updates dialog: what it lists, and how a stop is routed.

The dialog runs a modal loop while the monitor keeps working underneath it,
so a report dropped or checked meanwhile has to show up without reopening it.
Stopping goes through the window, so the SYSTEM row and the status text read
the same as from the report's context menu.
"""

import pytest
import wx

from src.gui.dialogs import WeatherSubscriptionsDialog
from src.model.weather_monitor import MAX_CONSECUTIVE_ERRORS, WeatherMonitor
from src.utils.weather_parsing import report_type_label
from tests.support import inline_worker

METAR = report_type_label("metar")
ATIS = report_type_label("vatatis")


class Connection:
    """Always connected; never asked for anything in these tests."""

    def is_connected(self):
        return True

    def send_info_request(self, info_type, icao):
        return f"{icao} REPORT"


@pytest.fixture
def monitor(logger, frame):
    """A monitor watching two reports, listed EGKK first (sorted by ICAO)."""
    monitor = WeatherMonitor(logger, Connection(), worker=inline_worker(logger))
    monitor._parent = frame
    monitor.subscribe("EGKK", "metar")
    monitor.subscribe("EGLL", "vatatis")
    return monitor


@pytest.fixture
def stopped():
    """What the window's stop helper was asked to stop, in order."""
    return []


@pytest.fixture
def subscriptions(dialog, monitor, stopped):
    return dialog(
        WeatherSubscriptionsDialog,
        monitor,
        lambda icao, info_type: stopped.append((icao, info_type)),
    )


def entries(dlg):
    return [dlg.subscription_list.GetString(i) for i in range(dlg.subscription_list.GetCount())]


def test_the_list_names_every_watched_report(subscriptions):
    assert entries(subscriptions) == [
        f"{METAR} EGKK, not yet checked",
        f"{ATIS} EGLL, not yet checked",
    ]
    assert subscriptions.subscription_list.GetSelection() == 0


def test_stop_updating_hands_the_selected_report_to_the_window(subscriptions, stopped, monitor):
    subscriptions.subscription_list.SetSelection(1)

    subscriptions.on_stop(None)

    assert stopped == [("EGLL", "vatatis")]
    # The dialog announces nothing itself: the window's helper unsubscribes
    # and says so, and the list follows the monitor from there.
    assert monitor.count() == 2


def test_the_list_follows_the_monitor(subscriptions, monitor):
    monitor.unsubscribe("EGLL", "vatatis")
    assert entries(subscriptions) == [f"{METAR} EGKK, not yet checked"]

    monitor.unsubscribe("EGKK", "metar")

    assert entries(subscriptions) == []
    assert subscriptions.stop_button.IsEnabled() is False
    assert subscriptions.stop_all_button.IsEnabled() is False
    assert subscriptions.check_button.IsEnabled() is False


def test_a_report_dropped_after_repeated_failures_leaves_the_list(subscriptions, monitor):
    """It used to stay listed until the dialog was reopened."""
    for _ in range(MAX_CONSECUTIVE_ERRORS):
        monitor._on_result("EGLL", "vatatis", None, "timeout")

    assert entries(subscriptions) == [f"{METAR} EGKK, not yet checked"]


def test_a_checked_report_shows_when_it_was_checked(subscriptions, monitor):
    monitor._on_result("EGKK", "metar", "EGKK 261150Z 24010KT Q1013", None)

    assert entries(subscriptions)[0].startswith(f"{METAR} EGKK, last checked ")


def test_the_selection_survives_a_refresh(subscriptions, monitor):
    subscriptions.subscription_list.SetSelection(1)

    monitor._on_result("EGKK", "metar", "EGKK 261150Z 24010KT Q1013", None)

    assert subscriptions.subscription_list.GetSelection() == 1


def test_stop_all_asks_first_and_then_hands_over_every_report(subscriptions, stopped, message_boxes):
    message_boxes.answer = wx.YES

    subscriptions.on_stop_all(None)

    assert message_boxes.captions == ["Confirm"]
    assert stopped == [("EGKK", "metar"), ("EGLL", "vatatis")]


def test_stop_all_declined_stops_nothing(subscriptions, stopped, message_boxes):
    message_boxes.answer = wx.NO

    subscriptions.on_stop_all(None)

    assert stopped == []


def test_a_closed_dialog_stops_listening(frame, monitor):
    dlg = WeatherSubscriptionsDialog(frame, monitor, lambda icao, info_type: None)
    assert len(monitor._listeners) == 1

    dlg.Destroy()

    assert monitor._listeners == []
```

- [ ] **Step 3: Write the failing window tests**

Append to `tests/test_main_window.py` (add `from src.utils.weather_parsing import report_type_label`):

```python
# --- stopping automatic weather updates ------------------------------------------


def test_stopping_updates_from_the_subscriptions_dialog_is_announced(window):
    """The dialog's Stop button used to remove the row silently, while the
    other two stop paths add a SYSTEM row and set the status text."""
    window.weather_monitor.subscribe("EGLL", "vatatis")
    label = report_type_label("vatatis")

    window._stop_weather_updates("EGLL", "vatatis")

    assert window.weather_monitor.count() == 0
    row = last_row(window)
    assert window.message_view.message_list.GetItemText(row, 0) == "SYSTEM"
    assert window.message_view.message_list.GetItemText(row, 1) == (
        f"Stopped automatic updates for {label} EGLL"
    )
    assert window.GetStatusBar().GetStatusText() == f"Stopped watching {label} EGLL."


def test_the_subscriptions_dialog_stops_reports_through_the_window(window, monkeypatch):
    opened = []

    class FakeSubscriptionsDialog:
        def __init__(self, parent, weather_monitor, on_stop):
            opened.append((weather_monitor, on_stop))

        def ShowModal(self):
            return wx.ID_CANCEL

        def Destroy(self):
            pass

    monkeypatch.setattr(mw, "WeatherSubscriptionsDialog", FakeSubscriptionsDialog)
    window.weather_monitor.subscribe("EGLL", "vatatis")

    window.on_weather_subscriptions(None)

    assert opened == [(window.weather_monitor, window._stop_weather_updates)]
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_weather_monitor.py tests/test_weather_subscriptions_dialog.py tests/test_main_window.py -k "listener or subscriptions_dialog or stopping_updates or follows or stop_all or dropped or checked or selection or names_every"`
Expected: `AttributeError: 'WeatherMonitor' object has no attribute 'subscribe_to_changes'`, `TypeError: __init__() takes 3 positional arguments but 4 were given` for the dialog, `AttributeError: 'MainWindow' object has no attribute '_stop_weather_updates'`.

- [ ] **Step 5: Add change listeners to `WeatherMonitor`**

In `src/model/weather_monitor.py`:

In `__init__`, after `self._cycle_pending = 0`:

```python
        # Zero-argument callables told after every change a dialog could show.
        self._listeners = []
```

Add a section before `# Update cycle`:

```python
    # ------------------------------------------------------------------
    # Change notification
    # ------------------------------------------------------------------

    def subscribe_to_changes(self, callback):
        """Call back whenever the subscription list or a check time changes.

        The subscriptions dialog uses this to stay current while it is open:
        a report dropped after repeated failures, or checked by a cycle,
        would otherwise be listed as it was when the dialog opened.

        Args:
            callback: Callable() run on the GUI thread after each change

        Returns:
            Callable() that stops the notifications; calling it twice is safe
        """
        self._listeners.append(callback)

        def stop_listening():
            if callback in self._listeners:
                self._listeners.remove(callback)

        return stop_listening

    def _notify_changed(self):
        """Tell every listener that something they show may have changed.

        A listener that raises is dropped: a dialog wx has already destroyed
        must not be able to break the update cycle for the rest of the
        session.
        """
        for callback in list(self._listeners):
            try:
                callback()
            except Exception:
                self.logger.exception("Error in a weather subscription listener")
                if callback in self._listeners:
                    self._listeners.remove(callback)
```

Call `self._notify_changed()`:
- in `subscribe`, after the `self.logger.info(f"Subscribed to automatic updates: ...")` line (new subscriptions only; the early `return False` path notifies nothing);
- in `unsubscribe`, inside `if subscription:` after the log line, before `return True`;
- in `clear`, inside a guard: change the method to

```python
    def clear(self):
        """Drop every subscription."""
        if not self._subscriptions:
            return
        self.logger.info(f"Cleared {len(self._subscriptions)} weather subscription(s)")
        self._subscriptions.clear()
        self._notify_changed()
```

- in `_on_result`, after the `if self.on_error: self.on_error(subscription, error)` block inside the drop branch (still inside `if subscription.error_count >= MAX_CONSECUTIVE_ERRORS:`), and after `subscription.last_update = time.time()` in the success path (before the signature comparison, so an unchanged report still refreshes "last checked").

- [ ] **Step 6: Rework `WeatherSubscriptionsDialog`**

In `src/gui/dialogs/weather_subscriptions_dialog.py`:

Change the constructor signature and docstring to

```python
    def __init__(self, parent, weather_monitor, on_stop):
        """
        Initialize the subscriptions dialog.

        Args:
            parent: The parent window
            weather_monitor: The WeatherMonitor whose subscriptions are listed
            on_stop: Callable(icao, info_type) that stops one report's updates
                and tells the pilot; the window's helper, so a stop from here
                reads the same as one from the report's context menu
        """
```

after `self.weather_monitor = weather_monitor` add `self._stop_updates = on_stop`, and replace the final `self._refresh()` of `__init__` with:

```python
        self._refresh()
        self._stop_listening = weather_monitor.subscribe_to_changes(self._refresh)

    def Destroy(self):
        """Stop following the monitor before wx tears the list down."""
        self._stop_listening()
        return super().Destroy()
```

Replace `_refresh`, `on_stop` and `on_stop_all`:

```python
    def _refresh(self):
        """Rebuild the list from the monitor, keeping the selected report if it is still there."""
        selected = self.subscription_list.GetSelection()
        selected_key = self._keys[selected] if 0 <= selected < len(self._keys) else None

        subscriptions = self.weather_monitor.get_subscriptions()
        self._keys = [s.key for s in subscriptions]
        self.subscription_list.Set([self._format_entry(s) for s in subscriptions])

        if subscriptions:
            index = self._keys.index(selected_key) if selected_key in self._keys else 0
            self.subscription_list.SetSelection(index)

        self._update_button_state(None)
```

```python
    def on_stop(self, _):
        """Stop updating the selected report, through the window so it is announced."""
        index = self.subscription_list.GetSelection()
        if index == wx.NOT_FOUND or index >= len(self._keys):
            return

        icao, info_type = self._keys[index]
        self._stop_updates(icao, info_type)

    def on_stop_all(self, _):
        """Stop updating every report, after confirming."""
        if not self._keys:
            return

        if (
            wx.MessageBox(
                "Stop automatic updates for all reports?",
                "Confirm",
                wx.YES_NO | wx.ICON_QUESTION,
            )
            != wx.YES
        ):
            return

        # The monitor's notification rebuilds self._keys as each report goes,
        # so iterate over a copy.
        for icao, info_type in list(self._keys):
            self._stop_updates(icao, info_type)
```

Neither handler calls `_refresh()` itself: the monitor's notification does, once the window's helper has unsubscribed.

- [ ] **Step 7: Route the window's stop paths through one helper**

In `src/gui/main_window.py`:

`on_weather_subscriptions`:

```python
        with self._show_dialog(
            WeatherSubscriptionsDialog(self, self.weather_monitor, self._stop_weather_updates)
        ):
            pass
```

Add before `_on_toggle_weather_updates`:

```python
    def _stop_weather_updates(self, icao, info_type):
        """Stop automatic updates for a report and say so.

        The report's context menu and the subscriptions dialog both come
        through here, so the SYSTEM row and the status text read the same.

        Args:
            icao: Airport ICAO code
            info_type: Report type key
        """
        label = report_type_label(info_type)
        self.weather_monitor.unsubscribe(icao, info_type)
        self._add_custom_message(
            f"Stopped automatic updates for {label} {icao}", "SYSTEM"
        )
        self.SetStatusText(f"Stopped watching {label} {icao}.")
```

and make the stop branch of `_on_toggle_weather_updates`:

```python
        if self.weather_monitor.is_subscribed(icao, info_type):
            self._stop_weather_updates(icao, info_type)
            return
```

(the `label = report_type_label(info_type)` line stays, as the subscribe branch still uses it).

- [ ] **Step 8: Run the tests and the suite**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_weather_monitor.py tests/test_weather_subscriptions_dialog.py tests/test_main_window.py`
Expected: all pass.

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 9: Update `tests/README.md`**

```markdown
| `test_weather_monitor.py` | Weather change detection, the update cycle on the worker, the timer lifecycle, change listeners |
| `test_weather_subscriptions_dialog.py` | The automatic weather updates dialog: what it lists, stopping through the window, following the monitor |
```

- [ ] **Step 10: Commit**

```bash
git add src/model/weather_monitor.py src/gui/dialogs/weather_subscriptions_dialog.py src/gui/main_window.py tests/test_weather_monitor.py tests/test_weather_subscriptions_dialog.py tests/test_main_window.py tests/README.md
git commit -m "Announce every stop of automatic weather updates and keep the dialog current"
```

---

### Task 7: A bare CONTACT frequency tunes the radio, and a HANDOVER with trailing text is followed

**Files:**
- Modify: `src/utils/frequency_parser.py:6-14`, `src/gui/main_window.py:54-56` (`HANDOVER_PATTERN`)
- Test: `tests/test_frequency_parser.py`, `tests/test_uplink_handling.py`

**Interfaces:**
- Produces: nothing new.

- [ ] **Step 1: Write the failing tests**

In `tests/test_frequency_parser.py` add to `CASES`, after `("MONITOR UNICOM 122.8", 122.8)`:

```python
    ("CONTACT 121.500", 121.5),
    ("MONITOR 122.800", 122.8),
    ("CONTACT ON 121.500", 121.5),
```

Append to `tests/test_uplink_handling.py`, in the handover section after `test_a_handover_keeps_the_old_station_answerable`:

```python
@pytest.mark.parametrize(
    "text",
    [
        "HANDOVER @EDGG@",
        "HANDOVER EDGG",
        "HANDOVER @EDGG@ CONTACT ON 132.850",
        "HANDOVER @EDGG@ EXPECT LOGON",
    ],
    ids=["wrapped", "bare", "with-contact", "with-note"],
)
def test_a_handover_is_followed_whatever_surrounds_the_station(logger, text):
    """The pattern demanded the exact form; trailing text left the pilot
    logged on to a station that had already handed them over."""
    window, session, connection, _ = build(logger)

    window._on_message_received(uplink(CURRENT, 48, text, rr=RR.NOT_REQUIRED))
    window.worker.run_pending()

    assert session.pending_logon_station == "EDGG"
    assert connection.sent == [("EDGG", 1, RR.YES.value, "REQUEST LOGON", None)]


def test_a_handover_to_something_that_is_not_a_station_is_only_shown(logger):
    window, session, connection, _ = build(logger)

    window._on_message_received(uplink(CURRENT, 48, "HANDOVER @EDGGX@", rr=RR.NOT_REQUIRED))

    assert session.get_current_station() == CURRENT
    assert connection.sent == []
    assert len(window.message_view.added) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_frequency_parser.py tests/test_uplink_handling.py -k "121.500 or 122.800 or whatever_surrounds or not_a_station"`
Expected: the three new parser cases return `None`; the `with-contact` and `with-note` handover cases fail with `pending_logon_station == ""`; the others pass.

- [ ] **Step 3: Make the unit name optional**

Replace the pattern in `src/utils/frequency_parser.py`:

```python
# Match CONTACT or MONITOR, an optional unit name, optional ON, then frequency
_FREQ_PATTERN = re.compile(
    r"(?:CONTACT|MONITOR)\s+"  # CONTACT or MONITOR keyword
    r"(?:.+?\s+)?"  # Optional unit name (one or more words, non-greedy)
    r"(?:ON\s+)?"  # Optional ON keyword
    r"(\d{3}\.\d{1,3})"  # Frequency: 3 digits, dot, 1-3 digits
    r"(?:\s*MHZ)?",  # Optional MHZ suffix
    re.IGNORECASE | re.DOTALL,  # DOTALL so the unit name may span a line break
)
```

- [ ] **Step 4: Loosen the HANDOVER pattern**

In `src/gui/main_window.py` replace the comment and pattern:

```python
# A HANDOVER names the next station as a 4-letter code, wrapped in @ separators
# by some networks and sometimes followed by free text. The word boundary keeps
# "HANDOVER EDGGX" from reading as a handover to EDGG.
HANDOVER_PATTERN = re.compile(r"^HANDOVER\s+@?([A-Z]{4})\b")
```

- [ ] **Step 5: Run the tests and the suite**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_frequency_parser.py tests/test_uplink_handling.py`
Expected: all pass.

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/utils/frequency_parser.py src/gui/main_window.py tests/test_frequency_parser.py tests/test_uplink_handling.py
git commit -m "Tune a bare CONTACT frequency and follow a HANDOVER with trailing text"
```

---

## Self-review

- **Spec coverage:** stripped getters and the logon rule with `on_logon`'s check dropped (Task 1, Task 3); ASCII numeric rules, padding, direct-to `[A-Z0-9]{2,7}` with its helper text, the collapsed Mach/knots branch (Task 1); the Telex counter and ASCII/220 gate (Task 2); `SettingsDialog.get_settings` strips and `on_settings` applies inside the success branch with the new wording (Task 3); `resource_path` off the working directory (Task 4, deviation 1); `@@` collapse, list-text space collapse, Sender column autosize and Message column on `EVT_SIZE` (Task 5); `on_stop` callback and `subscribe_to_changes` hook (Task 6); optional unit name with the comment corrected, HANDOVER with `@` and trailing text (Task 7); per-dialog OK-button tables, getter literals, Telex with a parent stub, extended formatting and parser tables (Tasks 1, 2, 5, 7).
- **Placeholders:** none; every step carries its code.
- **Type consistency:** `matches(rule, text)` and `pad_three(text)` are used with those names in Tasks 1 and 2; `WeatherSubscriptionsDialog(parent, weather_monitor, on_stop)` in Task 6's dialog, window and tests; `_stop_weather_updates(icao, info_type)` in the window and both window tests; `_fit_columns()` / `_on_list_size(event)` in Task 5's view and tests; `mw.resource_path(relative_path)` in Task 4.
