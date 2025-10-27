from datetime import datetime
from fastapi import APIRouter
from termcolor import colored
from CURD.db_CURD import DBSchema
from CURD.user_CURD import UserData
from app.dep import user_verification
from fastapi import Request, APIRouter
from fastapi import status, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse, HTMLResponse
from core.globals import get_storage_db, old_instructions_dict
from app.schema import Instructions,LogCompletionUsageResponse
from core.logger import instructions, instructions_update, log_error, get_completion_usage, monthly_completion_usage, filter_by_latest_week

from utility.decorators import time_it
router = APIRouter()

templates = Jinja2Templates(directory="static")

router.mount("/static", StaticFiles(directory="static"), name="static")

@router.get("/admin", response_class=HTMLResponse)
@time_it
async def read_root(request: Request, token: str):
    try:
        if not token:
            return JSONResponse(content={"status": 401, "message": 'Not an Admin User' })
        user = await user_verification(token)
        user_id = user.email
        if user.disabled is True:
            return JSONResponse(content={"status": 401, "message": 'User Disabled' })
        if user.admin is True and user.disabled is False:
            return templates.TemplateResponse("index.html", {"request": request, "user": user_id})
        else:
            return JSONResponse(content={"status": 401, "message": 'Not an Admin User' })
    except Exception as e:
        await log_error(user_id, str(e), "Error at Admin route")
        print(colored(f"Error at Admin route: {e}", "red"))
        return JSONResponse(content={"status": 401, "message": 'Error accessing Admin info ' })

@router.get("/release_notes")
@time_it
def read_root(request: Request):
    return templates.TemplateResponse("release_notes.html", {"request": request})

@router.post('/instruction')
@time_it
async def feedback(instruction_data : Instructions):
    id = instruction_data.id
    instruction = instruction_data.instruction
    logger_timestamp = datetime.now().isoformat(' ', 'seconds')
    logger_timestamp_mod = logger_timestamp.replace("-","_").replace(":","_").replace(" ","_")
    instructions(id=id, instruction=instruction, timestamp=logger_timestamp_mod)
    instructions_update()
    result = {'status':200, 'message':'Updated'}
    return result


@router.get('/get_instructions')
@time_it
def get_instructions():
    return JSONResponse(content={"status": 200, "data": old_instructions_dict})


   
@router.get("/statics", response_model=LogCompletionUsageResponse, status_code=status.HTTP_200_OK)
@time_it
async def log_completion_usage_route():
    try:
        # user = await user_verification(token)
        # user_id = user.email
        response = await get_completion_usage()
        print(colored(f"Statics response: {e}", "grey"))
        return JSONResponse(content={"status": 200, "logs": response})

    except Exception as e:
        # await log_error(user_id, str(e), "Error at Statics route")
        raise HTTPException(status_code=500, detail=f"Error logging completion usage: {e}")



@router.get("/latest-month-statistics", status_code=status.HTTP_200_OK)
@time_it
async def log_completion_usage_latest_month_route():
    try:
      
        logs = await monthly_completion_usage()
        
        
        return JSONResponse(content={"status": 200, "logs": logs})

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error filtering completion usage by latest month: {e}")
    


@router.get("/latest-week-statistics", status_code=status.HTTP_200_OK)
@time_it
async def log_completion_usage_latest_week_route():
    try:
        logs = await get_completion_usage()
        
        filtered_logs = await filter_by_latest_week(logs)
        
        return JSONResponse(content={"status": 200, "logs": filtered_logs})

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error filtering completion usage by latest week: {e}")


 
@router.get("/dashboard/stats", status_code=status.HTTP_200_OK)
@time_it
async def get_dashboard_stats():
    try:
        no_of_users = await get_total_users()
        no_of_tokens = await get_total_tokens()
        no_of_databases = await get_total_databases()
        total_price = await calculate_total_price(no_of_tokens)
 
        return {
            "NoOfUsers": no_of_users,
            "NoOfTokens": no_of_tokens,
            "NoOfDataBases": no_of_databases,
            "TotalPrice": total_price
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching dashboard stats: {e}")
 
@time_it
async def get_total_users():
    storage_db = next(get_storage_db())
    try:
        user_count = storage_db.query(UserData).count()
        return user_count
    finally:
        storage_db.close()

@time_it
async def get_total_tokens():
    try:
        logs = await get_completion_usage()
        total_tokens = sum(log.get('total_tokens', 0) for log in logs)
        return total_tokens
    except Exception as e:
        print(colored(f"Error in get_total_tokens: {e}", "red"))
        return 0

@time_it
async def get_total_databases():
    storage_db = next(get_storage_db())
    try:
        db_count = storage_db.query(DBSchema).count()
        return db_count
    finally:
        storage_db.close()

@time_it
async def calculate_total_price(total_tokens):
    # Assuming a price of $0.002 per 1000 tokens (GPT-3.5-turbo pricing)
    price_per_1000_tokens = 0.002
    total_price = (total_tokens / 1000) * price_per_1000_tokens
    return round(total_price, 2)