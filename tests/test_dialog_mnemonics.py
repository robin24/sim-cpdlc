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
