import io
from fastapi import UploadFile
import openai
import pandas as pd
import logging

from utility.decorators import time_it

# logging.basicConfig(
#     level=logging.DEBUG,  
#     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
#     handlers=[
#         logging.FileHandler("azure_openai_debug.log"),
#         logging.StreamHandler()
#     ]
# )

class CSVProcessor:
    def __init__(self, api_key, api_version, azure_endpoint):
        logging.debug("Initializing Azure OpenAI client")
        self.llm = openai.AsyncAzureOpenAI(
            api_key=api_key,
            api_version=api_version,
            azure_endpoint=azure_endpoint
        )

    @time_it
    async def generate_content(self, messages):
        logging.debug(f"Sending request to Azure OpenAI with messages: {messages}")
        try:
            response = await self.llm.chat.completions.create(
                model="gpt-4o",
                messages=messages
            )
            logging.debug(f"Raw response content: {response.model_dump()}")
            return response.model_dump()['choices'][0]['message']['content']
        except Exception as e:
            logging.error(f"Error in Azure OpenAI API call: {str(e)}", exc_info=True)
            raise e

@time_it
async def parse_dataframe(file_location: str):

    try:
        # Open and read the CSV from the saved location
        df = pd.read_csv(file_location)
        
        # head = df.head().to_dict()
        # desc = df.describe(include='all').to_dict()
        # cols = df.columns.to_list()
        # dtype = df.dtypes.apply(str).to_dict()
        head = str(df.head().to_dict())
        desc = str(df.describe().to_dict())
        cols = str(df.columns.to_list())
        dtype = str(df.dtypes.to_dict())

        
        return df, head, desc, cols, dtype

    except pd.errors.EmptyDataError:
        raise ValueError("CSV file appears to be empty or invalid.")
    except Exception as e:
        raise ValueError(f"Error processing CSV: {str(e)}")
    
    # content = await uploaded_file.read()
    # file_content = content.decode("utf-8")

    # df = pd.read_csv(io.StringIO(file_content))

    # head = str(df.head().to_dict())
    # desc = str(df.describe().to_dict())
    # cols = str(df.columns.to_list())
    # dtype = str(df.dtypes.to_dict())
    # return df, head, desc, cols, dtype

@time_it
def prepare_prompt(user_query, cols, dtype, desc, head):
    analysis_notes = (
        "Please consider the following points in your analysis:\n"
        "- Column Name Variations: Accommodate variations in column names, such as synonyms or different formats (e.g., 'Price/Earnings' as 'p/e' or 'price_earnings')." "When generating commands, ensure to use the following relevant original column names while maintaining their exact case sensitivity: {cols}.\n"
        "- Negative Values: Evaluate the relevance of negative values for the given metrics.\n"
            "  - If negative values are not meaningful in the context of the analysis (e.g., for performance scores or satisfaction ratings), consider excluding them to maintain the integrity of the analysis.\n"
            "  - If negative values are valid and informative, include them as appropriate, ensuring to communicate their implications clearly in the command.\n"
        "- Handling Missing Values: If there are missing or NaN values in critical columns, account for them in the command to prevent errors.\n"
        "- Data Distribution: Consider the distribution of the data, including outliers, as they may impact the results.\n"
            "  - Apply appropriate transformations or filtering to ensure meaningful comparisons.\n"
        "- Data Types: Be aware of the data types of each column, as this will determine the appropriate pandas methods and functions to use.\n"
            "  - Ensure any necessary type conversions are performed.\n"
        "- Aggregation: When performing comparisons, consider how data is aggregated or grouped.\n"
            "  - The choice of aggregation method can influence the analysis and should align with the user's intent.\n"
        "- Dimensionality: Take into account the dimensionality of the data.\n"
            "  - High dimensionality can complicate analyses and lead to overfitting in predictive models. Use dimensionality reduction techniques if necessary.\n"
        "- Correlation vs. Causation: Be cautious in interpreting correlations as causations.\n"
            "  - Ensure that the interpretation remains grounded in the context of the data.\n"
        "- Scalability and Performance: Consider the scalability of the command, especially if working with large datasets.\n"
            "  - Optimize the command for performance to ensure efficient execution."
    ).format(cols=', '.join(cols))
    
    final_query = (
        f"The dataframe name is 'df'. The dataframe has the following columns: {cols}.\n"
        f"Their datatypes are as follows: {dtype}.\n"
        f"The dataframe is formatted as: {desc}.\n"
        f"The head of the dataframe is: {head}.\n"
        f"{analysis_notes}\n"
        "You cannot use df.info() or any command that cannot be printed.\n"
        f"Write a pandas command to address the following query on the dataframe df: {user_query}"
    )
    
    prompt = [
        {
            "role": "system",
            "content": (
                "You are an expert Python developer specializing in pandas. "
                "Generate a simple pandas 'command' for user queries in JSON format. "
                "'command' should be in lower case. "
                "Do not include the 'print' function. Ensure you analyze the datatypes of the columns before generating the command."
                "Generate Response in JSON format."
                "For Example 'result': 'command' \n"
            )
        },
        {
            "role": "user",
            "content": final_query
        }
    ]
    return prompt

@time_it
def execute_pandas_command(command, df):
    local_vars = {'df': df}
    exec(f"data = {command}", {}, local_vars)
    return local_vars.get('data')
