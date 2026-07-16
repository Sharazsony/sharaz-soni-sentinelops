from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import crud, schemas
from app.database import get_db

router = APIRouter()


@router.get(
    "/stats/services",
    response_model=List[schemas.ServiceStats],
    status_code=200,
    summary="Per-service open-incident count and mean time to resolve",
    tags=["stats"],
)
def service_stats(db: Session = Depends(get_db)):
    return crud.get_service_stats(db)
