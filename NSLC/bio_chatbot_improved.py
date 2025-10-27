"""
BioInsight AI - Improved UI/UX
Professional biomedical chatbot with modern dark theme
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
from io import BytesIO
import base64
import plotly.io as pio

load_dotenv()

# ============================================================================
# Configuration
# ============================================================================

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
WS_BASE_URL = os.getenv("WS_BASE_URL", "ws://localhost:8000")

# ============================================================================
# Session State Initialization with Persistence
# ============================================================================

# Check for token in query parameters first (for page refresh persistence)
query_params = st.query_params
persisted_token = query_params.get("token", None)
persisted_username = query_params.get("user", None)

# Initialize session state
if 'authenticated' not in st.session_state:
    # Try to restore from query parameters
    if persisted_token and persisted_username:
        st.session_state.authenticated = True
        st.session_state.token = persisted_token
        st.session_state.username = persisted_username
    else:
        st.session_state.authenticated = False

if 'token' not in st.session_state:
    st.session_state.token = persisted_token

if 'username' not in st.session_state:
    st.session_state.username = persisted_username

if 'messages' not in st.session_state:
    st.session_state.messages = []

if 'ws_connected' not in st.session_state:
    st.session_state.ws_connected = False

# NEW: Add reasoning toggle state
if 'show_reasoning' not in st.session_state:
    st.session_state.show_reasoning = False

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

    # Clear persisted authentication from URL
    if "token" in st.query_params:
        del st.query_params["token"]
    if "user" in st.query_params:
        del st.query_params["user"]

# ============================================================================
# PDF Report Generation
# ============================================================================

def generate_pdf_report() -> BytesIO:
    """Generate PDF report of conversation history"""
    try:
        from reportlab.lib.pagesizes import letter, A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Image, Table, TableStyle
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT, TA_CENTER
    except ImportError:
        st.error("reportlab library not installed. Please run: pip install reportlab")
        return None

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.75*inch, bottomMargin=0.75*inch)
    story = []
    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#667eea'),
        spaceAfter=30,
        alignment=TA_CENTER
    )

    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#818cf8'),
        spaceAfter=12,
        spaceBefore=20
    )

    query_style = ParagraphStyle(
        'QueryStyle',
        parent=styles['Normal'],
        fontSize=11,
        textColor=colors.HexColor('#1e40af'),
        leftIndent=20,
        spaceAfter=10
    )

    response_style = ParagraphStyle(
        'ResponseStyle',
        parent=styles['Normal'],
        fontSize=10,
        leftIndent=20,
        spaceAfter=10
    )

    sql_style = ParagraphStyle(
        'SQLStyle',
        parent=styles['Code'],
        fontSize=9,
        leftIndent=30,
        textColor=colors.HexColor('#065f46'),
        backColor=colors.HexColor('#f0fdf4')
    )

    # Title
    story.append(Paragraph("BioInsight AI - Conversation Report", title_style))
    story.append(Spacer(1, 0.2*inch))

    # Metadata
    metadata = f"""
    <b>User:</b> {st.session_state.username}<br/>
    <b>Generated:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}<br/>
    <b>Total Queries:</b> {len([m for m in st.session_state.messages if m.get('is_user')])}<br/>
    """
    story.append(Paragraph(metadata, styles['Normal']))
    story.append(Spacer(1, 0.3*inch))

    # Conversation
    query_number = 0
    for idx, msg in enumerate(st.session_state.messages):
        if msg.get('is_user'):
            query_number += 1
            story.append(Paragraph(f"<b>Query #{query_number}</b>", heading_style))
            story.append(Paragraph(msg['content'], query_style))
            story.append(Spacer(1, 0.1*inch))
        else:
            story.append(Paragraph("<b>Response:</b>", heading_style))
            # Clean HTML tags from response
            clean_content = msg['content'].replace('<br>', ' ').replace('<br/>', ' ')
            story.append(Paragraph(clean_content, response_style))
            story.append(Spacer(1, 0.1*inch))

            # SQL Query
            if msg.get('sql'):
                story.append(Paragraph("<b>SQL Query:</b>", heading_style))
                # Handle multiple SQL queries - use special delimiter
                sql_queries = msg['sql'].split('\n\n--- NEXT QUERY ---\n\n') if '\n\n--- NEXT QUERY ---\n\n' in msg['sql'] else [msg['sql']]
                for sql_idx, sql in enumerate(sql_queries, 1):
                    if len(sql_queries) > 1:
                        story.append(Paragraph(f"<i>Query {sql_idx}:</i>", response_style))
                    # Format SQL with line breaks
                    formatted_sql = sql.strip().replace(' FROM ', '<br/>FROM ').replace(' JOIN ', '<br/>JOIN ').replace(' WHERE ', '<br/>WHERE ').replace(' ORDER BY ', '<br/>ORDER BY ').replace(' AND ', '<br/>  AND ')
                    story.append(Paragraph(f"<font face='Courier'>{formatted_sql}</font>", sql_style))
                    story.append(Spacer(1, 0.05*inch))
                story.append(Spacer(1, 0.1*inch))

            # Plot
            if msg.get('fig_json'):
                story.append(Paragraph("<b>Visualization:</b>", heading_style))
                try:
                    # Convert Plotly figure to image
                    fig_list = msg['fig_json'] if isinstance(msg['fig_json'], list) else [msg['fig_json']]

                    for fig_idx, fig_item in enumerate(fig_list):
                        if isinstance(fig_item, str):
                            fig_dict = json.loads(fig_item)
                        elif isinstance(fig_item, dict):
                            fig_dict = fig_item
                        else:
                            continue

                        if 'data' in fig_dict or 'layout' in fig_dict:
                            fig = go.Figure(fig_dict)
                            # Convert to image
                            img_bytes = pio.to_image(fig, format='png', width=600, height=400)
                            img = Image(BytesIO(img_bytes), width=5*inch, height=3.33*inch)
                            story.append(img)
                            story.append(Spacer(1, 0.1*inch))
                except Exception as e:
                    story.append(Paragraph(f"<i>[Visualization could not be rendered: {str(e)}]</i>", response_style))

            story.append(Spacer(1, 0.2*inch))
            # Add divider
            story.append(Paragraph("<hr/>", styles['Normal']))
            story.append(Spacer(1, 0.2*inch))

    # Build PDF
    doc.build(story)
    buffer.seek(0)
    return buffer

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
            final_response = None
            while True:
                try:
                    response = await websocket.recv()
                    response_data = json.loads(response)

                    if "status" in response_data:
                        continue
                    elif "message" in response_data:
                        final_response = response_data
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
    """Render modern login page"""
    st.markdown("""
    <div style='text-align: center; padding: 3rem 0 2rem 0;'>
        <div style='font-size: 4rem; margin-bottom: 1rem;'>🧬</div>
        <h1 style='color: #818cf8; font-size: 2.5rem; margin-bottom: 0.5rem; font-weight: 700;'>
            BioInsight AI
        </h1>
        <p style='color: #94a3b8; font-size: 1.1rem;'>
            Intelligent Biomedical Research Assistant
        </p>
    </div>
    """, unsafe_allow_html=True)

    # Center login form
    col1, col2, col3 = st.columns([1, 1.5, 1])

    with col2:
        with st.form("login_form", clear_on_submit=False):
            st.markdown("<h3 style='color: #e2e8f0; margin-bottom: 1.5rem;'>Sign In</h3>", unsafe_allow_html=True)

            email = st.text_input(
                "Email",
                placeholder="Enter your email",
                label_visibility="visible"
            )

            password = st.text_input(
                "Password",
                type="password",
                placeholder="Enter your password",
                label_visibility="visible"
            )

            submit = st.form_submit_button(
                "Sign In",
                use_container_width=True,
                type="primary"
            )

            if submit:
                if email and password:
                    with st.spinner("Authenticating..."):
                        auth_data = login(email, password)

                        if auth_data:
                            st.session_state.authenticated = True
                            st.session_state.token = auth_data["token"]
                            st.session_state.username = auth_data["username"]

                            # Persist token in URL query parameters for page refresh
                            st.query_params["token"] = auth_data["token"]
                            st.query_params["user"] = auth_data["username"]

                            st.success("Welcome!")
                            st.rerun()
                        else:
                            st.error("Invalid credentials")
                else:
                    st.warning("Please enter email and password")

        # Quick features
        st.markdown("<br>", unsafe_allow_html=True)
        feat1, feat2, feat3 = st.columns(3)

        with feat1:
            st.markdown("""
            <div style='text-align: center; padding: 1rem;'>
                <div style='font-size: 2rem; margin-bottom: 0.5rem;'>📊</div>
                <div style='color: #94a3b8; font-size: 0.85rem;'>SQL Analytics</div>
            </div>
            """, unsafe_allow_html=True)

        with feat2:
            st.markdown("""
            <div style='text-align: center; padding: 1rem;'>
                <div style='font-size: 2rem; margin-bottom: 0.5rem;'>🤖</div>
                <div style='color: #94a3b8; font-size: 0.85rem;'>AI-Powered</div>
            </div>
            """, unsafe_allow_html=True)

        with feat3:
            st.markdown("""
            <div style='text-align: center; padding: 1rem;'>
                <div style='font-size: 2rem; margin-bottom: 0.5rem;'>⚡</div>
                <div style='color: #94a3b8; font-size: 0.85rem;'>Real-time</div>
            </div>
            """, unsafe_allow_html=True)

def render_reasoning_steps(reasoning_steps: list):
    """Render reasoning and execution steps"""
    if not reasoning_steps:
        st.info("No reasoning steps available for this query.")
        return

    for step in reasoning_steps:
        step_type = step.get("type", "unknown")

        if step_type == "planning":
            # Planning step
            st.markdown(f"### 📋 {step.get('title', 'Planning')}")
            st.markdown(f"**Details:** {step.get('details', 'N/A')}")

            if step.get("steps"):
                st.markdown("**Execution Plan:**")
                for plan_step in step["steps"]:
                    st.markdown(
                        f"- **Step {plan_step['step_num']}:** `{plan_step['tool']}` - {plan_step['sub_question']}"
                    )

        elif step_type == "execution":
            # Execution step
            step_num = step.get("step_num", "?")
            tool = step.get("tool", "unknown")
            sub_question = step.get("sub_question", "N/A")
            status = step.get("status", "unknown")

            # Status emoji
            status_emoji = "✅" if status == "success" else "❌"

            st.markdown(f"### {status_emoji} Step {step_num}: {tool}")
            st.markdown(f"**Sub-question:** {sub_question}")

            # Show status indicators
            cols = st.columns(4)
            with cols[0]:
                if step.get("has_sql"):
                    st.markdown("🔍 SQL Generated")
            with cols[1]:
                if step.get("has_result"):
                    st.markdown("📊 Data Retrieved")
            with cols[2]:
                if step.get("has_visualization"):
                    st.markdown("📈 Visualization")
            with cols[3]:
                if step.get("query_id"):
                    st.markdown(f"🆔 `{step['query_id'][:8]}...`")

            # Show error if present
            if step.get("error"):
                st.error(f"**Error:** {step['error']}")

        elif step_type == "summary":
            # Summary step
            st.markdown(f"### ✨ {step.get('title', 'Summary')}")

            summary_cols = st.columns(4)
            with summary_cols[0]:
                st.metric("Total Steps", step.get("total_steps", 0))
            with summary_cols[1]:
                st.metric("SQL Generated", "Yes" if step.get("sql_generated") else "No")
            with summary_cols[2]:
                st.metric("Visualizations", step.get("visualizations_created", 0))
            with summary_cols[3]:
                st.metric("Follow-ups", step.get("followup_questions", 0))

        # Add separator
        st.markdown("---")

def render_plotly_chart(fig_json):
    """Render Plotly chart from JSON"""
    if not fig_json:
        return

    try:
        if isinstance(fig_json, list):
            for idx, fig_item in enumerate(fig_json):
                if isinstance(fig_item, str):
                    try:
                        fig_dict = json.loads(fig_item)
                    except:
                        continue
                elif isinstance(fig_item, dict):
                    fig_dict = fig_item
                else:
                    continue

                if 'data' in fig_dict or 'layout' in fig_dict:
                    fig = go.Figure(fig_dict)
                    # Update to dark theme
                    fig.update_layout(
                        template="plotly_dark",
                        paper_bgcolor='#1e293b',
                        plot_bgcolor='#1e293b',
                        font=dict(color='#e2e8f0')
                    )
                    st.plotly_chart(fig, use_container_width=True, key=f"plot_{idx}_{datetime.now().timestamp()}")

        elif isinstance(fig_json, str):
            try:
                fig_dict = json.loads(fig_json)
                if 'data' in fig_dict or 'layout' in fig_dict:
                    fig = go.Figure(fig_dict)
                    fig.update_layout(
                        template="plotly_dark",
                        paper_bgcolor='#1e293b',
                        plot_bgcolor='#1e293b',
                        font=dict(color='#e2e8f0')
                    )
                    st.plotly_chart(fig, use_container_width=True)
            except:
                pass

        elif isinstance(fig_json, dict):
            if 'data' in fig_json or 'layout' in fig_json:
                fig = go.Figure(fig_json)
                fig.update_layout(
                    template="plotly_dark",
                    paper_bgcolor='#1e293b',
                    plot_bgcolor='#1e293b',
                    font=dict(color='#e2e8f0')
                )
                st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.error(f"Chart error: {str(e)}")

def render_message(msg: Dict[str, Any]):
    """Render a chat message"""
    is_user = msg.get("is_user", False)

    if is_user:
        with st.chat_message("user", avatar="👤"):
            st.markdown(msg["content"])
    else:
        with st.chat_message("assistant", avatar="🤖"):
            # Main message
            st.markdown(msg["content"], unsafe_allow_html=True)

            # NEW: Reasoning steps (show if toggle is enabled)
            if st.session_state.show_reasoning and msg.get("reasoning_steps"):
                with st.expander("🧠 Reasoning & Execution Steps", expanded=False):
                    render_reasoning_steps(msg["reasoning_steps"])

            # SQL query
            if msg.get("sql"):
                with st.expander("🔍 SQL Query", expanded=False):
                    st.code(msg["sql"], language="sql")

            # Visualizations
            if msg.get("fig_json"):
                with st.expander("📊 Visualization", expanded=True):
                    render_plotly_chart(msg["fig_json"])

def render_chat_interface():
    """Render main chat interface"""

    # Compact header
    st.markdown("""
    <div style='padding: 1rem 0 0.5rem 0; border-bottom: 1px solid #334155;'>
        <h2 style='color: #818cf8; margin: 0; font-size: 1.5rem;'>💬 BioInsight Chat</h2>
    </div>
    """, unsafe_allow_html=True)

    # Sidebar
    with st.sidebar:
        # User info
        st.markdown(f"""
        <div style='
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 1rem;
            border-radius: 0.75rem;
            margin-bottom: 1rem;
            text-align: center;
        '>
            <div style='font-size: 2rem; margin-bottom: 0.25rem;'>👤</div>
            <div style='color: white; font-weight: 600;'>{st.session_state.username}</div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("### 💡 Example Queries")

        examples = [
            "Compare EGFR in KRAS-mutant cell lines",
            "Show TP53 expression in tumor vs normal",
            "Which genes are upregulated in tumor?",
            "EGFR levels in mutant cells"
        ]

        for example in examples:
            if st.button(example, key=f"ex_{hash(example)}", use_container_width=True):
                st.session_state.pending_message = example
                st.rerun()

        st.divider()

        # NEW: Reasoning toggle
        st.markdown("### ⚙️ Settings")
        st.session_state.show_reasoning = st.toggle(
            "Show Reasoning Steps",
            value=st.session_state.show_reasoning,
            help="Display detailed planning and execution steps for each query"
        )

        st.divider()

        # Stats
        query_count = len([m for m in st.session_state.messages if m.get('is_user')])
        st.metric("Queries", query_count)

        st.divider()

        # Export Report
        if query_count > 0:
            st.markdown("### 📄 Export")
            if st.button("📥 Download PDF Report", use_container_width=True, type="primary"):
                with st.spinner("Generating PDF report..."):
                    pdf_buffer = generate_pdf_report()
                    if pdf_buffer:
                        st.download_button(
                            label="💾 Save Report",
                            data=pdf_buffer,
                            file_name=f"bioinsight_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                            mime="application/pdf",
                            use_container_width=True
                        )
                        st.success("✅ Report generated successfully!")

            st.divider()

        if st.button("🚪 Logout", use_container_width=True, type="secondary"):
            logout()
            st.rerun()

    # Chat area
    if len(st.session_state.messages) == 0:
        st.markdown("""
        <div style='text-align: center; padding: 3rem 2rem;'>
            <div style='font-size: 3rem; margin-bottom: 1rem;'>🔬</div>
            <h3 style='color: #e2e8f0; margin-bottom: 0.5rem;'>Start Your Research</h3>
            <p style='color: #94a3b8; max-width: 500px; margin: 0 auto;'>
                Ask questions about gene expression, mutations, or biomedical data in natural language.
            </p>
        </div>
        """, unsafe_allow_html=True)
    else:
        for msg in st.session_state.messages:
            render_message(msg)

    # Check for pending message
    if hasattr(st.session_state, 'pending_message'):
        user_message = st.session_state.pending_message
        del st.session_state.pending_message
        process_message(user_message)
        st.rerun()

    # Chat input
    user_input = st.chat_input("Ask about genes, mutations, expression...")

    if user_input:
        process_message(user_input)
        st.rerun()

def process_message(user_input: str):
    """Process user message"""
    # Add user message
    st.session_state.messages.append({
        "content": user_input,
        "is_user": True,
        "timestamp": datetime.now().isoformat()
    })

    # Show user message
    with st.chat_message("user", avatar="👤"):
        st.markdown(user_input)

    # Get response
    with st.chat_message("assistant", avatar="🤖"):
        with st.spinner("⏳ Analyzing your query..." + (" (reasoning mode enabled)" if st.session_state.show_reasoning else "")):
            response_data = send_message(user_input)

        message = response_data.get("message", "No response")
        sql = response_data.get("sql")
        fig_json = response_data.get("fig_json")
        reasoning_steps = response_data.get("reasoning_steps", [])

        # Display message
        st.markdown(message, unsafe_allow_html=True)

        # Display reasoning if available and toggle is enabled
        if st.session_state.show_reasoning and reasoning_steps:
            with st.expander("🧠 Reasoning & Execution Steps", expanded=False):
                render_reasoning_steps(reasoning_steps)

        # Display SQL
        if sql:
            with st.expander("🔍 SQL Query", expanded=False):
                st.code(sql, language="sql")

        # Display visualization
        if fig_json:
            with st.expander("📊 Visualization", expanded=True):
                render_plotly_chart(fig_json)

        # Add to history
        st.session_state.messages.append({
            "content": message,
            "is_user": False,
            "sql": sql,
            "fig_json": fig_json,
            "reasoning_steps": reasoning_steps,
            "timestamp": datetime.now().isoformat()
        })

# ============================================================================
# Main App
# ============================================================================

def main():
    """Main application"""
    st.set_page_config(
        page_title="BioInsight AI",
        page_icon="🧬",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    # Modern dark theme CSS
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    /* Global */
    * {
        font-family: 'Inter', sans-serif;
    }

    html, body, [class*="css"] {
        background-color: #0f172a;
        color: #e2e8f0;
    }

    /* Hide Streamlit elements */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}

    /* Main container */
    .main {
        background-color: #0f172a;
        padding: 1rem;
    }

    .block-container {
        max-width: 1200px;
        padding-top: 2rem;
    }

    /* Sidebar */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1e293b 0%, #0f172a 100%);
        border-right: 1px solid #334155;
    }

    /* Buttons */
    .stButton button {
        background: #334155;
        color: #e2e8f0;
        border: 1px solid #475569;
        border-radius: 0.5rem;
        font-weight: 500;
        transition: all 0.2s;
    }

    .stButton button:hover {
        background: #475569;
        border-color: #64748b;
    }

    .stButton button[kind="primary"] {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border: none;
        color: white;
    }

    .stButton button[kind="primary"]:hover {
        opacity: 0.9;
    }

    /* Inputs */
    .stTextInput input {
        background-color: #1e293b;
        border: 1px solid #475569;
        color: #e2e8f0;
        border-radius: 0.5rem;
    }

    .stTextInput input:focus {
        border-color: #667eea;
        box-shadow: 0 0 0 2px rgba(102, 126, 234, 0.2);
    }

    .stTextInput label {
        color: #e2e8f0;
        font-weight: 500;
    }

    /* Chat input */
    .stChatInput input {
        background-color: #1e293b;
        border: 1px solid #475569;
        color: #e2e8f0;
    }

    /* Chat messages */
    .stChatMessage {
        background: #1e293b;
        border: 1px solid #334155;
        border-radius: 0.75rem;
        padding: 1rem;
    }

    /* Expander */
    .streamlit-expanderHeader {
        background-color: #334155;
        border: 1px solid #475569;
        border-radius: 0.5rem;
        color: #e2e8f0;
    }

    .streamlit-expanderContent {
        background-color: #1e293b;
        border: 1px solid #475569;
        border-top: none;
    }

    /* Code */
    code {
        background-color: #0f172a !important;
        color: #10b981 !important;
        border: 1px solid #334155;
        border-radius: 0.375rem;
        padding: 0.125rem 0.25rem;
    }

    pre {
        background-color: #0f172a !important;
        border: 1px solid #334155;
        border-radius: 0.5rem;
        padding: 1rem;
    }

    pre code {
        border: none;
        padding: 0;
    }

    /* Tables */
    table {
        background-color: #1e293b;
        border: 1px solid #334155;
        color: #e2e8f0;
    }

    th {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white !important;
        padding: 0.75rem;
    }

    td {
        border-bottom: 1px solid #334155;
        padding: 0.75rem;
    }

    tr:hover td {
        background-color: #334155;
    }

    /* Metrics */
    [data-testid="stMetricValue"] {
        color: #818cf8;
        font-size: 1.5rem;
    }

    /* Alerts */
    .stSuccess {
        background-color: rgba(16, 185, 129, 0.1);
        border: 1px solid #10b981;
        color: #10b981;
    }

    .stError {
        background-color: rgba(239, 68, 68, 0.1);
        border: 1px solid #ef4444;
        color: #ef4444;
    }

    .stWarning {
        background-color: rgba(251, 191, 36, 0.1);
        border: 1px solid #fbbf24;
        color: #fbbf24;
    }

    /* Scrollbar */
    ::-webkit-scrollbar {
        width: 8px;
        height: 8px;
    }

    ::-webkit-scrollbar-track {
        background: #1e293b;
    }

    ::-webkit-scrollbar-thumb {
        background: #475569;
        border-radius: 4px;
    }

    ::-webkit-scrollbar-thumb:hover {
        background: #64748b;
    }
    </style>
    """, unsafe_allow_html=True)

    # Route
    if st.session_state.authenticated:
        render_chat_interface()
    else:
        render_login_page()

if __name__ == "__main__":
    main()
