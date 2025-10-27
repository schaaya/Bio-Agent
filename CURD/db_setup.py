from decouple import config
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import create_engine, Column, Integer, Text, VARCHAR, JSON, Text, Boolean

from utility.decorators import time_it

DATABASE_URL = config('USERS_POSTGRES')

# Define the base class
StorageBase = declarative_base()

# Define the DBSchema model
class DBSchema(StorageBase):
    __tablename__ = 'db_schema'
    id = Column(Integer, primary_key=True, index=True)
    db_name = Column(VARCHAR, nullable=False)
    db_string = Column(Text, nullable=False)
    db_schema = Column(JSON, nullable=False)
    db_system = Column(VARCHAR, nullable=False)
    db_description = Column(Text)

# Define the UserGroup model
class UserGroup(StorageBase):
    __tablename__ = 'user_groups'
    id = Column(Integer, primary_key=True, index=True)
    group_name = Column(Text, unique=True, nullable=False)
    group_schema = Column(JSON, nullable=False)
    db_id = Column(VARCHAR, nullable=False)

class UserData(StorageBase):
    __tablename__ = 'user_data'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(Text, nullable=False)
    email = Column(Text, unique=True, nullable=False)
    password = Column(Text, nullable=False)
    disabled = Column(Boolean, default=False)
    admin = Column(Boolean, default=False)
    group_name = Column(Text, nullable=False)

class Schema_info(StorageBase):
    __tablename__ = 'schema_info'
    id = Column(Integer, primary_key=True, index=True)
    db_id = Column(Integer, nullable=False)
    table_name = Column(VARCHAR, nullable=False)
    description = Column(Text, nullable=False)
    db_name = Column(VARCHAR, nullable=False)

# Create the SQLAlchemy engine
engine = create_engine(DATABASE_URL)

# Create the tables in the database
StorageBase.metadata.create_all(bind=engine)

print("Tables created successfully.")
