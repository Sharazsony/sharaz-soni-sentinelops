import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import crud, schemas
from app.database import get_db

logger = logging.getLogger("sentinelops")

router = APIRouter()


@router.post(
    "/services",
    response_model=schemas.ServiceRead,
    status_code=201,
    summary="Create a service",
    tags=["services"],
)
def create_service(payload: schemas.ServiceCreate, db: Session = Depends(get_db)):
    existing = crud.get_service_by_name(db, payload.name)
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Service with name '{payload.name}' already exists",
        )
    try:
        service = crud.create_service(db, payload)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Service with name '{payload.name}' already exists",
        )
    logger.info("service.created id=%s name=%s", service.id, service.name)
    return service


@router.get(
    "/services",
    response_model=List[schemas.ServiceRead],
    status_code=200,
    summary="List all services",
    tags=["services"],
)
def list_services(db: Session = Depends(get_db)):
    return crud.list_services(db)
