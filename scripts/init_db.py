"""
Database Initialization Script
===============================

This script initializes the application database with tables for:
- User accounts
- User groups
- Database schemas
- Schema metadata

Usage:
    python scripts/init_db.py

Environment:
    - Local Dev: Set USE_LOCAL_DB=true (uses SQLite)
    - Production: Set USE_LOCAL_DB=false (uses PostgreSQL)
"""

import sys
from pathlib import Path

# Add parent directory to path so we can import from CURD
sys.path.insert(0, str(Path(__file__).parent.parent))

from CURD.flexible_db_session import init_db, get_db_info
from termcolor import colored

def main():
    print(colored("\n" + "="*70, "cyan"))
    print(colored("🚀 Application Database Initialization", "cyan", attrs=["bold"]))
    print(colored("="*70 + "\n", "cyan"))

    # Show database configuration
    db_info = get_db_info()
    print(colored(f"Database Type: {db_info['type']}", "yellow"))
    print(colored(f"Database Location: {db_info['url']}", "yellow"))
    print()

    # Initialize database
    try:
        init_db()
        print(colored("\n✅ Database initialization completed successfully!", "green", attrs=["bold"]))
        print(colored("\nYou can now:", "cyan"))
        print(colored("  1. Start your application", "white"))
        print(colored("  2. Create users with scripts/create_user.py", "white"))
        print(colored("  3. Add database schemas via the API\n", "white"))
    except Exception as e:
        print(colored(f"\n❌ Database initialization failed: {str(e)}", "red", attrs=["bold"]))
        sys.exit(1)

if __name__ == "__main__":
    main()
