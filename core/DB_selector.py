import json
import time
from termcolor import colored
import core.globals as globals
from core.globals import instructions_dict
from utility.tools import chat_completion_request
from core.db_ops import usergroup_schema

from utility.decorators import time_it

class  DBSelector:
    
    @classmethod
    @time_it
    def create_prompt(cls, question, user_id):
        db_descrip = []

        list_db_names = globals.databases_dict.keys()
        for db_name in list_db_names:
            db_descrip.append(globals.databases_dict[db_name]['db_description'])

        context_msg = globals.session_data[user_id][-4:]
        prompt = f"""
        List of Database Names: {list_db_names}

        Available Databases Description: {db_descrip}

        Context: {context_msg}

        Based on the user question, return any one of the database name available in the above list:
        {question}
        """
        return prompt
    
    @classmethod
    @time_it
    async def generate_response(cls, user_id, question):
        DB_Selector = instructions_dict["DB Selector"]
        prompt = cls.create_prompt(question, user_id)

        messages=[
            {"role": "system", "content":f'{DB_Selector}' },
            {"role": "user", "content": prompt}
        ]
        

        response = await chat_completion_request(user_id, messages,model="gpt-4o-mini", response_format=True)
        return response.model_dump()['choices'][0]['message']['content']

    @staticmethod
    @time_it
    async def database_selection(user_id, user_group, question):
        try:
            start = time.time()
            if user_group not in globals.gROUP_DB_SCHEMA:
                print(colored(f"User group {user_group}'s schema not found, fetching from DB", "grey"))
                group_dbInfo = await usergroup_schema(user_group)
                globals.gROUP_DB_SCHEMA[user_group] = group_dbInfo
                if not group_dbInfo:
                    return False, None, None, None

            group_dbInfo = globals.gROUP_DB_SCHEMA[user_group]
            end = time.time()
            # globals.functions_time_log.append(f"User Group Schema DB Selector API: {round(end - start, 2)} seconds")
            start = time.time()
            response = await DBSelector.generate_response(user_id, question)
            json_response = json.loads(response)
            database = json_response["database"]
            print(colored(f"Database Name:{database}", "grey"))
            end = time.time()
            # globals.functions_time_log.append(f"DB Selector API call: {round(end - start, 2)} seconds")

            start = time.time()
            if globals.databases_dict[database]['db_status'] is True:
                if json_response['database'] in group_dbInfo:
                    group_schema = group_dbInfo[json_response['database']]
                    dialect = None
                    for key in group_schema.keys():
                        dialect = key
                else:
                    return False, None, None, None

            else:
                print(colored(f"Database {database} is not available", "red"))
                return False, None, None, None
            end = time.time()
            # globals.functions_time_log.append(f"Validate DB access to user: {round(end - start, 2)} seconds")
            start = time.time()
            if group_schema:
                description = {}
                tables_info = list(group_schema.values())
                for tables in tables_info:
                    tables_info = list(tables.keys())
                    for table in tables_info:
                        if json_response['database'] in globals.table_descriptions.keys():
                            if table in globals.table_descriptions[json_response['database']]: 
                                description[table]  = globals.table_descriptions[json_response['database']][table]
            end = time.time()
            # globals.functions_time_log.append(f"Fetch table description: {round(end - start, 2)} seconds")
            return database, group_schema, description, dialect

        except Exception as e:
            print(colored(f"Error at Database Selector {e}", "red"))
            raise e
        


            


