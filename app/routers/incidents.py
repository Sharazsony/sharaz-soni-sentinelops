import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.database import get_db
from app.state_machine import assert_transition_allowed

logger = logging.getLogger("sentinelops")

router = APIRouter()


@router.post(
    "/incidents",
    response_model=schemas.IncidentRead,
    status_code=201,
    summary="Create an incident for a service",
    tags=["incidents"],
)
def create_incident(payload: schemas.IncidentCreate, db: Session = Depends(get_db)):
    service = crud.get_service(db, payload.service_id)
    if service is None:
        raise HTTPException(
            status_code=404, detail=f"Service {payload.service_id} not found"
        )
    incident = crud.create_incident(db, payload)
    logger.info(
        "incident.created id=%s service_id=%s severity=%s",
        incident.id,
        incident.service_id,
        incident.severity.value,
    )
    return incident


@router.get(
    "/incidents",
    response_model=schemas.IncidentListResponse,
    status_code=200,
    summary="List incidents with filtering and pagination",
    tags=["incidents"],
)
def list_incidents(
    status: Optional[models.StatusEnum] = None,
    severity: Optional[models.SeverityEnum] = None,
    service_id: Optional[int] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    total, items = crud.list_incidents(
        db,
        status=status,
        severity=severity,
        service_id=service_id,
        limit=limit,
        offset=offset,
    )
    return {"total": total, "limit": limit, "offset": offset, "items": items}


@router.patch(
    "/incidents/{incident_id}/status",
    response_model=schemas.IncidentRead,
    status_code=200,
    summary="Advance an incident's status through the state machine",
    tags=["incidents"],
)
def update_status(
    incident_id: int, payload: schemas.StatusUpdate, db: Session = Depends(get_db)
):
    incident = crud.get_incident(db, incident_id)
    if incident is None:
        raise HTTPException(
            status_code=404, detail=f"Incident {incident_id} not found"
        )

    assert_transition_allowed(incident.status, payload.status)

    old_status = incident.status.value
    incident = crud.update_incident_status(db, incident, payload.status)
    logger.info(
        "incident.status_changed id=%s %s -> %s",
        incident.id,
        old_status,
        incident.status.value,
    )
    return incident
