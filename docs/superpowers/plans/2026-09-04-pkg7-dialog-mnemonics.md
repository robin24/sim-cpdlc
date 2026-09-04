# Package 7: Dialog Access Keys — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every control in every dialog has a unique access key and an accessible name, following one convention, enforced by a test the way the menu mnemonics already are.

**Architecture:** No new code paths. The when-can-we dialog first separates its radio labels from the element text it sends (Task 1). Then the convention is applied label by label across the ten other dialogs, the two mnemonic helpers move from the window test into `tests/support.py`, and a new `tests/test_dialog_mnemonics.py` walks each dialog's children and checks collisions, coverage and names (Task 2).

**Tech Stack:** Python 3.12+, wxPython 4.2.5, pytest 9.1.1 with pytest-timeout.

## Global Constraints

- Run every command with `C:\Claude\sim-cpdlc\.claude\worktrees\review-25-ceb148\.venv\Scripts\python.exe` (below `$PY`; in Git Bash `PY=/c/Claude/sim-cpdlc/.claude/worktrees/review-25-ceb148/.venv/Scripts/python.exe`). Run the suite from the worktree root as `$PY -m pytest -q -p no:cacheprovider`. Baseline before this plan: 551 passed. The suite must be green at the end of every task.
- Work on branch `claude/pkg7-mnemonics`, cut from `main` at `52994bd`, in the worktree `C:\Claude\sim-cpdlc\.claude\worktrees\pkg7-mnemonics`. Never touch `C:\Claude\sim-cpdlc` itself. Never read `config.json` anywhere (it holds credentials).
- Test-driven: every task writes its failing tests first, runs them to see them fail for the expected reason, then implements. Tests must never reach the network, the real config file, SimBrief, the simulator or a modal dialog; dialogs are built through the `dialog` fixture in `tests/conftest.py`.
- Files this package may change: the eleven dialog modules under `src/gui/dialogs/` (`logon_dialog.py`, `altitude_change_dialog.py`, `direct_request_dialog.py`, `speed_request_dialog.py`, `when_can_we_dialog.py`, `telex_dialog.py`, `pdc_dialog.py`, `connect_dialog.py`, `settings_dialog.py`, `weather_dialog.py`, `weather_subscriptions_dialog.py`), `README.md`, and anything under `tests/`. Nothing else.
- Exact labels are those of the spec's table in `docs/superpowers/specs/2026-09-04-dialog-mnemonics-design.md` (repeated in Task 2). An input control's `SetName` is its label without `&` and without the trailing colon. Headings above radio groups (`Reason (optional):`, `Speed type:`, `Request type:`), helper lines, status lines and the telex counter carry no `&`.
- The downlink texts the when-can-we dialog builds do not change: `WHEN CAN WE EXPECT HIGHER LEVEL`, `... LOWER LEVEL`, `... BACK ON ROUTE`, `... CLIMB TO FL350`, `... DESCENT TO FL100`, `... M082`, `... 300K`.
- Commit messages: imperative sentence subject, body, trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. Git prints CRLF warnings on this machine; they are harmless. Write files with LF endings.
- Spec: `docs/superpowers/specs/2026-09-04-dialog-mnemonics-design.md`. Audit: `docs/audit/2026-09-03-codebase-audit.md`, I-4.

## Design notes

- On Windows, the access key in a `wx.StaticText` label focuses the next control in tab order, which is the control created right after it. Every input in these dialogs is created immediately after its label, so the test can pair them by position in `GetChildren()`.
- `wx.RadioBox` carries the key in its own label; its inner buttons are not `wx.RadioButton` Python objects and are ignored by the test.
- The settings spin control's existing name (`... in minutes`) changes to the label-derived form (`Automatic weather update interval (minutes)`) so one rule covers every input.

---

### Task 1: The when-can-we radio labels are spoken text, the element text is separate

**Files:**
- Modify: `src/gui/dialogs/when_can_we_dialog.py`
- Test: `tests/test_request_dialogs.py`

**Interfaces:**
- Produces: `WhenCanWeDialog.MESSAGE_TYPES` as a list of `(label, text, rule)` where `label` is the radio label with its access key, `text` is the element text (`"HIGHER LEVEL"`, `"LOWER LEVEL"`, `"BACK ON ROUTE"`, `"CLIMB TO FL"`, `"DESCENT TO FL"`, `"M"`, `"K"`) and `rule` is `None`, `FLIGHT_LEVEL`, `MACH` or `KNOTS`. Task 2's test reads the radio labels through `GetLabel()` only.

- [ ] **Step 1: Write the failing test**

Append to the when-can-we section of `tests/test_request_dialogs.py`:

```python
def test_the_request_types_read_in_sentence_case_with_access_keys(dialog):
    """The radios used to show the element text itself, shouted in capitals;
    the text sent is unchanged (see the parametrized test above)."""
    when = dialog(WhenCanWeDialog)

    assert [radio.GetLabel() for radio in when.radios] == [
        "&Higher level",
        "&Lower level",
        "&Back on route",
        "&Climb to FL",
        "&Descent to FL",
        "&Mach",
        "&Speed (knots)",
    ]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_request_dialogs.py -k sentence_case`
Expected: FAIL, the labels are `["HIGHER LEVEL", "LOWER LEVEL", ...]`.

- [ ] **Step 3: Separate the labels from the element text**

In `src/gui/dialogs/when_can_we_dialog.py` replace the class attribute and the four methods that read it:

```python
    # Message types: the radio label with its access key, the element text
    # that goes into the downlink, and the rule the value must match (None
    # means the type takes no value). "M" and "K" are the Mach and knots
    # markers the text is built around.
    MESSAGE_TYPES = [
        ("&Higher level", "HIGHER LEVEL", None),
        ("&Lower level", "LOWER LEVEL", None),
        ("&Back on route", "BACK ON ROUTE", None),
        ("&Climb to FL", "CLIMB TO FL", FLIGHT_LEVEL),
        ("&Descent to FL", "DESCENT TO FL", FLIGHT_LEVEL),
        ("&Mach", "M", MACH),
        ("&Speed (knots)", "K", KNOTS),
    ]
```

In `__init__`, the loop becomes `for i, (label, _, _) in enumerate(self.MESSAGE_TYPES):` (the rest of the loop unchanged).

```python
    def _on_type_change(self, _):
        """Show/hide value field based on selected type."""
        _, text, rule = self.MESSAGE_TYPES[self._get_selected_index()]

        if rule is not None:
            self.value_label.Show()
            self.value_text.Show()
            self.helper_text.Show()

            if text.endswith("FL"):
                self.helper_text.SetLabel(
                    "Enter flight level, 2 or 3 digits from 10 to 600 (e.g. 350)"
                )
            elif text == "M":
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
```

```python
    def _on_value_change(self, _):
        """Enable OK when the value fits the selected type's rule."""
        _, text, rule = self.MESSAGE_TYPES[self._get_selected_index()]

        if rule is None:
            self.ok_button.Enable()
            return

        # FLIGHT_LEVEL and MACH are both r"\d{2,3}": CPython folds equal
        # string literals in the same module into one object, so "rule is
        # FLIGHT_LEVEL" would also be true for the Mach rule. Dispatch on the
        # element text instead, as _on_type_change and get_message_text do.
        value = self._value()
        if text.endswith("FL"):
            ok = is_flight_level(value)
        else:
            ok = matches(rule, value)
        self.ok_button.Enable(ok)

    def get_message_text(self):
        """Build the full WHEN CAN WE EXPECT message text.

        Returns:
            str: The complete message text
        """
        _, text, rule = self.MESSAGE_TYPES[self._get_selected_index()]

        if rule is None:
            return f"WHEN CAN WE EXPECT {text}"

        value = self._value()

        if text.endswith("FL"):
            # CLIMB TO FL / DESCENT TO FL
            return f"WHEN CAN WE EXPECT {text}{pad_three(value)}"
        elif text == "M":
            return f"WHEN CAN WE EXPECT M{pad_three(value)}"
        else:
            # Speed in knots
            return f"WHEN CAN WE EXPECT {value}K"
```

Run `grep -rn "MESSAGE_TYPES" src tests` — expected: only `when_can_we_dialog.py`; if a test unpacks the tuples, update it to three elements.

- [ ] **Step 4: Run the tests and the suite**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_request_dialogs.py`
Expected: all pass, including the parametrized message-text cases, which prove the downlink text is unchanged.

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/gui/dialogs/when_can_we_dialog.py tests/test_request_dialogs.py
git commit -m "Give the when-can-we radios spoken labels apart from the element text"
```

---

### Task 2: One access-key convention across the dialogs, enforced by a test

**Files:**
- Modify: `tests/support.py`, `tests/test_main_window.py` (the two helpers move out), `src/gui/dialogs/logon_dialog.py`, `altitude_change_dialog.py`, `direct_request_dialog.py`, `speed_request_dialog.py`, `when_can_we_dialog.py` (the `Value:` label only), `telex_dialog.py`, `pdc_dialog.py`, `connect_dialog.py`, `settings_dialog.py`, `weather_subscriptions_dialog.py`, `README.md`, `tests/README.md`
- Test: `tests/test_dialog_mnemonics.py` (new)

**Interfaces:**
- Consumes: Task 1's when-can-we labels.
- Produces: `tests.support.mnemonic(label) -> str | None` and `tests.support.colliding_mnemonics(labels) -> dict`.

- [ ] **Step 1: Move the helpers**

Cut `_mnemonic` and `_colliding_mnemonics` (with their docstrings) from `tests/test_main_window.py` and add them to `tests/support.py` without the leading underscore:

```python
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
```

In `tests/test_main_window.py` import `colliding_mnemonics` from `tests.support` and replace the two `_colliding_mnemonics(...)` calls in `test_no_mnemonic_collides_within_a_menu_or_the_menu_bar`.

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_main_window.py -k mnemonic`
Expected: pass.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_dialog_mnemonics.py`:

```python
"""Keyboard access to every dialog: one access key per control, unique within
the dialog, and a name a screen reader can say.

wx marks an access key with '&'. A StaticText's key focuses the control created
right after it, so a label must directly precede its input; a check box, radio
button, radio box or button carries its own. Two labels claiming one letter
leave one of them unreachable by key, which is exactly what an NVDA user
relies on; a helper line with a stray '&' steals a letter the same way.
"""

import pytest
import wx

from src.gui.dialogs import (
    AltitudeChangeDialog,
    ConnectDialog,
    DirectRequestDialog,
    LogonDialog,
    PDCDialog,
    SettingsDialog,
    SpeedRequestDialog,
    TelexDialog,
    WeatherDialog,
    WeatherSubscriptionsDialog,
    WhenCanWeDialog,
)
from tests.support import colliding_mnemonics, mnemonic

INPUTS = (wx.TextCtrl, wx.Choice, wx.SpinCtrl, wx.ListBox)
KEYED = (wx.CheckBox, wx.RadioButton, wx.RadioBox)
LABELLED = (wx.StaticText, wx.Button) + KEYED


class NoFetch:
    """Stands in for the window's SimBrief fetch: no id configured."""

    def __call__(self, on_done):
        return False


class IdleMonitor:
    """Enough of WeatherMonitor for the subscriptions dialog to open empty."""

    interval_ms = 300000

    def get_subscriptions(self):
        return []

    def subscribe_to_changes(self, callback):
        return lambda: None


DIALOGS = {
    "logon": lambda dialog: dialog(LogonDialog),
    "altitude": lambda dialog: dialog(AltitudeChangeDialog),
    "direct": lambda dialog: dialog(DirectRequestDialog),
    "speed": lambda dialog: dialog(SpeedRequestDialog),
    "when-can-we": lambda dialog: dialog(WhenCanWeDialog),
    "telex": lambda dialog: dialog(TelexDialog, "EDDF"),
    "pdc": lambda dialog: dialog(PDCDialog, fetch_simbrief=NoFetch()),
    "connect": lambda dialog: dialog(ConnectDialog, fetch_simbrief=NoFetch()),
    "settings": lambda dialog: dialog(SettingsDialog),
    "weather": lambda dialog: dialog(WeatherDialog),
    "subscriptions": lambda dialog: dialog(
        WeatherSubscriptionsDialog, IdleMonitor(), lambda icao, info_type: None
    ),
}

every_dialog = pytest.mark.parametrize("build", list(DIALOGS.values()), ids=list(DIALOGS))


def plain(label):
    """The label as spoken: no access-key marker, no trailing colon."""
    return label.replace("&&", "\0").replace("&", "").replace("\0", "&").rstrip(":").strip()


@every_dialog
def test_no_access_key_collides_within_the_dialog(dialog, build):
    built = build(dialog)

    labels = [child.GetLabel() for child in built.GetChildren() if isinstance(child, LABELLED)]

    assert colliding_mnemonics(labels) == {}


@every_dialog
def test_every_input_follows_a_keyed_label_and_is_named_after_it(dialog, build):
    built = build(dialog)
    children = list(built.GetChildren())
    inputs = [(index, child) for index, child in enumerate(children) if isinstance(child, INPUTS)]
    assert inputs, "this dialog has no input control; the test is not for it"

    for index, control in inputs:
        label = children[index - 1] if index else None
        assert isinstance(label, wx.StaticText), f"no label right before {control!r}"
        assert mnemonic(label.GetLabel()) is not None, f"{label.GetLabel()!r} declares no access key"
        assert control.GetName() == plain(label.GetLabel())


@every_dialog
def test_every_choice_control_and_command_button_carries_an_access_key(dialog, build):
    built = build(dialog)

    for child in built.GetChildren():
        if isinstance(child, KEYED):
            assert mnemonic(child.GetLabel()) is not None, child.GetLabel()
        elif isinstance(child, wx.Button) and child.GetId() not in (wx.ID_OK, wx.ID_CANCEL):
            assert mnemonic(child.GetLabel()) is not None, child.GetLabel()


@every_dialog
def test_explanatory_text_claims_no_access_key(dialog, build):
    built = build(dialog)
    children = list(built.GetChildren())

    for index, child in enumerate(children):
        if not isinstance(child, wx.StaticText):
            continue
        follower = children[index + 1] if index + 1 < len(children) else None
        if not isinstance(follower, INPUTS):
            assert mnemonic(child.GetLabel()) is None, child.GetLabel()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_dialog_mnemonics.py`
Expected: the `weather` cases pass; `subscriptions` fails only on the list label's missing key; every other dialog fails `test_every_input_follows_a_keyed_label_and_is_named_after_it` (no key, `GetName()` is wx's default such as `"text"`) and, where it has check boxes or radio buttons, `test_every_choice_control_and_command_button_carries_an_access_key`; `settings` also fails on the spin control's name.

- [ ] **Step 4: Apply the convention**

Change these labels and add `SetName` calls right after each input is created. Nothing else in the dialogs changes.

`logon_dialog.py`: `label="&Station:"`; `self.station_text.SetName("Station")`.

`altitude_change_dialog.py`: `label="Requested &Altitude (FL):"`; `self.altitude_text.SetName("Requested Altitude (FL)")`; radios `label="&None"`, `label="Due to &weather"`, `label="Due to aircraft &performance"`.

`direct_request_dialog.py`: `label="&Fix / Waypoint:"`; `self.fix_text.SetName("Fix / Waypoint")`; the three reason radios as above.

`speed_request_dialog.py`: `label="&Mach"`, `label="&Knots"`; `label="Speed &value:"`; `self.speed_text.SetName("Speed value")`; the three reason radios as above.

`when_can_we_dialog.py`: `self.value_label = wx.StaticText(self, label="&Value:")`; `self.value_text.SetName("Value")`.

`telex_dialog.py`: `label="&To:"`; `self.recipient_text.SetName("To")`; `label="&Message:"`; `self.message_text.SetName("Message")`.

`pdc_dialog.py`: `label="&Departure ICAO:"` / `SetName("Departure ICAO")`; `label="Des&tination ICAO:"` / `SetName("Destination ICAO")`; `label="Aircraft &code:"` / `SetName("Aircraft code")`; `label="&Stand number:"` / `SetName("Stand number")`; `label="&ATIS:"` / `SetName("ATIS")`.

`connect_dialog.py`: the radio box `label="&Network"`; `label="&Callsign:"` / `self.callsign_text.SetName("Callsign")`; `label="&Logon code:"` / `self.logon_code_text.SetName("Logon code")`.

`settings_dialog.py`: `label="&SayIntentions Logon code:"` / `SetName("SayIntentions Logon code")`; `label="&Hoppie Logon code:"` / `SetName("Hoppie Logon code")`; `label="SimBrief &User ID:"` / `SetName("SimBrief User ID")`; check boxes `label="&Automatically check for updates"`, `label="Auto-&tune COM1 standby on CONTACT/MONITOR"`; `label="Automatic &weather update interval (minutes):"` and the spin control's name becomes `SetName("Automatic weather update interval (minutes)")`.

`weather_subscriptions_dialog.py`: `label="&Reports being kept up to date:"` (the list's existing name already matches).

`weather_dialog.py`: unchanged.

- [ ] **Step 5: Run the tests and the suite**

Run: `$PY -m pytest -q -p no:cacheprovider tests/test_dialog_mnemonics.py`
Expected: 44 passed (four tests over eleven dialogs).

Run: `$PY -m pytest -q -p no:cacheprovider`
Expected: all pass. If a test elsewhere asserted an old label text (for example the settings spin control's old name or a radio label), update it to the new text and say so in the report.

- [ ] **Step 6: Docs**

`README.md`, in "### Main Window" after the bullet list, add:

```markdown
Every control in the dialogs has an access key: press Alt together with the
letter your screen reader announces (or the underlined one) to jump straight to
it. Enter activates OK and Escape cancels.
```

`tests/README.md`: add the row

```markdown
| `test_dialog_mnemonics.py` | Every dialog control has a unique access key and an accessible name |
```

and change the `test_main_window.py` row to `The real window: menu bindings and mnemonics, message list, weather toggles, settings, the logon gate`.

- [ ] **Step 7: Commit**

```bash
git add tests/support.py tests/test_main_window.py tests/test_dialog_mnemonics.py src/gui/dialogs/logon_dialog.py src/gui/dialogs/altitude_change_dialog.py src/gui/dialogs/direct_request_dialog.py src/gui/dialogs/speed_request_dialog.py src/gui/dialogs/when_can_we_dialog.py src/gui/dialogs/telex_dialog.py src/gui/dialogs/pdc_dialog.py src/gui/dialogs/connect_dialog.py src/gui/dialogs/settings_dialog.py src/gui/dialogs/weather_subscriptions_dialog.py README.md tests/README.md
git commit -m "Give every dialog control an access key and an accessible name"
```

---

## Self-review

- **Spec coverage:** convention points 1 to 3 (Task 2: labels, `SetName`, the four checks), point 4 (Task 1), the table (Task 2 step 4), the helper move (Task 2 step 1), the README note (Task 2 step 6).
- **Placeholders:** none.
- **Type consistency:** `MESSAGE_TYPES` triples in Task 1 match the loop and the three readers; `mnemonic`/`colliding_mnemonics` names match between `tests/support.py`, the window test and the new test; `DIALOGS` construct each dialog with the constructor signatures on `main` (`TelexDialog(parent, recipient)`, `ConnectDialog(parent, fetch_simbrief=...)`, `PDCDialog(parent, fetch_simbrief=...)`, `WeatherSubscriptionsDialog(parent, weather_monitor, on_stop)`).
