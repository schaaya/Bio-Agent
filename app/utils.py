# Description: This file contains utility functions that are used in the application.  
import os
import bcrypt
from jose import jwt
from typing import Union, Any
from dotenv import load_dotenv
from datetime import datetime, timedelta
from utility.decorators import time_it

load_dotenv()

ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 4  # 4 hours (increased from 30 minutes for better UX)
REFRESH_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days
ALGORITHM = "HS256"
JWT_SECRET_KEY = os.environ['JWT_SECRET_KEY']     # should be kept secret
JWT_REFRESH_SECRET_KEY = os.environ['JWT_REFRESH_SECRET_KEY']      # should be kept secret

@time_it
def get_hashed_password(password: str) -> str:
    password = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password, salt)
    return hashed.decode('utf-8')  # Decode to convert bytes to string

@time_it
def verify_password(password: str, hashed_pass: str) -> bool:
    password = password.encode('utf-8')
    hashed_pass = hashed_pass.encode('utf-8')
    return bcrypt.checkpw(password, hashed_pass)

@time_it
def create_access_token(subject: Union[str, Any], expires_delta: int = None) -> str:
    if expires_delta is not None:
        expires_delta = datetime.now() + expires_delta 
    else:
        expires_delta = datetime.now() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode = {"exp": round(expires_delta.timestamp()), "email": str(subject)} 
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, ALGORITHM)
    return encoded_jwt

@time_it
def create_refresh_token(subject: Union[str, Any], expires_delta: int = None) -> str:
    if expires_delta is not None:
        expires_delta = datetime.now() + expires_delta
    else:
        expires_delta = datetime.now() + timedelta(minutes=REFRESH_TOKEN_EXPIRE_MINUTES)
    
    to_encode = {"exp": round(expires_delta.timestamp()), "email": str(subject)} 
    encoded_jwt = jwt.encode(to_encode, JWT_REFRESH_SECRET_KEY, ALGORITHM)
    return encoded_jwt
