"""
MOI_OPS Database Loader

Loads pre-configured table and column descriptions for the MOI_OPS airport operations database.
This ensures signal queries have proper context for SQL generation.
"""
import json
import os
from pathlib import Path
from termcolor import colored
import core.globals as globals


def load_moi_ops_descriptions():
    """
    Load MOI_OPS table and column descriptions into globals.table_descriptions

    This function reads the pre-configured descriptions from config/moi_ops_descriptions.json
    and populates them into the global table_descriptions dictionary so that the SQL
    generation engine has proper context when generating queries for signal retrieval.

    Returns:
        bool: True if descriptions were loaded successfully, False otherwise
    """
    try:
        # Find the config file
        config_path = Path(__file__).parent.parent / "config" / "moi_ops_descriptions.json"

        if not config_path.exists():
            print(colored(f"⚠️  MOI_OPS descriptions file not found at: {config_path}", "yellow"))
            return False

        # Load the descriptions
        with open(config_path, 'r') as f:
            descriptions = json.load(f)

        # Get the MOI_OPS database descriptions
        moi_ops_descriptions = descriptions.get("MOI_OPS", {})

        if not moi_ops_descriptions:
            print(colored("⚠️  No MOI_OPS descriptions found in config file", "yellow"))
            return False

        # Ensure globals.table_descriptions is initialized
        if not hasattr(globals, 'table_descriptions'):
            globals.table_descriptions = {}

        # Find the MOI_OPS database name in the databases_dict
        # It could be named "MOI-ops", "MOI_OPS", "moi_ops_db", or similar
        moi_ops_db_name = None

        # DEBUG: Print current databases_dict
        print(colored(f"🔍 DEBUG: databases_dict keys = {list(globals.databases_dict.keys()) if hasattr(globals, 'databases_dict') and globals.databases_dict else 'EMPTY OR NOT FOUND'}", "magenta"))

        if hasattr(globals, 'databases_dict') and globals.databases_dict:
            for db_name in globals.databases_dict.keys():
                # Match databases containing 'moi' and 'ops' (case insensitive, ignore separators)
                db_name_normalized = db_name.lower().replace('-', '').replace('_', '')
                print(colored(f"🔍 DEBUG: Checking db_name='{db_name}', normalized='{db_name_normalized}'", "magenta"))
                if 'moi' in db_name_normalized and 'ops' in db_name_normalized:
                    moi_ops_db_name = db_name
                    print(colored(f"✅ Found MOI_OPS database in databases_dict: {moi_ops_db_name}", "green"))
                    break

        if not moi_ops_db_name:
            # Force refresh of databases_dict if it's empty
            if not globals.databases_dict:
                print(colored(f"🔄 databases_dict is empty, calling dbs_info() to refresh...", "yellow"))
                try:
                    from core.globals import dbs_info
                    dbs_info()
                    print(colored(f"✅ databases_dict refreshed: {list(globals.databases_dict.keys())}", "green"))

                    # Try again after refresh
                    for db_name in globals.databases_dict.keys():
                        db_name_normalized = db_name.lower().replace('-', '').replace('_', '')
                        if 'moi' in db_name_normalized and 'ops' in db_name_normalized:
                            moi_ops_db_name = db_name
                            print(colored(f"✅ Found MOI_OPS database after refresh: {moi_ops_db_name}", "green"))
                            break
                except Exception as e:
                    print(colored(f"⚠️  Failed to refresh databases_dict: {e}", "yellow"))

            # If still not found, use fallback
            if not moi_ops_db_name:
                moi_ops_db_name = "MOI-ops"
                print(colored(f"⚠️  MOI_OPS database not found in databases_dict, using fallback: {moi_ops_db_name}", "yellow"))

        # Transform the descriptions into the format expected by globals.table_descriptions
        # Expected format: globals.table_descriptions[db_name][table_name] = {
        #     "table_description": "...",
        #     "column1": "description1",
        #     "column2": "description2",
        #     ...
        # }

        formatted_descriptions = {}

        for table_name, table_info in moi_ops_descriptions.items():
            formatted_descriptions[table_name] = {
                "table_description": table_info.get("table_description", "")
            }

            # Add column descriptions
            if "columns" in table_info:
                for column_name, column_description in table_info["columns"].items():
                    formatted_descriptions[table_name][column_name] = column_description

        # Store in globals
        globals.table_descriptions[moi_ops_db_name] = formatted_descriptions

        print(colored(f"✅ Loaded MOI_OPS descriptions for {len(formatted_descriptions)} tables", "green"))
        print(colored(f"   Database name: {moi_ops_db_name}", "green"))
        print(colored(f"   Tables: {', '.join(formatted_descriptions.keys())}", "green"))

        return True

    except Exception as e:
        print(colored(f"❌ Failed to load MOI_OPS descriptions: {str(e)}", "red"))
        import traceback
        traceback.print_exc()
        return False


def ensure_moi_ops_schema_in_group(user_group: str):
    """
    Ensure the MOI_OPS database schema is available for the given user group

    This function checks if the user group has access to MOI_OPS database schema,
    and if not, adds it temporarily for signal retrieval.

    Args:
        user_group: The user group name

    Returns:
        tuple: (moi_ops_db_name, moi_ops_schema) or (None, None) if failed
    """
    try:
        # First, find the actual MOI_OPS database name from globals.databases_dict
        # It might be 'MOI-ops', 'MOI_OPS', 'moi_ops_db', etc.
        actual_db_name = None

        # DEBUG: Print current databases_dict
        print(colored(f"🔍 DEBUG (ensure_schema): databases_dict keys = {list(globals.databases_dict.keys()) if hasattr(globals, 'databases_dict') and globals.databases_dict else 'EMPTY OR NOT FOUND'}", "magenta"))

        # Force refresh if empty
        if hasattr(globals, 'databases_dict') and not globals.databases_dict:
            print(colored(f"🔄 (ensure_schema) databases_dict is empty, calling dbs_info() to refresh...", "yellow"))
            try:
                from core.globals import dbs_info
                dbs_info()
                print(colored(f"✅ (ensure_schema) databases_dict refreshed: {list(globals.databases_dict.keys())}", "green"))
            except Exception as e:
                print(colored(f"⚠️  (ensure_schema) Failed to refresh databases_dict: {e}", "yellow"))

        if hasattr(globals, 'databases_dict') and globals.databases_dict:
            for db_name in globals.databases_dict.keys():
                # Match databases containing 'moi' and 'ops' (case insensitive, ignore separators)
                db_name_normalized = db_name.lower().replace('-', '').replace('_', '')
                print(colored(f"🔍 DEBUG (ensure_schema): Checking db_name='{db_name}', normalized='{db_name_normalized}'", "magenta"))
                if 'moi' in db_name_normalized and 'ops' in db_name_normalized:
                    actual_db_name = db_name
                    print(colored(f"✅ Found MOI_OPS database in databases_dict: {actual_db_name}", "green"))
                    break

        if not actual_db_name:
            print(colored("⚠️  MOI_OPS database not found in databases_dict", "yellow"))
            # Fallback to actual engine name
            actual_db_name = "MOI-ops"

        # Ensure globals.gROUP_DB_SCHEMA is initialized
        if not hasattr(globals, 'gROUP_DB_SCHEMA'):
            globals.gROUP_DB_SCHEMA = {}

        # Check if user group exists
        if user_group not in globals.gROUP_DB_SCHEMA:
            globals.gROUP_DB_SCHEMA[user_group] = {}

        group_schema = globals.gROUP_DB_SCHEMA[user_group]

        # Look for MOI_OPS database in the group schema (using the actual name)
        moi_ops_db_name = None
        moi_ops_schema = None

        # First check if it already exists with the actual database name
        if actual_db_name in group_schema:
            moi_ops_db_name = actual_db_name
            moi_ops_schema = group_schema[actual_db_name]
        else:
            # Also check for similar names
            for db_name, db_schema in group_schema.items():
                db_name_normalized = db_name.lower().replace('-', '').replace('_', '')
                if 'moi' in db_name_normalized and 'ops' in db_name_normalized:
                    moi_ops_db_name = db_name
                    moi_ops_schema = db_schema
                    break

        # If not found, we need to add it
        if not moi_ops_db_name:
            # Define the MOI_OPS schema structure
            moi_ops_schema = {
                "postgresql": {
                    "flights": {
                        "columns": ["id", "flight_number", "airport_code", "terminal", "arrival_time",
                                   "status", "passenger_count", "airline", "origin", "destination", "created_at"]
                    },
                    "terminal_occupancy": {
                        "columns": ["id", "airport_code", "terminal", "current_count", "capacity",
                                   "occupancy_percent", "timestamp"]
                    },
                    "weather": {
                        "columns": ["id", "airport_code", "condition", "temperature", "humidity",
                                   "wind_speed", "visibility", "timestamp"]
                    },
                    "passenger_sentiment": {
                        "columns": ["id", "airport_code", "terminal", "sentiment_score",
                                   "mood_category", "timestamp"]
                    },
                    "staff": {
                        "columns": ["id", "staff_id", "name", "role", "airport_code", "terminal",
                                   "status", "shift_start", "shift_end"]
                    },
                    "staff_morale": {
                        "columns": ["id", "staff_id", "airport_code", "terminal", "morale_score",
                                   "fatigue_level", "timestamp"]
                    },
                    "robots": {
                        "columns": ["id", "robot_id", "type", "airport_code", "terminal",
                                   "battery_percent", "status", "last_maintenance", "timestamp"]
                    },
                    "zone_conditions": {
                        "columns": ["id", "zone_id", "airport_code", "terminal", "condition",
                                   "severity", "timestamp"]
                    },
                    "zone_traffic": {
                        "columns": ["id", "zone_id", "airport_code", "terminal", "traffic_level",
                                   "foot_count", "timestamp"]
                    },
                    "cleaning_log": {
                        "columns": ["id", "zone_id", "airport_code", "cleaner_id", "cleaner_type",
                                   "started_at", "completed_at", "notes"]
                    },
                    "occupancy_predictions": {
                        "columns": ["id", "airport_code", "terminal", "prediction_time",
                                   "predicted_occupancy_percent", "confidence", "created_at"]
                    }
                }
            }

            moi_ops_db_name = actual_db_name  # Use the actual database name from databases_dict

            # Add to group schema
            globals.gROUP_DB_SCHEMA[user_group][moi_ops_db_name] = moi_ops_schema

            print(colored(f"✅ Added {moi_ops_db_name} schema to user group: {user_group}", "green"))

        return moi_ops_db_name, moi_ops_schema

    except Exception as e:
        print(colored(f"❌ Failed to ensure MOI_OPS schema: {str(e)}", "red"))
        return None, None


def initialize_moi_ops_for_signals(user_group: str):
    """
    Complete initialization of MOI_OPS database for signal retrieval

    This function:
    1. Loads table and column descriptions
    2. Ensures schema is available for the user group
    3. Returns the database name and schema for use in signal queries

    Args:
        user_group: The user group name

    Returns:
        tuple: (db_name, db_schema, descriptions, dialect) or (None, None, None, None) if failed
    """
    try:
        # Load descriptions
        load_moi_ops_descriptions()

        # Ensure schema is in user group
        db_name, db_schema = ensure_moi_ops_schema_in_group(user_group)

        if not db_name or not db_schema:
            return None, None, None, None

        # Get descriptions
        descriptions = globals.table_descriptions.get(db_name, {})

        # Get dialect (should be PostgreSQL with capitals to match DB_rules.py)
        dialect = "PostgreSQL"
        if db_schema and isinstance(db_schema, dict):
            # Get the first key from schema (should be 'postgresql')
            schema_dialect = list(db_schema.keys())[0] if db_schema else "postgresql"
            # Normalize to match DB_rules.py format
            if schema_dialect.lower() == "postgresql":
                dialect = "PostgreSQL"
            elif schema_dialect.lower() == "mysql":
                dialect = "MySQL"
            else:
                dialect = schema_dialect

        print(colored(f"✅ MOI_OPS initialized for signals", "green"))
        print(colored(f"   Database: {db_name}", "green"))
        print(colored(f"   Tables: {len(descriptions)}", "green"))
        print(colored(f"   Dialect: {dialect}", "green"))

        return db_name, db_schema, descriptions, dialect

    except Exception as e:
        print(colored(f"❌ Failed to initialize MOI_OPS: {str(e)}", "red"))
        return None, None, None, None
