import json
import openai
from termcolor import colored

from utility.tools import chat_completion_request

from utility.decorators import time_it

class ReportGenerator:
    def __init__(self, output_path="comparative_report.md"):
        self.output_path = output_path
    @time_it
    async def generate_comparative_report(self, user_query, data_sources, custom_instructions=None, context=None):
        """
        Generate a report summarizing comparative analysis results using LLM.
        - db_stats: Statistical summary of the database data.
        - comparison_insights: Insights from the comparative analysis.
        """
        print(colored("Generating comparative report...", "grey"))

        # Check if data_sources is empty or has no observations
        if not data_sources or all(not ds.get("observations") for ds in data_sources):
            print(colored("⚠️  No data sources available for comparative analysis", "yellow"))
            return type('obj', (object,), {
                'choices': [type('obj', (object,), {
                    'message': type('obj', (object,), {
                        'content': json.dumps({
                            "Report": "<div style='padding: 20px; background: #fff3cd; border-left: 4px solid #ffc107; border-radius: 4px;'><h4 style='color: #856404; margin-top: 0;'>⚠️ No Data Available</h4><p style='color: #856404;'>Unable to perform comparative analysis because no data was retrieved from the database.</p><p style='color: #856404;'><strong>Possible reasons:</strong></p><ul style='color: #856404;'><li>The database query failed due to validation errors</li><li>No matching data found for your query</li><li>Database connection issues</li></ul><p style='color: #856404;'><strong>Suggestions:</strong></p><ul style='color: #856404;'><li>Try rephrasing your question</li><li>Check if the gene/sample names are correct</li><li>Ensure the database is accessible</li></ul></div>"
                        })
                    })()
                })()]
            })()

        data_sources_json = json.dumps(data_sources)

        custom_instructions = custom_instructions or "No custom instructions provided."
        
        prompt = (
            f"User Question: {user_query}\n\n"
            f"Data Sources to be used for comparision:\n{data_sources_json}\n\n"  
        )

        base_prompt = [
                {"role": "system", "content": f"""You are a skilled business analyst specialized in creating professional and actionable reports. Your goal is to analyze relationships between two data sources provided by the user, generate clear insights, and structure the findings into a concise and polished report. You will perform comparisons, highlight trends, identify any gaps, and provide insights based on the data.
                Ensure the language is accessible to non-technical stakeholders and maintain a professional format throughout the report. Respond with a detailed comparative analysis report based on the insights provided.\n\n """

                f"In case of errors, handle it gracefully and prompt the user to retry the request or reach out to support without revealing any error details.\n\n"

                f"""Given the data sources that need to be analyzed for trends, gaps, and actionable insights based on user question. Here's the structure of the report needed:\n

                - Overview: Summarize the purpose and the data sources involved.
                - Data Sources: Briefly describe each data source, including its origin and focus.
                - Analysis Plan: Describe how the data will be extracted, processed, and compared.
                - Key Observations: Provide tabular insights, including trends, gaps, and other observations from the comparison.
                - Preliminary Insights: Summarize high-level findings and their potential impact.
                - Next Steps: Suggest actionable recommendations to address gaps or leverage opportunities.
                - Conclusion: Conclude with the importance of the findings and expected outcomes. """

                f"Use appropriate HTML tags to structure the report and highlight key insights.\n"
                f" Note: Avoid using HTML header tags smaller than <h6>."

                f"\n\n**CRITICAL INSTRUCTIONS:**\n"
                f"1. You MUST use ACTUAL DATA VALUES from the provided data sources\n"
                f"2. DO NOT use placeholders like [value], [median_value], [n_samples], etc.\n"
                f"3. ALWAYS fill in ALL numeric values with the real numbers from the data\n"
                f"4. If a value is not available in the data, write 'Not available' or omit that field\n"
                f"5. All tables, statistics, and metrics MUST contain real values, not placeholders\n\n"

                f"The Response should be in JSON format."
                f"For example: \n"

                    "```\n"
                    "{\n"
                    '    "Report": "<report>"\n'
                    "}\n"
                    "```\n"

                f"Respond in valid JSON format with the report content."

                },
                {"role": "user", "content": prompt}
            ]
        
        if context:
            base_prompt.extend(context)
        
        report_content = await chat_completion_request(
            messages= base_prompt,
            model="gpt-4o-mini",
            response_format= True
        )

        # with open(self.output_path, "w") as f:
        #     f.write(report_content.choices[0].message.content)

        return report_content
