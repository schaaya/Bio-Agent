import re
from termcolor import colored
import core.globals as globals
from sqlalchemy import create_engine, text
from sqlalchemy.orm import scoped_session, sessionmaker
from core.globals import dbs_info, fetch_table_description
import sqlparse
from sqlparse.tokens import DML, Keyword, Whitespace, Punctuation
from utility.decorators import time_it

dbs_info()
fetch_table_description()

# Example dictionary with database names as keys and URLs as values
db_info = {}

list_db_names = globals.databases_dict.keys() # List of DB Names
for db_name in list_db_names:
            db_info[db_name] = globals.databases_dict[db_name]['string'] # Add db_string to db_info

# Create a function to initialize connection pools for multiple databases``
@time_it
def create_engines(db_info):
    engines = {}
    sessions = {}
    try:
        for db_name, db_url in db_info.items():
            engine = create_engine(
                db_url,
                pool_size=5, # Increase the pool size if you have a large number of tables
                max_overflow=10,
                pool_timeout=30,
                pool_recycle=1800,
                pool_pre_ping=True  
            )
            engines[db_name] = engine
            
            # Prime the connection pool with a simple query
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            
            session_factory = sessionmaker(bind=engine)
            sessions[db_name] = scoped_session(session_factory)

        print(colored("Database engines and sessions created successfully.", "green"))
        print(colored(f"Engines:{list(engines.keys())}", "grey"))
        return engines, sessions

    except Exception as e:
        print(f"Error in create_engines: {e}")
        for engine in engines.values():
            engine.dispose()
        raise


# Initialize engines and session makers

engines, sessions = create_engines(db_info)

# @time_it
# def is_safe_query(query):
#     # Check if the query starts with SELECT, allowing only read operations
#     query = query.strip().lower()
#     return re.match(r"^select\b", query) is not None


import sqlparse
from sqlparse.tokens import Keyword, DML, Whitespace, Punctuation

# Define disallowed keywords as a set for O(1) lookup
DISALLOWED_KEYWORDS = {
    'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER', 'TRUNCATE',
    'MERGE', 'CALL', 'EXPLAIN', 'GRANT', 'REVOKE', 'COMMIT', 'ROLLBACK',
    'SAVEPOINT', 'LOCK', 'RELEASE', 'EXECUTE', 'EXEC', 'DESCRIBE'
}

@time_it
def is_safe_query(query):
    """
    Enhanced and optimized safety check using sqlparse to ensure the query is a SELECT or
    CTE-based SELECT without any disallowed operations.

    Parameters:
    - query (str): The SQL query string to validate.

    Returns:
    - bool: True if the query is safe, False otherwise.
    """
    # Parse the query
    parsed = sqlparse.parse(query)
    
    # Ensure only one statement is present
    if len(parsed) != 1:
        print("Multiple SQL statements detected.")
        return False
    
    statement = parsed[0]
    
    # Flatten all tokens for efficient iteration
    tokens = list(statement.flatten())
    
    # Initialize an iterator
    token_iter = iter(tokens)
    
    # Flag to check if the query starts with SELECT or WITH
    starts_correctly = False
    
    try:
        # Skip initial whitespace and punctuation
        while True:
            token = next(token_iter)
            if token.is_whitespace or token.ttype == Punctuation:
                continue
            elif token.is_keyword:
                upper_value = token.normalized.upper()
                if upper_value in ('SELECT', 'WITH'):
                    starts_correctly = True
                else:
                    print(f"Query starts with disallowed keyword: {upper_value}")
                    return False
                break
            else:
                # Any other token type is disallowed at the start
                print(f"Query starts with disallowed token type: {token.ttype}")
                return False
    except StopIteration:
        # No tokens found
        print("Empty query.")
        return False
    
    if not starts_correctly:
        return False
    
    # Iterate through all tokens to detect disallowed keywords
    for token in tokens:
        if token.is_group:
            # Groups can contain nested tokens; handled by flattening
            continue
        if token.is_keyword:
            upper_value = token.normalized.upper()
            if upper_value in DISALLOWED_KEYWORDS:
                print(f"Disallowed keyword detected: {upper_value}")
                return False
    
    return True



@time_it
def execute_query(db_name, query):
    if not is_safe_query(query):
        raise ValueError("Only SELECT queries are allowed")

    # Performance safety check: Add hard limit if query doesn't have one
    query_upper = query.upper()
    has_limit = 'LIMIT' in query_upper
    has_aggregation = any(keyword in query_upper for keyword in ['GROUP BY', 'COUNT(', 'AVG(', 'SUM(', 'MAX(', 'MIN('])

    # If query has no LIMIT and no aggregation, enforce a maximum row limit
    MAX_ROWS = 10000
    if not has_limit and not has_aggregation:
        print(colored(f"⚠️  Query has no LIMIT - enforcing maximum of {MAX_ROWS} rows for performance", "yellow"))
        # Add LIMIT clause to query
        if query.rstrip().endswith(';'):
            query = query.rstrip()[:-1] + f" LIMIT {MAX_ROWS};"
        else:
            query = query.rstrip() + f" LIMIT {MAX_ROWS}"

    session = sessions[db_name]()
    try:
        # Wrap the query string in text()
        result = session.execute(text(query).execution_options(timeout=30))
        data = result.fetchall()

        # Warn if we hit the limit
        if len(data) == MAX_ROWS and not has_limit and not has_aggregation:
            print(colored(f"⚠️  Query returned maximum rows ({MAX_ROWS}). Results may be incomplete. Consider adding filters or using aggregation.", "yellow"))

        return data
    except Exception as e:
        raise e
    finally:
        # Close and return the session to the pool
        sessions[db_name].remove()