"""
Pydantic v2 models ONLY. No SQLAlchemy here (see app/models.py for that).

Create-schemas never accept server-controlled fields (id, created_at,
opened_at, resolved_at, status-on-create) — those columns simply do not
exist on the Create models, so a client sending them has the value ignored.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models import SeverityEnum, StatusEnum


# ---------------------------------------------------------------- services --

class ServiceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    owner_team: str = Field(..., min_length=1, max_length=100)


class ServiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    owner_team: str
    created_at: datetime


# --------------------------------------------------------------- incidents --

class IncidentCreate(BaseModel):
    service_id: int
    title: str = Field(..., min_length=1, max_length=200)
    severity: SeverityEnum


class IncidentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    service_id: int
    title: str
    severity: SeverityEnum
    status: StatusEnum
    opened_at: datetime
    resolved_at: Optional[datetime] = None


class IncidentListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[IncidentRead]


class StatusUpdate(BaseModel):
    status: StatusEnum


# -------------------------------------------------------------------- stats --

class ServiceStats(BaseModel):
    service_id: int
    service_name: str
    open_count: int
    mean_time_to_resolve_minutes: Optional[float] = None
