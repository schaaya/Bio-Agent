"""
Flexible Database Session Manager
==================================

This module provides a unified database session that works with:
- SQLite for local/dev environments (hassle-free, no server needed)
- PostgreSQL for production environments (Azure Postgres)

Usage:
    from CURD.flexible_db_session import get_app_db, AppBase, init_db

    # Initialize DB on startup
    init_db()

    # Use in your code
    with get_app_db() as db:
        user = db.query(UserData).first()

Environment Variables:
    USE_LOCAL_DB=true          # Use SQLite (default for dev)
    USE_LOCAL_DB=false         # Use PostgreSQL (for production)
    LOCAL_DB_PATH=./data/app.db  # SQLite file path (optional)
    APP_DB_POSTGRES=...        # PostgreSQL connection string (for production)
"""

import os
from pathlib import Path
from contextlib import contextmanager
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from termcolor import colored

load_dotenv()

# Determine which database to use
USE_LOCAL_DB = os.getenv("USE_LOCAL_DB", "true").lower() == "true"
LOCAL_DB_PATH = os.getenv("LOCAL_DB_PATH", "./data/app_storage.db")
# Use dedicated app database URL for production (separate from USERS_POSTGRES)
POSTGRES_URL = os.getenv("APP_DB_POSTGRES")

# Create declarative base for app tables
AppBase = declarative_base()

def get_database_url():
    """Get the appropriate database URL based on environment"""
    if USE_LOCAL_DB:
        # Ensure the directory exists
        db_path = Path(LOCAL_DB_PATH)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        database_url = f"sqlite:///{LOCAL_DB_PATH}"
        print(colored(f"📁 Using Local SQLite DB: {LOCAL_DB_PATH}", "cyan"))
    else:
        if not POSTGRES_URL:
            raise ValueError(
                "APP_DB_POSTGRES environment variable must be set when USE_LOCAL_DB=false"
            )
        database_url = POSTGRES_URL
        print(colored(f"🐘 Using PostgreSQL DB (Production): {POSTGRES_URL.split('@')[1].split('/')[0]}", "green"))

    return database_url

# Create engine with appropriate settings
database_url = get_database_url()

if USE_LOCAL_DB:
    # SQLite specific settings
    app_engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False},  # Required for SQLite
        pool_pre_ping=True
    )
else:
    # PostgreSQL specific settings
    app_engine = create_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20
    )

# Create session factory
AppSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=app_engine)

@contextmanager
def get_app_db():
    """
    Get a database session for application data.

    Usage:
        with get_app_db() as db:
            users = db.query(UserData).all()
    """
    session = AppSessionLocal()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()

def init_db():
    """
    Initialize the database by creating all tables.
    Call this on application startup.
    """
    print(colored("\n" + "="*60, "cyan"))
    print(colored("🗄️  Initializing Application Database", "cyan", attrs=["bold"]))
    print(colored("="*60, "cyan"))

    # Import all models here so they're registered with AppBase
    from CURD.app_models import UserData, UserGroup, DBSchema, Schema_info

    # Create all tables
    AppBase.metadata.create_all(bind=app_engine)

    print(colored("✅ Database tables initialized successfully!", "green"))
    print(colored("="*60 + "\n", "cyan"))

def get_db_info():
    """Get information about the current database configuration"""
    return {
        "type": "SQLite" if USE_LOCAL_DB else "PostgreSQL",
        "url": database_url if not USE_LOCAL_DB else LOCAL_DB_PATH,
        "engine": app_engine
    }

# For backward compatibility, provide the old names
StorageBase = AppBase
storage_engine = app_engine
StorageSessionLocal = AppSessionLocal
get_storage_db = get_app_db
