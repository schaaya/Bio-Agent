"""
Bio Gene Expression Chatbot with Login
Streamlit UI for querying biomedical gene expression database
"""
import streamlit as st
import asyncio
import websockets
import json
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from datetime import datetime
import requests
from typing import Optional, Dict, Any
import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================================
# Configuration
# ============================================================================

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
WS_BASE_URL = os.getenv("WS_BASE_URL", "ws://localhost:8000")

# ============================================================================
# Session State Initialization
# ============================================================================

if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'token' not in st.session_state:
    st.session_state.token = None
if 'username' not in st.session_state:
    st.session_state.username = None
if 'messages' not in st.session_state:
    st.session_state.messages = []
if 'ws_connected' not in st.session_state:
    st.session_state.ws_connected = False

# ============================================================================
# Authentication Functions
# ============================================================================

def login(email: str, password: str) -> Optional[Dict[str, Any]]:
    """Authenticate user and get JWT token"""
    try:
        response = requests.post(
            f"{API_BASE_URL}/login",
            data={
                "username": email,
                "password": password
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

        if response.status_code == 200:
            data = response.json()
            return {
                "token": data.get("access_token"),
                "username": email.split("@")[0]
            }
        else:
            return None
    except Exception as e:
        st.error(f"Login failed: {str(e)}")
        return None

def logout():
    """Clear session state and logout"""
    st.session_state.authenticated = False
    st.session_state.token = None
    st.session_state.username = None
    st.session_state.messages = []
    st.session_state.ws_connected = False

# ============================================================================
# WebSocket Communication
# ============================================================================

async def send_message_ws(message: str, token: str) -> Dict[str, Any]:
    """Send message via WebSocket and get response"""
    uri = f"{WS_BASE_URL}/wss?token={token}"

    try:
        async with websockets.connect(uri) as websocket:
            # Receive greeting
            greeting = await websocket.recv()
            greeting_data = json.loads(greeting)

            # Send user message
            payload = {
                "message": message,
                "type": "QUERY"
            }
            await websocket.send(json.dumps(payload))

            # Keep receiving messages until we get the final response
            # (orchestrator sends status updates, then final response)
            final_response = None
            while True:
                try:
                    response = await websocket.recv()
                    response_data = json.loads(response)

                    # Status updates have "status" key, final response has "message" key
                    if "status" in response_data:
                        # This is a status update, keep waiting
                        print(f"Status: {response_data['status']}")
                        continue
                    elif "message" in response_data:
                        # This is the final response
                        final_response = response_data

                        # Debug: Print what we received
                        print(f"✅ Received response with keys: {list(response_data.keys())}")
                        print(f"   - Has SQL: {bool(response_data.get('sql'))}")
                        print(f"   - Has fig_json: {bool(response_data.get('fig_json'))}")
                        if response_data.get('fig_json'):
                            fig_data = response_data.get('fig_json')
                            print(f"   - fig_json type: {type(fig_data)}")
                            if isinstance(fig_data, list):
                                print(f"   - fig_json length: {len(fig_data)}")
                                if len(fig_data) > 0:
                                    print(f"   - First item type: {type(fig_data[0])}")
                                    if isinstance(fig_data[0], str):
                                        print(f"   - First item preview: {fig_data[0][:100]}...")
                            elif isinstance(fig_data, str):
                                print(f"   - fig_json preview: {fig_data[:100]}...")

                        break
                except websockets.exceptions.ConnectionClosed:
                    break

            return final_response if final_response else {
                "message": "No response received",
                "is_image": False,
                "sql": None,
                "fig_json": None
            }
    except Exception as e:
        return {
            "message": f"Error: {str(e)}",
            "is_image": False,
            "sql": None,
            "fig_json": None
        }

def send_message(message: str) -> Dict[str, Any]:
    """Wrapper to run async WebSocket call"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(
            send_message_ws(message, st.session_state.token)
        )
    finally:
        loop.close()

# ============================================================================
# UI Components
# ============================================================================

def render_login_page():
    """Render the login page"""
    # Center the login form
    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        st.markdown("<br><br>", unsafe_allow_html=True)

        # Logo and title
        st.markdown("""
        <div style='text-align: center; padding: 2rem 0;'>
            <h1 style='color: #1f77b4; font-size: 3rem; margin-bottom: 0.5rem;'>
                🧬 BioInsight AI
            </h1>
            <p style='color: #666; font-size: 1.2rem; margin-bottom: 2rem;'>
                Intelligent Biomedical Database Assistant
            </p>
        </div>
        """, unsafe_allow_html=True)

        # Login card
        st.markdown("""
        <div style='
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 0.25rem;
            border-radius: 1rem;
            margin-bottom: 2rem;
        '>
            <div style='
                background: #ffffff;
                padding: 2rem;
                border-radius: 0.9rem;
            '>
                <h4 style='color: #333; margin-bottom: 1.5rem;'>Sign In to Your Account</h4>
            </div>
        """, unsafe_allow_html=True)

        with st.form("login_form"):
            email = st.text_input(
                "Email Address",
                placeholder="user@example.com",
                help="Enter your registered email address"
            )
            password = st.text_input(
                "Password",
                type="password",
                placeholder="••••••••",
                help="Enter your password"
            )

            st.markdown("<br>", unsafe_allow_html=True)
            submit = st.form_submit_button(
                "🚀 Login",
                use_container_width=True,
                type="primary"
            )

            if submit:
                if email and password:
                    with st.spinner("🔐 Authenticating..."):
                        auth_data = login(email, password)

                        if auth_data:
                            st.session_state.authenticated = True
                            st.session_state.token = auth_data["token"]
                            st.session_state.username = auth_data["username"]
                            st.success(f"✅ Welcome back, {auth_data['username']}!")
                            st.rerun()
                        else:
                            st.error("❌ Invalid credentials. Please try again.")
                else:
                    st.warning("⚠️ Please enter both email and password.")

        st.markdown("</div></div>", unsafe_allow_html=True)

        # Features section
        st.markdown("""
        <div style='text-align: center; margin-top: 3rem;'>
            <p style='color: #888; font-size: 0.9rem; margin-bottom: 1rem;'>
                ✨ Powered by Advanced AI Technology
            </p>
        </div>
        """, unsafe_allow_html=True)

        # Feature cards
        feat_col1, feat_col2, feat_col3 = st.columns(3)

        with feat_col1:
            st.markdown("""
            <div style='text-align: center; padding: 1rem;'>
                <div style='font-size: 2rem; margin-bottom: 0.5rem;'>🔬</div>
                <div style='font-weight: bold; color: #333;'>Gene Expression</div>
                <div style='color: #666; font-size: 0.85rem;'>Query complex datasets</div>
            </div>
            """, unsafe_allow_html=True)

        with feat_col2:
            st.markdown("""
            <div style='text-align: center; padding: 1rem;'>
                <div style='font-size: 2rem; margin-bottom: 0.5rem;'>📊</div>
                <div style='font-weight: bold; color: #333;'>Smart Analytics</div>
                <div style='color: #666; font-size: 0.85rem;'>AI-powered insights</div>
            </div>
            """, unsafe_allow_html=True)

        with feat_col3:
            st.markdown("""
            <div style='text-align: center; padding: 1rem;'>
                <div style='font-size: 2rem; margin-bottom: 0.5rem;'>⚡</div>
                <div style='font-weight: bold; color: #333;'>Real-time</div>
                <div style='color: #666; font-size: 0.85rem;'>Instant responses</div>
            </div>
            """, unsafe_allow_html=True)

def render_plotly_chart(fig_json):
    """Render Plotly chart from JSON"""
    if not fig_json:
        st.warning("No visualization data available")
        return

    try:
        # Handle different formats
        if isinstance(fig_json, list):
            # List of figure dictionaries or JSON strings
            for idx, fig_item in enumerate(fig_json):
                # If it's a JSON string, parse it first
                if isinstance(fig_item, str):
                    try:
                        fig_dict = json.loads(fig_item)
                    except json.JSONDecodeError as e:
                        st.error(f"Chart {idx+1}: Failed to parse JSON - {str(e)}")
                        continue
                elif isinstance(fig_item, dict):
                    fig_dict = fig_item
                else:
                    st.warning(f"Chart {idx+1}: Unexpected type {type(fig_item)}")
                    continue

                # Now render the parsed dict
                if 'data' in fig_dict or 'layout' in fig_dict:
                    fig = go.Figure(fig_dict)
                    st.plotly_chart(fig, use_container_width=True, key=f"plot_{idx}_{datetime.now().timestamp()}")
                else:
                    st.warning(f"Chart {idx+1}: Invalid Plotly format (missing 'data' or 'layout')")

        elif isinstance(fig_json, str):
            # Single JSON string
            try:
                fig_dict = json.loads(fig_json)
                if 'data' in fig_dict or 'layout' in fig_dict:
                    fig = go.Figure(fig_dict)
                    st.plotly_chart(fig, use_container_width=True, key=f"plot_{datetime.now().timestamp()}")
                else:
                    st.warning("Invalid Plotly format (missing 'data' or 'layout')")
            except json.JSONDecodeError as e:
                st.error(f"Failed to parse JSON: {str(e)}")

        elif isinstance(fig_json, dict):
            # Single figure dictionary
            if 'data' in fig_json or 'layout' in fig_json:
                fig = go.Figure(fig_json)
                st.plotly_chart(fig, use_container_width=True, key=f"plot_{datetime.now().timestamp()}")
            else:
                st.warning("Invalid Plotly format (missing 'data' or 'layout')")
        else:
            st.warning(f"Unexpected visualization format: {type(fig_json)}")
    except Exception as e:
        st.error(f"Error rendering chart: {str(e)}")
        st.code(str(fig_json)[:500], language="text")  # Show first 500 chars for debugging

def render_sql_query(sql: str):
    """Render SQL query with syntax highlighting"""
    if sql:
        st.code(sql, language="sql")

def render_message(msg: Dict[str, Any], idx: int):
    """Render a single message bubble"""
    is_user = msg.get("is_user", False)

    if is_user:
        with st.chat_message("user", avatar="👤"):
            st.markdown(f"**{msg['content']}**")
    else:
        with st.chat_message("assistant", avatar="🤖"):
            # Main message - allow HTML rendering for tables
            st.markdown(msg["content"], unsafe_allow_html=True)

            # SQL query (if present)
            if msg.get("sql"):
                with st.expander("🔍 View Generated SQL Query", expanded=False):
                    st.markdown("**SQL Query:**")
                    render_sql_query(msg["sql"])
                    st.caption("This query was automatically generated from your natural language question")

            # Visualizations (if present)
            if msg.get("fig_json"):
                with st.expander("📊 Interactive Visualization", expanded=True):
                    render_plotly_chart(msg["fig_json"])
                    st.caption("💡 Tip: Hover over the chart for details, click-drag to zoom, double-click to reset")

def render_chat_interface():
    """Render the main chat interface"""
    # Sidebar
    with st.sidebar:
        # User profile section
        st.markdown(f"""
        <div style='
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 1.5rem;
            border-radius: 1rem;
            margin-bottom: 1.5rem;
            color: white;
            text-align: center;
        '>
            <div style='font-size: 3rem; margin-bottom: 0.5rem;'>👤</div>
            <div style='font-weight: bold; font-size: 1.1rem;'>{st.session_state.username}</div>
            <div style='font-size: 0.85rem; opacity: 0.9; margin-top: 0.25rem;'>Researcher</div>
        </div>
        """, unsafe_allow_html=True)

        # Example queries section
        st.markdown("### 💡 Quick Start Queries")
        st.markdown("<small style='color: #666;'>Click any example to try it out</small>", unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)

        examples = [
            {
                "icon": "🧬",
                "text": "Compare EGFR in KRAS-mutant cell lines",
                "category": "Mutation Analysis"
            },
            {
                "icon": "📊",
                "text": "Show TP53 expression in tumor vs normal",
                "category": "Expression Comparison"
            },
            {
                "icon": "🔬",
                "text": "Which genes are upregulated in tumor?",
                "category": "Differential Expression"
            },
            {
                "icon": "⚡",
                "text": "EGFR levels in mutant cells",
                "category": "Quick Query"
            },
            {
                "icon": "📈",
                "text": "Differential expression of TP53",
                "category": "Analysis"
            }
        ]

        for idx, example in enumerate(examples):
            col1, col2 = st.columns([1, 9])
            with col1:
                st.markdown(f"<div style='font-size: 1.5rem; margin-top: 0.25rem;'>{example['icon']}</div>", unsafe_allow_html=True)
            with col2:
                if st.button(
                    example['text'],
                    key=f"example_{idx}",
                    use_container_width=True,
                    help=f"Category: {example['category']}"
                ):
                    st.session_state.pending_message = example['text']
                    st.rerun()

        st.divider()

        # Stats section
        st.markdown("### 📊 Session Stats")
        message_count = len([m for m in st.session_state.messages if m.get('is_user')])
        st.metric("Queries Made", message_count)

        st.divider()

        # Logout button
        if st.button("🚪 Logout", use_container_width=True, type="secondary"):
            logout()
            st.rerun()

        st.divider()

        # Footer
        st.markdown("""
        <div style='text-align: center; color: #888; font-size: 0.75rem;'>
            <p style='margin-bottom: 0.5rem;'>🔬 BioInsight AI</p>
            <p style='margin-bottom: 0.5rem;'>Biomedical Gene Expression Database</p>
            <p style='margin-bottom: 0;'>Powered by Pydantic AI + FastAPI</p>
        </div>
        """, unsafe_allow_html=True)

    # Main chat area - modern header
    st.markdown("""
    <div style='
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        padding: 1.5rem;
        border-radius: 1rem;
        margin-bottom: 2rem;
        color: white;
    '>
        <h1 style='margin: 0; font-size: 2rem;'>💬 BioInsight Chat</h1>
        <p style='margin: 0.5rem 0 0 0; opacity: 0.9;'>Ask questions about gene expression, mutations, and biomedical data</p>
    </div>
    """, unsafe_allow_html=True)

    # Display chat messages or empty state
    if len(st.session_state.messages) == 0:
        # Empty state - show welcome message
        st.markdown("""
        <div style='
            text-align: center;
            padding: 4rem 2rem;
            color: #666;
        '>
            <div style='font-size: 4rem; margin-bottom: 1rem;'>🔬</div>
            <h2 style='color: #333; margin-bottom: 1rem;'>Welcome to BioInsight AI</h2>
            <p style='font-size: 1.1rem; margin-bottom: 2rem; max-width: 600px; margin-left: auto; margin-right: auto;'>
                Your intelligent assistant for exploring biomedical gene expression data.
                Ask questions in natural language and get instant insights backed by data.
            </p>
        </div>
        """, unsafe_allow_html=True)

        # Quick start tips
        col1, col2, col3 = st.columns(3)

        with col1:
            st.markdown("""
            <div style='
                background: linear-gradient(135deg, #667eea15 0%, #764ba215 100%);
                padding: 1.5rem;
                border-radius: 1rem;
                text-align: center;
                height: 100%;
            '>
                <div style='font-size: 2.5rem; margin-bottom: 0.5rem;'>💡</div>
                <h4 style='color: #333; margin-bottom: 0.5rem;'>Ask Anything</h4>
                <p style='color: #666; font-size: 0.9rem;'>
                    Query gene expression, mutations, or differential analysis in plain English
                </p>
            </div>
            """, unsafe_allow_html=True)

        with col2:
            st.markdown("""
            <div style='
                background: linear-gradient(135deg, #667eea15 0%, #764ba215 100%);
                padding: 1.5rem;
                border-radius: 1rem;
                text-align: center;
                height: 100%;
            '>
                <div style='font-size: 2.5rem; margin-bottom: 0.5rem;'>⚡</div>
                <h4 style='color: #333; margin-bottom: 0.5rem;'>Instant Results</h4>
                <p style='color: #666; font-size: 0.9rem;'>
                    Get automated SQL queries, statistical analysis, and visualizations
                </p>
            </div>
            """, unsafe_allow_html=True)

        with col3:
            st.markdown("""
            <div style='
                background: linear-gradient(135deg, #667eea15 0%, #764ba215 100%);
                padding: 1.5rem;
                border-radius: 1rem;
                text-align: center;
                height: 100%;
            '>
                <div style='font-size: 2.5rem; margin-bottom: 0.5rem;'>📊</div>
                <h4 style='color: #333; margin-bottom: 0.5rem;'>Smart Insights</h4>
                <p style='color: #666; font-size: 0.9rem;'>
                    AI-powered analysis with interactive charts and detailed breakdowns
                </p>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("<br><br>", unsafe_allow_html=True)

    else:
        # Display chat messages
        for idx, msg in enumerate(st.session_state.messages):
            render_message(msg, idx)

    # Check for pending message (from example button)
    if hasattr(st.session_state, 'pending_message'):
        user_message = st.session_state.pending_message
        del st.session_state.pending_message
        process_message(user_message)
        st.rerun()

    # Chat input with enhanced placeholder
    user_input = st.chat_input(
        "💬 Ask about genes, expression levels, mutations, comparisons...",
        key="chat_input"
    )

    if user_input:
        process_message(user_input)
        st.rerun()

def process_message(user_input: str):
    """Process user message and get response"""
    # Add user message to chat
    st.session_state.messages.append({
        "content": user_input,
        "is_user": True,
        "timestamp": datetime.now().isoformat()
    })

    # Show user message immediately
    with st.chat_message("user", avatar="👤"):
        st.markdown(f"**{user_input}**")

    # Get response from backend
    with st.chat_message("assistant", avatar="🤖"):
        # Enhanced loading state
        with st.spinner("🧠 Analyzing your query..."):
            response_data = send_message(user_input)

            # Extract response components
            message = response_data.get("message", "No response")
            sql = response_data.get("sql")
            fig_json = response_data.get("fig_json")

            # Display response - allow HTML rendering for tables
            st.markdown(message, unsafe_allow_html=True)

            # Display SQL
            if sql:
                with st.expander("🔍 View Generated SQL Query", expanded=False):
                    st.markdown("**SQL Query:**")
                    render_sql_query(sql)
                    st.caption("This query was automatically generated from your natural language question")

            # Display visualizations
            if fig_json:
                with st.expander("📊 Interactive Visualization", expanded=True):
                    render_plotly_chart(fig_json)
                    st.caption("💡 Tip: Hover over the chart for details, click-drag to zoom, double-click to reset")

            # Add assistant message to chat
            st.session_state.messages.append({
                "content": message,
                "is_user": False,
                "sql": sql,
                "fig_json": fig_json,
                "timestamp": datetime.now().isoformat()
            })

# ============================================================================
# Main App
# ============================================================================

def main():
    """Main application entry point"""
    # Page config
    st.set_page_config(
        page_title="BioInsight AI - Biomedical Database Assistant",
        page_icon="🧬",
        layout="wide",
        initial_sidebar_state="expanded",
        menu_items={
            'Get Help': None,
            'Report a bug': None,
            'About': "BioInsight AI - Intelligent Biomedical Database Assistant powered by Pydantic AI"
        }
    )

    # Custom CSS for professional styling
    st.markdown("""
    <style>
    /* Import Google Fonts */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    /* Global font and dark theme */
    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        color: #e2e8f0;
        background-color: #0f172a;
    }

    /* Main content - dark background */
    .main .block-container {
        color: #e2e8f0;
        background-color: #0f172a;
    }

    .main {
        background-color: #0f172a;
    }

    /* Element containers */
    .element-container {
        background-color: transparent;
    }

    /* App background - deep dark blue */
    .stApp {
        background-color: #0f172a;
    }

    /* Sidebar text - light colors */
    [data-testid="stSidebar"] * {
        color: #e2e8f0;
    }

    /* Form elements - light text on dark */
    .stForm label {
        color: #e2e8f0 !important;
    }

    /* Captions - muted light */
    .stCaptionContainer, [data-testid="stCaptionContainer"] {
        color: #94a3b8 !important;
    }

    small {
        color: #94a3b8 !important;
    }

    /* All text light by default */
    p, div, span, label, h1, h2, h3, h4, h5, h6 {
        color: #e2e8f0;
    }

    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}

    /* Sidebar styling - dark gradient */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1e293b 0%, #0f172a 100%);
        border-right: 1px solid #334155;
    }

    [data-testid="stSidebar"] .element-container {
        background-color: transparent;
    }

    [data-testid="stSidebar"] .stButton {
        background-color: transparent;
    }

    /* Chat messages - dark cards with glow */
    .stChatMessage {
        padding: 1.25rem;
        border-radius: 1rem;
        margin-bottom: 1rem;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
        background: linear-gradient(135deg, #1e293b 0%, #334155 100%);
        border: 1px solid #475569;
        max-width: 100%;
        overflow-x: auto;
        word-wrap: break-word;
    }

    /* User message styling */
    [data-testid="stChatMessageContent"] {
        background-color: transparent;
        color: #e2e8f0 !important;
        max-width: 100%;
        overflow-wrap: break-word;
    }

    /* Chat message text - light colors */
    .stChatMessage p, .stChatMessage div, .stChatMessage span {
        color: #e2e8f0 !important;
        word-wrap: break-word;
        overflow-wrap: break-word;
    }

    /* Markdown in chat - light text */
    .stMarkdown {
        color: #e2e8f0 !important;
        max-width: 100%;
    }

    .stMarkdown p, .stMarkdown div {
        color: #e2e8f0 !important;
        word-wrap: break-word;
        overflow-wrap: break-word;
    }

    /* Ensure tables in chat don't overflow */
    .stChatMessage table {
        max-width: 100%;
        overflow-x: auto;
        display: block;
    }

    /* Form styling */
    .stForm {
        background-color: transparent;
    }

    /* Button styling */
    .stButton button {
        border-radius: 0.75rem;
        border: none;
        font-weight: 500;
        transition: all 0.3s ease;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white !important;
    }

    .stButton button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    }

    /* Primary button */
    .stButton button[kind="primary"] {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white !important;
    }

    /* Form submit button */
    .stFormSubmitButton button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white !important;
        border: none;
    }

    /* Secondary buttons - dark theme */
    .stButton button[kind="secondary"] {
        background-color: #334155;
        color: #e2e8f0 !important;
        border: 1px solid #475569;
    }

    .stButton button[kind="secondary"]:hover {
        background-color: #475569;
        border-color: #64748b;
    }

    /* Sidebar example buttons - dark theme */
    [data-testid="stSidebar"] .stButton button {
        background-color: #334155;
        color: #e2e8f0 !important;
        border: 1px solid #475569;
    }

    [data-testid="stSidebar"] .stButton button:hover {
        background-color: #475569;
    }

    [data-testid="stSidebar"] .stButton button[kind="primary"] {
        color: white !important;
    }

    /* Input fields - dark theme */
    .stTextInput input, .stTextArea textarea {
        border-radius: 0.75rem;
        border: 2px solid #475569;
        padding: 0.75rem;
        transition: border-color 0.3s ease;
        background-color: #1e293b !important;
        color: #e2e8f0 !important;
    }

    .stTextInput input:focus, .stTextArea textarea:focus {
        border-color: #667eea;
        box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.3);
        background-color: #334155 !important;
    }

    /* Input labels - light text */
    .stTextInput label, .stTextArea label {
        color: #e2e8f0 !important;
        font-weight: 500;
    }

    /* Placeholder text */
    .stTextInput input::placeholder, .stTextArea textarea::placeholder {
        color: #64748b !important;
    }

    /* Chat input - dark theme */
    .stChatInputContainer {
        border-top: 2px solid #334155;
        padding-top: 1rem;
        background-color: #0f172a;
    }

    .stChatInput input {
        background-color: #1e293b !important;
        color: #e2e8f0 !important;
        border: 2px solid #475569;
    }

    .stChatInput input:focus {
        border-color: #667eea !important;
        box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.3) !important;
    }

    .stChatInput input::placeholder {
        color: #64748b !important;
    }

    /* Expander styling - dark theme */
    .streamlit-expanderHeader {
        border-radius: 0.75rem;
        background-color: #334155;
        font-weight: 500;
        color: #e2e8f0 !important;
        border: 1px solid #475569;
    }

    .streamlit-expanderHeader p {
        color: #e2e8f0 !important;
    }

    .streamlit-expanderContent {
        background-color: #1e293b;
        color: #e2e8f0 !important;
        border: 1px solid #475569;
        border-top: none;
        padding: 1rem;
        max-width: 100%;
        overflow-x: auto;
    }

    /* Expander wrapper */
    .streamlit-expander {
        width: 100%;
        max-width: 100%;
        overflow: visible;
    }

    /* Content inside expanders */
    .streamlit-expanderContent > div {
        max-width: 100%;
    }

    /* Code blocks - enhanced dark theme */
    code {
        white-space: pre-wrap !important;
        word-wrap: break-word !important;
        overflow-wrap: break-word !important;
        border-radius: 0.5rem;
        background-color: #0f172a !important;
        color: #10b981 !important;  /* Green for code */
        padding: 1rem !important;
        border: 1px solid #475569;
        font-family: 'Monaco', 'Menlo', 'Courier New', monospace;
        font-size: 0.9rem;
        line-height: 1.5;
        display: block;
        max-width: 100%;
    }

    pre {
        background-color: #0f172a !important;
        border-radius: 0.5rem;
        padding: 1rem !important;
        border: 1px solid #475569;
        overflow-x: auto;
        max-width: 100%;
    }

    pre code {
        padding: 0 !important;
        border: none !important;
        background-color: transparent !important;
    }

    /* SQL code in expanders */
    .streamlit-expanderContent code {
        width: 100%;
        overflow-x: auto;
    }

    .streamlit-expanderContent pre {
        width: 100%;
        overflow-x: auto;
    }

    /* Tables - dark theme */
    table {
        border-collapse: collapse;
        width: 100%;
        margin: 1rem 0;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.5);
        border-radius: 0.75rem;
        overflow: hidden;
        background-color: #1e293b;
        border: 1px solid #475569;
    }

    th {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white !important;
        font-weight: 600;
        padding: 0.75rem;
        text-align: left;
    }

    td {
        padding: 0.75rem;
        border-bottom: 1px solid #334155;
        background-color: #1e293b;
        color: #e2e8f0 !important;
    }

    tr:hover td {
        background-color: #334155;
    }

    tbody tr {
        border-bottom: 1px solid #334155;
    }

    /* Metric styling - dark theme */
    [data-testid="stMetricValue"] {
        font-size: 2rem;
        font-weight: 700;
        color: #818cf8 !important;  /* Lighter purple */
    }

    [data-testid="stMetricLabel"] {
        color: #94a3b8 !important;
    }

    /* Spinner - purple glow */
    .stSpinner > div {
        border-top-color: #818cf8 !important;
    }

    /* Success/Error/Warning messages - dark theme */
    .stSuccess {
        background-color: rgba(16, 185, 129, 0.1);
        border: 1px solid #10b981;
        border-radius: 0.75rem;
        padding: 1rem;
        color: #10b981 !important;
    }

    .stError {
        background-color: rgba(239, 68, 68, 0.1);
        border: 1px solid #ef4444;
        border-radius: 0.75rem;
        padding: 1rem;
        color: #ef4444 !important;
    }

    .stWarning {
        background-color: rgba(251, 191, 36, 0.1);
        border: 1px solid #fbbf24;
        border-radius: 0.75rem;
        padding: 1rem;
        color: #fbbf24 !important;
    }

    .stInfo {
        background-color: rgba(59, 130, 246, 0.1);
        border: 1px solid #3b82f6;
        border-radius: 0.75rem;
        padding: 1rem;
        color: #3b82f6 !important;
    }

    .stAlert {
        color: #e2e8f0 !important;
    }

    /* Plotly charts - dark theme */
    .js-plotly-plot {
        border-radius: 0.75rem;
        overflow: visible !important;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.5);
        background-color: #1e293b !important;
        border: 1px solid #475569;
        width: 100% !important;
        max-width: 100%;
    }

    .js-plotly-plot .plotly {
        width: 100% !important;
        height: auto !important;
    }

    /* Plotly container */
    .stPlotlyChart {
        width: 100%;
        max-width: 100%;
        overflow: visible;
    }

    /* Fix plotly modebar (toolbar) */
    .modebar {
        background-color: #1e293b !important;
        border-radius: 0.5rem;
    }

    .modebar-btn {
        color: #e2e8f0 !important;
    }

    .modebar-btn:hover {
        background-color: #334155 !important;
    }

    /* Plotly background */
    .plotly .bg {
        fill: #1e293b !important;
    }

    /* Plotly text */
    .plotly text {
        fill: #e2e8f0 !important;
    }

    /* Plotly gridlines */
    .plotly .gridlayer line {
        stroke: #334155 !important;
    }

    /* Plotly axis lines */
    .plotly .zerolinelayer line {
        stroke: #475569 !important;
    }

    /* Scrollbar - dark theme */
    ::-webkit-scrollbar {
        width: 10px;
        height: 10px;
    }

    ::-webkit-scrollbar-track {
        background: #1e293b;
        border-radius: 5px;
    }

    ::-webkit-scrollbar-thumb {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 5px;
        border: 2px solid #1e293b;
    }

    ::-webkit-scrollbar-thumb:hover {
        background: linear-gradient(135deg, #818cf8 0%, #a78bfa 100%);
    }

    /* Dividers - dark theme */
    hr {
        border-color: #334155 !important;
    }

    /* Links - purple theme */
    a {
        color: #818cf8 !important;
    }

    a:hover {
        color: #a78bfa !important;
    }

    /* General container fixes */
    .main .block-container {
        max-width: 100%;
        padding-left: 1rem;
        padding-right: 1rem;
    }

    /* Prevent horizontal scroll */
    .element-container {
        max-width: 100%;
        overflow-x: hidden;
    }

    /* Fix image containers */
    img {
        max-width: 100%;
        height: auto;
    }

    /* Fix dataframe containers */
    .dataframe-container {
        max-width: 100%;
        overflow-x: auto;
    }

    /* Ensure stMarkdown doesn't overflow */
    [data-testid="stMarkdownContainer"] {
        max-width: 100%;
        overflow-wrap: break-word;
    }

    /* Fix HTML tables in markdown */
    .stMarkdown table {
        width: 100% !important;
        max-width: 100%;
        display: table;
        table-layout: auto;
    }

    /* Responsive container */
    @media (max-width: 768px) {
        .main .block-container {
            padding-left: 0.5rem;
            padding-right: 0.5rem;
        }

        .stChatMessage {
            padding: 1rem;
        }
    }
    </style>
    """, unsafe_allow_html=True)

    # Route to appropriate page
    if st.session_state.authenticated:
        render_chat_interface()
    else:
        render_login_page()

if __name__ == "__main__":
    main()
