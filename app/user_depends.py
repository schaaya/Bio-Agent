import core.user_db as db
from termcolor import colored
from core.logger import log_error
from app.dep import user_verification
from core.logger import log_login_logout
from app.utils import get_hashed_password
from app.schema import TokenSchema, SystemUser
from CURD.user_CURD import get_storage_db, UserData
from fastapi.security import OAuth2PasswordRequestForm
from fastapi import status, HTTPException, Depends, APIRouter, Response, Request
from app.utils import (create_access_token, create_refresh_token, verify_password)
from utility.decorators import time_it

router = APIRouter()

@time_it
async def get_admin_status(request: Request):
    token = request.cookies.get("access_token")
    if token is None:
        raise HTTPException(status_code=401, detail= 'No Token recevied')
    user = await user_verification(token)
    if user.disabled is True:
        raise HTTPException(status_code=401, detail= 'User Disabled')  
    if user.admin is True:
        return user
    else:
        raise HTTPException(status_code=401, detail="Not an Admin")    
    
@router.post('/login', summary="Create access and refresh tokens for user", response_model=TokenSchema)
@time_it
async def login(response: Response, form_data: OAuth2PasswordRequestForm = Depends()):
    user = await db.get_user(form_data.username)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect email or password"
        )
    hashed_pass = user.password
    if not verify_password(form_data.password, hashed_pass):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect email or password"
        )
    
    access_token = create_access_token(user.email)
    refresh_token = create_refresh_token(user.email)

    # Set access token cookie with max_age matching token expiration
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=True,
        samesite="None",  # ✅ required for cross-origin cookies
        max_age=60 * 60 * 4  # 4 hours in seconds (matches ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    # Set refresh token cookie for automatic token refresh
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="None",
        max_age=60 * 60 * 24 * 7  # 7 days in seconds (matches REFRESH_TOKEN_EXPIRE_MINUTES)
    )

    # globals.users_whitelist.add(user[1])
     # Log the login activity
    await log_login_logout(user_id=user.email, activity="login", status_code=200)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
    }


@router.get('/me', summary='Get details of currently logged in user', response_model=SystemUser)
@time_it
async def get_me(token: str):
    user = await user_verification(token)
    return user


@router.post("/refresh", summary="Refresh access token using refresh token")
@time_it
async def refresh_token_endpoint(request: Request, response: Response):
    """
    Refresh the access token using the refresh token from cookies.
    This allows users to stay logged in without re-entering credentials.
    """
    refresh_token = request.cookies.get("refresh_token")

    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token not found"
        )

    try:
        # Verify the refresh token
        from jose import jwt, JWTError
        from app.utils import JWT_REFRESH_SECRET_KEY, ALGORITHM

        payload = jwt.decode(refresh_token, JWT_REFRESH_SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("email")

        if email is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token"
            )

        # Verify user still exists and is active
        user = await db.get_user(email)
        if user is None or user.disabled:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or disabled"
            )

        # Create new access token
        new_access_token = create_access_token(user.email)

        # Set new access token cookie
        response.set_cookie(
            key="access_token",
            value=new_access_token,
            httponly=True,
            secure=True,
            samesite="None",
            max_age=60 * 60 * 4  # 4 hours (matches ACCESS_TOKEN_EXPIRE_MINUTES)
        )

        return {
            "access_token": new_access_token,
            "message": "Token refreshed successfully"
        }

    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token"
        )


@router.post("/logout", summary="Log out the current user")
@time_it
async def logout(request: Request, response: Response):
    response.delete_cookie(key="access_token")
    response.delete_cookie(key="refresh_token")  # Also delete refresh token
    return {"message": "Successfully logged out"}

@router.put('/change_password')
@time_it
async def update_user_data(request: Request,  password: str = None):
    token = request.cookies.get("access_token")
    if token is None:
        raise HTTPException(status_code=401, detail= 'No Token recevied')
    user = await user_verification(token)
    user_id = user.id
    # Validate the group_name if provided
    if password is not None:
        password = get_hashed_password(password)
    
    storage_db = next(get_storage_db())
    try:
        user_data = storage_db.query(UserData).filter(UserData.id == user_id).first()
        
        if user_data is None:
            await log_error(user_id, e, "User data not found")
            raise HTTPException(status_code=404, detail="User data not found")
        
        if password is not None:
            user_data.password = password

        storage_db.commit()
        storage_db.refresh(user_data)
        return {'status': 200, 'message': 'User Password updated successfully', 'user_data': {
            'id': user_data.id,
        }}
    except Exception as e:
        await log_error(user_id, e, "Error updating user Password")
        print(colored(f"Error in update_user_data: {e}", "red"))
        raise HTTPException(status_code=500, detail="Error updating user Password")
    finally:
        storage_db.close()