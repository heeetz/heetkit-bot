"""AI defaults and internal request/output bounds.

Profile AI setup overlays question/answer character limits; provider token and
total-time bounds remain separate. These defaults preserve older profiles.
"""

AI_MEMORY_ENABLED = True
AI_MAX_RESPONSE_LENGTH = 220
AI_REQUEST_TIMEOUT_SECONDS = 60.0
