# Dialog access keys — design

## Purpose

Audit finding I-4: access keys (mnemonics) and accessible names are applied
unevenly across the dialogs. The weather request dialog and the automatic
weather updates dialog have them; the nine other dialogs have none, so a
keyboard or screen-reader user reaches every field by Tab alone, and the
only mnemonic test covers the menus. This design gives every dialog the same
convention and a test that enforces it, the way the menu test does.

## Convention

1. Every control a keyboard user focuses has an access key, unique within its
   dialog. wx marks it with `&` in the label.
   - An input control (`wx.TextCtrl`, `wx.Choice`, `wx.SpinCtrl`, `wx.ListBox`)
     is labelled by the `wx.StaticText` created immediately before it; that
     label carries the key, so Alt+letter focuses the input.
   - A `wx.CheckBox`, `wx.RadioButton` or `wx.RadioBox` carries its own key in
     its label.
   - A `wx.Button` carries its own key, except the buttons with the `wx.ID_OK`
     or `wx.ID_CANCEL` ids, which Enter and Escape already reach (they may
     still carry one, as the subscriptions dialog's `&Close` does).
2. Every input control has an accessible name, `SetName(...)`, equal to its
   label without the `&` and without the trailing colon.
3. Explanatory static texts (helper lines, status lines, headings above a
   radio group) carry no access key: a stray `&` would steal a letter from a
   control. A literal ampersand is written `&&`.
4. The when-can-we radio buttons read in sentence case ("Higher level",
   "Climb to FL"); the downlink text they build is unchanged
   (`WHEN CAN WE EXPECT HIGHER LEVEL`, `... CLIMB TO FL350`, `... M082`,
   `... 300K`).

## Access keys per dialog

| Dialog | Labels (key) |
|---|---|
| Logon | `&Station:` (S) |
| Altitude change | `Requested &Altitude (FL):` (A); `&None` (N), `Due to &weather` (W), `Due to aircraft &performance` (P) |
| Direct to | `&Fix / Waypoint:` (F); `&None`, `Due to &weather`, `Due to aircraft &performance` |
| Speed change | `&Mach` (M), `&Knots` (K); `Speed &value:` (V); `&None`, `Due to &weather`, `Due to aircraft &performance` |
| When can we expect | `&Higher level` (H), `&Lower level` (L), `&Back on route` (B), `&Climb to FL` (C), `&Descent to FL` (D), `&Mach` (M), `&Speed (knots)` (S); `&Value:` (V) |
| Telex | `&To:` (T), `&Message:` (M) |
| PDC | `&Departure ICAO:` (D), `Des&tination ICAO:` (T), `Aircraft &code:` (C), `&Stand number:` (S), `&ATIS:` (A) |
| Connect | `&Network` (N, the radio box), `&Callsign:` (C), `&Logon code:` (L) |
| Settings | `&SayIntentions Logon code:` (S), `&Hoppie Logon code:` (H), `SimBrief &User ID:` (U), `&Automatically check for updates` (A), `Auto-&tune COM1 standby on CONTACT/MONITOR` (T), `Automatic &weather update interval (minutes):` (W) |
| Weather request | unchanged: `&Report type:` (R), `Airport &ICAO code:` (I), `&Keep this report updated automatically` (K) |
| Automatic weather updates | `&Reports being kept up to date:` (R); buttons unchanged: `Check &now` (N), `&Stop updating` (S), `Stop &all` (A), `&Close` (C) |

Headings that carry no key: `Reason (optional):`, `Speed type:`,
`Request type:`. Helper, status and counter texts carry none.

## Test

`tests/test_dialog_mnemonics.py`, parametrized over the eleven dialogs, walks
`GetChildren()` (creation order) and asserts, per dialog:

- no two labels claim the same letter;
- every input control is preceded by a `wx.StaticText` whose label has a key,
  and the control's `GetName()` equals that label without `&` and colon;
- every check box, radio button, radio box and non-OK/Cancel button has a key;
- a `wx.StaticText` not followed by an input control has no key.

The `_mnemonic` and `_colliding_mnemonics` helpers move from
`tests/test_main_window.py` to `tests/support.py` so both tests share them.

## Out of scope

Menu accelerators (`CTRL+S`, `CTRL+O`, ...) reusing OS conventions; the main
window's list and detail pane, which the menus already reach.
