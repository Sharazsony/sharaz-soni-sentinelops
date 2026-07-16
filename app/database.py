"""
Engine / session / Base / get_db().

Every route that touches the DB obtains its session via
`db: Session = Depends(get_db)` — no route calls SessionLocal() directly,
and the engine is created lazily enough that tests can override get_db.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, future=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
