import os
import requests
from jose import jwt
import core.user_db as db
from datetime import datetime
from termcolor import colored
from dotenv import load_dotenv
from pydantic import ValidationError
from jwt.algorithms import RSAAlgorithm
from fastapi import HTTPException, status
from app.schema import TokenPayload, SystemUser, MsalUser
from CURD.user_CURD import UserData
from utility.decorators import time_it

load_dotenv()

JWT_SECRET_KEY = os.environ['JWT_SECRET_KEY']     # should be kept secret

AZAD_SECRET_KEY = os.environ['CLIENT_SECRET']     # should be kept secret
AZAD_CLIENT_ID = os.environ['CLIENT_ID'] # should be kept secret
AZAD_TENANT_ID = os.environ['TENANT_ID']     

ALGORITHM = "HS256"

class AuthError(Exception):
    def __init__(self, error_msg:str, status_code:int):
        super().__init__(error_msg)

        self.error_msg = error_msg
        self.status_code = status_code


@time_it
async def user_verification(token: str) -> SystemUser:

    try:
        token_version = await get_token_version(token)

        if token_version:
            payload = await msal_verify_user(token, token_version)
            token_data = MsalUser(**payload)
            user_email = token_data.preferred_username

        else:
            payload = await bi_bot_user_verify(token)
            token_data = TokenPayload(**payload)
            user_email = token_data.email


        if datetime.fromtimestamp(token_data.exp) < datetime.now():
            print(colored(f"Token expired at:{ datetime.fromtimestamp(token_data.exp)}", "red"))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expired",
                headers={"WWW-Authenticate": "Bearer"},
            )

        print(colored(f"Token subject (user id): {user_email}", "blue"))

        user = await db.get_user(user_email)
        user_data = { 'id' : user.id,
                    'username': user.name,
                    'email': user.email,
                    'disabled': user.disabled,
                    'admin': user.admin,
                    'group_name': user.group_name}

        if user is None:
            print(colored(f"User not found in database for id: {user_email}", "red"))
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Could not find user",
            )

        return SystemUser(**user_data)
    except Exception as e:
            print(colored(f"User validation error: {e}", "red"))
            raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

@time_it
async def msal_verify_user(token: str, token_version) -> SystemUser:

    tenant_id = AZAD_TENANT_ID
    client_id= AZAD_CLIENT_ID
    
    keys = await get_public_keys()

    if token_version == "1.0":
        _issuer = f'https://sts.windows.net/{tenant_id}/'
        _audience=f'api://{client_id}'
    else:
        _issuer = f'https://login.microsoftonline.com/{tenant_id}/v2.0'
        _audience=f'{client_id}'
    try:
        unverified_header = jwt.get_unverified_header(token)
        key_id = unverified_header['kid']
        public_key = await get_public_key(key_id, keys)
        
        if not public_key:
            return "Public key not found"

        # Decode and verify the token
        payload = jwt.decode(token, public_key, algorithms=['RS256'], audience=_audience)

    except jwt.ExpiredSignatureError:
        raise AuthError("Token error: The token has expired", 401)
    except jwt.JWTClaimsError:
        raise AuthError("Token error: Please check the audience and issuer", 401)
    except Exception:
        raise AuthError("Token error: Unable to parse authentication", 401)
    except (jwt.JWTError, ValidationError) as e:
        print(colored(f"JWT decode error or validation error: {e}", "red"))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


@time_it
async def get_token_version(token):
    unverified_claims = jwt.get_unverified_claims(token)
    if unverified_claims.get("ver"):
        return unverified_claims["ver"]   
    else:
        return None

@time_it
async def get_public_keys():
    jwks_url = "https://login.microsoftonline.com/common/discovery/v2.0/keys"
    response = requests.get(jwks_url)
    keys = response.json()
    return keys['keys']

# Find the public key corresponding to the token's key ID
@time_it
async def get_public_key(key_id, keys):
    for key in keys:
        if key['kid'] == key_id:
            return RSAAlgorithm.from_jwk(key)
    return None
@time_it
async def bi_bot_user_verify(token:str) -> TokenPayload:
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[ALGORITHM])
        return payload

    except (jwt.JWTError, ValidationError) as e:
        print(colored(f"JWT decode error or validation error: {e}", "red"))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    