import io
import os
import uuid
from dotenv import load_dotenv
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from CI_parser import process_document
from app.user_depends import get_admin_status
from schemas.db_models import CustomInstructionDB, Base as StorageBase, storage_engine, get_db
from schemas.instructions import CustomInstructionsRead, CustomInstructionsUpdate, ResponseMessage
from utility.decorators import time_it
from azure.storage.blob import BlobServiceClient
# Ensure database tables are created
StorageBase.metadata.create_all(bind=storage_engine)

router = APIRouter()

load_dotenv()

GLOBAL_INSTRUCTIONS_USER_ID = "global_instructions"

storage_connection_string = os.getenv("BLOB_CONNECTION_STRING")
container_name = "custom-instructions-docs"

@router.get("/custom-instructions", response_model=CustomInstructionsRead)
@time_it
def get_custom_instructions(
    db: Session = Depends(get_db)
):
    """
    Fetch the current user's instructions (one record).
    If no record found, return empty or default values.
    """
    user_id = GLOBAL_INSTRUCTIONS_USER_ID
    # Execute synchronous query
    db_item = db.execute(
        select(CustomInstructionDB).filter(CustomInstructionDB.user_id == user_id)
    ).scalars().first()
    
    # Return empty/default values if no record found
    if db_item is None:
        return CustomInstructionsRead(
            user_id=user_id,
            instructions=""
        )
    
    # Return found record
    return CustomInstructionsRead(
        user_id=db_item.user_id,
        instructions=db_item.instructions if db_item.instructions is not None else ""
    )

@router.put("/custom-instructions", response_model=ResponseMessage)
@time_it
async def upsert_custom_instructions(
    data: CustomInstructionsUpdate, 
    db: Session = Depends(get_db), 
    current_user: str = Depends(get_admin_status)
):
    """
    Upsert = Create or Update the single row for this user.
    - If record doesn't exist, create it.
    - If it does, update it.
    """
    user_id = GLOBAL_INSTRUCTIONS_USER_ID
    
    db_item = db.execute(
        select(CustomInstructionDB).filter(CustomInstructionDB.user_id == user_id)
    ).scalars().first()
    
    blob_service_client = BlobServiceClient.from_connection_string(storage_connection_string)
    blob_client = blob_service_client.get_blob_client(container=container_name, blob="custom_instructions.txt")
    
    # If no record, create a new one
    if db_item is None:
        new_record = CustomInstructionDB(
            user_id=user_id,
            instructions=data.instructions
        )
        db.add(new_record)
        db.commit()
        db.refresh(new_record)

        try:
            data_stream = io.StringIO(data.instructions)
            blob_client.upload_blob(data_stream.getvalue(), overwrite=True)
            print("Data stored in blob storage")
        except Exception as e:
            print(f"Error: {e}")
        message = "Custom instructions created successfully!"
        
        return ResponseMessage(
            success=True,
            message=message,
            data= new_record.to_dict()
        )
    
    # Otherwise, Update existing record
    if data.instructions is not None:
        db_item.instructions = data.instructions

        try:
            if blob_client.exists():
                existing_data = blob_client.download_blob().readall().decode('utf-8')
                combined_data = existing_data + "\n\n" + data.instructions
            else:
                combined_data = data.instructions
                
            data_stream = io.StringIO(combined_data)
            blob_client.upload_blob(data_stream.getvalue(), overwrite=True)
            print("Data stored(created/appended) in blob storage")
        except Exception as e:
            print(f"Error: {e}")
            
    db.commit()
    db.refresh(db_item)
    
    await process_document()
    print("Document processed successfully")
    
    custom_instruction_read = CustomInstructionsRead(
        user_id=db_item.user_id,
        instructions=db_item.instructions if db_item.instructions is not None else ""
    )
    
    return ResponseMessage(
        success=True, 
        message="Custom instructions updated successfully!", 
        data=custom_instruction_read.model_dump()
    )
