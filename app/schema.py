from typing import Optional, List
from pydantic import BaseModel, EmailStr


class UserAuth(BaseModel):
    email: EmailStr 
    username: str 
    password: str   

class UserOut(BaseModel):    
    username: str
    email: EmailStr
    disabled: bool
    
class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None

class TokenSchema(BaseModel):
    access_token: str
    refresh_token: str

class TokenPayload(BaseModel):
    email: EmailStr = None
    exp: int = None

class SystemUser(BaseModel):
    id : int
    username: str
    email: EmailStr
    disabled: bool
    admin: bool
    group_name : str 

class InstructionResponse(BaseModel):
    status: int
    data: List[dict]

class Instructions(BaseModel) :
    id : str
    instruction : str

class FeedbackRequest(BaseModel):
    feedback: str
    status: str
    time_stamp: str
    user: str
    feedmessage: str

class MsalUser(BaseModel):
    preferred_username : EmailStr
    name : str
    exp : int

class CompletionUsageEntry(BaseModel):
    user_id: int
    completion_tokens: int
    prompt_tokens: int
    total_tokens: int

class LogCompletionUsageRequest(BaseModel):
    entries: List[CompletionUsageEntry]

class LogCompletionUsageResponse(BaseModel):
    message: str
    logs: List[dict]