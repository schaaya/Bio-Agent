import re
from termcolor import colored
import core.globals as globals
from sqlalchemy import create_engine, text
from sqlalchemy.orm import scoped_session, sessionmaker
from core.globals import dbs_info, fetch_table_description
import sqlparse
from sqlparse.tokens import DML, Keyword, Whitespace, Punctuation
from utility.decorators import time_it

# Global variables for lazy initialization
_engines = None
_sessions = None
_initialized = False

# Create a function to initialize connection pools for multiple databases
@time_it
def create_engines(db_info):
    engines = {}
    sessions = {}
    try:
        for db_name, db_url in db_info.items():
            print(colored(f"Creating engine for {db_name}: {db_url}", "cyan"))

            # For SQLite databases, convert relative paths to absolute paths
            if db_url.startswith("sqlite:///") and not db_url.startswith("sqlite:////"):
                # Extract the relative path after sqlite:///
                relative_path = db_url.replace("sqlite:///", "")

                # If it's not an absolute path, make it absolute relative to /app
                if not relative_path.startswith("/"):
                    import os
                    absolute_path = os.path.abspath(relative_path)
                    db_url_absolute = f"sqlite:///{absolute_path}"
                    print(colored(f"  Converting relative path to absolute:", "yellow"))
                    print(colored(f"    Original: {db_url}", "yellow"))
                    print(colored(f"    Absolute: {db_url_absolute}", "yellow"))

                    # Check if file exists
                    if os.path.exists(absolute_path):
                        print(colored(f"  ✓ File exists: {absolute_path}", "green"))
                        db_url = db_url_absolute
                    else:
                        print(colored(f"  ✗ File not found: {absolute_path}", "red"))
                        # List files in the directory to help debug
                        dir_path = os.path.dirname(absolute_path)
                        if os.path.exists(dir_path):
                            files = os.listdir(dir_path)
                            print(colored(f"  Files in {dir_path}: {files[:10]}", "yellow"))

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
        print(colored(f"Error in create_engines: {e}", "red"))
        import traceback
        print(colored(traceback.format_exc(), "red"))
        for engine in engines.values():
            engine.dispose()
        raise


def _ensure_initialized():
    """
    Lazy initialization of database engines and sessions.
    Called on first use to ensure databases_dict is populated.
    """
    global _engines, _sessions, _initialized

    if _initialized:
        return

    try:
        # Load database info if not already loaded
        if not globals.databases_dict:
            print(colored("Loading database schemas...", "yellow"))
            dbs_info()
            fetch_table_description()

        # Build db_info dictionary
        db_info = {}
        for db_name in globals.databases_dict.keys():
            db_info[db_name] = globals.databases_dict[db_name]['string']

        # Create engines and sessions
        if db_info:
            _engines, _sessions = create_engines(db_info)
            _initialized = True
        else:
            print(colored("⚠️  No databases found in databases_dict", "yellow"))
            _engines = {}
            _sessions = {}
            _initialized = True

    except Exception as e:
        print(colored(f"⚠️  Error initializing database engines: {e}", "red"))
        _engines = {}
        _sessions = {}
        _initialized = True


# Getter functions to ensure lazy initialization
def get_engines():
    """Get engines, initializing if needed"""
    _ensure_initialized()
    return _engines

def get_sessions():
    """Get sessions, initializing if needed"""
    _ensure_initialized()
    return _sessions

# Backward compatibility: initialize on first access
class LazyEngines:
    def __getitem__(self, key):
        return get_engines()[key]

    def keys(self):
        return get_engines().keys()

    def values(self):
        return get_engines().values()

    def items(self):
        return get_engines().items()

    def get(self, key, default=None):
        return get_engines().get(key, default)

class LazySessions:
    def __getitem__(self, key):
        return get_sessions()[key]

    def keys(self):
        return get_sessions().keys()

    def values(self):
        return get_sessions().values()

    def items(self):
        return get_sessions().items()

    def get(self, key, default=None):
        return get_sessions().get(key, default)

# Export lazy wrappers to maintain backward compatibility
engines = LazyEngines()
sessions = LazySessions()

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