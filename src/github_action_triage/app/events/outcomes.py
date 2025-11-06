from enum import Enum


class TriageOutcome(str, Enum):
    FIX_APPLIED = "fix_applied"
    DEFERRED = "deferred"
    UNSUPPORTED = "unsupported"
