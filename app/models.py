"""
SQLAlchemy ORM models ONLY. No Pydantic here (see app/schemas.py for that).

Two tables:
    services  <──FK── incidents (incidents.service_id -> services.id, ON DELETE RESTRICT)

Two native PostgreSQL enum types:
    severity_enum: sev1 | sev2 | sev3
    status_enum:   open | acknowledged | resolved

This is why the app can only run against PostgreSQL, never SQLite.
"""

import enum
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SeverityEnum(str, enum.Enum):
    sev1 = "sev1"
    sev2 = "sev2"
    sev3 = "sev3"


class StatusEnum(str, enum.Enum):
    open = "open"
    acknowledged = "acknowledged"
    resolved = "resolved"


class Service(Base):
    __tablename__ = "services"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    owner_team = Column(String(100), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    incidents = relationship(
        "Incident", back_populates="service", passive_deletes=False
    )


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    service_id = Column(
        Integer,
        ForeignKey("services.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    title = Column(String(200), nullable=False)
    severity = Column(
        SAEnum(
            SeverityEnum,
            name="severity_enum",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
    )
    status = Column(
        SAEnum(
            StatusEnum,
            name="status_enum",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
        default=StatusEnum.open,
        server_default=StatusEnum.open.value,
    )
    opened_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    service = relationship("Service", back_populates="incidents")
