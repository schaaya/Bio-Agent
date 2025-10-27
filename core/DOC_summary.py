from utility.tools import chat_completion_request
from utility.decorators import time_it

class CSV_summary:

    @classmethod
    @time_it
    def _create_prompt(cls, columns, dtype, head, desc):



        prompt = f"""
                
                "Columns: <<<{columns}>>>"
                "data type: /'/'/ {dtype} /'/'/'
                "head: ||| {head} |||"
                "Description of Dataframe: %^%^% {desc} %^%^% \n"
                "Return the output in strict JSON format". \n
                "For Example 'Result': summary \n
                   
        """
        return prompt

    @classmethod
    @time_it
    async def approve_query(cls, user_id, columns, dtype, head, desc ):

        prompt = cls._create_prompt(columns, dtype, head, desc )

        messages=[
            {"role": "system", "content": f""" You are an expert Data Analyst designed to generate a summary of a CSV file based on the given columns, data type, head, and description.\n
             The CSV data is loaded to a Pandas DataFrame.\n
           
            Key Considerations:\n

            Pay careful attention to data type, head, and description to generate summary.\n
          
            Input Structure:\n

            The Dataframe columns will be provided inside <<< Columns >>>.\n
            The Data Type: /'/'/ Data Type /'/'/\n
            DataFrame head will be provided within ||| Head |||.\n
            Description of the dataframe: %^%^% query %^%^% \n
            
            Your Task:\n

            Analyze the columns, data type, head, and description..\n
            Generate a summary of the CSV file within two or three sentences.\n

            """},
            {"role": "user", "content": prompt}
        ]
 
        response = await chat_completion_request(user_id, messages, response_format=True)
        return response.model_dump()['choices'][0]['message']['content']