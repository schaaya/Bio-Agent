from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Request, BackgroundTasks
from typing import List
import aiofiles, os, traceback
from datetime import datetime
from app.dep import user_verification
from core.metadata_manager import MetadataManager, get_metadata_manager 
from core.PDF_Processor import DocumentProcessor
from core.DOC_summary import CSV_summary
from core.CSV_Processor import parse_dataframe
from utility.decorators import time_it
from core.globals import send_status_to_user, store_summary

router = APIRouter()

UPLOAD_DIR = "uploads/"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

# Function to process PDF and update metadata without status updates
async def process_pdf_background(user_id: str, file_location: str, filename: str, metadata_manager: MetadataManager):
    try:
        summarizer = DocumentProcessor(user_id)
        tokens_used, file_hash = await summarizer.process_pdf_and_summarize(file_location, filename)
        # Retrieve current metadata and update tokens and file_hash (omit status)
        metadata = await metadata_manager.get(user_id, filename)
        if metadata:
            metadata["tokens"] = tokens_used
            metadata["file_hash"] = file_hash
            await metadata_manager.set(user_id, filename, metadata)
        print(f"PDF '{filename}' processed successfully in background.")
    except Exception as e:
        print(f"Error processing PDF '{filename}' in background: {e}")
        # Optionally, log or store error details without using a status field
        metadata = await metadata_manager.get(user_id, filename)
        if metadata:
            metadata["error"] = str(e)
            await metadata_manager.set(user_id, filename, metadata)

@router.post("/upload-file")
@time_it
async def upload_file(
    request: Request, 
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    metadata_manager: MetadataManager = Depends(get_metadata_manager)
):
    try:
        token = request.cookies.get("access_token")
        if token is None:
            raise HTTPException(status_code=401, detail='No Token received')
        user = await user_verification(token)
        if user.disabled:
            raise HTTPException(status_code=401, detail='User Disabled')
        user_id = user.email

        csv_summaries = {}
        user_metadata = {}

        for uploaded_file in files:
            file_extension = uploaded_file.filename.split('.')[-1].lower()
            file_location = os.path.join(UPLOAD_DIR, uploaded_file.filename)
            # Save file asynchronously
            async with aiofiles.open(file_location, "wb") as file_object:
                content = await uploaded_file.read()
                await file_object.write(content)
            upload_time = datetime.utcnow().isoformat()

            if file_extension == "csv":
                try:
                    df, head, desc, cols, dtype = await parse_dataframe(file_location)
                except Exception as e:
                    raise HTTPException(status_code=500, detail=f"Error processing CSV: {str(e)}")

                summary = await CSV_summary.approve_query(user_id, cols, dtype, head, desc)
                user_metadata[uploaded_file.filename] = {
                    "file_type": "csv",
                    "columns": cols,
                    "dtypes": dtype,
                    "head": head,
                    "description": desc,
                    "df": df.to_dict(),
                    "upload_time": upload_time
                    # Status field removed
                }
                csv_summaries[uploaded_file.filename] = summary
                store_summary(user_id, {uploaded_file.filename: {"summary": summary}})
                print(f"CSV '{uploaded_file.filename}' processed successfully.")

            elif file_extension == "pdf":
                # Immediately store metadata without a status flag
                user_metadata[uploaded_file.filename] = {
                    "file_type": "pdf",
                    "upload_time": upload_time
                    # Status field removed
                }
                # Process PDF synchronously (wait until processing is done)
                await process_pdf_background(user_id, file_location, uploaded_file.filename, metadata_manager)
                print(f"PDF '{uploaded_file.filename}' processed successfully.")

            else:
                raise HTTPException(status_code=400, detail=f"Unsupported file type: {file_extension}")

        # Store metadata synchronously
        for filename, metadata in user_metadata.items():
            await metadata_manager.set(user_id, filename, metadata)

        response_message = {
            "status": 200,
            "message": "Files uploaded and processed successfully.",
            "files_processed": list(user_metadata.keys())
        }
        if csv_summaries:
            response_message["csv_summaries"] = csv_summaries

        return response_message

    except Exception as e:
        error_details = traceback.format_exc()
        print(f"Error occurred: {error_details}")
        raise HTTPException(status_code=500, detail=f"Error occurred: {str(e)}")
