from termcolor import colored
from CURD.db_CURD import DBSchema
from CURD.groups_CURD import UserGroup
from core.globals import get_storage_db
from CURD.schema_CURD import Schema_info
from core.globals import databases_dict

from utility.decorators import time_it

# async def usergroup_schema(user_group):
#     try:
#         storage_db = next(get_storage_db())
#         user_group = storage_db.query(UserGroup).filter(UserGroup.group_name == user_group).first()
#         group_dbID = user_group.db_id.split(',')
#         db_info = {}
#         for i in group_dbID:
#             schema = {}
#             name = await fetch_db_schema(i)
#             group_schema = user_group.group_schema[i]
#             schema[name.db_system]= group_schema
#             db_info[name.db_name] = schema
#         return db_info
#     except:
#         return False
#     finally:
#         storage_db.close()        
# async def schema_auth(user_group, table_name):
#     try:
#         storage_db = next(get_storage_db())
#         user_group = storage_db.query(UserGroup).filter(UserGroup.group_name == user_group).first()
#         schema = user_group.group_schema
#         if table_name in schema.values():
#             return True
#     except:
#         return False
#     finally:
#         storage_db.close()

@time_it
async def usergroup_schema(user_group):
    try:
        storage_db = next(get_storage_db())
        user_group = storage_db.query(UserGroup).filter(UserGroup.group_name == user_group).first()
        group_dbID = user_group.db_id.split(',')
        db_info = {}
        
        for db_id in group_dbID:
          
            db_id = int(db_id.strip())
            
            db_entry = next((db for db in databases_dict.values() if db['id'] == db_id), None)
            if not db_entry:
                continue  # Skip if no matching db_entry is found
            
            db_name = db_entry.get('name')
            db_system = db_entry.get('db_type')
            
            # retrieve the group schema for this db_id
            group_schema = user_group.group_schema.get(str(db_id), {})
            schema = {db_system: group_schema}
            
            db_info[db_name] = schema
        
        return db_info
    except Exception as e:
        # log the error message
        print(f"Error fetching user group schema: {e}")
        return False
    finally:
        storage_db.close()

    
# async def fetch_db_schema(db_id: int):
#     storage_db = next(get_storage_db())
#     try:
#         # Query the db_schema table for the given id
#         db_schema_record = storage_db.query(DBSchema).filter(DBSchema.id == db_id).first()
        
#         if db_schema_record is None:
#             raise "Schema not found"
#         return db_schema_record
#     except Exception as e:
#         print(colored(f"Error in fetch_db_schema: {e}", "red"))
#         raise e
#     finally:
#         storage_db.close()


# async def fetch_table_description(table_name: str):
#     storage_db = next(get_storage_db())
#     try:

#         # Query the db_schema table for the given id
#         table_description = storage_db.query(Schema_info.description).filter(Schema_info.table_name == table_name).first()
        
#         if table_description:
#             return table_description
#     except Exception as e:
#         print(colored(f"Error in db_schema_description: {e}", "red"))
#         raise e
#     finally:
#         storage_db.close()