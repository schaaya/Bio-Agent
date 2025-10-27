from pydantic import BaseModel
from typing import Optional

class CustomInstructionsCreate(BaseModel):
    instructions: Optional[str] = None


class CustomInstructionsRead(BaseModel):
    user_id: str
    instructions: str
    
    class Config:
        from_attributes = True
        
class CustomInstructionsUpdate(BaseModel):
    instructions: Optional[str] = None


class ResponseMessage(BaseModel):
    success: bool
    message: str
    data: Optional[dict] = None