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


def assert_transition_allowed(current: StatusEnum, requested: StatusEnum) -> None:
    """Raise HTTPException(409, ...) if `current -> requested` is not legal."""

    # Rule 1: open -> acknowledged is allowed
    if current == StatusEnum.open and requested == StatusEnum.acknowledged:
        return  # legal move, do nothing (no error)

    # Rule 2: acknowledged -> resolved is allowed
    if current == StatusEnum.acknowledged and requested == StatusEnum.resolved:
        return  # legal move, do nothing (no error)

    # Anything else (same-state no-ops, skipping a step, going backwards)
    # is NOT allowed, so we raise a 409 error.
    raise HTTPException(
        status_code=409,
        detail=f"Cannot transition incident from '{current.value}' to '{requested.value}'",
    )