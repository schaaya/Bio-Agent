"""
Application Database Models
============================

Defines the SQLAlchemy models for application data:
- UserData: User accounts and authentication
- UserGroup: User groups with database access permissions
- DBSchema: Database schema definitions
- Schema_info: Table and column descriptions

These models work with both SQLite (local) and PostgreSQL (production).
"""

from sqlalchemy import Column, Integer, Text, VARCHAR, JSON, Boolean
from CURD.flexible_db_session import AppBase

class UserData(AppBase):
    """User account information"""
    __tablename__ = 'user_data'

    id = Column(Integer, primary_key=True, index=True)
    name = Column(Text, nullable=False)
    email = Column(Text, unique=True, nullable=False, index=True)
    password = Column(Text, nullable=False)
    disabled = Column(Boolean, default=False)
    admin = Column(Boolean, default=False)
    group_name = Column(Text, nullable=False, index=True)

class UserGroup(AppBase):
    """User groups with database access permissions"""
    __tablename__ = 'user_groups'

    id = Column(Integer, primary_key=True, index=True)
    group_name = Column(Text, unique=True, nullable=False, index=True)
    group_schema = Column(JSON, nullable=False)
    db_id = Column(VARCHAR, nullable=False)

class DBSchema(AppBase):
    """Database schema definitions"""
    __tablename__ = 'db_schema'

    id = Column(Integer, primary_key=True, index=True)
    db_name = Column(VARCHAR, nullable=False, index=True)
    db_string = Column(Text, nullable=False)
    db_schema = Column(JSON, nullable=False)
    db_system = Column(VARCHAR, nullable=False)
    db_description = Column(Text)
    db_status = Column(Boolean, default=True)
    db_column_description = Column(JSON, nullable=False)

class Schema_info(AppBase):
    """Table and column descriptions"""
    __tablename__ = 'schema_info'

    id = Column(Integer, primary_key=True, index=True)
    db_id = Column(Integer, nullable=False, index=True)
    table_name = Column(VARCHAR, nullable=False, index=True)
    description = Column(Text, nullable=False)
    db_name = Column(VARCHAR, nullable=False, index=True)
