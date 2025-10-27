import asyncio
import hashlib
import io
import os
import time
from typing import Dict, List, Optional, Tuple, Union
import uuid
import openai
import pandas as pd
import requests
import subprocess
import core.logger as logger
from termcolor import colored
from dotenv import load_dotenv
from openai import AsyncAzureOpenAI
from core.globals import send_status_to_user,api_time_log
import plotly.express as px
import plotly.graph_objects as go
import plotly
from plotly.subplots import make_subplots
import plotly.io as pio
import os
from azure.ai.inference import ChatCompletionsClient
from azure.core.credentials import AzureKeyCredential

from utility.decorators import time_it

load_dotenv()
temp_dir = "./temp"

weather_api_key = os.getenv("weather_api_key")
api = "azure"

if api == "openai":
    openai.api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("model4")
    client = openai.AsyncOpenAI(api_key=openai.api_key)

elif api == "azure":
    model="gpt-4o"
    client = AsyncAzureOpenAI(  
        api_key = os.getenv("AZURE_OPENAI_KEY"),  
        api_version = "2023-03-15-preview",
        azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    )


api_key = os.getenv("AZURE_DEEPSEEK_KEY", '')
model_endpoint = os.getenv("AZURE_DEEPSEEK_ENDPOINT", '')

if not api_key:
  raise Exception("A key should be provided to invoke the endpoint")

dp_client = ChatCompletionsClient(
        endpoint=model_endpoint,
        credential=AzureKeyCredential(api_key)
    )
def ds_chat_completion_request(user_id=None, messages=None):

    response = dp_client.complete(messages)

    print("Response:", response.choices[0].message.content)
    print("Model:", response.model)
    print("Usage:")
    print(" Prompt tokens:", response.usage.prompt_tokens)
    print(" Total tokens:", response.usage.total_tokens)
    print(" Completion tokens:", response.usage.completion_tokens)
@time_it
async def chat_completion_request(user_id=None, messages=None, model ="gpt-4o", tools=None, response_format = None, stop = None, max_tokens = None, temperature = None):
    start = time.time()
    if tools is not None:
        tool_choice = "auto"
    else:
        tool_choice = None
    
    if response_format is True:
        response_format={"type": "json_object"}
    else:
        response_format = None
        
    if model == "gpt-35-turbo-16k":
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature
        )
    else:
        response = await client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                response_format=response_format,
                stop = stop,
                max_tokens=max_tokens,
                temperature=temperature
            )
    end = time.time()
    api_time_log.append(round(end - start, 2))
    completion_tokens = response.usage.completion_tokens
    prompt_tokens = response.usage.prompt_tokens
    total_tokens = response.usage.total_tokens
    
    await logger.log_completion_usage(user_id, completion_tokens, prompt_tokens, total_tokens)

    return response



@time_it
async def generate_embedding(text):
    print("Generating the embeddings...")
    try:
        embedding = await client.embeddings.create(model="text-embedding-3-large", input=text)
        if isinstance(embedding.data, list):
            return [item.embedding for item in embedding.data]
        else:
            return embedding.data[0].embedding
        
        
    except Exception as e:
        print(f"Error generating embedding: {e}")
        return None
    
@time_it
async def embeddings_request(user_id, input):

    embedding = await client.embeddings.create(model="text-embedding-3-small", input= input)

    embedded_query= embedding.data[0].embedding
   
    embedding_total_tokens = embedding.usage.total_tokens
    embedding_prompt_tokens = embedding.usage.prompt_tokens
    # embedding_completion_tokens = embedding.usage.completion_tokens

    # await logger.log_completion_usage(user_id, embedding_completion_tokens, embedding_prompt_tokens, embedding_total_tokens)

    return embedded_query

@time_it
async def build_graph(code, user_id, logger_timestamp):
    await send_status_to_user(user_id, status="executing plot script...")
    file_name = f"plot_code_{user_id}_{logger_timestamp}.py"

    try:
        with open(file_name, 'w', encoding='utf-8') as file:
            file.write(code)

        result = subprocess.run(
            ['python', file_name],
            capture_output=True,
            text=True            
        )
        print(colored(f"Return Code at build_graph: {result.returncode}", "grey"))
        if result.returncode != 0:
            error_message = result.stderr.strip() or "An unknown error occurred."
            raise RuntimeError(f"Error executing script: {error_message}")
        elif result.returncode == 0:
            print("Result at build graph",result.stdout)
        

        return 'Plot saved.'

    except Exception as e:
        print(colored(f"Error at build_graph: {e}", "red"))
        raise RuntimeError(f"Error executing script: {error_message}")

    finally:
        if os.path.exists(file_name):
            os.remove(file_name)



@time_it
async def get_weather_data(location):
    """Function to get weather data from Open Weather API."""
    
    base_url = "http://api.openweathermap.org/data/2.5/weather"
    params = {
        "q": location,
        "appid": weather_api_key
    }
    try:
        response = requests.get(base_url, params=params)
        response.raise_for_status()
        weather_data = response.json()
        return weather_data

    except Exception as e:
        print(colored(f"Error at get_weather_data: {e}", "red"))
        return "Please provide a valid location."

@time_it
def get_plotly_figure(
    plotly_code: str,
    dfs: Dict[str, pd.DataFrame],
    dark_mode: bool = True
) -> Tuple[Optional[go.Figure], Optional[str]]:
    """
    Get a Plotly figure from a dictionary of dataframes and Plotly code.

    Args:
        plotly_code (str): The Plotly code to execute.
        dfs (Dict[str, pd.DataFrame]): A dictionary of dataframes (or data convertible to DataFrame).
        dark_mode (bool): Whether to apply a dark mode theme to the figure.

    Returns:
        Tuple[Optional[go.Figure], Optional[str]]: The Plotly figure and an optional error message.
    """

    try:
        local_dict = {
            **{
                key: (pd.DataFrame(value) if not isinstance(value, pd.DataFrame) else value)
                for key, value in dfs.items()
            },
            "px": px,
            "go": go,
            "pd": pd  # Add pandas to local scope for concat and other operations
        }
    except Exception as e:
        return None, f"Error converting an item in dfs to a DataFrame: {e}"

    try:
        compiled_code = compile(plotly_code, '<string>', 'exec')
    except Exception as e:
        return None, f"Error compiling Plotly code: {e}"

    try:
        exec(compiled_code, {}, local_dict)
    except Exception as e:
        return None, f"Error executing Plotly code: {e}"

    fig = local_dict.get("fig")
    if not isinstance(fig, go.Figure):
        return None, "The Plotly figure is None or invalid."

    if dark_mode:
        fig.update_layout(template="plotly_dark")

    return fig, None

@time_it
async def save_plotly_figure(fig, user_id: str, logger_timestamp: str, tool_id) -> str:
    print("Saving the Plotly figure...")
    if fig is None:
        raise ValueError("The figure is None and cannot be saved.")
    
    os.makedirs(temp_dir, exist_ok=True)

    filename = f"plot_code_{user_id}_{logger_timestamp}_{tool_id}.png"
    file_path = os.path.join(temp_dir, filename)
    
    try:
        pio.write_image(fig, file_path, scale=1.0)
        print(f"Figure saved to {file_path}")
    except Exception as e:
        print(f"Error saving figure: {e}")
        raise
    
    return file_path

def _generate_cache_key(tool_id: str, user_id: str) -> str:
        """Generates a unique cache key based on the tool name and input data."""
        hash_input = f"{tool_id}"
        hash = hashlib.sha256(hash_input.encode()).hexdigest()
        return f"{user_id}:{hash}"
    
async def clean_dataframe(df):
    """
    Cleans the provided DataFrame by handling NaN values and other issues.

    Args:
        df (pd.DataFrame): The DataFrame to clean.

    Returns:
        pd.DataFrame: The cleaned DataFrame.
    """
    if df is None or df.empty:
        return df

    df = df.dropna(how="all")
    
    df = df.fillna(0)
    
    df = df.drop_duplicates()
    
    return df

