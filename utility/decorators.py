import time
import asyncio
import inspect
from functools import wraps

def time_it(func):
    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        start_time = time.time()
        # Get caller info
        caller_frame = inspect.currentframe().f_back
        caller_name = caller_frame.f_code.co_name if caller_frame else "unknown"
        
        result = func(*args, **kwargs)
        end_time = time.time()
        # print(f"{func.__name__} called by {caller_name} executed in {end_time - start_time:.4f} seconds")
        return result

    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        start_time = time.time()
        # Get caller info
        caller_frame = inspect.currentframe().f_back
        caller_name = caller_frame.f_code.co_name if caller_frame else "unknown"
        
        result = await func(*args, **kwargs)
        end_time = time.time()
        # print(f"{func.__name__} called by {caller_name} executed in {end_time - start_time:.4f} seconds")
        return result

    # Check if the function is async
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    else:
        return sync_wrapper