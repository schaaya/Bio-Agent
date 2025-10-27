import core.globals as globals
from typing import List, Dict
from sqlalchemy.orm import sessionmaker
from fastapi import APIRouter, HTTPException
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import create_engine, Column, Integer, Text, JSON, VARCHAR
from CURD.db_session import StorageBase, storage_engine, get_storage_db

from utility.decorators import time_it

# DATABASE_URL = config('USERS_POSTGRES')

router = APIRouter()

# # Set up the storage database engine and session
# StorageBase = declarative_base()
# storage_engine = create_engine(DATABASE_URL)
# StorageSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=storage_engine)

class UserGroup(StorageBase):
    __tablename__ = 'user_groups'
    id = Column(Integer, primary_key=True, index=True)
    group_name = Column(Text, unique=True, nullable=False)
    group_schema = Column(JSON, nullable=False)
    db_id = Column(VARCHAR, nullable=False)

# Create the user_groups table if it does not exist
StorageBase.metadata.create_all(bind=storage_engine)


# # Function to get a database session
# def get_storage_db():
#     try:
#         db = StorageSessionLocal()
#         yield db
#     finally:
#         db.close()


@router.get('/user-groups')
@time_it
async def read_user_groups():
    storage_db = next(get_storage_db())
    try:
        # Get all user groups
        # user_groups = storage_db.query(UserGroup).all()
        user_groups = storage_db.query(UserGroup).order_by(UserGroup.id.desc()).all()
        result = [
            {
                'id': user_group.id,
                'group_name': user_group.group_name,
                'group_schema': user_group.group_schema,
                'db_id': user_group.db_id
            } for user_group in user_groups
        ]
        return {'status': 200, 'data': result}
    except Exception as e:
        
        print(f"Error in read_user_groups: {e}")
        raise HTTPException(status_code=500, detail="Error fetching User groups")
    finally:
        storage_db.close()


@router.get('/user-groups/{group_id}')
@time_it
async def read_user_group(group_id: int):
    storage_db = next(get_storage_db())
    try:
        # Get a user group by ID
        user_group = storage_db.query(UserGroup).filter(UserGroup.id == group_id).first()
        if user_group is None:
            raise HTTPException(status_code=404, detail="User group not found")
        return {'status': 200, 'id': user_group.id, 'group_name': user_group.group_name, 'group_schema': user_group.group_schema, 'db_id':user_group.db_id}
    except Exception as e:
        print(f"Error in read_user_group: {e}")
        raise HTTPException(status_code=500, detail="Error fetching User group")
    finally:
        storage_db.close()


@router.delete('/user-groups/{group_id}')
@time_it
async def delete_user_group(group_id: int):
    storage_db = next(get_storage_db())
    try:
        # Get the user group by ID
        user_group = storage_db.query(UserGroup).filter(UserGroup.id == group_id).first()
        if user_group is None:
            raise HTTPException(status_code=404, detail="User group not found")

        # Delete the user group
        storage_db.delete(user_group)
        storage_db.commit()
        if globals.gROUP_DB_SCHEMA.get(user_group.group_name) is not None:
            globals.gROUP_DB_SCHEMA.pop(user_group.group_name)
        return {'status': 200, 'message': 'User group deleted successfully'}
    except Exception as e:
        print(f"Error in delete_user_group: {e}")
        raise HTTPException(status_code=500, detail="Error deleting User group")
    finally:
        storage_db.close()


@router.post('/user-groups')
@time_it
async def create_user_group(group_name: str, group_schema: List[Dict], db_id: str):
    db_schema_dict = {str(db["id"]): db["db_schema"] for db in group_schema}
    storage_db = next(get_storage_db())
    try:
        new_user_group = UserGroup(group_name=group_name, group_schema=db_schema_dict, db_id=db_id)
        storage_db.add(new_user_group)
        storage_db.commit()
        storage_db.refresh(new_user_group)
        return {'status': 200, 'message': 'User group created successfully', 'id': new_user_group.id}
    except Exception as e:
        print(f"Error in create_user_group: {e}")
        raise HTTPException(status_code=500, detail="Error creating User group")
    finally:
        storage_db.close()


@router.put('/user-groups/{group_id}')
@time_it
async def update_user_group(group_id: int, group_name: str = None, group_schema: List[Dict] = None, db_id: str = None):
    
    storage_db = next(get_storage_db())
    try:
        # Get the user group by ID
        user_group = storage_db.query(UserGroup).filter(UserGroup.id == group_id).first()
        print("user group at route",user_group.id)
        if user_group is None:
            raise HTTPException(status_code=404, detail="User group not found")

        # Update the user group
        if group_name is not None:
            user_group.group_name = group_name
        if group_schema is not None:
            db_schema_dict = {str(db["id"]): db["db_schema"] for db in group_schema}
            user_group.group_schema = db_schema_dict
        if db_id is not None:
            user_group.db_id = db_id
        
        storage_db.commit()
        storage_db.refresh(user_group)
        if globals.gROUP_DB_SCHEMA.get(user_group.group_name) is not None:
            globals.gROUP_DB_SCHEMA.pop(user_group.group_name)
        return {'status': 200, 'message': 'User group updated successfully', 'user_group': {
            'id': user_group.id,
            'group_name': user_group.group_name,
            'group_schema': user_group.group_schema
        }}
    except Exception as e:
        print(f"Error in update_user_group: {e}")
        raise HTTPException(status_code=500, detail="Error updating user group")
    finally:
        storage_db.close()