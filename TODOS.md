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

### 9. Message log grows unbounded — DEFERRED
**File:** `src/model/message_manager.py`
`message_log` dict and `acknowledged_messages` set grow indefinitely. Very slow leak; typical sessions are single flights. Requires design decisions on cap size and UI behavior.

### ~~10. SimBrief API failures silently swallowed in dialogs~~ DONE

### 11. Exception handling in connection_manager loses error context — DEFERRED
**File:** `src/model/connection_manager.py` (multiple locations)
Changing return type from `bool` to include error info requires touching all callers. Larger refactor.

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
