import io
import json
import time
import uuid
import pandas as pd
from termcolor import colored
import core.globals as globals
from core.DB_selector import DBSelector
from core.query_executer import execute_query
from core.logger import log_sql_error
from core.Agent_Validator import Validator
from utility import biomedical_knowledge_qdrant as search_semantic
from utility.retrieval import get_similar_query
from core.SQL_engine_stage2 import Stage_two
from core.SQL_engine_stage1 import SQLGenerator
from utility.decorators import time_it

# Import evaluation system
from core.sql_analyzer import SQLAnalyzer
from core.evaluation_manager import SQLEvaluationManager
from core.feedback_system import FeedbackCollector, FeedbackType

# Initialize global evaluation manager and feedback collector
_evaluation_manager = None
_feedback_collector = None

def get_evaluation_manager():
    """Get or create the global evaluation manager instance"""
    global _evaluation_manager, _feedback_collector
    if _evaluation_manager is None:
        import os

        # Read configuration from environment variables with defaults
        confidence_threshold = float(os.getenv('SQL_CONFIDENCE_THRESHOLD', '75.0'))
        max_retries = int(os.getenv('SQL_MAX_RETRIES', '3'))
        enable_auto_retry = os.getenv('SQL_ENABLE_AUTO_RETRY', 'true').lower() == 'true'

        _feedback_collector = FeedbackCollector()
        _evaluation_manager = SQLEvaluationManager(
            feedback_collector=_feedback_collector,
            confidence_threshold=confidence_threshold,
            max_retries=max_retries,
            enable_auto_retry=enable_auto_retry
        )
    return _evaluation_manager, _feedback_collector

@time_it
async def SQL_Agent(userText, user_id, user_group, logger_timestamp_mod, tool_id=None, tag=None):
    max_attempts = 4
    attempts = 0
    message = None
    query_id = None
    sql_query = None  # Initialize to avoid UnboundLocalError in exception handler
    relevent_query = await get_similar_query(userText, top_n=2, csv_path=r'utility/queries.csv', embedding_path=r'utility/queries_embedding.csv')
    if relevent_query is None:
        relevent_query = None
    # print(colored(f"Relevant Query: {relevent_query}", "green"))
    relevant_domain_knowledge = await search_semantic.get_relevant_domain_knowledge(userText, top_k=5)  # Increased from 3 to 5
    print(colored(f"Relevant Domain Knowledge Retrieved:", "green"))
    print(colored(f"{relevant_domain_knowledge[:1000]}...", "cyan"))  # Print first 1000 chars
    await globals.send_status_to_user(user_id, status="Receiving your query...")
    while attempts < max_attempts:
        print(colored(f"SQLEngine Attempt: {attempts}", "yellow"))
        if message is None:
            message = {
            "User_Question": userText,
            "Error_Message": ''
            }
        user_str = json.dumps(message)
        print(colored(f"User Query + Error: {user_str}", "yellow"))
        try:
            start = time.time()
            context_msg = globals.session_data.get(user_id, [])[-4:] if globals.session_data.get(user_id) else []
            await globals.send_status_to_user(user_id, status="Selecting Database...")
            if (user_id, user_group) in globals.db_cache:
                print(colored(f"Database Cache Hit", "green"))
                database, db_schema, description, dialect = globals.db_cache[(user_id, user_group)]
            else:
                database, db_schema, description, dialect = await DBSelector.database_selection(user_id, user_group, userText)
                globals.db_cache[(user_id, user_group)] = (database, db_schema, description, dialect)
            if database is False:
                return "Sorry, either the database is not available or User does not have access to Database. Please contact Adminstrator.", None, None, None
            end = time.time()
            await globals.send_status_to_user(user_id, status="Gathering Schema...")
            start = time.time()
            engine = await SQLGenerator.create(db_schema, database)
            response = await engine.generate_query(user_id, user_str, context_msg, description, relevent_query, relevant_domain_knowledge)
            json_response = json.loads(response)
            sql_query = None
            tables_description = json_response["tables"]
            end = time.time()
            await globals.send_status_to_user(user_id, status="Generating SQL query...")
            start = time.time()
            sql_response = await Stage_two.generate_query(user_id, question=user_str, description=tables_description, dialect = dialect, relevent_query=relevent_query, relevant_domain_knowledge=relevant_domain_knowledge)
            json_results = json.loads(sql_response)
            sql_query = json_results["sql_query"]
            print(colored(f"SQL Query: {sql_query}", "yellow"))
            end = time.time()

            # Execute query to get preview for analyzer
            temp_results = execute_query(database, sql_query)
            if temp_results is None:
                raise Exception("Query execution returned no results for analysis")

            # Create dataframe preview for analyzer (first 5 rows)
            temp_df = pd.DataFrame(temp_results)
            df_preview = temp_df.head(5).to_string()

            # Analyze SQL query with confidence scoring
            await globals.send_status_to_user(user_id, status="Analyzing query quality...")

            # Get evaluation manager to access dynamic configuration
            eval_manager, _ = get_evaluation_manager()

            analyzer = SQLAnalyzer(
                schema=db_schema,
                relevant_query=relevent_query if relevent_query else [],
                relevant_domain_knowledge=relevant_domain_knowledge if relevant_domain_knowledge else [],
                description=description,
                custom_instructions="",  # Add custom instructions if available
                tables_description=tables_description,
                user_question=userText,
                sql_query=sql_query,
                dialect=dialect,
                df_preview=df_preview,
                confidence_threshold=eval_manager.confidence_threshold,
                max_retries=eval_manager.max_retries
            )

            # Analyze the query
            analysis_response = await analyzer.analyze_query()
            confidence_score = analysis_response.get("confidence_score", 0.0)
            feedback = analysis_response.get("feedback", "")

            # Log detailed evaluation breakdown for developers
            print(colored("\n" + "="*80, "cyan"))
            print(colored("📊 SQL QUALITY EVALUATION REPORT", "cyan", attrs=["bold"]))
            print(colored("="*80, "cyan"))

            print(colored(f"\n🎯 Overall Confidence Score: {confidence_score:.2f}%", "cyan", attrs=["bold"]))
            print(colored(f"📝 Summary: {feedback}\n", "cyan"))

            # Detailed dimension scores
            print(colored("📊 SCORE BREAKDOWN:", "yellow", attrs=["bold"]))
            print(colored("-" * 80, "yellow"))

            # Correctness (30 points)
            correctness = analysis_response.get("correctness_score", 0.0)
            print(colored(f"\n1️⃣  Correctness: {correctness:.1f}/30.0", "green" if correctness >= 24 else "yellow"))
            print("   ├─ SQL syntax validation")
            print("   ├─ Schema compatibility check")
            print("   ├─ Table/column existence verification")
            print("   └─ Data type correctness")

            # Relevance (30 points)
            relevance = analysis_response.get("relevance_score", 0.0)
            print(colored(f"\n2️⃣  Relevance: {relevance:.1f}/30.0", "green" if relevance >= 24 else "yellow"))
            print("   ├─ User question alignment")
            print("   ├─ Required data included")
            print("   ├─ Appropriate scope")
            print("   └─ Filters match intent")

            # Completeness (20 points)
            completeness = analysis_response.get("completeness_score", 0.0)
            print(colored(f"\n3️⃣  Completeness: {completeness:.1f}/20.0", "green" if completeness >= 16 else "yellow"))
            print("   ├─ Necessary JOINs present")
            print("   ├─ WHERE clauses appropriate")
            print("   ├─ Aggregations correct")
            print("   └─ GROUP BY/ORDER BY logic")

            # Performance (10 points)
            performance = analysis_response.get("performance_score", 0.0)
            print(colored(f"\n4️⃣  Performance: {performance:.1f}/10.0", "green" if performance >= 8 else "yellow"))
            print("   ├─ Query optimization")
            print("   ├─ Index usage potential")
            print("   ├─ Cartesian product check")
            print("   └─ Complexity assessment")

            # Data Quality (10 points)
            data_quality = analysis_response.get("data_quality_score", 0.0)
            print(colored(f"\n5️⃣  Data Quality: {data_quality:.1f}/10.0", "green" if data_quality >= 8 else "yellow"))
            print("   ├─ NULL handling")
            print("   ├─ Result preview validation")
            print("   ├─ Type consistency")
            print("   └─ Data completeness")

            # Issues and improvements
            issues = analysis_response.get("issues", [])
            if issues:
                print(colored(f"\n⚠️  ISSUES DETECTED ({len(issues)}):", "red", attrs=["bold"]))
                print(colored("-" * 80, "red"))
                for idx, issue in enumerate(issues, 1):
                    severity_color = "red" if issue.get("severity") == "critical" else "yellow" if issue.get("severity") == "warning" else "blue"
                    severity_icon = "🔴" if issue.get("severity") == "critical" else "🟡" if issue.get("severity") == "warning" else "🔵"
                    print(colored(f"   {severity_icon} Issue #{idx} [{issue.get('severity', 'unknown').upper()}]", severity_color))
                    print(colored(f"      Type: {issue.get('type', 'N/A')}", severity_color))
                    print(colored(f"      Description: {issue.get('description', 'N/A')}", severity_color))
            else:
                print(colored("\n✅ NO ISSUES DETECTED", "green", attrs=["bold"]))

            # Suggested improvements
            improvements = analysis_response.get("suggested_improvements", [])
            if improvements:
                print(colored(f"\n💡 SUGGESTED IMPROVEMENTS ({len(improvements)}):", "blue", attrs=["bold"]))
                print(colored("-" * 80, "blue"))
                for idx, improvement in enumerate(improvements, 1):
                    print(colored(f"   {idx}. {improvement}", "blue"))

            print(colored("\n" + "="*80 + "\n", "cyan"))

            # Check for critical issues FIRST (regardless of confidence score)
            critical_issues = analyzer.get_critical_issues(analysis_response)

            # Also check for completeness/relevance issues that indicate wrong query
            completeness_issues = [
                issue for issue in analysis_response.get("issues", [])
                if issue.get("type") in ["completeness", "relevance"]
                and ("filter" in issue.get("description", "").lower()
                     or "where" in issue.get("description", "").lower()
                     or "year" in issue.get("description", "").lower()
                     or "missing" in issue.get("description", "").lower())
            ]

            # Combine critical and important completeness issues
            blocking_issues = critical_issues + completeness_issues

            # CRITICAL: If there are blocking issues OR confidence < 75, retry
            should_retry = (len(blocking_issues) > 0) or (confidence_score < 75)

            if should_retry:
                # Determine retry reason
                if len(blocking_issues) > 0:
                    issues_summary = "; ".join([issue['description'] for issue in blocking_issues])
                    retry_reason = f"Critical/Completeness issues detected: {issues_summary}"
                    print(colored(f"🔴 CRITICAL ISSUE DETECTED! Confidence: {confidence_score:.1f}%", "red", attrs=["bold"]))
                    print(colored(f"   Issues: {issues_summary}", "red"))
                else:
                    # Include ALL issues and suggestions in retry reason (not just blocking ones)
                    all_issues = analysis_response.get("issues", [])
                    improvements = analysis_response.get("suggested_improvements", [])

                    issues_summary = "; ".join([issue['description'] for issue in all_issues]) if all_issues else "No specific issues"
                    improvements_summary = "; ".join(improvements) if improvements else "No suggestions"

                    retry_reason = f"Confidence Score {confidence_score:.1f}% below threshold. Issues: {issues_summary}. Suggestions: {improvements_summary}"
                    print(colored(f"⚠️  LOW CONFIDENCE! Score: {confidence_score:.1f}%", "yellow", attrs=["bold"]))
                    print(colored(f"   Issues: {issues_summary}", "yellow"))
                    print(colored(f"   Suggestions: {improvements_summary}", "blue"))

                await globals.send_status_to_user(user_id, status="Refining Query...")

                # Store analysis in globals for feedback collection later
                if not hasattr(globals, 'query_evaluations'):
                    globals.query_evaluations = {}
                globals.query_evaluations[user_id] = {
                    'analysis': analysis_response,
                    'sql_query': sql_query,
                    'user_question': userText,
                    'attempt': attempts
                }

                raise Exception(retry_reason)

            # Store successful analysis for feedback collection
            if not hasattr(globals, 'query_evaluations'):
                globals.query_evaluations = {}
            globals.query_evaluations[user_id] = {
                'analysis': analysis_response,
                'sql_query': sql_query,
                'user_question': userText,
                'attempt': attempts,
                'confidence_score': confidence_score
            }
            # Validation step (DISABLED - causes false negatives, trust analyzer confidence instead)
            # The analyzer already validates with confidence scoring, validator is redundant
            if False and attempts >= 2:  # Disabled
                await globals.send_status_to_user(user_id, status="Validating SQL query...")
                start = time.time()
                validation_response = json.loads( await Validator.approve_query(user_id, question=user_str, description=tables_description, dialect = dialect, query=sql_query))
                validation_status = validation_response["Result"]
                if validation_status == "False":
                    print(colored(f"SQL Query Validation Failed: {validation_status}", "red"))
                    error_msg = validation_response["Reason"]
                    raise Exception(error_msg)
                elif validation_status == "True":
                    print(colored(f"SQL Query Validated: {validation_status}", "green"))
                end = time.time()

            await globals.send_status_to_user(user_id, status="Executing final query...")
            start = time.time()
            # Use the temp_results we already executed for analysis
            results = temp_results
            end = time.time()
            if results is not None:
                # Generate a query ID if not already generated
                if query_id is None:
                    query_id = uuid.uuid4().hex[:10]  # Using uuid for unique ID

                print(colored(f"Query ID: {query_id}", "green"))

                # Construct file path - include query_id to prevent overwrites when multiple queries run
                csv_file_path = f"temp/{user_id}_{logger_timestamp_mod}_{tool_id}_{query_id}_results.csv"
                print(colored(f"Results: {csv_file_path}", "green"))
                
                # Save results to CSV
                df = pd.DataFrame(results)

                # Check for empty results - trigger retry
                if len(df) == 0 and attempts < max_attempts - 1:
                    print(colored(f"⚠️  Query returned 0 rows. Triggering retry.", "yellow"))
                    message["Error_Message"] = "Query returned 0 rows. Please revise the query to return actual data."
                    if sql_query is not None:
                        message["Previous_Query"] = sql_query
                    attempts += 1
                    await globals.send_status_to_user(user_id, status="Retrying query...")
                    continue

                df.to_csv(csv_file_path, index=False)

                # Store info about dataframe
                buffer = io.StringIO()
                df.info(buf=buffer)
                df_info = buffer.getvalue()
                
                user_email = user_id.split("_")[0]
                
                # Store path in globals
                globals.csv_path(user_email, file_path=csv_file_path)
                
                # Also store in the new mapping for easier retrieval
                globals.add_csv_path_mapping(user_email, query_id, csv_file_path)

                # Sample for display in results
                sample_size = min(len(df), 31)
                df_sample = df.sample(n=sample_size).sort_index()
                df_preview_display = df_sample.to_string()

                # Create feedback log in evaluation manager
                eval_manager, feedback_collector = get_evaluation_manager()
                if user_id in globals.query_evaluations:
                    eval_data = globals.query_evaluations[user_id]
                    feedback_log = feedback_collector.create_log(
                        user_id=user_id,
                        question=userText,
                        sql_query=sql_query,
                        confidence_score=eval_data.get('confidence_score', 0.0),
                        analyzer_result=eval_data.get('analysis', {})
                    )
                    # Update with execution details
                    feedback_log.execution_success = True
                    feedback_log.result_count = len(df)
                    feedback_log.regeneration_count = attempts

                    # Store log_id for later feedback collection
                    globals.query_evaluations[user_id]['log_id'] = feedback_log.id

                    print(colored(f"✓ Evaluation logged. Log ID: {feedback_log.id}", "green"))

                # Construct response with download link and confidence info
                confidence_info = ""
                if user_id in globals.query_evaluations:
                    conf_score = globals.query_evaluations[user_id].get('confidence_score', 0)
                    confidence_info = f"\n📊 Query Confidence: {conf_score:.1f}%\n"

                if len(df) > sample_size:
                    data = (
                        f"The result set is large; here's a sample of {sample_size} rows out of {len(df)} total rows:\n\n"
                        f"{df_preview_display}\n\n"
                        f"Summary:\n{df_info}\n\n"
                        f"{confidence_info}"
                        f"Download the full results CSV with: /download/csv/{query_id}"
                    )
                else:
                    data = (
                        f"Here are the results ({len(df)} rows):\n\n"
                        f"{df_preview_display}\n\n"
                        f"Summary:\n{df_info}\n\n"
                        f"{confidence_info}"
                        f"Download the results CSV with: /download/csv/{query_id}"
                    )
                print("Data Info:", data)
                return data, sql_query, df_info, query_id
            break

        except Exception as e:
            await globals.send_status_to_user(user_id, status="Ran into Error, Retrying your request...")
            print(colored(f"Error at process_user_query: {e}", "red"))
            message["Error_Message"] = str(e)
            if sql_query is not None:
                message["Previous_Query"] = sql_query
            await log_sql_error(dialect, sql_query, str(e))
        attempts += 1

    return "Ran into Error, Please try again.", None, None, None
