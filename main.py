from contextlib import asynccontextmanager
import os
from typing import AsyncGenerator
from dotenv import load_dotenv
from CURD.db_CURD import router as db_CURD
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse
from fastapi import FastAPI, Request, Depends
from fastapi.templating import Jinja2Templates
from CURD.user_CURD import router as user_CURD
from CURD.groups_CURD import router as group_CURD
from CURD.schema_CURD import router as schema_CURD
from fastapi.middleware.cors import CORSMiddleware
from app.admin_depends import router as admin_router
from starlette.middleware.sessions import SessionMiddleware
from app.websocket_depends import router as websocket_router
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from app.user_depends import router as user_router, get_admin_status
from app.upload_files import router as upload_router
from app.custom_instructions import router as custom_instructions_router
from app.tables_ack import router as table_ack_router
from app.csv_downloder import router as csv_downloder_router
from app.feedback_routes import router as feedback_router
from app.airport_decision_routes import router as airport_decision_router
from starlette.responses import JSONResponse

# MCP Infrastructure imports
from mcp_files.mcp_fastapi_integration import mcp_router as mcp_api_router, mcp_lifespan
from mcp_files.mcp_middleware import MCPRequestIDMiddleware, MCPMetricsMiddleware
from mcp_files.mcp_internal_client import close_internal_mcp_client

# BioAgent Integration
# from NSLC.bio_agent_integration import initialize_bio_agent, add_bio_routes  # Commented out - module doesn't exist

load_dotenv()

JWT_SECRET_KEY = os.environ['JWT_SECRET_KEY']
JWT_REFRESH_SECRET_KEY = os.environ['JWT_REFRESH_SECRET_KEY']


# ============================================================================
# Periodic Cleanup Task
# ============================================================================

async def periodic_csv_cleanup():
    """
    Periodic task to clean up old CSV files from temp directory.
    Runs every hour and deletes files older than 2 hours.
    """
    import asyncio
    import time
    from termcolor import colored

    while True:
        try:
            await asyncio.sleep(3600)  # Run every hour

            temp_folder = "temp"
            if not os.path.exists(temp_folder):
                continue

            now = time.time()
            cleanup_age = 7200  # 2 hours in seconds

            files_cleaned = 0
            for file in os.listdir(temp_folder):
                if file.endswith('.csv'):
                    file_path = os.path.join(temp_folder, file)
                    try:
                        # Delete if older than 2 hours
                        if now - os.path.getmtime(file_path) > cleanup_age:
                            os.remove(file_path)
                            files_cleaned += 1
                            print(colored(f"🧹 Cleaned up old CSV file: {file}", "grey"))
                    except Exception as e:
                        print(colored(f"⚠️ Error cleaning up {file}: {e}", "yellow"))

            if files_cleaned > 0:
                print(colored(f"✓ Cleaned up {files_cleaned} old CSV files", "green"))

        except asyncio.CancelledError:
            print(colored("🛑 CSV cleanup task cancelled", "grey"))
            break
        except Exception as e:
            print(colored(f"⚠️ Error in CSV cleanup task: {e}", "red"))
            # Continue running despite errors


# ============================================================================
# Lifespan with MCP Infrastructure
# ============================================================================

@asynccontextmanager
async def app_lifespan(app: FastAPI):
    """Application lifespan with MCP infrastructure"""
    # Start MCP infrastructure
    async with mcp_lifespan():
        try:
            # CRITICAL: Load all databases from PostgreSQL db_schema table
            print("\n" + "="*80)
            print("Loading database schemas...")
            print("="*80)
            try:
                from core.globals import dbs_info, fetch_table_description, databases_dict
                dbs_info()  # Load all databases from db_schema table
                fetch_table_description()  # Load table descriptions
                print(f"✓ Loaded {len(databases_dict)} databases from db_schema")
                print(f"  Available databases: {', '.join(databases_dict.keys())}")
            except Exception as e:
                print(f"⚠️ Database loading error: {e}")
                print("   Application may not function correctly")
            print("="*80 + "\n")

            # Initialize BioAgent during startup
            # print("\n" + "="*80)
            # print("Initializing BioAgent...")
            # print("="*80)
            # try:
            #     await initialize_bio_agent()
            #     print("✓ BioAgent initialized successfully!")
            # except Exception as e:
            #     print(f"⚠️ BioAgent initialization warning: {e}")
            #     print("   Application will continue without BioAgent")
            # print("="*80 + "\n")

            # Start periodic cleanup task for old CSV files
            import asyncio
            cleanup_task = asyncio.create_task(periodic_csv_cleanup())
            print("✓ Started periodic CSV cleanup task")

            yield
        finally:
            # Cancel cleanup task
            cleanup_task.cancel()
            try:
                await cleanup_task
            except asyncio.CancelledError:
                pass

            # Close internal MCP client on shutdown
            await close_internal_mcp_client()


app = FastAPI(lifespan=app_lifespan)

# ✅ CORS setup (use "*" temporarily if debugging)
# origins = [
#     "https://chat.buildbetter-tech.com",
#     "https://api.chat.buildbetter-tech.com",
#     "https://localhost:3000"
# ]

origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,             # Use ["*"] if testing
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



# ✅ Proxy headers fix (only hostnames, no https:// or trailing slashes)
app.add_middleware(
    ProxyHeadersMiddleware,
    trusted_hosts=[
        "localhost",
        "chat.buildbetter-tech.com",
        "api.chat.buildbetter-tech.com"
    ]
)

# ✅ Session Middleware
app.add_middleware(SessionMiddleware, secret_key=JWT_SECRET_KEY, session_cookie=JWT_REFRESH_SECRET_KEY)

# ✅ MCP Middleware (Request ID tracking and Metrics)
app.add_middleware(MCPRequestIDMiddleware)
app.add_middleware(MCPMetricsMiddleware)

# Include routes
app.include_router(user_router, tags=["Sign In"])
app.include_router(admin_router, tags=["Admin"], dependencies=[Depends(get_admin_status)])
app.include_router(db_CURD, tags=["DB CURD"], dependencies=[Depends(get_admin_status)])
app.include_router(group_CURD, tags=["Group CURD"], dependencies=[Depends(get_admin_status)])
app.include_router(user_CURD, tags=["User CURD"], dependencies=[Depends(get_admin_status)])
app.include_router(schema_CURD, tags=["Schema CURD"], dependencies=[Depends(get_admin_status)])
app.include_router(websocket_router, tags=["WebSocket"])
app.include_router(upload_router, tags=["Upload Files"])
app.include_router(custom_instructions_router, tags=["Custom Instructions"], dependencies=[Depends(get_admin_status)])
app.include_router(table_ack_router, tags=["Table Acknowledgement"])
app.include_router(csv_downloder_router, tags=["CSV Downloader"])
app.include_router(feedback_router, tags=["SQL Evaluation & Feedback"])
app.include_router(airport_decision_router, tags=["Airport A2A Decisions"])

# ✅ BioAgent Routes - Biomedical gene expression analysis
# add_bio_routes(app)  # Commented out - module doesn't exist

# ✅ MCP Routes - Fully MCP-compliant protocol endpoints
app.include_router(mcp_api_router)

# ✅ Preflight handler for OPTIONS (catch-all, comes AFTER specific routes)
@app.options("/{rest_of_path:path}")
async def preflight_handler():
    return JSONResponse(content={"message": "Preflight OK"}, status_code=200)

# Run the app (usually done by uvicorn/gunicorn inside Docker)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
