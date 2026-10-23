"""AI defaults and internal request/output bounds.

Memory enablement is overlaid by profile settings; response and context limits
currently use application defaults; profile controls are a separate change.
"""

AI_MEMORY_ENABLED = True
AI_MAX_RESPONSE_LENGTH = 220
AI_MEMORY_MAX_ENTRIES = 5
AI_REQUEST_TIMEOUT_SECONDS = 60.0
