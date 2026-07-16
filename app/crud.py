"""
All SQLAlchemy queries for this service live in this module.

Layering rule (see README "Architecture"): routers parse input, call a
function here, and shape the HTTP response. Routers never build a `select()`,
never touch a `Session` directly beyond passing it through, and never contain
raw SQL strings.
"""

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app import models, schemas

# ---------------------------------------------------------------- services --


def get_service_by_name(db: Session, name: str) -> Optional[models.Service]:
    return db.query(models.Service).filter(models.Service.name == name).first()


def get_service(db: Session, service_id: int) -> Optional[models.Service]:
    return db.query(models.Service).filter(models.Service.id == service_id).first()


def create_service(db: Session, service_in: schemas.ServiceCreate) -> models.Service:
    service = models.Service(name=service_in.name, owner_team=service_in.owner_team)
    db.add(service)
    db.commit()
    db.refresh(service)
    return service


def list_services(db: Session) -> List[models.Service]:
    return db.query(models.Service).order_by(models.Service.id.asc()).all()


# --------------------------------------------------------------- incidents --


def get_incident(db: Session, incident_id: int) -> Optional[models.Incident]:
    return db.query(models.Incident).filter(models.Incident.id == incident_id).first()


def create_incident(db: Session, incident_in: schemas.IncidentCreate) -> models.Incident:
    incident = models.Incident(
        service_id=incident_in.service_id,
        title=incident_in.title,
        severity=incident_in.severity,
        status=models.StatusEnum.open,
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)
    return incident


def _filtered_incidents_query(
    db: Session,
    status: Optional[models.StatusEnum],
    severity: Optional[models.SeverityEnum],
    service_id: Optional[int],
):
    query = db.query(models.Incident)
    if status is not None:
        query = query.filter(models.Incident.status == status)
    if severity is not None:
        query = query.filter(models.Incident.severity == severity)
    if service_id is not None:
        query = query.filter(models.Incident.service_id == service_id)
    return query


def list_incidents(
    db: Session,
    status: Optional[models.StatusEnum] = None,
    severity: Optional[models.SeverityEnum] = None,
    service_id: Optional[int] = None,
    limit: int = 20,
    offset: int = 0,
) -> Tuple[int, List[models.Incident]]:
    """
    Returns (total, items).

    `total` is the count of rows matching the filters, ignoring limit/offset.
    Both the count and the page are built from the SAME filter set so they
    can never drift apart.
    """
    base_query = _filtered_incidents_query(db, status, severity, service_id)

    total = base_query.with_entities(func.count(models.Incident.id)).scalar()

    items = (
        base_query.order_by(models.Incident.opened_at.desc(), models.Incident.id.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    return total, items


def update_incident_status(
    db: Session, incident: models.Incident, new_status: models.StatusEnum
) -> models.Incident:
    incident.status = new_status
    if new_status == models.StatusEnum.resolved:
        incident.resolved_at = datetime.now(timezone.utc)
    db.add(incident)
    db.commit()
    db.refresh(incident)
    return incident


# -------------------------------------------------------------------- stats --


def get_service_stats(db: Session) -> List[dict]:
    """
    One row per service (including services with zero incidents), computed
    with a single LEFT OUTER JOIN + aggregate query — no N+1 loop.

    - open_count: incidents with status == 'open' exactly (acknowledged does
      not count).
    - mean_time_to_resolve_minutes: AVG() over resolved incidents'
      (resolved_at - opened_at) in minutes, NULL (-> None) when there are
      zero resolved incidents for that service. AVG() ignores SQL NULLs,
      which is exactly the "resolved only" semantics we want.
    """
    open_case = case((models.Incident.status == models.StatusEnum.open, 1), else_=0)
    resolved_minutes_case = case(
        (
            models.Incident.status == models.StatusEnum.resolved,
            func.extract(
                "epoch", models.Incident.resolved_at - models.Incident.opened_at
            )
            / 60.0,
        ),
        else_=None,
    )

    rows = (
        db.query(
            models.Service.id.label("service_id"),
            models.Service.name.label("service_name"),
            func.coalesce(func.sum(open_case), 0).label("open_count"),
            func.avg(resolved_minutes_case).label("mttr"),
        )
        .outerjoin(models.Incident, models.Incident.service_id == models.Service.id)
        .group_by(models.Service.id, models.Service.name)
        .order_by(models.Service.id.asc())
        .all()
    )

    return [
        {
            "service_id": row.service_id,
            "service_name": row.service_name,
            "open_count": int(row.open_count),
            "mean_time_to_resolve_minutes": (
                round(float(row.mttr), 1) if row.mttr is not None else None
            ),
        }
        for row in rows
    ]
