"""
Setup Alpha Group Permissions - Dynamic Version
================================================

This script automatically:
1. Finds the bio_gene_expression database ID
2. Creates or updates the Alpha user group
3. Grants access to all databases (MOI, MOI-ops, bio_gene_expression)
"""
import os
import sys
import json
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from termcolor import colored
from CURD.flexible_db_session import get_app_db
from CURD.app_models import DBSchema, UserGroup

load_dotenv()


def setup_alpha_group():
    """Create or update Alpha group with access to all databases"""
    print("\n" + "="*80)
    print(colored("🔧 Setting up Alpha group permissions", "cyan", attrs=["bold"]))
    print("="*80 + "\n")

    try:
        with get_app_db() as db:
            # Step 1: Get all active databases
            print(colored("📊 Finding all active databases...", "cyan"))
            databases = db.query(DBSchema).filter(DBSchema.db_status == True).all()

            if not databases:
                print(colored("❌ No active databases found!", "red"))
                return False

            print(colored(f"✓ Found {len(databases)} active database(s):", "green"))
            for db_entry in databases:
                print(f"  - {db_entry.db_name} (ID: {db_entry.id}, Type: {db_entry.db_system})")

            # Step 2: Build group schema
            print(colored("\n📋 Building group schema...", "cyan"))

            db_ids = []
            group_schema = {}

            for db_entry in databases:
                db_ids.append(str(db_entry.id))

                # Extract table/column info from db_column_description
                tables_dict = {}
                if db_entry.db_column_description:
                    for table_info in db_entry.db_column_description:
                        table_name = table_info.get("Table_Name")
                        columns = [col.get("ColumnName") for col in table_info.get("Columns", [])]
                        if table_name and columns:
                            tables_dict[table_name] = columns

                if tables_dict:
                    group_schema[str(db_entry.id)] = tables_dict
                    print(f"  ✓ {db_entry.db_name}: {len(tables_dict)} tables")

            db_id_str = ','.join(db_ids)
            print(colored(f"\n✓ Schema built for database IDs: {db_id_str}", "green"))

            # Step 3: Check if Alpha group exists
            print(colored("\n👥 Checking for Alpha group...", "cyan"))
            alpha_group = db.query(UserGroup).filter(UserGroup.group_name == "alpha").first()

            if alpha_group:
                print(colored(f"✓ Found existing Alpha group (ID: {alpha_group.id})", "yellow"))
                print(f"  Current databases: {alpha_group.db_id}")

                # Update existing group
                alpha_group.db_id = db_id_str
                alpha_group.group_schema = group_schema

                db.commit()
                print(colored("\n✅ Updated Alpha group permissions", "green", attrs=["bold"]))
            else:
                print(colored("⚠️  Alpha group not found, creating new...", "yellow"))

                # Create new group
                new_group = UserGroup(
                    group_name="alpha",
                    db_id=db_id_str,
                    group_schema=group_schema
                )
                db.add(new_group)
                db.commit()

                print(colored("\n✅ Created Alpha group", "green", attrs=["bold"]))

            # Step 4: Verify
            print(colored("\n📊 Final Alpha group configuration:", "cyan"))
            print(f"  Group name: alpha")
            print(f"  Database IDs: {db_id_str}")
            print(f"  Databases with access:")
            for db_entry in databases:
                print(f"    - {db_entry.db_name}")

            return True

    except Exception as e:
        print(colored(f"\n❌ Error: {str(e)}", "red"))
        import traceback
        traceback.print_exc()
        return False


def verify_user_group():
    """Check user's group assignment"""
    print("\n" + "="*80)
    print(colored("👤 Checking user group assignments...", "cyan"))
    print("="*80 + "\n")

    try:
        with get_app_db() as db:
            # Import UserData model
            from CURD.app_models import UserData

            users = db.query(UserData).all()

            if not users:
                print(colored("⚠️  No users found in database", "yellow"))
                print("   Run: python scripts/create_test_user.py")
                return

            print(colored(f"Found {len(users)} user(s):", "green"))
            for user in users:
                group_emoji = "✓" if user.group_name == "alpha" else "⚠️"
                print(f"  {group_emoji} {user.name} ({user.email})")
                print(f"     Group: {user.group_name}")
                if user.group_name != "alpha":
                    print(colored(f"     ⚠️  User should be in 'alpha' group!", "yellow"))

    except Exception as e:
        print(colored(f"\n❌ Error checking users: {str(e)}", "red"))


def main():
    print("\n" + "="*80)
    print(colored("🚀 ALPHA GROUP SETUP - DYNAMIC VERSION", "cyan", attrs=["bold"]))
    print("="*80)

    # Setup group
    if not setup_alpha_group():
        print(colored("\n❌ Setup failed!", "red"))
        return 1

    # Verify users
    verify_user_group()

    print("\n" + "="*80)
    print(colored("✅ SETUP COMPLETE!", "green", attrs=["bold"]))
    print("="*80)
    print("\n" + colored("Next steps:", "cyan"))
    print("  1. If any users have wrong group:")
    print("     UPDATE user_data SET group_name='alpha' WHERE email='your@email.com';")
    print("  2. Restart your backend: uvicorn main:app --reload")
    print("  3. Test query: 'Show TP53 expression in tumor vs normal'")
    print()

    return 0


if __name__ == "__main__":
    exit(main())
