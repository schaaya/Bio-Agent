import base64
import html
from io import StringIO
import io
import json
import os
import re
import time
import pandas as pd
import plotly
from termcolor import colored
from core.legacy_agents.Agent_SQL_original import SQL_Agent
from core.CSV_Processor import prepare_prompt
from core.PDF_Processor import DocumentProcessor
from core.Report_Generator import ReportGenerator
from core.generate_ploty import generate_plotly_code, modify_plot_code_based_on_query                                                    
from core.globals import conv_his, get_conversation_ids, get_csv_path, get_metadata, get_metadata_all, get_tool, send_status_to_user, functions_time_log, global_plots
from core.logger import code_logs, file_logs, log_error
from core.metadata_manager import get_metadata_manager
from utility.tools import build_graph, chat_completion_request, clean_dataframe, embeddings_request, get_plotly_figure, get_weather_data, save_plotly_figure
import plotly.io as pio

from utility.decorators import time_it

metadata_manager =  get_metadata_manager()

class ToolHandler:
    def __init__(self, cache_client, user_id, logger_timestamp, user_group):
        self.cache_client = cache_client
        self.functions_time_log = []
        self.user_id = user_id
        self.logger_timestamp = logger_timestamp
        self.user_group = user_group
        self.sql_list = []
        self.sanitized_code_list = []
        self.fig_json_list = []
        self.base64_code_list = []
        self.sql = None
        self.base64_code = None
        self.code = None
        self.fig_json = None
    
    @time_it
    async def handle_tool_call(self, tool_call, report_content, summary_data, user_text, tool_types_used, tool_id, fig_json, sub_question, sub_question_list, custom_instructions=None, context_msg=None, query_id=None):
        """
        Handles a tool call by finding the relevant handler function and executing it.
        """
        handler_name = tool_call["function"]["name"]
        handlers = {
            "get_weather_data": self.handle_get_weather_data,
            "ask_database": self.handle_ask_database,
            "gen_plotly_code": self.handle_plotly,
            "csv_query": self.handle_csv_query,
            "pdf_query": self.handle_pdf_query,
            "comparative_analyzer": self.compare_data_sources
        }


        if handler_name in handlers:
            handler = handlers[handler_name]
            if handler_name == "ask_database":
                self.sql, tool_types_used, query_id, results_data = await handler(
                    tool_call, summary_data, tool_types_used, tool_id, sub_question
                )
                # Set report_content to results data for ask_database
                if results_data:
                    report_content = results_data
            elif handler_name == "gen_plotly_code":
                fig_json = await handler(tool_call, summary_data, fig_json, tool_id, sub_question, sub_question_list)
                # Keep query_id as None for plotly
            elif handler_name == "pdf_query":
                tool_types_used = await handler(tool_call, user_text, summary_data, tool_types_used, context_msg)
            elif handler_name == "csv_query":
                await handler(tool_call, user_text, summary_data)
            elif handler_name == "get_weather_data":
                await handler(tool_call, summary_data)
            else:
                report_content = await handler(tool_call, summary_data, custom_instructions, context_msg)

            return self.sql, self.base64_code_list, self.sanitized_code_list, tool_types_used, report_content, self.fig_json_list, query_id

    @time_it
    async def handle_get_weather_data(self, tool_call, summary_data):
        """
        Asynchronously handles the process of fetching weather data and updating the user with the status.

        Args:
            tool_call (dict): A dictionary containing the function call details, including arguments.
            user_id (str): The ID of the user requesting the weather data.
            summary_data (list): A list to append the fetched weather data summary.

        Returns:
            None

        Logs:
            Appends the time taken to fetch the weather data to the functions_time_log.
        """
        start = time.time()
        print(colored("Function at get_weather_data called", "grey"))
        await send_status_to_user(self.user_id, status="Fetching weather data...")
        value = tool_call["function"]["arguments"]
        if isinstance(value, str):
            value = json.loads(value)
            
        location = value.get("location")
        if location:
            result = await get_weather_data(location)
        else:
            result = "No location provided."
        summary_data.append({"source": "weather", "content": result})
        end = time.time()
        functions_time_log.append(f"Weather API: {round(end - start, 2)} seconds")
    
    @time_it
    async def handle_ask_database(self, tool_call, summary_data, tool_types_used, tool_id, sub_question):
        """
        Handles the process of asking a database-related question and processing the results.

        Args:
            tool_call (dict): The tool call containing the function arguments.
            user_id (str): The ID of the user making the request.
            user_group (str): The group to which the user belongs.
            logger_timestamp_mod (str): The logger timestamp modifier.
            summary_data (list): A list to store the summary of the results.
            sql_list (list): A list to store the SQL queries executed.

        Returns:
            str: A combined string of all executed SQL queries, separated by commas, or None if no queries were executed.

        """
        
        start = time.time()
        tool_types_used.add("database")
        # question_value = tool_call["function"]["arguments"].get("query")
        input = tool_call["function"]["arguments"]
        
        if isinstance(input, str):
            value = json.loads(input)
        else:
            value = input
        question_value =  sub_question
        tag = value.get("tag")
        results = sql = df_info = None
        # print(colored(f"Question: {question_value}", "blue"))
        status_message = f"Fetching details of {tag.strip('_df')}" if tag else "Processing your database query..."
        await send_status_to_user(self.user_id, status=status_message)
        results, sql, df_info, query_id = await SQL_Agent(question_value, self.user_id, self.user_group, self.logger_timestamp, tool_id, tag)
        # data = {'role': 'assistant', 'content': df_info}
        # conv_his(self.user_id, data)
        summary_data.append({"source": "database", "content": results})
        if sql is not None:
            self.sql_list.append(sql)
        sql = str(','.join(self.sql_list))
        end = time.time()
        functions_time_log.append(f"SQL Engine Total: {round(end - start, 2)} seconds")
        return sql, tool_types_used, query_id, results

    @time_it
    async def handle_plotly(self, tool_call, summary_data, fig_json, tool_id, sub_question, sub_question_list):
        """
        Handles the generation of a Plotly plot based on provided code, saves the plot, and returns the plot as a base64-encoded string.

        Args:
            tool_call (dict): Contains details of the function call, including the plotly code to execute.
            summary_data (list): A list to append the result of the plot generation.
            fig_json (str): JSON representation of the generated Plotly figure.

        Returns:
            tuple: (base64-encoded plot image, executed code, JSON representation of the figure).

        Raises:
            ValueError: If plot generation or saving fails.
        """
        start = time.time()
        print(colored("Function at Plotly called", "yellow"))
        await send_status_to_user(self.user_id, status="Generating plot...")

        error = None
        sql_list = []
        dfs = {}
        sub_questions = {}
        dfs_status = {}
        value = tool_call["function"]["arguments"]
        
        if isinstance(value, str):
            try:
                if isinstance(value, dict):
                    value = json.dumps(value)
                # print("Debug: JSON value before parsing:", value)
                value = json.loads(value)
            except json.JSONDecodeError as e:
                print(colored(f"JSONDecodeError: {e}", "red"))
                raise ValueError("Invalid JSON format in the tool call arguments.") from e
                
        input_text = value.get("question")
        tags = value.get("tags", [])
        modify = value.get("modify", False)
        query_ids_list = value.get("query_ids", [])  # Get query_ids from the tool call
        csv_file_paths_list = value.get("csv_file_paths", [])  # Get CSV paths directly

        print(colored(f"Plotly Input Text: {input_text}", "light_blue"))
        print(colored(f"Query IDs received: {query_ids_list}", "cyan"))
        print(colored(f"CSV file paths received: {csv_file_paths_list}", "green"))

        temp_folder = "temp"
        csv_files = [f for f in os.listdir(temp_folder) if f.endswith('.csv')]

        tag_to_path = {}
        if len(tags) > 0:
            if isinstance(tags, list):
                for tag in tags:
                    regex = re.compile(tag)
                    matching_files = [os.path.join(temp_folder, f) for f in csv_files if regex.search(f)]
                    if matching_files:
                        tag_to_path[tag] = matching_files[0]
            elif isinstance(tags, str):
                regex = re.compile(tags)
                matching_files = [os.path.join(temp_folder, f) for f in csv_files if regex.search(f)]
                if matching_files:
                    tag_to_path[tags] = matching_files[0]
            else:
                tag_to_path["default"] = [os.path.join(temp_folder, f) for f in csv_files]
        else:
            # When no tags specified, use CSV paths directly (best option)
            if csv_file_paths_list:
                # Use CSV paths directly - most reliable method
                for idx, csv_path in enumerate(csv_file_paths_list):
                    tag_name = f"data_{idx}"
                    tag_to_path[tag_name] = csv_path
                    print(colored(f"✅ Using CSV path {idx}: {csv_path}", "green"))

            # FALLBACK 1: Try query_ids if CSV paths not provided
            elif query_ids_list:
                # Use all query_ids to find multiple CSV files
                for idx, qid in enumerate(query_ids_list):
                    matching_files = [os.path.join(temp_folder, f) for f in csv_files if qid in f]
                    if matching_files:
                        # Create a unique tag for each CSV file (e.g., data_0, data_1, data_2)
                        tag_name = f"data_{idx}"
                        tag_to_path[tag_name] = matching_files[0]
                        print(colored(f"Found CSV for query_id {qid}: {matching_files[0]}", "green"))
                    else:
                        print(colored(f"⚠️ No CSV file found for query_id {qid}", "yellow"))

                # FALLBACK 2: If no files found by query_id, use timestamp-based matching
                # Find all CSV files matching the current user_id and timestamp pattern
                if not tag_to_path:
                    print(colored(f"⚠️ Query IDs didn't match files. Using timestamp-based matching...", "yellow"))
                    # Pattern: {user_id}_{timestamp}_mcp_*_results.csv
                    user_prefix = self.user_id.split("_")[0]  # Extract email part
                    timestamp_pattern = self.logger_timestamp

                    # Find files matching this session
                    session_files = [
                        os.path.join(temp_folder, f) for f in csv_files
                        if user_prefix in f and timestamp_pattern in f
                    ]
                    # Sort by modification time to get them in order
                    session_files.sort(key=lambda x: os.path.getmtime(x))

                    # Use the most recent files (up to len(query_ids_list))
                    for idx, file_path in enumerate(session_files[-len(query_ids_list):]):
                        tag_name = f"data_{idx}"
                        tag_to_path[tag_name] = file_path
                        print(colored(f"Using session CSV file {idx}: {file_path}", "green"))
            else:
                # Fallback: check conversation history
                query_id_to_use = None
                conversation_ids = get_conversation_ids()

                # Check recent conversation history for query_id
                if conversation_ids:
                    # Look through recent conversations (check last 3)
                    for conv_id in reversed(conversation_ids[-3:]):
                        cached_data = self.cache_client.get(conv_id)
                        if cached_data:
                            try:
                                data = json.loads(cached_data)
                                potential_query_id = data.get("query_id")
                                if potential_query_id:
                                    query_id_to_use = potential_query_id
                                    print(colored(f"Found query_id from conversation history: {query_id_to_use}", "cyan"))
                                    break
                            except Exception as e:
                                print(colored(f"Error parsing cached data: {e}", "yellow"))

                # If we found a query_id, look for its CSV file
                if query_id_to_use:
                    matching_files = [os.path.join(temp_folder, f) for f in csv_files if query_id_to_use in f]
                    if matching_files:
                        tag_to_path["data"] = matching_files[0]
                        print(colored(f"Using CSV from query_id {query_id_to_use}: {matching_files[0]}", "green"))
                    else:
                        print(colored(f"⚠️ No CSV file found for query_id {query_id_to_use}", "yellow"))

                # Fallback: use the most recent CSV file
                if not tag_to_path and csv_files:
                    csv_files_sorted = sorted(
                        [os.path.join(temp_folder, f) for f in csv_files],
                        key=lambda x: os.path.getmtime(x),
                        reverse=True
                    )
                    tag_to_path["data"] = csv_files_sorted[0]
                    print(colored(f"No tags specified, using most recent CSV: {csv_files_sorted[0]}", "yellow"))
            
        if tag_to_path:
            for tag, path in tag_to_path.items():
                try:
                    df = pd.read_csv(path)
                    
                    if df.empty:
                        print(f"Warning: DataFrame for tag '{tag}' is empty. Skipping.")
                        dfs_status[tag] = "Empty"
                        continue
                    
                    dfs[tag] = await clean_dataframe(df)
                    dfs_status[tag] = "Has data"

                except pd.errors.EmptyDataError:
                    print(f"Error: File '{path}' is empty or has no valid columns. Skipping.")
                    dfs_status[tag] = "Empty"
                    continue
                except Exception as e:
                    print(f"Error while reading file '{path}' for tag '{tag}': {e}")
                    dfs_status[tag] = f"Error: {str(e)}"
                    continue
                
                
            if sub_question_list:
                sub_questions = {tag: sub_question for tag, sub_question in zip(tag_to_path.keys(), sub_question_list)}
                combined = {tag: {'df': dfs[tag], 'sub_question': sub_questions[tag]} for tag in tag_to_path.keys() if dfs_status.get(tag) == "Has data"}
                
            else:
                combined = {tag: {'df': dfs[tag], 'sub_question': sub_question} for tag in tag_to_path.keys() if dfs_status.get(tag) == "Has data"}
        

            df_metadata_list = []
            for tag , df in dfs.items():
                if dfs_status.get(tag) == "Has data":
                    buffer = StringIO()
                    df.info(buf=buffer)
                    df_metadata_list.append(buffer.getvalue())

            tool_ids = get_tool()
            sql_list = [
                json.loads(self.cache_client.get(tool_id))["sql"]
                for tool_id in tool_ids
                if self.cache_client.get(tool_id)
            ]
            

        if modify:
            max_retries = 1  # Reduced from 3 to 1 (orchestrator handles retries)
            attempts = 0
            success = False
            
            while attempts < max_retries and not success:
                try:
                    print(colored(f"Attempt {attempts + 1} to modify plot code...", "yellow"))
                    conversation_ids = get_conversation_ids()
                    if conversation_ids:
                        last_conversation_id = conversation_ids[-1]
                        # print(colored(f"Last Conversation ID: {last_conversation_id}", "yellow"))
                        cached_value = self.cache_client.get(last_conversation_id)
                        if cached_value:
                            try:
                                plot_code = json.loads(cached_value).get("code")
                            except (json.JSONDecodeError, KeyError) as e:
                                print(colored(f"Error decoding plot code: {e}", "red"))
                                plot_code = None
                        else:
                            print(colored("No cached value found for the last conversation ID.", "red"))
                            plot_code = None
                        
                    sanitized_code = await modify_plot_code_based_on_query(
                        self.user_id, input_text, plot_code, sql_list, df_metadata_list, tags, error
                    )
                    
                    # print(colored(f"Sanitized Code: {sanitized_code}", "yellow"))
            
                    if sanitized_code:

        
                        if isinstance(sanitized_code, list):
                            for code in sanitized_code:
                                fig, error = get_plotly_figure(code, dfs, False)
                                self.sanitized_code_list.append(code)

                                if fig:
                                    fig_json = pio.to_json(fig)
                                    # png_img = pio.to_image(fig)
                                    
                                    if fig_json:
                                        self.fig_json_list.append(fig_json)

                                    # self.base64_code_list.append(base64.b64encode(png_img))
                                else:
                                    raise ValueError("No figure generated.")
                        else:
                            fig, error = get_plotly_figure(sanitized_code, dfs, False)
                            self.sanitized_code_list.append(sanitized_code)

                            if fig:
                                fig_json = pio.to_json(fig)
                                # png_img = pio.to_image(fig)
                                
                                if fig_json:
                                    self.fig_json_list.append(fig_json)

                                # self.base64_code_list.append(base64.b64encode(png_img))
                            else:
                                raise ValueError("No figure generated.")
                    success = True
            
                except ValueError as e:
                    attempts += 1
                    print(colored(f"Value Error: {e}", "red"))
                    if attempts >= max_retries:
                        print(colored(f"Failed to modify plot code after {max_retries} attempts.", "red"))
                        summary_data.append({"source": "plotly", "content": f"Error generating plot: {e}"})
                        end = time.time()
                        functions_time_log.append(f"Plotly Engine: {round(end - start, 2)} seconds")
                        return None
                    
                
                except Exception as e:
                    attempts += 1
                    print(colored(f"Unexpected Error on attempt {attempts}: {e}", "red"))
                    if attempts >= max_retries:
                        print(colored(f"Unexpected failure after {max_retries} attempts: {e}", "red"))
                        summary_data.append({"source": "plotly", "content": f"Unexpected failure after {max_retries} attempts: {e}"})
                        return None
                
            summary_data.append({"source": "plotly", "content": f"Generated plot code(s):\n {self.sanitized_code_list}"})
            end = time.time()
            functions_time_log.append(f"Plotly Engine: {round(end - start, 2)} seconds")

            return fig_json
        
        elif not tag_to_path :
            print(colored(f"Attempt to generate plot...", "yellow"))
            sanitized_code = await generate_plotly_code(
                self.user_id, input_text, None, None, None, error
            )
            
        else:
            try:
                # Check if we should combine plots based on:
                # 1. Multiple data sources AND
                # 2. Box plot request OR comparison across groups
                should_combine = False
                if len(tag_to_path) > 1:
                    input_lower = input_text.lower() if input_text else ""
                    # Keywords indicating we should combine data for box plots
                    combine_keywords = ["box plot", "compare", "versus", "vs", "across", "between", "tumor vs normal", "normal vs tumor"]
                    should_combine = any(keyword in input_lower for keyword in combine_keywords)

                if should_combine:
                    print(colored(f"🔄 Detected multi-group comparison request - combining {len(tag_to_path)} datasets", "magenta"))
                    attempts = 0
                    max_attempts = 3
                    while attempts < max_attempts:
                        try:
                            print(colored(f"Attempt {attempts + 1} to generate combined plot...", "yellow"))
                            await send_status_to_user(self.user_id, status=f"Generating combined plot...")

                            sanitized_code = await generate_plotly_code(self.user_id, input_text, None, df_metadata_list, tags, error)

                            if sanitized_code:
                                code_logs(container_name="code-log", code=sanitized_code, user_id=self.user_id, logger_timestamp=self.logger_timestamp)
                                self.sanitized_code_list.append(sanitized_code)

                            fig, error = get_plotly_figure(sanitized_code, dfs, False)
                            if fig:
                                fig_json = pio.to_json(fig)
                                # png_img = pio.to_image(fig)

                                if fig_json:
                                    self.fig_json_list.append(fig_json)

                                # self.base64_code_list.append(base64.b64encode(png_img))
                                break
                            else:
                                error_msg = f"No figure generated. Error: {error}" if error else "No figure generated."
                                raise ValueError(error_msg)

                        except Exception as e:
                            print(colored(f"Error generating combined plot on attempt {attempts + 1}: {e}", "red"))
                            attempts += 1
                            if attempts >= max_attempts:
                                print(colored(f"Failed to generate combined plot after {max_attempts} attempts.", "red"))
                                continue


                else:    
                    for tag, data in combined.items():
                        attempts = 0
                        max_attempts = 3
                        while attempts < max_attempts:
                            try:
                                print(colored(f"Attempt {attempts + 1} to generate plot for tag {tag}...", "yellow"))
                                await send_status_to_user(self.user_id, status=f"Generating plot for {tag}...")

                                df = data['df']
                                if not df.empty:
                                    buffer = io.StringIO()
                                    df.info(buf=buffer)
                                    df_info = buffer.getvalue()
                                sub_question = data['sub_question']
                                

                                print(colored(f"Tag: {tag}", "yellow"))
                                # print(colored(f"Plot Question: {input_text}", "light_blue"))
                                
                                if sub_question_list:
                                    sanitized_code = await generate_plotly_code(self.user_id, sub_question, None, df_info, tag, error)
                                else:
                                    sanitized_code = await generate_plotly_code(self.user_id, input_text, None, df_info, tag, error)
                                
                                if sanitized_code:
                                    code_logs(container_name="code-log", code=sanitized_code, user_id=self.user_id, logger_timestamp=self.logger_timestamp)
                                    self.sanitized_code_list.append(sanitized_code)

                                fig, error = get_plotly_figure(sanitized_code, dfs, False)
                                if fig:
                                    fig_json = pio.to_json(fig)
                                    # png_img = pio.to_image(fig)
                                    
                                    if fig_json:
                                        self.fig_json_list.append(fig_json)

                                    # self.base64_code_list.append(base64.b64encode(png_img))
                                    break
                                else:
                                    raise ValueError("No figure generated.")

                            except Exception as e:
                                print(colored(f"Error generating plot for tag {tag} on attempt {attempts + 1}: {e}", "red"))
                                attempts += 1
                                if attempts >= max_attempts:
                                    print(colored(f"Failed to generate plot for tag {tag} after {max_attempts} attempts.", "red"))
                                    continue
            
            except Exception as e:
                print(colored(f"Error generating plot: {e}", "red"))
                summary_data.append({"source": "plotly", "content": f"Error generating plot: {e}"})
                end = time.time()
                functions_time_log.append(f"Plotly Engine: {round(end - start, 2)} seconds")
                return None

                
            summary_data.append({"source": "plotly", "content": f"Generated plot code:\n {self.sanitized_code_list}"})
            end = time.time()
            functions_time_log.append(f"Plotly Engine: {round(end - start, 2)} seconds")

            return fig_json       
                
                
        if sanitized_code:

            try:
                if isinstance(sanitized_code, list):
                    for code in sanitized_code:
                        fig, error = get_plotly_figure(code, dfs, False)
                        self.sanitized_code_list.append(code)

                        if fig:
                            fig_json = pio.to_json(fig)
                            # png_img = pio.to_image(fig)
                            
                            if fig_json:
                                self.fig_json_list.append(fig_json)

                            # self.base64_code_list.append(base64.b64encode(png_img))
                        else:
                            raise ValueError("No figure generated.")
                else:
                    fig, _ = get_plotly_figure(sanitized_code, dfs, False)
                    self.sanitized_code_list.append(sanitized_code)

                    if fig:
                        fig_json = pio.to_json(fig)
                        # png_img = pio.to_image(fig)
                        
                        if fig_json:
                            self.fig_json_list.append(fig_json)

                        # self.base64_code_list.append(base64.b64encode(png_img))
                    else:
                        raise ValueError("No figure generated.")
        
            except ValueError as e:
                print(colored(f"Value Error: {e}", "red"))
                summary_data.append({"source": "plotly", "content": f"Error generating plot: {e}"})
                end = time.time()
                functions_time_log.append(f"Plotly Engine: {round(end - start, 2)} seconds")
                return None
            
            except Exception as e:
                print(colored(f"Error generating plot: {e}", "red"))
                summary_data.append({"source": "plotly", "content": f"Error generating plot: {e}"})
                end = time.time()
                functions_time_log.append(f"Plotly Engine: {round(end - start, 2)} seconds")
                return None
            
        summary_data.append({"source": "plotly", "content": f"Generated plot code(s):\n {self.sanitized_code_list}"})
        end = time.time()
        functions_time_log.append(f"Plotly Engine: {round(end - start, 2)} seconds")

        return fig_json

    @time_it
    async def handle_csv_query(self, tool_call, user_id, summary_data):
        """
        Handles a CSV query by processing the provided tool call and user text, and generating a response based on the CSV data.

        Args:
            tool_call (dict): The tool call containing function arguments.
            user_id (str): The ID of the user making the request.
            userText (str): The text of the user's query.
            summary_data (list): A list to append the summary of the response.

        Returns:
            None

        This function performs the following steps:
        1. Sends a status update to the user indicating that the CSV query is being processed.
        2. Extracts the filename from the tool call arguments.
        3. Retrieves metadata for the specified file, including dataframe information, column names, data types, and descriptions.
        4. Prepares a prompt based on the user query and metadata.
        5. Attempts to process the CSV query up to a maximum number of retries.
        6. Executes the command extracted from the response and retrieves the result data.
        7. Generates a natural language response based on the result data.
        8. Appends the bot response to the summary data.
        9. Logs the time taken to process the CSV query.
        """
        start = time.time()
        await send_status_to_user(self.user_id, status="Processing CSV query...")
        print("Getting File name...")
        # filename = json.loads(tool_call["function"]["arguments"])["filename"]
        user_email = self.user_id.split("_")[0]
        metadata_dict = get_metadata_all(user_email)
        
        if not metadata_dict:
            summary_data.append({"source": "csv", "content": "No csv file found/uploaded."})
            return
        # print(f"Metadata Dict: {metadata_dict}")
        first_key, _ = next(iter(metadata_dict.items()))
        filename = first_key
        
        
        query = tool_call["function"]["arguments"]
        print(f"Filename fetched : {filename}")
        print("Getting Metadata...")
        metadata = get_metadata(user_email, file_name=filename)
        print("Fetching df infos...")
        df_dict = metadata.get("df")
        head = metadata.get("head")
        desc = metadata.get("description")
        cols = metadata.get("columns")
        dtype = metadata.get("dtypes")
        df = pd.DataFrame.from_dict(df_dict)
        print("Preparing the prompt...")
        max_retries = 1  # Reduced from 3 to 1 (orchestrator handles retries)
        attempt = 0
        result_data = None
        response_text = ""
        while attempt < max_retries:
            try:
                attempt += 1
                prompt = prepare_prompt(query, cols, dtype, desc, head)
                print(f"Attempt {attempt} for CSV query processing...")
                response_text = await chat_completion_request(self.user_id, prompt, response_format=True)
                # print(f"Response Text: {response_text}")
                response_content = response_text.choices[0].message.content
                # print(f"Extracted Response Content: {response_content}")
                cleaned_response_text = json.loads(response_content)
                command = cleaned_response_text['result']
                if not command:
                    raise ValueError("No command found in the response")
                local_vars = {'df': df}
                exec(f"data = {command}", {}, local_vars)
                result_data = local_vars.get('data')
                if result_data is not None:
                    break
            except Exception as e:
                print(f"Retry {attempt} failed: {e}")
                await log_error(self.user_id, f"Retry {attempt} failed: {e}", 'CSV query processing error')
                if attempt == max_retries:
                    print("Max retries reached. Returning error response.")
                    result_data = None
        if result_data is not None:
            natural_response = f"The user query is {query}. The output of the command is {str(result_data)}. If the data is 'None', you can say 'Please ask a query to get started'. Do not mention the command used. Generate a response in natural language for the output."
        else:
            natural_response = "The command did not return any data. Please try a different query."
        bot_response = await chat_completion_request(user_id, [{"role": "system", "content": "Your task is to comprehend. You must analyse the user query and response data to generate a response data in natural language. Respond in JSON"}, {"role": "user", "content": natural_response}], response_format=True)
        # print(f"Bot Response: {bot_response}")
        # summary_data.append(bot_response)
        summary_data.append({"source": "csv", "content": bot_response.choices[0].message.content })
        end = time.time()
        functions_time_log.append(f"CSV Parser: {round(end - start, 2)} seconds")

    async def handle_pdf_query(self, tool_call, userText, summary_data, tool_types_used, context_msg):
        start = time.time()
        tool_types_used.add("pdf")
        await send_status_to_user(self.user_id, status="Processing PDF query...")

        user_email = self.user_id.split("_")[0]
        # Retrieve all PDF metadata
        all_metadata = await metadata_manager.get_all(user_email)
        pdf_files = {fname: meta for fname, meta in all_metadata.items() if meta.get("file_type") == "pdf"}

        if not pdf_files:
            summary_data.append({"source": "pdf", "content": "No PDF file found/uploaded."})
            tool_types_used.remove("pdf")
            return tool_types_used

        # Select the most recent PDF (using upload_time)
        sorted_files = sorted(pdf_files.items(), key=lambda x: x[1].get("upload_time", ""), reverse=True)
        selected_filename, metadata = sorted_files[0]
        print(f"Selected PDF file for query: {selected_filename}")

        file_hash = metadata.get("file_hash")
        embedded_query = await embeddings_request(self.user_id, tool_call["function"]["arguments"])

        summarizer = DocumentProcessor(user_email)
        results = summarizer.search_similar_documents(embedded_query, file_hash, selected_filename)
        # print(colored(f" Search Results: {results}", "yellow"))
        response = await summarizer.synthesize_responses(userText, results, context_msg)
        # print(colored(f"Response: {response}", "yellow"))

        if response is not None:
            llm_response_text = (
                response.strip() if isinstance(response, str)
                else response.choices[0].message.content.strip()
            )
            summary_data.append({"source": "pdf", "content": llm_response_text})
        else:
            summary_data.append({"source": "pdf", "content": "No response generated from PDF."})

        elapsed = time.time() - start
        print(f"PDF Parser took: {round(elapsed, 2)} seconds")
        return tool_types_used

    
    @time_it
    async def compare_data_sources(self, tool_call, summary_data, custom_instructions=None, context_msg=None):
        """
        Compares the summarized insights from the LLM model with the database data.

        Args:
            llm_summary (str): The summarized insights from the LLM model.
            db_data (pd.DataFrame): The database data.

        Returns:
            tuple: A tuple containing the database statistics and the comparison insights.
        """
        print(colored("Function at Comparative Analysis called", "grey"))
        
        input = tool_call["function"]["arguments"]
        
        if isinstance(input, str):
            value = json.loads(input)
        else:
            value = input
            
        user_query = value.get("question")
        data =  value.get("data") if value.get("data") else None
        
        tool_ids = get_tool()

        data_sources = []
        for tool_id in tool_ids:
            # Try cache_client first (for legacy/non-orchestrator calls)
            cached_result = self.cache_client.get(tool_id)

            # If not in cache_client, check global tool_cache (for orchestrator)
            if not cached_result:
                from core.globals import tool_cache
                cached_result = tool_cache.get(tool_id)

            tool_blob = {}
            if cached_result:
                tool_name = json.loads(cached_result)["tool_name"]
                observations = json.loads(cached_result)["observation"]
                tool_blob = {"tool_name": tool_name, "observations": observations}
                # print(colored(f"Tool Blob: {tool_blob}", "grey"))
                data_sources.append(tool_blob)
                
        if data:
            tool_bob = {"tool_name": "Provided data", "observations": data}
            data_sources.append(tool_bob)
                
        report_generator = ReportGenerator()
        report_content = await report_generator.generate_comparative_report(user_query, data_sources, custom_instructions, context_msg)
        
        summary_data.append({"source": "comparative_analysis", "content": report_content.choices[0].message.content})
        
        return report_content.choices[0].message.content
    
    
    
    