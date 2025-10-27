import io
import os
import json
import time
import pandas as pd
from termcolor import colored
import core.globals as globals
from openai import AsyncAzureOpenAI
from core.DB_selector import DBSelector
from core.globals import instructions_dict
from core.query_executer import execute_query
from core.logger import log_sql_error
from core.Agent_Validator import Validator
from core.SQL_engine_stage2 import Stage_two
from utility.qdrant_rag_schema import SchemaRetriever
from utility.tools import chat_completion_request
from utility.retrieval import get_similar_query
from functools import lru_cache
import asyncio
from utility.decorators import time_it

client = AsyncAzureOpenAI(
        api_key = os.getenv("AZURE_OPENAI_KEY"),  
        api_version = "2023-03-15-preview",
        azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
)

class SQLGenerator:
    def __init__(self, schema, database, db_retriever):
        self.schema = schema
        self.database = database
        self.ddl_path = os.path.join(os.path.dirname(__file__), "../data", "schema-01-09-2025.sql")
        self.db_retriever = db_retriever
        self._schema_description_cache = None
        
    @classmethod
    async def create(cls, schema, database):
        ddl_path = os.path.join(os.path.dirname(__file__), "../data", "schema-01-09-2025.sql")
        db_retriever = await SchemaRetriever.create(schema, database)
        return cls(schema, database, db_retriever)
    
    def _create_prompt(self, question, context_msg, description, relevant_query, combined_context):
        
        prompt = f"""
            Schema: {combined_context}
            Question: {question}
            Relevant Query: {relevant_query}

            You are given a schema and a user's query. 
            Return output in valid JSON format within 'tables' key: 
            - "tables": "..." (a list of tables and columns, with their dTypes and column descriptions(as provided in the schema definitions), and foreign keys defined on the tables, needed)
            
        """
        return prompt

    async def generate_query(self, user_id, question, context_msg, description, relevent_query, relevant_domain_knowledge):
        # Create a constant for the system prompt outside the method to avoid string reconstruction
        SQL_Engine_stage_1_prompt = self._get_sql_engine_stage_1_prompt(relevant_domain_knowledge)
        
        # Search Qdrant asynchronously
        top_chunks = await self.db_retriever.search_qdrant(question)
        
        # Process chunks more efficiently using list comprehension
        context_snippets = [json.dumps(chunk_obj, indent=2) for chunk_obj, score in top_chunks]
        
        # Join once instead of repeated concatenations
        combined_context = "\n\n".join(context_snippets)
        
        # Create prompt and request completion
        prompt = self._create_prompt(question, context_msg, description, relevent_query, combined_context)
        messages = [
            {"role": "system", "content": SQL_Engine_stage_1_prompt},
            {"role": "user", "content": prompt}
        ]
        
        response = await chat_completion_request(user_id, messages, model="gpt-4o-mini", response_format=True)
        return response.model_dump()['choices'][0]['message']['content']
        
    def _get_sql_engine_stage_1_prompt(self, relevant_domain_knowledge):
        """Extract the prompt creation to a separate method for readability and reuse"""
        prompt = """
        You are a brilliant Database Engineer who can select exactly which tables and columns, with their dtypes and descriptions(refer the schema defitions for column descriptions (including column value examples if provided)), and foreign keys defined on the tables, needed to answer user's question based on given Database schema.\n

                Your Task:\n
                1. Select exactly which tables and columns(along with their dtypes and column descriptions(refer schema)), and foreign keys defined on the tables, required to answer user's question based on schema.\n
                2. Only if provided in the schema descriptions, mention the alias of columns within the column descriptions\n
                3. Refer the relevant Domain Specific Knowledge(if provided) for specific instructions on choosing the columns.\n
                4. Generate schema description and format them in JSON within "tables" key as table_name: [column1:dtype:<column1_description>, column2:dtype:<column2_description>, ...], <foreign keys> format.\n
                
                Instructions:\n
                1. Users question will be in between double angle brackets << User question >>.\n
		        2. **Error Correction** : If given, mind the 'Error Message' and correct the data.\n
                3. Schema of the database will be given in between triple angled brackets <-<-< schema >->->. \n
                4. Additional information related to schema will be in between triple squared brackets [[[ Schema information ]]]. \n
                5. Unless specifically requested by user, respond with Site and Facility Names instead of IDs in the data. For example, use "FacilityName" instead of "FacilityID" or use 'SiteName' instead of 'SiteID'.\n
                 
                Restricted Actions:\n
                1. You are not allowed to generate mock data for demonstration purposes or any other schema code.\n
        """
        
        prompt += f"Relevant Domain Specific Knowledge: {relevant_domain_knowledge}"
        return prompt