import os
from termcolor import colored
from typing import List, Dict
import core.globals as globals
from dotenv import load_dotenv
from collections import defaultdict
from azure.storage.blob import BlobServiceClient
from azure.data.tables import TableServiceClient
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from utility.decorators import time_it

load_dotenv()

connection_string = os.getenv("BLOB_CONNECTION_STRING")
          
#----------------------------------Azure Blob Storage Connection Parameters---------------------------------------#
container_name = "prompts-dev"

blob_service_client = BlobServiceClient.from_connection_string(connection_string)
container_client = blob_service_client.get_container_client(container=container_name)
table_service_client = TableServiceClient.from_connection_string(conn_str=connection_string)

local_path = "./temp"

@time_it
def file_logs(container_name, local_file_name):
    try:    
            upload_file_path = os.path.join(local_path, local_file_name)

            blob_client = blob_service_client.get_blob_client(container=container_name, blob=local_file_name)

            with open(file=upload_file_path, mode="rb") as data:
                blob_client.upload_blob(data)
            
            print(colored(f"Uploaded to Azure Storage as blob: {local_file_name}", "grey"))

    except Exception as e:
         print(colored(f"Error uploading File to Blob: {e}", "red"))

#------------------------------------------------Azure Tables -------------------------------------------------------------# 
@time_it
def chat_logs(user, bot, query, logger_timestamp, model, user_id):
    try:
        user_id_split = user_id.split('_')
        partition_key = user_id_split[0]
        timestamp_key = user_id_split[1]
        my_entity = {
            "PartitionKey"      : partition_key,
            "RowKey"            : str(logger_timestamp), 
            "SessionTimeKey"    : timestamp_key,
            "User_query"        : user,
            "Bot_response"      : bot,
            "Query"             : query,
            "model"             : model,
            "Feedback"          : "NA"
        }


        table_client = table_service_client.get_table_client(table_name="logs")

        table_client.create_entity(entity=my_entity)
        print(colored(f"Chat log inserted successfully.", "grey"))
    except Exception as e:
        print(colored(f"Error inserting Chat into Azure Table: {e}", "red"))

@time_it
def feedback_logs(bot_response, status, logger_timestamp, user_id,feedmessage):
    try:
        my_entity = {
            'PartitionKey': user_id,
            'RowKey': str(logger_timestamp), 
            'Bot_response': bot_response,
            'status':status,
            'Feedback':feedmessage
        }


        table_client = table_service_client.get_table_client(table_name="feedback")

        table_client.create_entity(entity=my_entity)
        print(colored(f"Feedback log inserted successfully.", "grey"))
    except Exception as e:
        print(colored(f"Error inserting Feedback into Azure Table: {e}", "red"))
#--------------------------------------------Code Logs---------------------------------------------------#

@time_it
def code_logs(container_name, code, user_id, logger_timestamp):
    try: 
            # Create a file in the local data directory to upload and download
            local_file_name = f'{user_id}_{logger_timestamp}_code.txt'
            upload_file_path = os.path.join(local_path, local_file_name)

            # Write text to the file
            file = open(file=upload_file_path, mode='w')
            file.write(code)
            file.close()  

            upload_file_path = os.path.join(local_path, local_file_name)

            blob_client = blob_service_client.get_blob_client(container=container_name, blob=local_file_name)

            with open(upload_file_path, mode="rb") as data:
                blob_client.upload_blob(data, overwrite=True)
            
            print(colored(f"Code Uploaded to Azure Storage as blob: {local_file_name}", "grey"))
            os.remove(upload_file_path)

    except Exception as e:
        print(colored(f"Error inserting Code into Azure Table: {e}", "red"))

#----------------------------------------------Instructions--------------------------------------------------------#
@time_it
def instructions(id,instruction,timestamp):
    container_name = f"prompts-dev/{id}"
    try: 
        # Create a file in the local data directory to upload and download
        local_file_name = f'{id}_{timestamp}.txt'
        upload_file_path = os.path.join(local_path, local_file_name)

        # Write text to the file
        file = open(file=upload_file_path, mode='w')
        file.write(instruction)
        file.close()  

        upload_file_path = os.path.join(local_path, local_file_name)

        blob_client = blob_service_client.get_blob_client(container=container_name, blob=local_file_name)

        with open(file=upload_file_path, mode="rb") as data:
            blob_client.upload_blob(data)
        
        print(colored(f"Instruction Uploaded to Azure Storage as blob: {local_file_name}", "grey"))
        os.remove(upload_file_path)

    except Exception as e:
         print(colored(f"Error inserting Instructions into Blob: {e}", "red"))

#--------------------------------Downloads All Instructions versions--------------------------------------#
@time_it
def download_blob_to_string(folder_name):
    container_name = "prompts-dev"
    
    blob_list = container_client.list_blobs(name_starts_with=folder_name)

    if folder_name not in globals.old_instructions_dict:
        globals.old_instructions_dict[folder_name] = {}
    
    for blobs in blob_list:
        blob_name = blobs.name[len(folder_name) + 1:]
        blob_name = blob_name.rstrip(".txt")
        blob_client = blob_service_client.get_blob_client(container=container_name, blob=blobs)

        # encoding param is necessary for readall() to return str, otherwise it returns bytes
        downloader = blob_client.download_blob(max_concurrency=1, encoding='UTF-8')
        blob_text = downloader.readall()
        globals.old_instructions_dict[folder_name][blob_name]= blob_text 
        
#----------------------------------------Downloads latest Instructions Versions-----------------------------#
@time_it
def download_latest_blob(folder_name):

    blob_list = container_client.list_blobs(name_starts_with=folder_name)
    blob_info = {}
    for blob in blob_list:
        blob_name = blob.name[len(folder_name) + 1:]
        blob_client = container_client.get_blob_client(blob.name)
        properties = blob_client.get_blob_properties()
        last_modified = properties['last_modified']
        blob_info[blob_name] = last_modified

    latest_blob_name = max(blob_info, key=blob_info.get)

    # Download the latest blob
    blob_client = container_client.get_blob_client(os.path.join(folder_name, latest_blob_name))
    # encoding param is necessary for readall() to return str, otherwise it returns bytes
    blob_data = blob_client.download_blob(max_concurrency=1, encoding='UTF-8')
    blob_text = blob_data.readall()
    globals.instructions_dict[folder_name]= blob_text

#--------------------------------------Updates both Old and latest instructions versions-----------------------------#
@time_it   
def instructions_update():
    globals.instructions_dict.clear()
    print(colored("Instructions_dict cleared.", "grey"))

    items = ['Chat Engine', 'Weather Data', 'Ask Database', 'Gen Code', 'Matplotlib', 'SQL Graphs','DB Selector', 'SQL Engine stage 1', 'SQL Engine stage 2', 'Graph Engine', 'Summarization']
    # items = ['weather_summary', 'summarize_combined_results','ask_database','matplotlib_code', 'get_weather_data',  'greetings_tools', 'greetings_system_message', 'greetings_prompt_message', 'sql_chain_system_message', 'db_server_message']
    try:
        with ThreadPoolExecutor(max_workers=5) as executor:
            executor.map(download_latest_blob, items)
            executor.map(download_blob_to_string, items)

        print(colored("Instructions Updated", "green"))

    except Exception as e:
        print(colored(f"Error at Instructions update: {e}", "red"))
         
         
#----------------------------------------Error Logs---------------------------------------#    
async def log_error(user_id, error_message, error_code):
    try:
        logger_timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        my_entity = {
            'PartitionKey': user_id,
            'RowKey': str(logger_timestamp),
            'Error_message': error_message,
            'Error_code': error_code,
        }
        
        table_client = table_service_client.get_table_client(table_name="errorLogs")
        table_client.create_entity(entity=my_entity)
        print(colored("Error log inserted successfully.", "grey"))
    except Exception as e:
        print(colored(f"Error inserting into error_logs table:{e}", "red"))

@time_it
async def log_login_logout(user_id, activity, status_code):
    try:
        logger_timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        my_entity = {
            'PartitionKey': user_id,
            'RowKey': str(logger_timestamp),
            'Activity': activity,
            'status_code': status_code,
        }
        
        table_client = table_service_client.get_table_client(table_name="userLoginOutLogs")
        table_client.create_entity(entity=my_entity)
        print(colored("UserLoginLogoutLogs inserted successfully.", "grey"))
    except Exception as e:
        print(colored(f"Error inserting into userLoginLogoutLogs table:{e}", "red"))

@time_it
async def log_completion_usage(user_id, completion_tokens, prompt_tokens, total_tokens):
    try:
       
        logger_timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        
      
        my_entity = {
            'PartitionKey': user_id,
            'RowKey': str(logger_timestamp),
            'CompletionTokens': completion_tokens,
            'PromptTokens': prompt_tokens,
            'TotalTokens': total_tokens,
        }

       
      
        table_client = table_service_client.get_table_client(table_name="CompletionUsageLogs")
        table_client.create_entity(entity=my_entity)
        
        print(colored("Completion usage log inserted successfully.", "grey"))
    
    except Exception as e:
        print(colored(f"Error inserting into CompletionUsageLogs table: {e}", "red"))

@time_it
async def get_completion_usage():
    try:
        info = []
       
      
        table_client = table_service_client.get_table_client(table_name="CompletionUsageLogs")
        # entities = table_client.list_entities(results_per_page=3)
        entities = table_client.list_entities()
        
        page = next(entities.by_page(), None)
        
        if page:
            for i in page:
                info.append(i)
            return info
        else:
            print(colored("No entities found.", "grey"))
            return None
            
    except Exception as e:
        print(colored(f"Error fetching from CompletionUsageLogs table: {e}", "red"))

@time_it
async def monthly_completion_usage() -> List[Dict]:
    try:
        table_client = table_service_client.get_table_client(table_name="CompletionUsageLogs")

        entities = table_client.list_entities()

        # Get the current month and year
        now = datetime.now()
        current_year = now.year
        current_month = now.month

        # Filter the entities based on the current month
        current_prefix = f"{current_year}{current_month:02d}"
        info = [
            entity for entity in entities
            if entity.get('RowKey', '').startswith(current_prefix)
        ]

        if not info:
            print("No entities found for the current month.")
            return []
        info.sort(key=lambda x: x['RowKey'])  
        return info

    except Exception as e:
        print(f"Error fetching from CompletionUsageLogs table: {e}")
        return []
   
@time_it
async def filter_by_latest_week(logs: List[Dict]) -> List[Dict]:
    if not logs:
        return []
    for log in logs:
        log['datetime'] = datetime.strptime(log['RowKey'], "%Y%m%d%H%M%S")
    latest_log = max(logs, key=lambda x: x['datetime'])
    latest_year, latest_week = latest_log['datetime'].isocalendar()[:2]
    filtered_logs = [log for log in logs if log['datetime'].year == latest_year and log['datetime'].isocalendar()[1] == latest_week]
    filtered_logs.sort(key=lambda x: x['datetime'])
    for log in filtered_logs:
        del log['datetime']
    
    return filtered_logs        

@time_it
async def get_chat_logs(user_id):
    try:
        now = datetime.now()
        ten_days_ago = now - timedelta(days = 10)
        start_date_str = ten_days_ago.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_date_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        table_client = table_service_client.get_table_client(table_name="logs")
        selected_columns = ["PartitionKey", "RowKey", "SessionTimeKey"]
        query_filter = (f"PartitionKey eq '{user_id}' and "
                        f"RowKey ge '{start_date_str}' and "
                        f"RowKey le '{end_date_str}'")
        
        entities = table_client.query_entities(query_filter=query_filter, select=selected_columns)
        transformed_data = defaultdict(set)
        
        if(entities != ''):
            for item in entities:
                main_id = item['RowKey'].split(' ')[0]
                
                session_id = item['SessionTimeKey']
                transformed_data[main_id].add(session_id)

            result = [
                {
                    "conversation_main_id": main_id,
                    "conversationlist": [{"id": session_id} for session_id in sorted(conversation_data)]
                }
                for main_id, conversation_data in transformed_data.items()
            ]
        else:
            result = []
        return result

    except Exception as e:
        print(colored(f"Error fetching from logs table: {e}", "red"))
        return []

# get_chat_logs('lovelyram39@gmail.com')

@time_it
async def get_chat_conversationbyid(id) :
    try:
        info = []

        table_client = table_service_client.get_table_client(table_name="logs")
        query_filter = (f"SessionTimeKey eq '{id}'")
        entities = table_client.query_entities(query_filter=query_filter)
        if(entities != ''):
            for item in entities:
                dt = datetime.strptime(item['RowKey'], "%Y-%m-%d %H:%M:%S")
                time_str = dt.strftime("%H:%M")
                info.append({
                    "sent_message"          : item['User_query'], 
                    "tool"                  : "", 
                    "sent_time"             : time_str, 
                    "received_message"      : item['Bot_response'], 
                    "parsed_questions"      : "", 
                    "received_time"         : time_str, 
                    "timestamp"             : item['RowKey'], 
                    "is_image"              : False, 
                    "is_sql"                : item["Query"] if item.get("Query") else None, 
                    "feedback"              : None, 
                    "code"                  : [], 
                    "graphdata"             : [], 
                    "star"                  : False,
                    "like"                  : False,
                    "dislike"               : False, 
                    "toolSelected"          : "",
                    "imageSources"          : [] 
                })

        return info

    except Exception as e:
        print(f"Error fetching from logs given time : {e}")

@time_it
async def log_sql_error(dialect: str, sql: str, error: str):
    try:
       
        logger_timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        
      
        my_entity = {
            'PartitionKey': dialect,
            'RowKey': str(logger_timestamp),
            'SQL': sql,
            'Error': error
        }      
        table_client = table_service_client.get_table_client(table_name="SQLerrorLogs")
        table_client.create_entity(entity=my_entity)
        
        print(colored("Completion usage log inserted successfully.", "grey"))
    
    except Exception as e:
        print(colored(f"Error inserting into CompletionUsageLogs table: {e}", "red"))

@time_it
async def get_errors_by_dialect(dialect: str):
    try:
        # Get the table client
        table_client = table_service_client.get_table_client(table_name="SQLerrorLogs")
        
        # Query for entities with the specified PartitionKey (Dialect)
        error_entities = table_client.query_entities(query_filter=f"PartitionKey eq '{dialect}'")
        
        # Collect SQL and Error fields from each entity
        errors = [{"SQL": entity["SQL"], "Error": entity["Error"]} for entity in error_entities]
        
        return errors
    
    except Exception as e:
        print(colored(f"Error retrieving data from SQLerrorLogs table: {e}", "red"))
        return []


instructions_update() # Update Instructions (Prompts)


# get_chat_conversationbyid('2024-09-01-03-32-50')       
        
# log_error("test", "test", 500)
#-------------------Not using -------------------#

# import pyodbc
# from datetime import datetime
# #-------------------------------Azure SQL Database Connection Parameters-----------------------------------------#
# server = 'bi-bot.database.windows.net'
# database = 'chat-logs'
# username = 'bibotadmin'
# password = 'Admin@123'
# connection_string = f'DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server};DATABASE={database};UID={username};PWD={password}'

# def chat_logs(user,bot,query,model):
#     connection = pyodbc.connect(connection_string)
#     insert_query = "INSERT INTO user_bot_log_info (user_question, bot_response, query, timestamp, model) VALUES (?, ?, ?, ?, ?)"
#     insert_params = (user, bot, query, datetime.now(), model)
#     cursor = connection.cursor()
#     cursor.execute(insert_query, insert_params)
#     connection.commit()
#     cursor.close()
#     connection.close()
         
# -------------------------------PostgreSQL Database Connection Parameters--------------------------------------- #
# host = '20.205.128.184'
# database = 'bi_bot'
# user = 'bi_user'
# password = 'bi@123'
# port = '5432'

# connection_string = f"host={host} dbname={database} user={user} password={password} port={port}"

# def chat_logs(user, bot, query, logger_timestamp, model, user_id):
#     try:
        
#             connection = psycopg2.connect(connection_string)
#             insert_query = "INSERT INTO user_bot_log_info (user_question, bot_response, query, timestamp, model, user_id) VALUES (%s, %s, %s, %s, %s, %s)"
#             insert_params = (user, bot, query, logger_timestamp, model, user_id)

#             cursor = connection.cursor()
#             cursor.execute(insert_query, insert_params)
#             connection.commit()

#             cursor.close()
#             connection.close()
#     except Exception as e:
#           print("Error Inserting into Postgres:",e)

# instruction = "Use this function to fetch weather data for a specified location in metric format."
# instructions(container_name="instructions",id="get_weather_data",instruction=instruction)
