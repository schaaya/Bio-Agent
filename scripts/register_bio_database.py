"""
Register Bio Gene Expression Database
======================================

Registers the bio_gene_expression SQLite database in the db_schema table
so it can be used by the chat pipeline.

Usage:
    python scripts/register_bio_database.py
"""

import sys
import os
import json
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from CURD.flexible_db_session import get_app_db, init_db
from CURD.app_models import DBSchema
from termcolor import colored
from dotenv import load_dotenv

load_dotenv()

# Bio database configuration
BIO_DB_PATH = os.getenv("BIO_DB_PATH", "NSLC/bio_gene_expression.db")
BIO_DB_NAME = "bio_gene_expression"

# Bio database schema from the integration
BIO_SCHEMA = {
    "bio_gene_expression": {
        "db_type": "sqlite",
        "db_column_description": [
            {
                "Table_Name": "gene_expression",
                "Table_Description": "Gene expression data for lung cancer research",
                "Columns": [
                    {
                        "ColumnName": "gene_symbol",
                        "ColumnKey": "TEXT",
                        "Column_Description": "Official gene symbol (e.g., EGFR, TP53)"
                    },
                    {
                        "ColumnName": "expression_level",
                        "ColumnKey": "REAL",
                        "Column_Description": "Expression level measurement"
                    },
                    {
                        "ColumnName": "sample_id",
                        "ColumnKey": "TEXT",
                        "Column_Description": "Sample identifier"
                    },
                    {
                        "ColumnName": "patient_id",
                        "ColumnKey": "TEXT",
                        "Column_Description": "Patient identifier"
                    },
                    {
                        "ColumnName": "tissue_type",
                        "ColumnKey": "TEXT",
                        "Column_Description": "Type of tissue (tumor, normal)"
                    }
                ]
            },
            {
                "Table_Name": "clinical_data",
                "Table_Description": "Clinical information about patients",
                "Columns": [
                    {
                        "ColumnName": "patient_id",
                        "ColumnKey": "TEXT",
                        "Column_Description": "Patient identifier (primary key)"
                    },
                    {
                        "ColumnName": "age",
                        "ColumnKey": "INTEGER",
                        "Column_Description": "Patient age at diagnosis"
                    },
                    {
                        "ColumnName": "gender",
                        "ColumnKey": "TEXT",
                        "Column_Description": "Patient gender"
                    },
                    {
                        "ColumnName": "smoking_status",
                        "ColumnKey": "TEXT",
                        "Column_Description": "Smoking history"
                    },
                    {
                        "ColumnName": "stage",
                        "ColumnKey": "TEXT",
                        "Column_Description": "Cancer stage"
                    }
                ]
            }
        ]
    }
}

def register_bio_database():
    """Register the bio gene expression database in db_schema table"""

    print(colored("\n" + "="*70, "cyan"))
    print(colored("🧬 Registering Bio Gene Expression Database", "cyan", attrs=["bold"]))
    print(colored("="*70 + "\n", "cyan"))

    # Check if bio database file exists
    bio_path = Path(BIO_DB_PATH)
    if not bio_path.exists():
        print(colored(f"❌ Bio database file not found: {BIO_DB_PATH}", "red"))
        print(colored("   Make sure the file exists before registering.", "yellow"))
        return False

    print(colored(f"✓ Bio database file found: {BIO_DB_PATH}", "green"))
    print(colored(f"  Size: {bio_path.stat().st_size / 1024 / 1024:.2f} MB\n", "white"))

    # Initialize database if needed
    try:
        init_db()
    except:
        pass  # Already initialized

    with get_app_db() as db:
        # Check if already registered
        existing = db.query(DBSchema).filter(
            DBSchema.db_name == BIO_DB_NAME
        ).first()

        if existing:
            print(colored(f"⚠️  Database '{BIO_DB_NAME}' already registered!", "yellow"))
            print(colored("   Updating existing entry...\n", "yellow"))

            # Update existing
            existing.db_string = f"sqlite:///{BIO_DB_PATH}"
            existing.db_schema = BIO_SCHEMA
            existing.db_system = "sqlite"
            existing.db_description = "Biomedical gene expression database for lung cancer research"
            existing.db_status = True
            existing.db_column_description = BIO_SCHEMA["bio_gene_expression"]["db_column_description"]

            db.commit()
            print(colored("✅ Database entry updated!", "green"))
        else:
            # Create new entry
            print(colored("Creating new database entry...\n", "cyan"))

            bio_db = DBSchema(
                db_name=BIO_DB_NAME,
                db_string=f"sqlite:///{BIO_DB_PATH}",
                db_schema=BIO_SCHEMA,
                db_system="sqlite",
                db_description="Biomedical gene expression database for lung cancer research",
                db_status=True,
                db_column_description=BIO_SCHEMA["bio_gene_expression"]["db_column_description"]
            )

            db.add(bio_db)
            db.commit()
            db.refresh(bio_db)

            print(colored("✅ Database registered successfully!", "green", attrs=["bold"]))

        # Show summary
        print(colored("\n" + "="*70, "cyan"))
        print(colored("📊 Database Registration Summary", "cyan", attrs=["bold"]))
        print(colored("="*70, "cyan"))
        print(colored(f"  Database Name:  {BIO_DB_NAME}", "white"))
        print(colored(f"  Database Type:  sqlite", "white"))
        print(colored(f"  Database Path:  {BIO_DB_PATH}", "white"))
        print(colored(f"  Status:         Active", "white"))
        print(colored(f"  Tables:         {len(BIO_SCHEMA['bio_gene_expression']['db_column_description'])}", "white"))
        print(colored("="*70 + "\n", "cyan"))

        # List all databases
        all_dbs = db.query(DBSchema).filter(DBSchema.db_status == True).all()
        print(colored(f"✓ Total active databases: {len(all_dbs)}", "green"))
        for db_entry in all_dbs:
            print(colored(f"  - {db_entry.db_name} ({db_entry.db_system})", "white"))

        print(colored("\n✅ Restart your server to use the bio database!\n", "green", attrs=["bold"]))
        return True

def main():
    try:
        success = register_bio_database()
        if not success:
            sys.exit(1)
    except Exception as e:
        print(colored(f"\n❌ Failed to register database: {str(e)}", "red"))
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
