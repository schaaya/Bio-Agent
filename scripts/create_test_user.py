"""
Create Test User Script
========================

Creates a test user in the application database.

Usage:
    python scripts/create_test_user.py

This will create a default test user:
    - Email: test@example.com
    - Password: test123
    - Group: alpha
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from CURD.flexible_db_session import get_app_db, init_db
from CURD.app_models import UserData
from termcolor import colored
import bcrypt

def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def create_test_user(
    name: str = "Test User",
    email: str = "test@example.com",
    password: str = "test123",
    group_name: str = "alpha",
    admin: bool = True
):
    """Create a test user in the database"""

    # Initialize database if needed
    try:
        init_db()
    except:
        pass  # Already initialized

    with get_app_db() as db:
        # Check if user already exists
        existing = db.query(UserData).filter(UserData.email == email).first()
        if existing:
            print(colored(f"⚠️  User with email '{email}' already exists!", "yellow"))
            return existing

        # Hash password
        hashed_pw = hash_password(password)

        # Create user
        user = UserData(
            name=name,
            email=email,
            password=hashed_pw,
            group_name=group_name,
            admin=admin,
            disabled=False
        )

        db.add(user)
        db.commit()
        db.refresh(user)

        print(colored("\n✅ Test user created successfully!", "green", attrs=["bold"]))
        print(colored(f"\nLogin Credentials:", "cyan"))
        print(colored(f"  Email:    {email}", "white"))
        print(colored(f"  Password: {password}", "white"))
        print(colored(f"  Group:    {group_name}", "white"))
        print(colored(f"  Admin:    {admin}\n", "white"))

        return user

def main():
    print(colored("\n" + "="*60, "cyan"))
    print(colored("👤 Create Test User", "cyan", attrs=["bold"]))
    print(colored("="*60 + "\n", "cyan"))

    try:
        create_test_user()
    except Exception as e:
        print(colored(f"\n❌ Failed to create user: {str(e)}", "red"))
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
