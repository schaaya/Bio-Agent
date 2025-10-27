from core.DB_rules import rules
from core.globals import instructions_dict
from utility.tools import chat_completion_request

from utility.decorators import time_it

class Stage_two:

    @classmethod
    @time_it
    def _create_prompt(cls, question, description, dialect, relevent_query ):
        

        db_rules = rules[dialect]

        prompt = f"""
                "Guidelines for generating query in {dialect} : {db_rules}"
                "User's question and error message(if any): <<<{question}>>>"
                "Tables and respective columns(with their dtypes) to answer user question: ((({description} )))" 
                "Relevant Query: ^^^ {relevent_query} ^^^"
                "Don't use the columns and table names that are not in schema. Return the output in strict JSON format with no additional text, containing the validated query in proper dialect under the key 'sql_query'. The output must be a valid JSON object that can be extracted using `json.loads` and executed with `pd.read_sql(sql_query, engine)` on a database."
                "If there is an Error Message, analyze it and make the necessary corrections to the query or data."
        """
        return prompt

    @classmethod
    @time_it
    async def generate_query(cls, user_id, question, description, dialect, relevent_query, relevant_domain_knowledge=None):
        sql_engine_stage_2 = instructions_dict["SQL Engine stage 2"]
        
        sql_engine_stage_2 += f"Relevant Domain Specific Knowledge: {relevant_domain_knowledge}"

        prompt = cls._create_prompt(question, description, dialect, relevent_query )

        messages=[
            {"role": "system", "content": f""" {sql_engine_stage_2} """},
            {"role": "user", "content": prompt}
        ]
        # messages.append({"role": "system", "content": f"Relevant Domain Knowledge to consider: {relevant_domain_knowledge}"})
        response = await chat_completion_request(user_id, messages, response_format=True)
        return response.model_dump()['choices'][0]['message']['content']
    
    
    