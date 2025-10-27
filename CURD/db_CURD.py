from termcolor import colored
from pydantic import BaseModel, Field   
from fastapi import APIRouter, HTTPException
from sqlalchemy import create_engine, MetaData, inspect, text
from CURD.db_session import StorageBase, storage_engine, get_storage_db, StorageSessionLocal
from core.globals import DBSchema, databases_dict, dbs_info
from typing import Union, List, Dict, Optional, Any
from delete_collection import delete_collection
from utility.decorators import time_it
import json

class UpdateDBSchemaRequest(BaseModel):
    db_name: str = None
    db_string: str = None
    db_system: str = None
    db_description: str = None
    db_status: bool = None


class DBSchemaDescription(BaseModel): 
    id: int
    name: str
    db_description: Optional[str] = None
    db_schema: Optional[List[Dict[str, Any]]]

class DBSchemaRequest(BaseModel):
    mode: Union[str, int, List[DBSchemaDescription]]

# Define your FastAPI router
router = APIRouter()

# Create the db_schema table if it does not exist
StorageBase.metadata.create_all(bind=storage_engine)

@time_it
async def get_db_schema(connection_string):
    db_info = {}
    try:
        # Debugging: print the connection string
        print(f"Connecting to database with connection string: {connection_string}")
        
        engine = create_engine(connection_string)
        metadata = MetaData()
        metadata.reflect(bind=engine)
        inspector = inspect(engine)
        table_names = inspector.get_table_names()
        
        # Debugging: print the table names
        print(f"Tables found: {table_names}")

        for table_name in table_names:
            columns = inspector.get_columns(table_name)
            table_info = {column['name']: str(column['type']) for column in columns}
            db_info[table_name] = table_info

        print("Updated Database Metadata")
        return db_info
    except Exception as e:
      
        print(colored(f"Error at get_db_schema: {e}", "red"))
        raise e

@router.post('/databases')
@time_it
async def put_db_string(db_string: str, db_name: str, db_system: str, db_description: str):
    try:
        db_info = await get_db_schema(db_string)

        # Save the db_string and db_info to the storage database
        storage_db = StorageSessionLocal()
        new_db_schema = DBSchema(db_name=db_name, db_string=db_string, db_schema=db_info, db_system= db_system, db_description = db_description, db_status = True)
        storage_db.add(new_db_schema)
        storage_db.commit()
        storage_db.refresh(new_db_schema)


        return {'status': 200, 'message': 'Database schema saved successfully', 'id': new_db_schema.id}
    except Exception as e:
        print(colored(f"Error in put_db_string: {e}", "red"))
        raise HTTPException(status_code=500, detail="Error accessing or saving Database info")
    finally:
        databases_dict.clear()
        dbs_info()
        storage_db.close()

@router.get('/databases/{db_id}')
@time_it
async def fetch_db_schema(db_id: int):
    storage_db = next(get_storage_db())
    try:
        # Query the db_schema table for the given id
        db_schema_record = storage_db.query(DBSchema).filter(DBSchema.id == db_id).first()
        
        if db_schema_record is None:
            raise HTTPException(status_code=404, detail="Schema not found")

        return {'status': 200,'db_name':db_schema_record.db_name, 'db_string': db_schema_record.db_string, 'db_schema': db_schema_record.db_schema, 'db_type':db_schema_record.db_system, 'db_description': db_schema_record.db_description, 'db_status': db_schema_record.db_status}
    except Exception as e:
        print(colored(f"Error in fetch_db_schema: {e}", "red"))
        raise HTTPException(status_code=500, detail="Error fetching Database schema")

# Function to test the database connection
@time_it
async def test_db_connection(connection_string):
    try:
        # Attempt to create an engine and connect to the database
        engine = create_engine(connection_string)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {'status': 200, 'message': 'Database connection successful'}
    except Exception as e:
        return {'status': 500, 'message': f'Error connecting to database: {str(e)}'}

@router.post('/test-connection')
@time_it
async def test_connection(db_string: str):
    result = await test_db_connection(db_string)
    if result['status'] == 200:
        return result
    else:
        raise HTTPException(status_code=500, detail=result['message'])

# Function to remove a database connection string
@time_it
async def remove_db_string(db_id: int):
    storage_db = next(get_storage_db())
    try:
        # Query the db_schema table for the given id
        db_schema_record = storage_db.query(DBSchema).filter(DBSchema.id == db_id).first()
        
        if db_schema_record is None:
            raise HTTPException(status_code=404, detail="Schema not found")

        # Delete the record
        storage_db.delete(db_schema_record)
        storage_db.commit()
        return {'status': 200, 'message': 'Database schema deleted successfully'}
    except Exception as e:
        print(colored(f"Error in remove_db_string: {e}", "red"))
        raise HTTPException(status_code=500, detail="Error deleting Database schema")
    finally:
        databases_dict.clear()
        dbs_info()
        storage_db.close()

@router.delete('/databases/{db_id}')
@time_it
async def delete_db_string(db_id: int):
    return await remove_db_string(db_id)

# Function to list all database schemas
@time_it
async def list_db_schemas():
    storage_db = next(get_storage_db())
    try:
        # Query all records from the db_schema table
        db_schemas = storage_db.query(DBSchema).all()
        # Convert records to a list of dictionaries
        result = [
            {
                'id': db_schema.id,
                'name':db_schema.db_name,
                'db_string': db_schema.db_string,
                'db_schema': db_schema.db_schema,
                'db_type':db_schema.db_system,
                'db_description':db_schema.db_description,
                "db_status":db_schema.db_status
            } for db_schema in db_schemas
        ]
        return {'status': 200, 'data': result}
    except Exception as e:
        print(colored(f"Error in list_db_schemas: {e}", "red"))
        raise HTTPException(status_code=500, detail="Error fetching Database schemas")
    finally:
        storage_db.close()

@router.get('/databases')
@time_it
async def get_db_schemas():
    return await list_db_schemas()
  

@router.put('/databases/{db_id}')
@time_it
async def put_db_update(db_id: int, request: UpdateDBSchemaRequest):
    storage_db = next(get_storage_db())
    try:
        # Query the db_schema table for the given id
        db_schema_record = storage_db.query(DBSchema).filter(DBSchema.id == db_id).first()
 
        if db_schema_record is None:
            raise HTTPException(status_code=404, detail="Schema not found")
 
        # Update the db_string and db_schema
        if request.db_name is not None:
            db_schema_record.db_name = request.db_name
        if request.db_string is not None:
            db_schema_record.db_string = request.db_string
            db_schema_record.db_schema = await get_db_schema(request.db_string)
        if request.db_system is not None:
            db_schema_record.db_system = request.db_system
        if request.db_description is not None:
            db_schema_record.db_description = request.db_description
        if request.db_status is not None:
            db_schema_record.db_status = request.db_status
       
        storage_db.commit()
        storage_db.refresh(db_schema_record)
 
        if request.db_status is not None:
            return {'status': 200, 'message': f"Database '{db_schema_record.db_name}' status updated to {request.db_status}"}
        else:
            return {'status': 200, 'message': 'Database schema updated successfully'}
    except Exception as e:
        print(colored(f"Error in update_db_string: {e}", "red"))
        raise HTTPException(status_code=500, detail="Error updating Database schema")
    finally:
        databases_dict.clear()
        dbs_info()
        storage_db.close()

@router.post('/getuserdatabases')
@time_it
async def get_user_databases(request: DBSchemaRequest):
    storage_db = next(get_storage_db())
    request_mode = request.mode
    try:
        if request_mode == "names":
            db_schemas = storage_db.query(DBSchema).all()
            result = [
                {
                    'id': db_schema.id,
                    'name': db_schema.db_name,
                    'db_status': db_schema.db_status,
                }
                for db_schema in db_schemas
            ]
            return {'status': 200, 'data': result}

        elif isinstance(request_mode, int):
            db_schemas = storage_db.query(DBSchema).filter(DBSchema.id == request_mode).all()
            result = [
                {
                    'id': db_schema.id,
                    'name': db_schema.db_name,
                    'db_description': db_schema.db_description,
                    'db_status': db_schema.db_status,
                    'db_schema': db_schema.db_schema,
                    'db_column_description': db_schema.db_column_description if db_schema.db_column_description is not None else {}
                }
                for db_schema in db_schemas
            ]
            return {'status': 200, 'data': result}

        elif isinstance(request_mode, list):
            
            if not request_mode:
                return {'status': 400, 'message': 'Invalid request mode'}
            
            delete_collection()
            db_schema = storage_db.query(DBSchema).filter(DBSchema.id == request_mode[0].id).first()
            if not db_schema:
                return {"status": 404, "message": "Record not found"}
            
            db_schema.db_description = request_mode[0].db_description
            db_schema.db_column_description = request_mode[0].db_schema
            storage_db.commit()
            storage_db.refresh(db_schema)

            return {"status": 200, "message": "Record updated successfully"}
        
        elif request_mode == "all":
            return await list_db_schemas()

        else:
            return {'status': 400, 'message': 'Invalid request mode'}

    except Exception as e:
        storage_db.rollback()
        print(colored(f"Error in Updating Database: {e}", "red"))
        raise HTTPException(status_code=500, detail="Please check the request body")

    finally:
        storage_db.close()
