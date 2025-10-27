#function_dicts.py
from core.globals import get_metadata, instructions_dict, csv_path_data, user_file_data, get_summary

def tools(user_id=None, logger_timestamp=None):

    code = instructions_dict["Matplotlib"]
    ask_database = instructions_dict["Ask Database"]
    get_weather_data = instructions_dict["Weather Data"]
    gen_code = instructions_dict["Gen Code"]
    matplotlib_code = code.format(csv_path = csv_path_data.get(user_id, 'None'),user_id=user_id,logger_timestamp=logger_timestamp)
    sql_graphs = instructions_dict["SQL Graphs"]
    user_email = user_id.split("_")[0]
    docs_summary = get_summary(user_email)
    print(user_email, docs_summary)
    

    
    greetings_tools = [
        {
            "type": "function",
            "function":{
                "name": "ask_database",
                "description": f"""Use this tool to answer SQL-related questions connected to the database. Along with the detailed question, include a dataframe tag with a specific identifier related to its purpose (e.g., issues_df, ratings_df, occupancy_df, capacities_df) in strict JSON format. For example, {{"question": "<question>", "tag": "<tag>"}}. Always, use different tag names from the ones present in the conversation history.""",
                "parameters" : {
                    "type": "object",
                    "properties":{
                        "question":{
                            "type": "string",
                            "description": "Questions related to Database. NOT A SQL QUERY."
                        }
                    },
                    "required":["question"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_weather_data",
                "description": f"""This tool fetches weather data for a given location. Input should include the question and valid location parameters. The location should be a string. For example, {{"question": "<question>", "location": "<location>"}}""",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "Location for which to fetch weather data."
                        }
                    },
                    "required": ["location"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "gen_plotly_code",
                "description": f"""This tool is designed for plotting data or modifying existing plot data. Do not generate your own data. Always check the data available in the user's question or context, or query the database for data. The input to this tool should be in strict JSON format and include the comprehensive question, a list of dataframe tags (referenced from the database calls, if none of the calls are made then refrence from conversation history), and a modify flag set to True (where applicable). For example, {{"question": "<question>", "tags": ["<tag1>", "<tag2>", ...], "modify": true/false}}""",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "matplotlib_code": {"type": "string", "description": "Functional Python code that generates a matplotlib plot"}
                        },
                    "required": ["matplotlib_code"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "csv_query",
                "description": f"Handle queries related to uploaded CSV file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "Filename of the CSV file."
                        }
                    },
                    "required": ["filename"]
                }
            }
        }, 
        {
            "type": "function",
            "function": {
                "name": "pdf_query",
                "description": f"Handle queries related to the uploaded PDF file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "Filename of the PDF file."
                        }
                    },
                    "required": ["filename"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "comparative_analyzer",
                "description": f"""This tool conducts comparative analyses between two data sources. The required input must include a comprehensive question, and optionally any accompanying data (either provided directly by the user or sourced from conversation history). All inputs must follow a strict JSON format and include the question. For example: {{"question": "<question>, "data": "< optional data>"}}""",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "input": {
                            "type": "string",
                            "description": "Input prompt for the comparative analysis."
                        }
                    },
                    "required": ["code"]
                }
            }
        }
    ]

    return greetings_tools