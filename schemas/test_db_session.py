import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager

load_dotenv()
TEST_DB = os.getenv("TEST_DB")

engine = create_engine(TEST_DB, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@contextmanager
def get_db_session():
    """
    Provides a transactional scope around a series of operations.
    Use this function as a context manager to obtain a database session.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

