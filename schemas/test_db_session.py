import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager

load_dotenv()

# Global variables for lazy initialization
_engine = None
_SessionLocal = None

def _ensure_initialized():
    """Lazy initialization of database engine and session maker"""
    global _engine, _SessionLocal

    if _engine is not None:
        return

    TEST_DB = os.getenv("TEST_DB")

    # Only create engine if TEST_DB is configured
    if TEST_DB:
        _engine = create_engine(TEST_DB, pool_pre_ping=True)
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    else:
        # TEST_DB not configured - this is OK for production
        # This module is only needed for testing/development
        _engine = None
        _SessionLocal = None

@contextmanager
def get_db_session():
    """
    Provides a transactional scope around a series of operations.
    Use this function as a context manager to obtain a database session.
    """
    _ensure_initialized()

    if _SessionLocal is None:
        raise RuntimeError(
            "TEST_DB environment variable not configured. "
            "This session is only available in test/development environments."
        )

    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()

