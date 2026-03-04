# TODOS — Code Review Issues

Prioritized list of bugs and issues found during code review.

---

## Critical

### ~~1. Unhandled exception in poll timer can silently stop polling~~ DONE

### ~~2. Event handler accumulation on context menu creation~~ DONE

### ~~3. Update checker thread can call wx.CallAfter on destroyed window~~ DONE

---

## High

### ~~4. `network_type` not initialized in `__init__`, relies on `hasattr` check~~ DONE

### ~~5. Config file write is not atomic~~ DONE

### ~~6. `isinstance` check not used for TelexMessage~~ DONE

### ~~7. `import re` inside frequently-called method~~ DONE

---

## Medium

### ~~8. No validation that acknowledgement sender matches current station~~ DONE

### ~~9. Message log grows unbounded~~ WON'T FIX
Typical sessions are single flights (1-4 hours, a few hundred messages at most). Not worth the complexity of eviction logic.

### ~~10. SimBrief API failures silently swallowed in dialogs~~ DONE

### ~~11. Exception handling in connection_manager loses error context~~ DONE

### ~~12. `send_logoff_message()` duplicates `logoff()` logic~~ DONE

### ~~13. Hardcoded dialog sizes don't adapt to DPI/screen size~~ DONE

### ~~14. `format_message_text` swallows all exceptions~~ DONE

---

## Low

### ~~15. No format validation on PDC dialog fields~~ DONE

### ~~16. Altitude change dialog accepts unrealistic values~~ DONE

### ~~17. Logon dialog validation mismatch~~ DONE

### ~~18. Context menu items lack descriptive labels for screenreaders~~ DONE

### ~~19. Sound file missing shows error icon instead of warning~~ DONE

### ~~20. Menu item help strings have leading spaces~~ DONE

---

## CPDLC Protocol Conformance (from Hoppie ACARS log analysis)

### ~~21. Acknowledgements sent with wrong Response Requirement code — HIGH~~ DONE
**File:** `src/model/cpdlc_session.py:225`

`send_acknowledgement()` sends responses with `RR.NOT_REQUIRED` (`NE`), but real Hoppie network traffic consistently uses `RR.NO` (`N`) for acknowledgement/response messages.

- Real traffic: `/data2/4/5/N/WILCO`, `/data2/1/2/N/WILCO`
- Code produces: `/data2/X/Y/NE/WILCO`

`N` means "no further response needed" (standard for responses); `NE` means "not expected" (used for informational messages like LOGOFF or status updates). Some ATC clients may not correctly process acknowledgements sent with `NE`.

### ~~22. `_get_cpdlc_responses` mishandles RR.YES and RR.NO — MEDIUM~~ DONE
**File:** `src/model/message_manager.py:204-208`

- `RR.YES` (Y) means "a yes/no response is required" — code only offers `"YES"`. Should offer both `"YES"` and `"NO"`.
- `RR.NO` (N) means "no response required" (used on response messages) — code offers `"NO"` as a response option. Should offer **nothing** (same semantic as `NE`).

These RR codes are rare in pilot-bound messages but the logic is still incorrect.

### ~~23. Message type detection uses fragile substring matching on raw packet content — MEDIUM~~ DONE
**File:** `src/gui/main_window.py:596-654`

`_on_message_received` checks for `"LOGON ACCEPTED"`, `"HANDOVER"`, and `"LOGOFF"` as substring matches against the raw packet content (including `/data2/MIN/MRN/RR/` prefix). A message like `"LOGOFF NOT REQUIRED AT THIS TIME"` from the current station would incorrectly trigger the logoff handler. Checks should be performed on extracted message text and use more precise matching (exact or starts-with).

### ~~24. No MRN validation on LOGON ACCEPTED — LOW~~ DONE
**File:** `src/gui/main_window.py:600-605`

When `LOGON ACCEPTED` is received, the code updates session state for any sender without checking the MRN field to verify it's a response to the pilot's `REQUEST LOGON`. A misdirected `LOGON ACCEPTED` could change session state. Real traffic: `/data2/1/1/NE/LOGON ACCEPTED` where MRN=1 references the pilot's MIN=1.
