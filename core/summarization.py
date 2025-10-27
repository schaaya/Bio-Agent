import json
from core.globals import instructions_dict
from utility.tools import chat_completion_request
from utility.decorators import time_it
from functools import lru_cache

class summary:
    # Cache the instructions to avoid repeatedly loading them
    # NOTE: Cache disabled during development to ensure changes take effect immediately
    @classmethod
    # @lru_cache(maxsize=10)  # TEMPORARILY DISABLED - re-enable in production
    def _get_summarization_instructions(cls, custom_instructions=None):
        """Cache and return summarization instructions"""
        base_instructions = """
        You are an expert biomedical data analyst specializing in gene expression analysis. Produce publication-quality, data-driven summaries with rigorous statistical reporting suitable for research scientists, bioinformaticians, and clinical researchers.

        Instructions:
        1. Thoroughly analyze the user's query and the provided log data to produce a precise, scientifically-accurate summary.
        2. If the log data explicitly indicates that the results represent a sample set, include in the summary a note stating that these are only sample results and that the user can download the full results using the provided option.
        3. Use HTML tags (<p>, <strong>, <b>, or <h6>) to highlight critical information; do not reference any specific UI elements.
        4. ALL DATA POINTS MUST BE PRESENTED IN TABLE FORMAT for better readability when applicable.
        5. **CRITICAL: ALWAYS include ACTUAL NUMERICAL VALUES with appropriate precision (e.g., TPM values to 2 decimal places, fold changes to 2 decimal places, p-values in scientific notation if < 0.001). NEVER use qualitative descriptions like "Higher", "Lower", "More", "Less" when actual numbers are available.**
        6. Return the response as a JSON object: {"summary": "<Summary>"}.
        7. Convert temperatures from Kelvin to Celsius when weather data is present.
        8. If the user requests a graph or plot, discuss only the pertinent data insights (avoid mentioning UI elements).
        9. In case of errors, handle it gracefully and prompt the user to retry the request or reach out to support.

        **BIOMEDICAL-SPECIFIC REQUIREMENTS:**

        For Differential Expression Analysis (Tumor vs Normal, Mutant vs WT, etc.):
        - Include: Mean/Median TPM, Sample counts (n), Standard deviation or range
        - Report fold change (linear and log2) if available
        - Interpret biological directionality (e.g., "upregulated in tumor" vs "downregulated")
        - Provide brief biological context (e.g., role in tumorigenesis, DNA damage response)
        - If p-value is available, report it (e.g., "p < 0.05" or "p = 0.004")
        - Mention dataset source explicitly (e.g., "Zhang et al. 2016 dataset", "FL3C cell line panel")
        - Use proper scientific terminology (e.g., "expression dysregulation", "compensatory upregulation")

        For Statistical Summaries:
        - **ALWAYS extract and report ALL numerical values that are present in the data**
        - Report: Mean, Median, SD/Range, n (sample count) - USE ACTUAL VALUES FROM DATA
        - Only mark as "N/A" or omit values that are explicitly None/null in the data
        - Include measures of variability (standard deviation, min-max range, or IQR if available)
        - For comparisons, calculate and show the difference/ratio
        - **CRITICAL: Extract median_tpm, std_dev_tpm, n_samples from the data - these are separate columns!**

        For Mutation-Stratified Analysis:
        - Clearly state mutation status groups (e.g., "TP53-mutant vs TP53-WT")
        - Compare expression levels with numerical values
        - Relate findings to known biology when possible

        Table Formatting Standards:
        - Include column headers with units (e.g., "Mean TPM", "Median (TPM)", "n samples")
        - Use consistent decimal precision (2 decimal places for TPM, fold change)
        - Organize rows logically (e.g., Tumor before Normal, or by ascending/descending values)

        Interpretation Guidelines:
        - For log2FC: |log2FC| > 1 indicates ≥2-fold change (biologically significant)
        - For TPM: >1 = detected, >10 = expressed, >100 = highly expressed
        - Briefly explain biological relevance (e.g., TP53's role as tumor suppressor)
        - Note limitations (e.g., "further validation required", "small sample size")

        Prohibited Actions:
        1. Do not include mock data, code snippets, plot code, or SQL queries.
        2. Avoid using HTML header tags smaller than <h6>.
        3. Do not repeat the user's query or log content verbatim.
        4. Exclude data types, memory usage details, or any technical metadata.
        5. Do not reference UI-related terms (e.g., "frontend," "dashboard," "graph interface").
        6. In case of errors, do not reveal any error details to the user.
        7. **NEVER replace actual numerical data with qualitative terms like "Higher/Lower" - always show the real numbers.**
        8. **NEVER mark numerical columns as "N/A" if they contain actual numbers in the data - extract median_tpm, std_dev_tpm, n_samples, etc.**
        9. Do not overclaim significance - acknowledge when statistical tests are unavailable
        10. Do not use vague terms like "potential biomarker" without data support

        Focus on delivering scientifically rigorous, publication-quality summaries with complete numerical data and appropriate biological interpretation.
        """

        if custom_instructions:
            return f"{base_instructions}\n\nIncorporate the following custom instructions:\n{custom_instructions}"
        return base_instructions

    @classmethod
    @time_it
    def _create_prompt(cls, results, userText, sql=None, base64_code=None):
        """Create a prompt for summarization with optional SQL and base64 code"""
        sql_part = f"SQL Query: ||| {sql} |||" if sql else ""

        # Detect if this is a differential expression query
        is_diff_exp = any(keyword in userText.lower() for keyword in
                         ["tumor vs normal", "tumor versus normal", "differential expression",
                          "cancer vs healthy", "mutant vs wildtype", "mutant vs wt"])

        biotech_template = ""
        if is_diff_exp:
            biotech_template = """
EXAMPLE BIOTECH-GRADE RESPONSE FORMAT (adapt to your specific data):

<h6>TP53 Differential Expression Analysis</h6>
<p>The <strong>TP53</strong> gene was analyzed for expression differences between tumor and adjacent normal tissues using RNA-seq TPM values from the Zhang et al. (2016) dataset.</p>

<table border="1" style="border-collapse: collapse; margin: 10px 0;">
  <thead>
    <tr>
      <th>Group</th>
      <th>Mean (TPM)</th>
      <th>Median (TPM)</th>
      <th>Range (TPM)</th>
      <th>SD</th>
      <th>n</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>Tumor</td>
      <td>13.21</td>
      <td>12.45</td>
      <td>3.43 – 35.09</td>
      <td>6.78</td>
      <td>50</td>
    </tr>
    <tr>
      <td>Normal</td>
      <td>10.17</td>
      <td>9.82</td>
      <td>4.41 – 19.54</td>
      <td>3.45</td>
      <td>50</td>
    </tr>
  </tbody>
</table>

<p><strong>⚠️ CRITICAL INSTRUCTION:</strong> In the example above, ALL numerical values (13.21, 12.45, 3.43-35.09, 6.78, 50) are REAL numbers extracted from the data. You MUST do the same - extract mean_tpm, median_tpm, std_dev_tpm, n_samples from your results and fill in the table. If a value is None/null, use "N/A". If a value is a number, SHOW THE NUMBER!</p>

<p><strong>Fold Change:</strong> 1.30-fold upregulation (log₂FC = 0.37)</p>

<p><strong>Interpretation:</strong> TP53 shows modest upregulation in tumor tissues compared to adjacent normal controls. This pattern aligns with its role as a tumor suppressor, where increased expression may reflect compensatory responses to DNA damage or oncogenic stress. However, the magnitude of change (log₂FC < 1) suggests this is not a major driver of differential expression in this cohort.</p>

<p><strong>Note:</strong> Statistical significance testing is recommended for validation. Results are based on the Zhang et al. 2016 dataset (n=50 paired samples).</p>

IMPORTANT: Use this format ONLY as a guide. Generate your response based on the ACTUAL data provided in the results. Replace all values with real data from the query results.
"""

        prompt = f"""
                "User's question: <<<{userText}>>>"
                "Generated results to user question: \"\"\"{results}\"\"\""
                {sql_part}
                "Will show your response in web browser."
                "Provide your answer in JSON structure like this "summary": "<Summary>"
                "Answer must be in string type"

                "🚨 CRITICAL INSTRUCTION - READ CAREFULLY:"
                "The data may have various column names depending on the query. Common patterns:"
                "- Expression: mean_tpm, mean_expression, median_tpm, median_expression"
                "- Variability: std_dev_tpm, std_dev, sd_expression, sd"
                "- Range: min_tpm, min_expression, max_tpm, max_expression"
                "- Counts: n_samples, n_cell_lines, count"
                "- Groups: sample_group, KRAS_status, TP53_status, tissue_type"

                "Your HTML table MUST extract and show ACTUAL VALUES from whichever columns are present:"
                "- Mean: Extract from mean_tpm, mean_expression, or similar"
                "- Median: Extract from median_tpm, median_expression if present (else N/A)"
                "- SD: Extract from std_dev_tpm, std_dev, sd_expression if present (else N/A)"
                "- Range: Calculate from min/max columns if both present (else N/A)"
                "- n: Extract from n_samples, n_cell_lines, or count"

                "EXAMPLES:"
                "Data with: mean_tpm=14.30, median_tpm=13.02, std_dev_tpm=6.99, n_samples=30"
                "→ Show: <td>14.30</td><td>13.02</td><td>...</td><td>6.99</td><td>30</td>"

                "Data with: mean_expression=2.26, min_expression=1.69, max_expression=2.83, n_samples=2"
                "→ Show: <td>2.26</td><td>N/A</td><td>1.69 – 2.83</td><td>N/A</td><td>2</td>"

                "RULES:"
                "1. If a numeric value EXISTS in the data, SHOW IT (never replace with N/A)"
                "2. Only use 'N/A' when column is missing or value is None/null"
                "3. Be flexible with column names - adapt to what's actually in the data"

                "IMPORTANT: ALL DATA POINTS MUST BE PRESENTED IN TABLE FORMAT using HTML tables"
                "CRITICAL: Extract ALL numerical columns that are present - don't assume fixed column names!"
                "CRITICAL: Include ACTUAL NUMERICAL VALUES from the results in your summary tables (e.g., mean TPM values, median, SD, range, counts, fold changes, log2FC). DO NOT use qualitative terms like 'Higher' or 'Lower' when real numbers are available."
                {biotech_template}
        """
        return prompt

    @classmethod
    @time_it
    async def summarize_results(cls, user_id, results, userText, sql=None, base64_code=None):
        """Legacy summarization method"""
        Summarization = instructions_dict["Summarization"]
        
        prompt = cls._create_prompt(results, userText, sql, base64_code)

        messages=[
            {"role": "system", "content": f""" {Summarization} """},
            {"role": "user", "content": prompt}
        ]
        
        # Set a reasonable timeout and max tokens to improve performance
        response = await chat_completion_request(
            user_id, 
            messages, 
            model="gpt-4o-mini", 
            response_format=True,
            max_tokens=1000,  # Limit token usage for faster response
            temperature=0.3   # Lower temperature for more deterministic responses
        )
        
        json_result = response.model_dump()['choices'][0]['message']['content']
        json_result = json.loads(json_result)
        summary = json_result["summary"]
        return summary
    
    @classmethod
    @time_it
    async def summarize_results_v2(cls, user_id, log, userText, sql=None, base64_code=None, custom_instructions=None, fig_json_list=None):
        """Improved summarization method with better performance"""
        # Get cached or generate summarization instructions
        system_content = cls._get_summarization_instructions(custom_instructions)

        # Detect if this is a plotting request
        is_plotting_request = any(keyword in userText.lower() for keyword in
                                 ["plot", "graph", "visualize", "visualization", "chart", "show me", "display"])

        # Check if a plot was actually generated
        plot_was_generated = fig_json_list is not None and len(fig_json_list) > 0

        # If user asked for a plot and it was generated, still summarize the data but keep it concise
        # REMOVED: Early return that skipped summarization for plotting requests
        # We want to summarize all the data from database queries even when plotting

        # Detect if this is a differential expression query
        is_diff_exp = any(keyword in userText.lower() for keyword in
                         ["tumor vs normal", "tumor versus normal", "differential expression",
                          "cancer vs healthy", "mutant vs wildtype", "mutant vs wt"])

        biotech_template = ""
        if is_diff_exp:
            biotech_template = """

EXAMPLE BIOTECH-GRADE RESPONSE FORMAT (adapt to your specific data):

<h6>Gene Name Differential Expression Analysis</h6>
<p>The <strong>GENE_NAME</strong> gene was analyzed for expression differences between [groups] using RNA-seq TPM values from the [Dataset] dataset.</p>

<table border="1" style="border-collapse: collapse; margin: 10px 0;">
  <thead>
    <tr>
      <th>Group</th>
      <th>Mean (TPM)</th>
      <th>Median (TPM)</th>
      <th>Range (TPM)</th>
      <th>SD</th>
      <th>n</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>Group 1</td>
      <td>[mean1]</td>
      <td>[median1]</td>
      <td>[min1] – [max1]</td>
      <td>[sd1]</td>
      <td>[n1]</td>
    </tr>
    <tr>
      <td>Group 2</td>
      <td>[mean2]</td>
      <td>[median2]</td>
      <td>[min2] – [max2]</td>
      <td>[sd2]</td>
      <td>[n2]</td>
    </tr>
  </tbody>
</table>

<p><strong>Fold Change:</strong> [X.XX]-fold [upregulation/downregulation] (log₂FC = [X.XX])</p>

<p><strong>Interpretation:</strong> [Gene] shows [direction and magnitude] in [group1] compared to [group2]. This pattern aligns with its known role in [biological context]. [Additional biological interpretation based on fold change magnitude].</p>

<p><strong>Note:</strong> [Mention dataset source and any caveats about statistical testing or validation needs].</p>

CRITICAL: Replace ALL bracketed placeholders with ACTUAL values from the query results. Use this format as a structural guide only.
"""

        # Create user prompt with f-string
        user_prompt = f"""
        User's Query: <<<{userText}>>>
        Log Data: \"\"\"{log}\"\"\"

        ⚠️ CRITICAL RULES:
        1. If a numeric column EXISTS in the data with a real value, SHOW THAT VALUE - never replace with N/A
        2. Only use "N/A" when the column is missing OR the value is None/null/NaN
        3. Adapt your table columns based on what data is actually available
        4. For Range: if both min and max columns exist with values, show "min – max", else "N/A"

        Additional Notes:
        - Do not include any mock data, code snippets, plot code, or SQL queries in your response.
        - ALL DATA POINTS MUST BE PRESENTED IN TABLE FORMAT using HTML.
        - **CRITICAL: Include ACTUAL NUMERICAL VALUES (means, medians, TPM values, counts, fold changes, log2FC, SD, ranges) in your summary tables. NEVER replace real numbers with qualitative terms like "Higher", "Lower", "More", or "Less".**
        - For differential expression queries, interpret biological directionality (upregulated/downregulated) and provide brief biological context.
        - Always mention the dataset source (e.g., "Zhang et al. 2016 dataset").
        {biotech_template}
        """

        # Create message structure directly
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_prompt}
        ]

        # Make API call more efficient with optimized parameters
        response = await chat_completion_request(
            user_id,
            messages,
            model="gpt-4o-mini",
            response_format=True,
            temperature=0.1  # Very low temperature for deterministic data extraction
        )

        try:
            # Extract content directly with error handling
            json_result = json.loads(response.model_dump()['choices'][0]['message']['content'])
            return json_result["summary"]
        except (json.JSONDecodeError, KeyError) as e:
            # Fallback in case of parsing errors
            return "<p><strong>Error:</strong> Unable to generate summary. Please try again or contact support.</p>"
    
    @classmethod
    @time_it
    async def summarize_results_parallel(cls, user_id, log, userText, custom_instructions=None):
        """New method that uses parallel processing for faster summarization of large datasets"""
        import asyncio
        from concurrent.futures import ThreadPoolExecutor
        
        # For large logs, split into chunks and process in parallel
        max_chunk_size = 4000  # Adjust based on token limits
        
        if len(log) > max_chunk_size:
            # Split the log into manageable chunks
            chunks = [log[i:i + max_chunk_size] for i in range(0, len(log), max_chunk_size)]
            
            # Process each chunk in parallel
            async with ThreadPoolExecutor(max_workers=3) as executor:
                tasks = []
                for i, chunk in enumerate(chunks):
                    chunk_text = f"(Part {i+1}/{len(chunks)}) {chunk}"
                    task = asyncio.create_task(
                        cls.summarize_results_v2(
                            user_id, 
                            chunk_text, 
                            userText, 
                            custom_instructions=custom_instructions
                        )
                    )
                    tasks.append(task)
                
                # Gather all results
                chunk_summaries = await asyncio.gather(*tasks)
                
                # Combine the summaries
                combined_summary = "<h6>Combined Summary</h6>" + "".join(chunk_summaries)
                return combined_summary
        else:
            # For smaller logs, use the standard approach
            return await cls.summarize_results_v2(user_id, log, userText, custom_instructions=custom_instructions)