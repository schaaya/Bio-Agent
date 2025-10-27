import base64
import csv
import logging
import os
import sys
from cachetools import TTLCache
from dotenv import load_dotenv
import httpx
import requests
import aiofiles
from termcolor import colored
from app.dep import user_verification
from app.schema import FeedbackRequest
from datetime import datetime, timezone
import json
from json.decoder import JSONDecodeError
from core.ChatEngine import process_user_input, cache_client
from starlette.websockets import WebSocketDisconnect
from fastapi import WebSocket, HTTPException, APIRouter, Request
from core.globals import active_connections, clear_conversation_ids, remove_files_with_user_id, ws_manager

from core.image_blob_storage import BlobStorage
from core.logger import log_error, feedback_logs, get_chat_logs, get_chat_conversationbyid
from utility.decorators import time_it
import keyring

from utility.tools import chat_completion_request




router = APIRouter()

load_dotenv()

AZURE_STORAGE_CONNECTION_STRING = os.getenv("BLOB_CONNECTION_STRING")

@time_it
async def close_websocket_connection(user_id: str):
    if user_id in active_connections:
        websocket = active_connections[user_id]
        await websocket.close()
        del active_connections[user_id]

@time_it
async def get_chat_response(data,user_id,user_group):

        try:
            response, base64_string, is_image, sql, logger_timestamp_mod, code, fig_json, parsed_questions, query_id, reasoning_steps = await process_user_input(data,user_id,user_group)

            # # Debug: Show what ChatEngine returned
            # print(colored(f"🔄 ChatEngine returned to WebSocket:", "blue"))
            # print(colored(f"   - SQL: {sql}", "blue"))
            # print(colored(f"   - Parsed Questions: {parsed_questions}", "blue"))
            # print(colored(f"   - Query ID: {query_id}", "blue"))
            # print(colored(f"   - Reasoning Steps: {len(reasoning_steps) if reasoning_steps else 0}", "blue"))

            return response, base64_string, is_image, sql, logger_timestamp_mod, code, fig_json, parsed_questions, query_id, reasoning_steps
        except FileNotFoundError as e:
            await log_error(user_id, str(e), 404)
            print(colored(f"Error: {e}", "red"))
            return "Error, Please click on 'Clear Conversation", None, False, None, None, None, None, None, None, []

@time_it
async def send_response(websocket: WebSocket, response: str, is_image: bool, sql: str,
                       base64_string: str = None, logger_timestamp_mod: str = None,
                       code: str = None, fig_json: list = None, parsed_questions: str = None,
                       user_id: str = None, query_id: str = None, reasoning_steps: list = None):
    try:
        # Debug: Show what send_response received
        print(colored(f"📨 send_response() received:", "yellow"))
        print(colored(f"   - SQL: {sql}", "yellow"))
        print(colored(f"   - Parsed Questions: {parsed_questions}", "yellow"))
        print(colored(f"   - Parsed Questions Type: {type(parsed_questions)}", "yellow"))
        print(colored(f"   - Query ID: {query_id}", "yellow"))

        # Initialize blob storage
        connection_string = os.getenv("BLOB_CONNECTION_STRING")
        blob_storage = BlobStorage(connection_string, "chat-images")
        user_email = user_id.split("_")[0]
        # Store fig_json data if present
        fig_json_refs = []
        if fig_json:
            fig_json_refs = await blob_storage.store_fig_json(
                fig_json, 
                user_email, 
                logger_timestamp_mod
            )
            
            # Store reference in cache for quicker retrieval
            cache_key = f"fig_json_{user_id}_{logger_timestamp_mod}"
            cache_client[cache_key] = json.dumps({
                "fig_json_refs": fig_json_refs
            })
        
        # Prepare the response
        response_data = {
            "message": response,
            "is_image": is_image,
            "sql": sql,
            "timestamp": logger_timestamp_mod,
            "code": code,
            "parsed_questions": parsed_questions,
            "query_id": query_id,
            "reasoning_steps": reasoning_steps if reasoning_steps else []  # NEW: Add reasoning steps
        }

        # Add fig_json and its references
        if fig_json:
            response_data["fig_json"] = fig_json  # Send the actual fig_json for immediate use
            response_data["fig_json_refs"] = fig_json_refs  # Send references for later retrieval

        # Debug: Print what we're sending
        print(colored(f"📤 Sending to UI:", "magenta"))
        print(colored(f"   - SQL: {sql}", "magenta"))
        print(colored(f"   - Parsed Questions: {parsed_questions}", "magenta"))
        print(colored(f"   - Query ID: {query_id}", "magenta"))
        print(colored(f"   - Full response_data keys: {list(response_data.keys())}", "magenta"))

        # Send the response
        await websocket.send_json(response_data)

        # Clear last status to allow new status messages in next query
        from core.globals import clear_last_status
        clear_last_status(user_id)

    except Exception as e:
        print(colored(f"Error in send_response: {e}", "red"))
        await log_error(user_id, str(e), 500)
        await websocket.send_json({
            "message": "Error, Please click on 'Clear Conversation'.",
            "is_image": False
        })

@router.websocket("/wss")
@time_it
async def websocket_endpoint(websocket: WebSocket, token: str):
    token = websocket.query_params.get('token')
    if not token:
        await websocket.close(code=1008, reason="Token is missing")
        return
    try:
        user = await user_verification(token)
        session_id = datetime.now().strftime('%Y-%m-%d-%H-%M-%S')
        user_id = user.email + '_' + session_id
        user_group = user.group_name
        if user.disabled is False:
            await websocket.accept()
            active_connections[user_id] = websocket

            # Send greeting message as JSON
            greeting_message = f"Hi there! {user.username} How can I assist you today? 😊"
            await websocket.send_json({"message": greeting_message, "is_image": False})
            
        else:
            await websocket.close(code=1008, reason="User Disabled")

    except HTTPException as e:
        await log_error(None, str(e), 1008)
        await websocket.close(code=1008, reason="Invalid token")
        return

    try:
        while True:
            try:
                data = await websocket.receive_json()
                msg_type = data.get("type")
                
                if msg_type == "TABLES_ACK":
                    print(colored(f"Received TABLES_ACK message: {data}", "green"))
                    chosen_tables = data["tables"]
                    ws_manager.set_ack(user_id, chosen_tables)
                else:
                    print(colored(f"Received message: {data}", "green"))
                    response, base64_string, is_image, sql, logger_timestamp_mod, code, fig_json, parsed_questions, query_id, reasoning_steps = await get_chat_response(data, user_id, user_group)
                    await send_response(websocket, response, is_image, sql, base64_string, logger_timestamp_mod, code, fig_json, parsed_questions, user_id, query_id, reasoning_steps)
            except WebSocketDisconnect as e:
                print(colored(f"WebSocketDisconnect {e}", "grey"))
                break
    finally:
        if user_id in active_connections:
            del active_connections[user_id]
            # Don't delete CSV files immediately - they may be needed for follow-up plot requests
            # Files will be cleaned up by periodic cleanup job instead
            # await remove_files_with_user_id(user_id)



@router.post('/feedback')
@time_it
async def feedback(feedback_request: FeedbackRequest):
    feedback = feedback_request.feedback
    status = feedback_request.status
    time_stamp = feedback_request.time_stamp
    user = feedback_request.user
    feedmessage = feedback_request.feedmessage
    
    user_email = user.split("_")[0].rsplit(":", 1)[0]
    print(colored(f"user_email: {user_email}", "yellow"))
    if status == 'positive':
        stored_conv_cache_key = keyring.get_password("chatengine", user_email)
        print(f"Stored cache key for this user: {stored_conv_cache_key}")
        
        if not stored_conv_cache_key:
            print("No cache key found for this user.")
            return {'status': 400, 'message': 'No cache key found for this user.'}
        
        cached_data_str = cache_client.get(stored_conv_cache_key)
        if not cached_data_str:
            print("No cached data found for this user.")
            return {'status': 400, 'message': 'No cached data found for this user.'}
        
        try:
            cached_data = json.loads(cached_data_str)
            correct_sql = cached_data.get('sql')
            user_input = cached_data.get('input')
            
            try:
                user_input_data = json.loads(user_input)
                user_question = user_input_data.get("User_Question", user_input)
            except Exception:
                user_question = user_input
            
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            csv_path = os.path.join(project_root, "utility", "queries.csv")

            with open(csv_path, 'a+', newline='', encoding='utf-8') as csv_file:
                csv_file.seek(0, os.SEEK_END)
                if csv_file.tell() != 0:
                    csv_file.write("\n")
                writer = csv.writer(csv_file)
                writer.writerow([str(user_question), correct_sql])
        except Exception as e:
            print(f"Error processing cached data: {str(e)}")
            return {'status': 400, 'message': 'Error processing cached data.'}  
    
    feedback_logs(feedback,status,time_stamp,user,feedmessage)
    result = {'status': 200, 'message': 'Feedback received'}
    return result

@router.post('/reset')
@time_it
async def reset_messages(request: Request):
    try:
        data = await request.json()
        user_id = data.get('user_id')

        if user_id is None:
            raise HTTPException(status_code=400, detail="User ID is missing in the request.")
        if user_id in active_connections:
            del globals.session_id[user_id]
            await close_websocket_connection(user_id)
            await remove_files_with_user_id(user_id)
            temp_folder = "temp"
            csv_files = [f for f in os.listdir(temp_folder) if f.endswith('.csv')]
            for csv_file in csv_files:
                os.remove(os.path.join(temp_folder, csv_file))
            
            clear_conversation_ids()
            
        return 'Messages reset', 200
    except JSONDecodeError:
        await log_error(None, "Invalid JSON format in the request.", 400)
        raise HTTPException(status_code=400, detail="Invalid JSON format in the request.")
    except Exception as e:
        #log_error(user_id, error_message, 500)
        #raise HTTPException(status_code=500, detail=error_message)
        raise HTTPException(status_code=500, detail=str(e))

@router.get('/chatlogs') 
@time_it
async def getmessageslist(request : Request):
    try :
        token = request.cookies.get("access_token")
        if token is None:
            raise HTTPException(status_code=401, detail= 'No Token recevied')
        user = await user_verification(token)
        if user.disabled is True:
            raise HTTPException(status_code=401, detail= 'User Disabled') 
        else :
            data = await get_chat_logs(user.email)
            return data
        
    except JSONDecodeError:
        await log_error(None, "Invalid JSON format in the request.", 400)
        raise HTTPException(status_code=400, detail="Invalid JSON format in the request.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@router.get('/getconversationbyid/{timestamp}')  
@time_it 
async def getmessagesbyid(request: Request, timestamp: str):     
    try:         
        token = request.cookies.get("access_token")         
        if token is None:             
            raise HTTPException(status_code=401, detail='No Token received')                      
        
        user = await user_verification(token)         
        if user.disabled is True:             
            raise HTTPException(status_code=401, detail='User Disabled')                      
        
        # Get base conversation data         
        data = await get_chat_conversationbyid(timestamp)                  
        
        title = await chat_completion_request(             
            messages=[                 
                {"role": "user", "content": f"Generate a concise summarized title based on user question : {data[0]['sent_message']} and assistant response : {data[0]['received_message']}."}             
            ],             
            model="gpt-4o-mini")                  
        
        data[0]["title"] = title.model_dump()['choices'][0]['message']['content']                  
        
        # Check cache for fig_json references         
        cache_key = f"fig_json_{user.email}_{timestamp}"         
        cached_refs = cache_client.get(cache_key)                  
        
        fig_json_data = []         
        if cached_refs:             
            # Use cached references to retrieve fig_json data             
            refs_data = json.loads(cached_refs)             
            fig_json_refs = refs_data.get("fig_json_refs", [])                          
            
            # Initialize blob storage             
            connection_string = os.getenv("BLOB_CONNECTION_STRING")             
            blob_storage = BlobStorage(connection_string, "chat-images")                          
            
            # Retrieve each fig_json by its reference ID             
            for ref in fig_json_refs:                 
                fig_data = await blob_storage.get_fig_json_by_id(                     
                    ref["ref_id"],                      
                    user.email,                      
                    timestamp                 
                )                 
                if fig_data:                     
                    fig_json_data.append({                         
                        "data": fig_data,                         
                        "ref_id": ref["ref_id"],                         
                        "index": ref.get("index", 0)                     
                    })         
        else:             
            # Try to retrieve all fig_json data directly from blob storage             
            connection_string = os.getenv("BLOB_CONNECTION_STRING")             
            blob_storage = BlobStorage(connection_string, "chat-images")                          
            
            
            retrieved_data = await blob_storage.retrieve_fig_json(user.email, timestamp)
            
            if retrieved_data and isinstance(retrieved_data, list):
                fig_json_data = retrieved_data
            elif retrieved_data:
                if isinstance(retrieved_data, dict) and "data" in retrieved_data:
                    fig_json_data = retrieved_data["data"]
                else:
                    fig_json_data = [retrieved_data]
                          
        # Add fig_json data to the response if any was found         
        if fig_json_data:             
            data[0]["fig_json_data"] = sorted(fig_json_data, key=lambda x: x.get("index", 0))             
            data[0]["is_image"] = True                  
        
        return data              
    except Exception as e:         
        print(colored(f"Error in getmessagesbyid: {str(e)}", "red"))         
        await log_error(user.email if 'user' in locals() else "unknown_user", str(e), "getmessagesbyid")         
        raise HTTPException(status_code=500, detail=str(e))