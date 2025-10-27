from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from schemas.db_models import CustomInstructionDB
from schemas.instructions import CustomInstructionsRead

from utility.decorators import time_it

@time_it
def get_user_custom_instructions( db: Session, current_user: str) -> Optional[str]:
    """
    Fetch the current user's instructions (one record).
    If no record found, return empty or default values.
    """
    user_id = current_user.email
    # Execute synchronous query
    db_item = db.execute(
        select(CustomInstructionDB).filter(CustomInstructionDB.user_id == user_id)
    ).scalars().first()
    
    # Return empty/default values if no record found
    if db_item is None:
        return ""
    
    # Return found record
    return db_item.instructions if db_item.instructions is not None else ""
    