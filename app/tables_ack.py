from fastapi import APIRouter, Query, Body
from pydantic import BaseModel
from typing import List
from core.globals import table_descriptions


router = APIRouter()

def get_all_table_names():
    """
    Returns a list of table names stored in the global table_descriptions dictionary.
    """
    table_names = []
    for _, tables in table_descriptions.items():
        table_names.extend(tables.keys())
    return table_names

ALL_TABLES = get_all_table_names()

class TablesPayload(BaseModel):
    tables: List[str]

@router.get("/tables")
def get_tables(search: str = Query("", description="Search term for tables")):
    """
    Return a list of table names that include the given 'search' term.
    If 'search' is empty, you could return [] or all tables (example below returns all).
    """
    search_lower = search.lower()
    if search_lower:
        matched_tables = [t for t in ALL_TABLES if search_lower in t.lower()]
        return matched_tables
    else:
        # If no search term provided, return everything or an empty list
        return ALL_TABLES

@router.post("/selected-tables")
def save_selected_tables(payload: TablesPayload = Body(...)):
    """
    Accepts a JSON body with a list of selected tables, e.g.:
       {"tables": ["uber.trips", "uber.cities"]}
    Then performs some action (like storing them in a DB).
    """
    selected = payload.tables
    # Example: print or store in DB
    print("User selected tables:", selected)

    return {
        "message": "Tables saved successfully!",
        "selected_tables": selected
    }
