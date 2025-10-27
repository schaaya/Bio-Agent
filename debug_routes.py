"""
Debug script to check registered routes
Run this to see what routes are actually registered
"""
import sys
import os

# Add the project directory to the path
sys.path.insert(0, os.path.dirname(__file__))

# Mock environment variables if needed
os.environ.setdefault('JWT_SECRET_KEY', 'debug-key')
os.environ.setdefault('JWT_REFRESH_SECRET_KEY', 'debug-refresh-key')

try:
    from fastapi import FastAPI
    from mcp_files.mcp_fastapi_integration import mcp_router

    # Create minimal app
    app = FastAPI()

    # Add just the MCP router
    app.include_router(mcp_router)

    print("=== MCP Routes ===")
    for route in app.routes:
        if hasattr(route, 'path') and hasattr(route, 'methods'):
            print(f"Path: {route.path}")
            print(f"  Methods: {route.methods}")
            if hasattr(route, 'name'):
                print(f"  Name: {route.name}")
            print()

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
