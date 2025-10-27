import json
import re
from typing import List

from termcolor import colored
from utility.tools import chat_completion_request

from utility.decorators import time_it

@time_it
async def _extract_python_code(markdown_string: str) -> str:

    pattern = r"```[\w\s]*python\n([\s\S]*?)```|```([\s\S]*?)```"

    matches = re.findall(pattern, markdown_string, re.IGNORECASE)

    python_code = []
    for match in matches:
        python = match[0] if match[0] else match[1]  
        if python:  
            python_code.append(python.strip())

    if len(python_code) == 0:
        return markdown_string  

    return python_code[0]  

@time_it
async def _sanitize_plotly_code(raw_plotly_code: str) -> str:
    plotly_code = re.sub(r'^.*\.show\(\)\s*$', '', raw_plotly_code, flags=re.MULTILINE).strip()
    
    return plotly_code

@time_it
async def sanitize_df_info(df_info_str):
    # Example sanitization: remove memory usage line
    if df_info_str is None:
        return ""
    if isinstance(df_info_str, list):
        df_info_str = '\n'.join(df_info_str)
    sanitized_str = '\n'.join([line for line in df_info_str.split('\n') if 'memory usage' not in line])
    return sanitized_str

@time_it
async def generate_plotly_code(user_id, question: str = None, sql_list: list = None, df_metadata: any = None, tag: any = None, error: str = None) -> str:
    # print("DF Metadata List:", df_metadata_list)
    # System message sets expectations for the LLM
    sanitized_df_info = await sanitize_df_info(df_metadata)

    system_msg = (
    "You are a Python Plotly assistant tasked with generating valid visualization code based on user-provided data.\n"
    "\n"
    "🚨 CRITICAL INSTRUCTION - PLOT TYPE ENFORCEMENT:\n"
    "**YOU MUST USE THE EXACT PLOT TYPE SPECIFIED BY THE USER. THIS IS NON-NEGOTIABLE.**\n"
    "- If user says 'box plot' or 'box plots' → ONLY use px.box() - DO NOT use bar charts, scatter plots, or any other plot type\n"
    "- If user says 'bar chart' or 'bar plot' → ONLY use px.bar() - DO NOT use box plots or line plots\n"
    "- If user says 'scatter plot' → ONLY use px.scatter() - DO NOT use box plots or bar charts\n"
    "- If user says 'line plot' or 'line chart' → ONLY use px.line() - DO NOT use bar charts or box plots\n"
    "- If user says 'violin plot' → ONLY use px.violin() - DO NOT use box plots\n"
    "\n"
    "**FAILURE TO USE THE CORRECT PLOT TYPE WILL BE CONSIDERED A CRITICAL ERROR.**\n"
    "\n"
    "Instructions:\n"
    "1. **READ THE USER'S QUESTION CAREFULLY to identify the requested plot type (box plot, bar chart, scatter, etc.)**\n"
    "2. **USE ONLY THE PLOT TYPE SPECIFIED - do not substitute with a different type**\n"
    "3. Ensure all plots are meaningful and include appropriate titles, axis labels, and legends.\n"
    f"4. Use the following tag for naming the DataFrame, if provided: {tag}.\n"
    "5. Provide only valid Python code for Plotly—no explanations or comments\n"
    "\n"
    "CRITICAL - Choosing the X-axis for Grouping:\n"
    "When creating bar charts or grouped visualizations:\n"
    "- Look for columns with VARIABLE categorical data: KRAS_status, TP53_status, EGFR_status, sample_group, tissue_type, etc.\n"
    "- Use these columns for the X-axis (grouping variable)\n"
    "- DO NOT use gene_name for X-axis if it contains only one unique value (e.g., all rows are 'EGFR')\n"
    "- For mutation-stratified data (KRAS-mutant, TP53-mutant): Use the mutation status column (KRAS_status, TP53_status) as X-axis\n"
    "- For tumor vs normal data: Use sample_group or tissue_type as X-axis\n"
    "\n"
    "Examples:\n"
    "- DataFrame with columns [gene_name='EGFR', KRAS_status=['p.G12S', 'p.G12D'], mean_expression, min_expression, max_expression]\n"
    "  → Use KRAS_status for x-axis (it varies), NOT gene_name (it's constant)\n"
    "  → Code: fig = px.bar(df, x='KRAS_status', y=['mean_expression', 'min_expression', 'max_expression'])\n"
    "\n"
    "- DataFrame with columns [gene_name='TP53', sample_group=['Tumor', 'Normal'], mean_tpm, median_tpm]\n"
    "  → Use sample_group for x-axis (it varies), NOT gene_name (it's constant)\n"
    "  → Code: fig = px.bar(df, x='sample_group', y=['mean_tpm', 'median_tpm'])\n"
    "\n"
    "IMPORTANT - Multiple DataFrames for Box Plots:\n"
    "- If you receive multiple DataFrames (e.g., data_0, data_1, data_2) and need to create box plots:\n"
    "  * Add a 'group' column to each DataFrame identifying its source (e.g., 'Normal', 'Tumor', 'Cell Lines')\n"
    "  * Use pd.concat() to combine them vertically\n"
    "  * Example:\n"
    "    data_0['group'] = 'Normal'\n"
    "    data_1['group'] = 'Tumor'\n"
    "    data_2['group'] = 'Cell Lines'\n"
    "    combined_df = pd.concat([data_0, data_1, data_2], ignore_index=True)\n"
    "    fig = px.box(combined_df, x='group', y='tpm_value', color='group', title='EGFR Expression Across Groups', points='all')\n"
    "\n"
    "🔴 CRITICAL - Box Plot Configuration:\n"
    "- ALWAYS include points='all' parameter in px.box() to show ALL data points overlaid on boxes\n"
    "- This provides full transparency showing individual samples AND the statistical summary\n"
    "- NEVER use boxmode='overlay' - use default mode for side-by-side boxes\n"
    "- Example: fig = px.box(df, x='tissue_type', y='tpm_value', points='all')\n"
    "- points='all' shows every sample as a point, making small sample sizes visible\n"
    "- Alternative: points='outliers' only shows statistical outliers (use for large datasets)\n"
    "\n"
    "Restricted Actions:\n"
    "1. Avoid generating any mock data or including pd.read_csv() or pd.DataFrame() or using placeholders (like Ellipsis) in your responses.\n"
    "2. **Never include fig.show() in the code.**\n"
    )


    # Construct the user message with dynamic input
    user_msg = "Generate Python Plotly code to visualize provided data. Improve the code if any errors are given."
    
    # Add details to user message based on provided parameters
    if question:
        user_msg += f"\n\n User's question and error(if any): '{question} \n error: {error}'."
    
    if sql_list and all(query is not None for query in sql_list):
        user_msg += "\n\nSQL queries used to create the DataFrame:\n" + "\n".join(sql_list)
        
    if df_metadata:
        user_msg += "\n\n Metadata of the DataFrame:\n" + sanitized_df_info + "\n"  

    # Prepare the conversation messages for the model
    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg + "\n" + "Avoid generating any mock data or including pd.read_csv() or pd.DataFrame() or using placeholders (like Ellipsis) in your responses.\n"}
    ]

    # Send the prompt to generate the Plotly code
    response = await chat_completion_request(user_id, messages,model="gpt-4o-mini")
    
    # Extract and sanitize the Python code from the model's response
    plotly_code = response.choices[0].message.content
    extracted_code = await _extract_python_code(plotly_code)
    sanitized_code = await _sanitize_plotly_code(extracted_code)

    return sanitized_code

@time_it
async def modify_plot_code_based_on_query(
        user_id: str,
        question: str = None,
        plot_code: List[str] = None,
        sql_list: List[str] = None,
        df_metadata_list: List[str] = None,
        tags: any = None, error: str = None
    ) -> List[str]:
    """
    Modify the Plotly plot code based on the user's follow-up question, DataFrame metadata, SQL query, and the existing plot code.

    Args:
        user_id (str): The ID of the user making the request.
        question (str): The follow-up question the user asked to modify the plot.
        plot_code (List[str]): The existing Python Plotly codes for the current plots.
        sql_list (List[str]): The SQL queries that generated the DataFrames.
        df_metadata_list (List[str]): Information about the resulting pandas DataFrames.
        tags (any): Tags associated with the DataFrames.
        error (str): Any error messages.

    Returns:
        List[str]: A list of modified Python Plotly codes.
    """

    # Prepare the conversation messages for the LLM
    messages = [
        {"role": "system", "content": f"""
        You are an expert Python coding assistant skilled in modifying existing Plotly visualizations using data in pandas DataFrame(s).

        ## 🚨 CRITICAL INSTRUCTION - PLOT TYPE ENFORCEMENT:
        **YOU MUST USE THE EXACT PLOT TYPE SPECIFIED BY THE USER. THIS IS NON-NEGOTIABLE.**
        - If user says 'box plot' or 'box plots' → ONLY use px.box() - DO NOT use bar charts, scatter plots, or any other plot type
        - If user says 'bar chart' or 'bar plot' → ONLY use px.bar() - DO NOT use box plots or line plots
        - If user says 'scatter plot' → ONLY use px.scatter() - DO NOT use box plots or bar charts
        - If user says 'line plot' or 'line chart' → ONLY use px.line() - DO NOT use bar charts or box plots
        - If user says 'violin plot' → ONLY use px.violin() - DO NOT use box plots

        **FAILURE TO USE THE CORRECT PLOT TYPE WILL BE CONSIDERED A CRITICAL ERROR.**

        ## Instructions:
        - Your task is to update the existing Python Plotly code(s) based on the user's follow-up request and specific instructions.
        - **PRIORITIZE THE USER'S REQUESTED PLOT TYPE** - if they ask for box plots, you MUST generate box plots
        - If a DataFrame contains only one value, generate a suitable Indicator chart.
        - Return only the modified Python code for the Plotly chart without explanations, comments, or additional text.
        - Ensure the response is a valid JSON array of strings, where each string is a modified Plotly code corresponding to the input plot codes.
        - Name the DataFrame(s) with the following tags: {tags}.

        ## Context:
        Here is the information about the resulting pandas DataFrame(s):
        {df_metadata_list}

        The DataFrame(s) was/were produced using the following SQL query(s):
        {sql_list}

        The current Plotly chart(s) generated using the following code(s):
        {plot_code}

        ## Response Format:
        Return a JSON array of modified Plotly code strings. For example:
        [
            "modified_plot_code_1",
            "modified_plot_code_2",
            ...
        ]
        """},

        {"role": "user", "content": f"Please modify the existing Python Plotly code to meet the following request: '{question}'. **CRITICAL: If the request mentions a specific plot type (box plot, bar chart, scatter, etc.), you MUST use that exact plot type.** Ensure that you make changes only to the provided Plotly code to reflect the requested modifications. Respond only with a JSON array of the updated Python codes."}
    ]

    # Submit the prompt to get the modified Plotly code response
    response = await chat_completion_request(user_id, messages, model="gpt-4o-mini")

    plotly_code_response = response.choices[0].message.content

    try:
        # Parse the JSON response to get the list of modified codes
        plotly_code_list = json.loads(plotly_code_response)
        
        if not isinstance(plotly_code_list, list):
            raise ValueError("The response is not a list.")
        
    except json.JSONDecodeError as e:
        print(colored(f"JSON decoding failed: {e}", "red"))
        # Handle the error as needed, possibly returning the original codes or raising an exception
        return []
    except ValueError as ve:
        print(colored(f"Unexpected response format: {ve}", "red"))
        return []

    sanitized_code_list = []
    
    for code in plotly_code_list:
        extracted_code = await _extract_python_code(code)
        sanitized_code = await _sanitize_plotly_code(extracted_code)
        sanitized_code_list.append(sanitized_code)

    return sanitized_code_list
