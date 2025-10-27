from core.globals import Schema_info, fetch_table_description, table_descriptions
from fastapi import APIRouter, HTTPException
from CURD.db_session import StorageBase, storage_engine, get_storage_db

from utility.decorators import time_it

# DATABASE_URL = config('USERS_POSTGRES')

# Define your FastAPI router
router = APIRouter()

# # Set up the storage database engine and session
# StorageBase = declarative_base()
# storage_engine = create_engine(DATABASE_URL)
# StorageSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=storage_engine)


# Create the db_schema table if it does not exist
StorageBase.metadata.create_all(bind=storage_engine)


@router.get('/schema_info')
@time_it
async def read_schema_info():
    storage_db = next(get_storage_db())
    try:
        info = storage_db.query(Schema_info).order_by(Schema_info.id.desc()).all()
        result = [
            {
                'id': id.id,
                'db_id': id.db_id,
                'db_name': id.db_name,
                'table_name': id.table_name,
                'description': id.description
            } for id in info
        ]
        return {'status': 200, 'data': result}
    except Exception as e:
        print(f"Error in read_schema_info: {e}")
        raise HTTPException(status_code=500, detail="Error fetching Table Info")
    finally:
        storage_db.close()


@router.get('/schema_info/{id}')
@time_it
async def read_table_info(id: int):
    storage_db = next(get_storage_db())
    try:

        table_info = storage_db.query(Schema_info).filter(Schema_info.id == id).first()
        if table_info is None:
            raise HTTPException(status_code=404, detail="Table Info not found")
        return {'status': 200,
                'id': table_info.id,
                'db_id': table_info.db_id,
                'db_name': table_info.db_name,
                'table_name': table_info.table_name,
                'description': table_info.description
            }
    except Exception as e:
        print(f"Error in Table Info by id: {e}")
        raise HTTPException(status_code=500, detail="Error fetching Table Info")
    finally:
        storage_db.close()


@router.delete('/schema_info/{id}')
@time_it
async def delete_table_info(id: int):
    storage_db = next(get_storage_db())
    try:
        table_info = storage_db.query(Schema_info).filter(Schema_info.id == id).first()
        if table_info is None:
            raise HTTPException(status_code=404, detail="Table Info not found")

        storage_db.delete(table_info)
        storage_db.commit()

        table_descriptions.clear()
        fetch_table_description()
        return {'status': 200, 'message': 'Table Info deleted successfully'}
    except Exception as e:
        print(f"Error in delete_table_info: {e}")
        raise HTTPException(status_code=500, detail="Error deleting table_info")
    finally:
        storage_db.close()


@router.post('/schema_info')
@time_it
async def create_table_info(db_id: int, db_name: str, table_name: str, description: str):
    storage_db = next(get_storage_db())
    try:
        new_table_info = Schema_info(db_id=db_id, db_name = db_name, table_name=table_name, description=description)
        storage_db.add(new_table_info)
        storage_db.commit()
        storage_db.refresh(new_table_info)

        table_descriptions.clear()
        fetch_table_description()
        return {'status': 200, 'message': 'Table Info created successfully', 'id': new_table_info.id}
    except Exception as e:
        print(f"Error in create_table_info: {e}")
        raise HTTPException(status_code=500, detail="Error creating table_info")
    finally:
        storage_db.close()


@router.put('/schema_info/{id}')
@time_it
async def update_table_info(id: int, db_id: int = None, db_name:str = None, table_name: str = None, description: str = None):
    
    storage_db = next(get_storage_db())
    try:
        table_info = storage_db.query(Schema_info).filter(Schema_info.id == id).first()
        if table_info is None:
            raise HTTPException(status_code=404, detail="Table Info not found")

        if db_id is not None:
            table_info.db_id = db_id
        if db_name is not None:
            table_info.db_name = db_name
        if table_name is not None:
            table_info.table_name = table_name
        if description is not None:
            table_info.description = description
        
        storage_db.commit()
        storage_db.refresh(table_info)
        table_descriptions.clear()
        fetch_table_description()
        return {'status': 200, 'message': 'Table Info updated successfully', 'Table Info': {
                'id': table_info.id,
                'db_id': table_info.db_id,
                'db_name': table_info.db_name,
                'table_name': table_info.table_name,
                'description': table_info.description
            }}
    except Exception as e:
        print(f"Error in update_Table Info: {e}")
        raise HTTPException(status_code=500, detail="Error updating Table Info")
    finally:
        storage_db.close()