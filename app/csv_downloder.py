from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse
from typing import Optional
import os
from starlette.status import HTTP_404_NOT_FOUND, HTTP_403_FORBIDDEN
from app.user_depends import get_admin_status
import core.globals as globals
from app.schema import SystemUser  

# Create a router for file download endpoints
router = APIRouter(
    prefix="/download",
    tags=["download"],
)

@router.get("/csv/{query_id}")
async def download_csv(
    query_id: str,
    user: SystemUser = Depends(get_admin_status)
):
    """
    Download the full CSV result file for a specific query.
    
    Parameters:
    - query_id: The unique identifier for the query results
    
    Returns:
    - The CSV file as a downloadable attachment
    
    Raises:
    - 404 if the file doesn't exist
    - 403 if the user doesn't have permission to access this file
    """
    # Extract email as the user identifier
    user_id_str = user.email
    
    # Get the file path from globals
    if user_id_str not in globals.session_data:
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="User session not found"
        )
    
    # Get the CSV path from globals
    csv_paths = globals.get_csv_paths(user_id_str)
    
    if not csv_paths or query_id not in csv_paths:
        # Try to find the file by pattern matching in the temp directory
        temp_dir = "temp"
        file_pattern = f"{user_id_str}_{query_id}"
        
        # Look for files in temp directory that match the pattern
        matched_files = [f for f in os.listdir(temp_dir) 
                        if f.startswith(file_pattern) and f.endswith("_results.csv")]
        
        if not matched_files:
            raise HTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail="CSV file not found"
            )
        
        # Use the first matched file
        file_path = os.path.join(temp_dir, matched_files[0])
    else:
        file_path = csv_paths[query_id]
    
    # Check if file exists
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail="CSV file not found"
        )
    
    # Get the filename for the download
    filename = os.path.basename(file_path)
    
    # Return the file as a downloadable attachment
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="text/csv"
    )

# The rest of the code remains the same
def add_csv_path_mapping(user_id: str, query_id: str, file_path: str):
    """Add a mapping from query_id to file_path for a user"""
    if not hasattr(globals, 'csv_paths'):
        globals.csv_paths = {}
    
    if user_id not in globals.csv_paths:
        globals.csv_paths[user_id] = {}
    
    globals.csv_paths[user_id][query_id] = file_path

def get_csv_paths(user_id: str):
    """Get all CSV paths for a user"""
    if not hasattr(globals, 'csv_paths'):
        return None
    
    return globals.csv_paths.get(user_id)