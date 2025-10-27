import json
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

        # Smarter aggregation hint - only for gene expression comparison queries
        question_lower = question.lower() if isinstance(question, str) else json.dumps(question).lower()

        # Only add hint if it's clearly a comparison query about gene expression
        is_gene_comparison = (
            any(gene_word in question_lower for gene_word in ["expression", "levels", "tpm", "raw", "individual"]) and
            any(comp_word in question_lower for comp_word in ["compare", "versus", "vs", "tumor", "normal", "mutant", "wildtype", "tissue", "cell line"])
        )

        if is_gene_comparison:
            sql_engine_stage_2 += """

💡 BIOMEDICAL QUERY GUIDANCE - Gene Expression Comparisons:

For comparing gene expression between groups (tumor vs normal, mutant vs wildtype):
- Prefer using GROUP BY with aggregations to show summary statistics
- Include: AVG(), MIN(), MAX(), COUNT()
- Note: SQLite doesn't support STDDEV() - omit it or calculate manually
- Example: SELECT gene_name, tissue_type, AVG(tpm_value), MIN(tpm_value), MAX(tpm_value), COUNT(*) FROM... GROUP BY gene_name, tissue_type

For mutation-stratified queries (KRAS-mutant, TP53-mutant):
- Use gene_expression table (required for mutation filtering)
- Join with cell_line_metadata for mutation status

For simple tumor vs normal comparisons:
- Can use gene_statistics table (pre-aggregated) for better performance
- Or use gene_expression with GROUP BY for custom aggregations

🔴 CRITICAL: When fetching RAW individual expression values:
- ALWAYS include identifying columns in SELECT: gene_name, sample_id, tissue_type (or sample_group)
- Example: SELECT ge.tpm_value, g.gene_name, s.sample_id, htm.tissue_type FROM...
- This ensures data can be properly labeled and combined in visualizations
- NEVER SELECT only tpm_value alone - always include context columns
"""

        sql_engine_stage_2 += f"\n\nRelevant Domain Specific Knowledge: {relevant_domain_knowledge}"

        prompt = cls._create_prompt(question, description, dialect, relevent_query )

        messages=[
            {"role": "system", "content": f""" {sql_engine_stage_2} """},
            {"role": "user", "content": prompt}
        ]
        # messages.append({"role": "system", "content": f"Relevant Domain Knowledge to consider: {relevant_domain_knowledge}"})
        response = await chat_completion_request(user_id, messages, response_format=True)
        return response.model_dump()['choices'][0]['message']['content']
    
    
    