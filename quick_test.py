import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import json

load_dotenv()
DATABASE_URL = os.getenv('USERS_POSTGRES')
engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    result = conn.execute(text("SELECT group_schema FROM user_groups WHERE group_name ='Alpha'"))
    row = result.fetchone()
    if row:
        schema = row[0]
        print("Current Alpha group schema:")
        print(json.dumps(schema, indent=2))
    else:
        print("Alpha group not found!")