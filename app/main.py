import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.routers import incidents, services, stats

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(levelname)-5s %(name)s %(message)s",
)
logger = logging.getLogger("sentinelops")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Tables are created automatically on startup against an empty DB.
    Base.metadata.create_all(bind=engine)

    db_status = "connected"
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
        finally:
            db.close()
    except SQLAlchemyError:
        db_status = "unavailable"

    logger.info("sentinelops starting | env=%s | db=%s", settings.APP_ENV, db_status)
    yield


app = FastAPI(title="SentinelOps", version="1.0.0", lifespan=lifespan)

app.include_router(services.router)
app.include_router(incidents.router)
app.include_router(stats.router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Collapse FastAPI's default {"detail": [ {...}, {...} ]} shape into the
    single-string {"detail": "<string>"} envelope this API uses everywhere.
    """
    parts = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err.get("loc", []) if part != "body")
        msg = err.get("msg", "Invalid input")
        parts.append(f"{loc}: {msg}" if loc else msg)
    detail = "; ".join(parts) if parts else "Invalid request"
    return JSONResponse(status_code=422, content={"detail": detail})


@app.get("/health", summary="Liveness + DB connectivity check", tags=["health"])
def health():
    """
    Required, unauthenticated. Does NOT count against the six-endpoint
    budget and is EXEMPT from the {"detail": ...} error envelope — it
    returns exactly one of the two bodies below.
    """
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "ok"}
    except SQLAlchemyError:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "database": "unavailable"},
        )
    finally:
        db.close()
