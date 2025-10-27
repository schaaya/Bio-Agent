"""
DEPRECATED: This file is deprecated and replaced by CURD/flexible_db_session.py

For backward compatibility, this file re-exports from the new flexible database system.
All imports should eventually migrate to:
    from CURD.flexible_db_session import get_app_db, AppBase
    from CURD.app_models import UserData, DBSchema, etc.
"""

from CURD.flexible_db_session import (
    AppBase as StorageBase,
    app_engine as storage_engine,
    AppSessionLocal as StorageSessionLocal,
)

from utility.decorators import time_it

# Backward-compatible wrapper that supports both next() and with statement
def get_storage_db():
    """
    Backward-compatible database session getter.

    Supports both old style (next()) and new style (with):
        Old: storage_db = next(get_storage_db())
        New: with get_storage_db() as storage_db:
    """
    session = StorageSessionLocal()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()