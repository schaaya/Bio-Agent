from sqlalchemy import Column, String, Text
from decouple import config
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from utility.decorators import time_it

DATABASE_URL = config('INSTRUCTIONS_POSTGRES')

Base = declarative_base()
storage_engine = create_engine(DATABASE_URL)
StorageSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=storage_engine)

@time_it
def get_db():
    db = StorageSessionLocal()
    try:
        return db
    finally:
        db.close()
        
class CustomInstructionDB(Base):
    __tablename__ = "custom_instructions"
    
    user_id = Column(String,primary_key=True, index=True)
    
    instructions = Column(Text, nullable=True)
    
    @time_it
    def to_dict(self):
        return {
            "user_id": self.user_id,
            "instructions": self.instructions,
        }