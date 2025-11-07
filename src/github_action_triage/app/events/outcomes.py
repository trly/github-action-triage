from enum import Enum


class TriageOutcome(str, Enum):
    FIX_APPLIED = "fix_applied"
    ANALYZED = "analyzed"
    DEFERRED = "deferred"
    UNSUPPORTED = "unsupported"
