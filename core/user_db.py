import asyncpg
from fastapi import HTTPException

from CURD.db_session import get_storage_db
from CURD.user_CURD import UserData

from decouple import config

from utility.decorators import time_it

# DEPRECATED: This line is not used, keeping for backward compatibility
# The actual database connection comes from get_storage_db() which uses flexible_db_session
db_url = config('APP_DB_POSTGRES', default=config('USERS_POSTGRES', default=''))

@time_it
async def get_user(email: str):
    storage_db = next(get_storage_db())
    try:
        user_data = storage_db.query(UserData).filter(UserData.email == email).first()

        if user_data is None:
            raise HTTPException(status_code=404, detail="User data not found")

        return user_data
    except Exception as e:
        print(f"Error in read_user_data: {e}")
        raise HTTPException(status_code=500, detail="Error fetching user data")
    finally:
        storage_db.close()