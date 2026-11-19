from typing import Literal

JoinCodeStatus = Literal["active", "paused", "revoked"]
ApprovalMode = Literal["auto", "manual"]

# 30 letters and digits without look-alikes (no I L O U 0 1). 8 characters = ~39 bits of
# randomness, shown as K7M2-9QXA (join-codes.md).
ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"
LENGTH = 8

# A code only lets people join once its structure is open for reports.
CLAIMABLE_FORM_STATUSES = ("pilot", "active")
