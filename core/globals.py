import asyncio
from contextlib import contextmanager
import os
from typing import Dict
from decouple import config
from termcolor import colored
from fastapi import WebSocket
from sqlalchemy import create_engine
from CURD.db_session import StorageBase
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import create_engine, MetaData, inspect, Column, Integer, Text,VARCHAR, JSON, text, Boolean

from utility.decorators import time_it
import plotly.io as pio


class DBSchema(StorageBase):
    __tablename__ = 'db_schema'
    id = Column(Integer, primary_key=True, index=True)
    db_name = Column(VARCHAR, nullable=False)
    db_string = Column(Text, nullable=False)
    db_schema = Column(JSON, nullable=False)
    db_system = Column(VARCHAR, nullable=False)
    db_description = Column(Text)
    db_status = Column(Boolean)
    db_column_description = Column(JSON, nullable=False)

class Schema_info(StorageBase):
    __tablename__ = 'schema_info'
    id = Column(Integer, primary_key=True, index=True)
    db_id = Column(Integer, nullable=False)
    table_name = Column(VARCHAR, nullable=False)
    description = Column(Text, nullable=False)
    db_name = Column(VARCHAR, nullable=False)


# Use APP_DB_POSTGRES for the new flexible database setup, fallback to USERS_POSTGRES
DATABASE_URL = config('APP_DB_POSTGRES', default=config('USERS_POSTGRES', default=''))

tool_ids = []

tool_cache = {} # Holds tool results for comparative_analyzer (cache bridge for orchestrator)

functions_time_log = [] # Holds Functions Time Logs

api_time_log = [] # Holds API Time Logs

instructions_dict = {} # Holds Last Modified Instructions 

old_instructions_dict = {} # Holds Old Instructions

session_data = {} # Holds Live session IDs

csv_path_data = {} # Holds CSV Paths

gROUP_DB_SCHEMA = {} # Holds Group DB Schema

databases_dict = {} # Holds List of Databases

table_descriptions = {} # Holds Table Descriptions

user_file_data = {} # This dictionary will store the metadata for uploaded files for each user

csv_summary = {}

active_tool_state = {}

global_plots = {}

conversation_ids = []

db_cache = {} # Holds DB Cache

active_connections: Dict[str, WebSocket] = {}

csv_paths = {}


class WebSocketManager:
    """
    This manager helps send personal JSON messages to a given user,
    and also provides a mechanism to wait for user 'ack' data.
    """
    def __init__(self):
        # For ack logic:
        #   user_ack_events : user_id -> asyncio.Event
        #   user_ack_data   : user_id -> data we store until someone awaits it
        self.user_ack_events = {}
        self.user_ack_data = {}

    async def send_personal_json(self, user_id: str, data: dict):
        """
        Send a JSON message to the WebSocket of a given user_id.
        """
        print(colored(f"Sending JSON to {user_id}: {data}", "cyan"))
        if user_id in active_connections:
            print(colored(f"User {user_id} is connected.", "cyan"))
            websocket = active_connections[user_id]
            print( "Websocket:",websocket)
            await websocket.send_json(data)
            print(colored(f"Sent JSON to {user_id}: {data}", "cyan"))

    async def wait_for_ack(self, user_id: str):
        """
        Pause (async) until the user with `user_id` sends back an ACK.
        Returns the data that was "acked."
        """
        if user_id not in self.user_ack_events:
            self.user_ack_events[user_id] = asyncio.Event()

        # Wait until set_ack() is called for this user
        await self.user_ack_events[user_id].wait()

        # Retrieve the data for this user, then clean up
        ack_data = self.user_ack_data.pop(user_id, None)
        self.user_ack_events[user_id].clear()
        self.user_ack_events.pop(user_id, None)

        return ack_data

    def set_ack(self, user_id: str, ack_data: dict):
        """
        Called when the user (via WebSocket) sends an ACK. 
        This unblocks whoever is awaiting wait_for_ack(user_id).
        """
        # Store the data from user
        self.user_ack_data[user_id] = ack_data

        # Unblock any 'wait_for_ack()' call
        if user_id in self.user_ack_events:
            self.user_ack_events[user_id].set()

# Create a single global instance
ws_manager = WebSocketManager()


@time_it
def conv_his(user_id,userText):
    if user_id in session_data:
        session_data[user_id].append(userText)
    else:
        session_data[user_id] = []
        session_data[user_id].append(userText)

@time_it
def add_tool(tool_id):
    tool_ids.append(tool_id)
    print(f"Tool {tool_id} added to the list of active tools")

@time_it
def get_tool():
    return tool_ids

@time_it
def clear_tool():
    tool_ids.clear()
    print("Tool list cleared")

@time_it
def add_conversation_id(conversation_id):
    conversation_ids.append(conversation_id)
    print(f"Conversation ID {conversation_id} added to the list of active conversations")

@time_it
def get_conversation_ids():
    return conversation_ids

@time_it
def clear_conversation_ids():
    
    conversation_ids.clear()
    print("Conversation ID list cleared")

# @time_it    
# def csv_path(user_id,file_path):
#     csv_path_data[user_id] = file_path

@time_it
def get_csv_path(user_id):
    return csv_path_data.get(user_id, None)

@time_it
def store_metadata(user_email, metadata):
    user_file_data[user_email] = metadata

@time_it
def get_metadata(user_email, file_name):
    return user_file_data.get(user_email, {}).get(file_name, {})

@time_it
def get_metadata_all(user_email):
    return user_file_data.get(user_email, {})

@time_it
def store_summary(user_email, summary):
    csv_summary[user_email] = summary

@time_it
def get_summary(user_email):
    return csv_summary.get(user_email, None)

# Track last status message per user to prevent duplicates
_last_status_by_user = {}

@time_it
async def send_status_to_user(user_id: str, status: str):
    # Skip if same status was just sent
    if user_id in _last_status_by_user and _last_status_by_user[user_id] == status:
        return  # Don't send duplicate consecutive status messages

    if user_id in active_connections:
        websocket = active_connections[user_id]
        print(colored(f"Status:{status}", "grey"))
        await websocket.send_json({"status": status})
        _last_status_by_user[user_id] = status  # Track last status
    else:
        print(colored(f"User {user_id} not connected.", "red"))

@time_it
def clear_last_status(user_id: str):
    """Clear the last status for a user (call when query completes)"""
    if user_id in _last_status_by_user:
        del _last_status_by_user[user_id]


@time_it
async def remove_files_with_user_id(user_id):
    directory = "temp"
    files = os.listdir(directory)

    for file in files:
        if file.startswith(user_id):
            if file.lower().endswith(('.csv', '.png', '.jpg', '.txt')):
                file_path = os.path.join(directory, file)
                os.remove(file_path)
                print(colored(f"Removed file: {file_path}", "grey"))

# users_whitelist = set()
# maintain hashmap
# recommended to use extenernal db to store and access concervation


StorageBase = declarative_base()
storage_engine = create_engine(DATABASE_URL)
StorageSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=storage_engine)

@time_it
def get_storage_db():
    try:
        db = StorageSessionLocal()
        yield db
    finally:
        db.close()
        

@contextmanager
def get_storage_db_2():
    try:
        db = StorageSessionLocal()
        yield db
    finally:
        db.close()

@time_it
def dbs_info():
    # from CURD.db_CURD import DBSchema
    global databases_dict
    storage_db = next(get_storage_db())
    try:
        # Query all records from the db_schema table
        db_schemas = storage_db.query(DBSchema).all()
        # Convert records to a list of dictionaries
        if db_schemas:
            for db_schema in db_schemas:
                if db_schema.db_status is True:
                    databases_dict[db_schema.db_name]={
                            'id': db_schema.id,
                            'name':db_schema.db_name,
                            'string':db_schema.db_string,
                            'db_type':db_schema.db_system,
                            'db_description':db_schema.db_description,
                            "db_status":db_schema.db_status,
                            "db_column_description":db_schema.db_column_description
                        }
            print(colored("Databases List Updated", "green"))
    except Exception as e:
        print(colored(f"Error in list_db_schemas: {e}", "red"))
        raise "Error fetching Database schemas"
    finally:
        storage_db.close()

@time_it
def fetch_table_description():
    storage_db = next(get_storage_db())
    try:

        # Query the db_schema table for the given id
        table_description = storage_db.query(Schema_info).all()
        
        if table_description:
            for table in table_description:
                data = {
                        table.table_name:table.description
                        }
                if table.db_name in table_descriptions:
                    table_descriptions[table.db_name].update(data)
                else:
                    table_descriptions[table.db_name] = data              
        print(colored("Table Descriptions Updated", "green"))
    except Exception as e:
        print(colored(f"Error in db_schema_description: {e}", "red"))
        raise e
    finally:
        storage_db.close()

def db_description():
    info = {}
    for item in databases_dict.values():
        name = item['name']
        string = item['db_description']
        info[name] = string
    return info


def add_csv_path_mapping(user_id: str, query_id: str, file_path: str):
    """Add a mapping from query_id to file_path for a user"""
    global csv_paths
    
    if user_id not in csv_paths:
        csv_paths[user_id] = {}
    
    csv_paths[user_id][query_id] = file_path

def get_csv_paths(user_id: str):
    """Get all CSV paths for a user"""
    global csv_paths
    
    return csv_paths.get(user_id, {})


def csv_path(user_id, file_path=None):
    """Get or set the CSV path for a user"""
    global session_data
    
    if file_path:
        # Store the latest CSV path in session data
        if user_id not in session_data:
            session_data[user_id] = []
        
        # Store the path in session data (for backward compatibility)
        session_data[user_id] = session_data[user_id] + [{"csv_path": file_path}]
        return True
    
    # Get the latest CSV path from session data (for backward compatibility)
    if user_id in session_data:
        for item in reversed(session_data[user_id]):
            if isinstance(item, dict) and "csv_path" in item:
                return item["csv_path"]
    
    return None