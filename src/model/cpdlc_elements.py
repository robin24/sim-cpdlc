"""Standard FANS-1/A message elements shared across the request dialogs.

Keeping the exact wording in one place stops the same element being spelled
differently in different dialogs, which is how "DUE TO AIRCRAFT PERFORMANCE"
had drifted to "DUE TO PERFORMANCE" in every dialog that offered it.
"""

# DM65. The reason appended to a request when weather is the cause.
REASON_WEATHER = "WEATHER"

# DM66. The full wording matters: the standard element is "AIRCRAFT
# PERFORMANCE", not "PERFORMANCE".
REASON_AIRCRAFT_PERFORMANCE = "AIRCRAFT PERFORMANCE"
