from core.logger import log_error
from CURD.groups_CURD import UserGroup
from sqlalchemy.orm import sessionmaker
from app.utils import get_hashed_password
from fastapi import APIRouter, HTTPException
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import create_engine, Column, Integer, Text, Boolean
from CURD.db_session import StorageBase, storage_engine, get_storage_db

from utility.decorators import time_it

# DATABASE_URL = config('USERS_POSTGRES')


router = APIRouter()

# # Set up the storage database engine and session
# StorageBase = declarative_base()
# storage_engine = create_engine(DATABASE_URL)
# StorageSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=storage_engine)

# def get_storage_db():
#     try:
#         db = StorageSessionLocal()
#         yield db
#     finally:
#         db.close()

class UserData(StorageBase):
    __tablename__ = 'user_data'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(Text, nullable=False)
    email = Column(Text, unique=True, nullable=False)
    password = Column(Text, nullable=False)
    disabled = Column(Boolean, default=False)
    admin = Column(Boolean, default=False)
    group_name = Column(Text, nullable=False)

@time_it
async def validate_group_name(group_name: str):
    storage_db = next(get_storage_db())
    try:
        # Query the user_groups table for the given group_name
        user_group = storage_db.query(UserGroup).filter(UserGroup.group_name == group_name).first()
        
        if user_group is None:
            raise HTTPException(status_code=400, detail="Group name not found in user groups")
    except Exception as e:
        print(f"Error in validate_group_name: {e}")
        raise HTTPException(status_code=500, detail="Error validating group name")
    finally:
        storage_db.close()

@router.get('/user-data')
@time_it
async def read_user_data():
    storage_db = next(get_storage_db())
    try:
        # Get all user groups
        user_data_all = storage_db.query(UserData).all()
        result = [
            {
            'id': user_data.id,
            'name': user_data.name,
            'email': user_data.email,
            'disabled': user_data.disabled,
            'admin': user_data.admin,
            'group_name': user_data.group_name
            } for user_data in user_data_all
        ]
        return {'status': 200, 'data': result}
    except Exception as e:
        print(f"Error in read_user_data: {e}")
        raise HTTPException(status_code=500, detail="Error fetching User data")
    finally:
        storage_db.close()

@router.post('/user-data')
@time_it
async def create_user_data(name: str, email: str, password: str, group_name: str, disabled: bool = False, admin: bool = False):
    # Validate the group_name
    await validate_group_name(group_name)
    password = get_hashed_password(password)  
    storage_db = next(get_storage_db())
    try:
        new_user = UserData(name=name, email=email, password=password, disabled=disabled, admin=admin, group_name=group_name)
        storage_db.add(new_user)
        storage_db.commit()
        storage_db.refresh(new_user)
        return {'status': 200, 'message': 'User data created successfully', 'user_data': {
            'id': new_user.id,
            'name': new_user.name,
            'email': new_user.email,
            'password': new_user.password,
            'disabled': new_user.disabled,
            'admin': new_user.admin,
            'group_name': new_user.group_name
        }}
    except Exception as e:
        await log_error(new_user.id, e, "Error creating user data, User email might be already exists.")
        print(f"Error in create_user_data: {e}")
        raise HTTPException(status_code=500, detail="Error creating user data")
    finally:
        storage_db.close()

@router.get('/user-data/{user_id}')
@time_it
async def read_user_data(user_id: int):
    storage_db = next(get_storage_db())
    try:
        user_data = storage_db.query(UserData).filter(UserData.id == user_id).first()
        
        if user_data is None:
            raise HTTPException(status_code=404, detail="User data not found")
        
        return {'status': 200, 'user_data': {
            'id': user_data.id,
            'name': user_data.name,
            'email': user_data.email,
            'disabled': user_data.disabled,
            'admin': user_data.admin,
            'group_name': user_data.group_name
        }}
    except Exception as e:
        await log_error(user_data.id, e, "Error fetching user data")
        print(f"Error in read_user_data: {e}")
        raise HTTPException(status_code=500, detail="Error fetching user data")
    finally:
        storage_db.close()

@router.put('/user-data/{user_id}')
@time_it
async def update_user_data(user_id: int, name: str = None, email: str = None, password: str = None, disabled: bool = None, admin: bool = None, group_name: str = None):
    # Validate the group_name if provided
    if group_name is not None:
        await validate_group_name(group_name)
    if password is not None:
        password = get_hashed_password(password)
    
    storage_db = next(get_storage_db())
    try:
        user_data = storage_db.query(UserData).filter(UserData.id == user_id).first()
        
        if user_data is None:
            await log_error(user_id, e, "User data not found")
            raise HTTPException(status_code=404, detail="User data not found")
        
        # Update fields if provided
        if name is not None:
            user_data.name = name
        if email is not None:
            user_data.email = email
        if password is not None:
            user_data.password = password
        if disabled is not None:
            user_data.disabled = disabled
        if admin is not None:
            user_data.admin = admin
        if group_name is not None:
            user_data.group_name = group_name
        
        storage_db.commit()
        storage_db.refresh(user_data)
        return {'status': 200, 'message': 'User data updated successfully', 'user_data': {
            'id': user_data.id,
            'name': user_data.name,
            'email': user_data.email,
            'disabled': user_data.disabled,
            'admin': user_data.admin,
            'group_name': user_data.group_name
        }}
    except Exception as e:
        await log_error(user_id, e, "Error updating user data")
        print(f"Error in update_user_data: {e}")
        raise HTTPException(status_code=500, detail="Error updating user data")
    finally:
        storage_db.close()

@router.delete('/user-data/{user_id}')
@time_it
async def delete_user_data(user_id: int):
    storage_db = next(get_storage_db())
    try:
        user_data = storage_db.query(UserData).filter(UserData.id == user_id).first()
        
        if user_data is None:
            await log_error(user_id, e, "User data not found")
            raise HTTPException(status_code=404, detail="User data not found")
        
        storage_db.delete(user_data)
        storage_db.commit()
        return {'status': 200, 'message': 'User data deleted successfully'}
    except Exception as e:
        await log_error(user_id, e, "Error deleting user data")
        print(f"Error in delete_user_data: {e}")
        raise HTTPException(status_code=500, detail="Error deleting user data")
    finally:
        storage_db.close()


