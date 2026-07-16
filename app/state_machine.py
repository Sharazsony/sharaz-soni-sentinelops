"""
Status state machine for incidents.

Exactly two legal moves:
    open          -> acknowledged
    acknowledged  -> resolved

Every other combination (including no-op "transitions" to the same state,
and any attempt to move backwards) is a 409.
"""

from fastapi import HTTPException

from app.models import StatusEnum

ALLOWED_TRANSITIONS: dict[StatusEnum, set[StatusEnum]] = {
    StatusEnum.open: {StatusEnum.acknowledged},
    StatusEnum.acknowledged: {StatusEnum.resolved},
    StatusEnum.resolved: set(),
}


def assert_transition_allowed(current: StatusEnum, requested: StatusEnum) -> None:
    """Raise HTTPException(409, ...) if `current -> requested` is not legal."""
    if requested not in ALLOWED_TRANSITIONS.get(current, set()):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot transition incident from '{current.value}' to '{requested.value}'",
        )
