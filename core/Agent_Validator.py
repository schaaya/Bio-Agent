from core.DB_rules import rules
from core.globals import instructions_dict
from utility.tools import chat_completion_request
from utility.decorators import time_it

class Validator:

    @classmethod
    @time_it
    def _create_prompt(cls, question, description, dialect, query):

        db_rules = rules[dialect]

        prompt = f"""
                "Guidelines used for generating query in ***/ {dialect} : {db_rules}" /***
                "User's question and error message(if any): <<<{question}>>>"
                "Tables and respective columns to answer user question from stage 1: /'/'/ {description} /'/'/'
                "Generated Query from stage 2: %^%^% {query} %^%^% \n"
                "Return the output in strict JSON format with no additional text, Only respond with a single word: True or False. \n
                "For Example 'Result': True or 'Result': False. The output must be a valid JSON object that can be extracted using `json.loads`"
                "If Result is False, then give a reason like 'Reason': 'Reason' "
        """
        return prompt

    @classmethod
    @time_it
    async def approve_query(cls, user_id, question, description, dialect, query ):

        prompt = cls._create_prompt(question, description, dialect, query )

        messages=[
            {"role": "system", "content": f""" You are an expert database engineer designed to validate the quality of an LLM-generated SQL query.\n

            The model was asked to generate a SQL query based on the given tables and columns, ensuring they are contextually appropriate.\n 
            There are two stages for SQL queries: stage 1 and stage 2. The stage 1 query is designed to generate the tables and columns to be used in stage 2. The stage 2 query is designed to generate the SQL query.\n 
            
            Key Considerations:\n

            Pay careful attention to which columns belong to which tables when forming queries.\n
            Always ensure the syntax of the query is valid, double-checking and triple-checking before returning it.\n
            Follow the specific rules and guidelines outlined in the / dialect : Rules / section.\n
            
            Join Operations: If the context involves multiple tables, construct a query using JOIN operations where necessary to retrieve the required data.\n
            
            Input Structure:\n

            The user's question will be provided inside <<< user's question >>>.\n
            The tables, columns, clauses, filters, and expressions relevant to the query will be given in JSON format inside triple quotes, like so: /'/'/ description /'/'/\n
            Key information related to tables and columns will be provided within ||| key info |||.\n
            Generated Query from stage 2: %^%^% query %^%^% \n
            
            Your Task:\n

            Analyze the query and determine if it is valid.\n
            If the query is valid, respond with 'Result': True.\n
            If the query is invalid, respond with 'Result': False and provide a reason for the invalidity.\n

            If Result is False, then give a reason like 'Reason': 'Reason' \n
            
            If there is an Error Message, analyze it and make the necessary corrections to the query or data.\n

            """},
            {"role": "user", "content": prompt}
        ]
 
        response = await chat_completion_request(user_id, messages, response_format=True)
        return response.model_dump()['choices'][0]['message']['content']