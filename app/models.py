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


def get_current_utc_time() -> datetime:
    """Return the current time, timezone-aware, in UTC.

    Used as the default value for created_at / opened_at columns so every
    timestamp in the database is stamped by the server, never the client.
    """
    return datetime.now(timezone.utc)


def enum_values_only(enum_class) -> list[str]:
    """Turn a Python Enum class into a plain list of its string values.

    Example: SeverityEnum -> ["sev1", "sev2", "sev3"]

    SQLAlchemy needs this so the database enum type stores "sev1" instead
    of the Python name "SeverityEnum.sev1".
    """
    values = []
    for member in enum_class:
        values.append(member.value)
    return values


# ---------------------------------------------------------------------------
# Plain Python enums. Because they inherit from `str`, a value like
# StatusEnum.open behaves as the string "open" wherever needed.
# ---------------------------------------------------------------------------

class SeverityEnum(str, enum.Enum):
    sev1 = "sev1"
    sev2 = "sev2"
    sev3 = "sev3"


class StatusEnum(str, enum.Enum):
    open = "open"
    acknowledged = "acknowledged"
    resolved = "resolved"


# ---------------------------------------------------------------------------
# Table: services
# ---------------------------------------------------------------------------

class Service(Base):
    __tablename__ = "services"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    owner_team = Column(String(100), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=get_current_utc_time,
    )

    # One service can have many incidents.
    incidents = relationship("Incident", back_populates="service")


# ---------------------------------------------------------------------------
# Table: incidents
# ---------------------------------------------------------------------------

class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Foreign key pointing back to services.id.
    # ondelete="RESTRICT" means: you cannot delete a service that still
    # has incidents pointing at it.
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
            values_callable=enum_values_only,
        ),
        nullable=False,
    )

    status = Column(
        SAEnum(
            StatusEnum,
            name="status_enum",
            values_callable=enum_values_only,
        ),
        nullable=False,
        default=StatusEnum.open,
    )

    opened_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=get_current_utc_time,
    )

    resolved_at = Column(DateTime(timezone=True), nullable=True)

    # Lets you do incident.service.name instead of a manual query.
    service = relationship("Service", back_populates="incidents")