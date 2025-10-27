# Bio Gene Expression Chatbot - Streamlit UI

This directory contains the Streamlit web interface for the Bio Gene Expression Database chatbot.

## 📁 Contents

- `bio_chatbot_with_login.py` - Main Streamlit application
- `bio_gene_expression.db` - SQLite database with gene expression data

## 🚀 Quick Start

### 1. Start the FastAPI Backend

```bash
# From the project root directory
uvicorn main:app --reload
```

**Expected output**:
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

### 2. Start the Streamlit UI

```bash
# From the project root directory
streamlit run NSLC/bio_chatbot_with_login.py
```

**Expected output**:
```
You can now view your Streamlit app in your browser.
Local URL: http://localhost:8501
```

### 3. Login

Open your browser to `http://localhost:8501` and login with your credentials.

**Default test credentials** (if you have them set up):
- Email: `test@example.com`
- Password: `testpass123`

## 💡 Features

### ✅ Authentication
- JWT token-based login
- Secure WebSocket connection
- Session management

### ✅ Chat Interface
- Natural language queries
- Real-time responses via WebSocket
- Message history

### ✅ SQL Query Display
- View generated SQL queries
- Syntax highlighting
- Collapsible query view

### ✅ Visualizations
- Automatic Plotly chart rendering
- Interactive plots (zoom, pan, hover)
- Multiple charts support

### ✅ Example Queries
- Pre-loaded biomedical query examples
- One-click query insertion
- Domain-specific suggestions

## 📊 Example Queries

Try these queries in the chat:

1. **Gene Expression Comparison**
   ```
   Compare EGFR in KRAS-mutant cell lines
   ```

2. **Tumor vs Normal Analysis**
   ```
   Show TP53 expression in tumor vs normal
   ```

3. **Differential Expression**
   ```
   Which genes are upregulated in tumor?
   ```

4. **Mutation-Specific Queries**
   ```
   EGFR levels in mutant cells
   ```

5. **Fold Change Analysis**
   ```
   Genes with log2 fold change > 1 in tumor
   ```

## 🔧 Configuration

### Environment Variables

Create a `.env` file in the project root (or use existing one):

```bash
# API Configuration
API_BASE_URL=http://localhost:8000
WS_BASE_URL=ws://localhost:8000

# Database (backend uses this)
QDRANT_ENDPOINT=https://your-qdrant-instance.com
QDRANT_API_KEY=your_api_key

# Azure OpenAI (backend uses this)
AZURE_OPENAI_ENDPOINT=https://your-instance.openai.azure.com/
AZURE_OPENAI_KEY=your_azure_key
```

### Streamlit Configuration (Optional)

Create `.streamlit/config.toml`:

```toml
[theme]
primaryColor = "#667eea"
backgroundColor = "#FFFFFF"
secondaryBackgroundColor = "#F0F2F6"
textColor = "#262730"

[server]
port = 8501
enableCORS = false
enableXsrfProtection = true
```

## 📦 Dependencies

The app requires these Python packages (already in `requirements.txt`):

```
streamlit>=1.28.0
websockets>=11.0
plotly>=5.17.0
pandas>=2.0.0
requests>=2.31.0
python-dotenv>=1.0.0
```

Install if needed:
```bash
pip install streamlit websockets plotly pandas requests python-dotenv
```

## 🏗️ Architecture

```
┌─────────────────┐          ┌──────────────────┐
│  Streamlit UI   │          │  FastAPI Backend │
│  (Port 8501)    │          │  (Port 8000)     │
└────────┬────────┘          └─────────┬────────┘
         │                             │
         │  1. POST /token (login)     │
         ├────────────────────────────>│
         │  2. Returns JWT token       │
         │<────────────────────────────┤
         │                             │
         │  3. WebSocket /wss?token=X  │
         ├────────────────────────────>│
         │  4. Send query message      │
         ├────────────────────────────>│
         │  5. Receive response        │
         │<────────────────────────────┤
         │     (message, sql, charts)  │
         │                             │
```

### WebSocket Message Format

**Client → Server**:
```json
{
  "message": "Compare EGFR in KRAS-mutant cell lines",
  "type": "QUERY"
}
```

**Server → Client**:
```json
{
  "message": "Results text...",
  "sql": "SELECT ... FROM ...",
  "fig_json": [{...plotly figure...}],
  "query_id": "abc123",
  "timestamp": "2025-10-21T12:00:00"
}
```

## 🐛 Troubleshooting

### Issue: "Connection refused" when opening Streamlit

**Solution**: Make sure the FastAPI backend is running:
```bash
uvicorn main:app --reload
```

### Issue: "Invalid credentials" on login

**Solution**: Create a test user in the database:
```bash
python scripts/create_test_user.py
```

Or use the existing user credentials from your database.

### Issue: No visualizations showing

**Solution**: Check that `fig_json` is in the response:
```python
# In browser console (F12), check Network → WS → Messages
```

The backend should return `fig_json` array with Plotly figure objects.

### Issue: "Module not found" errors

**Solution**: Install dependencies:
```bash
pip install -r requirements.txt
```

Or install missing packages individually:
```bash
pip install streamlit websockets plotly
```

## 📝 Code Structure

### Main Components

```python
# Authentication
login(email, password) → token
logout() → clear session

# WebSocket Communication
send_message(message) → response_data

# UI Rendering
render_login_page() → login form
render_chat_interface() → chat UI
render_plotly_chart(fig_json) → visualization
render_sql_query(sql) → code block

# Message Processing
process_message(user_input) → add to chat, get response
```

### Session State

```python
st.session_state = {
    "authenticated": bool,
    "token": str,
    "username": str,
    "messages": [
        {
            "content": str,
            "is_user": bool,
            "sql": str (optional),
            "fig_json": list (optional),
            "timestamp": str
        }
    ]
}
```

## 🎨 Customization

### Change Theme Colors

Edit the custom CSS in `bio_chatbot_with_login.py`:

```python
st.markdown("""
<style>
.stChatMessage {
    background-color: #f0f0f0;  /* Change background */
}
</style>
""", unsafe_allow_html=True)
```

### Add More Example Queries

Edit the `examples` list:

```python
examples = [
    "Your custom query 1",
    "Your custom query 2",
    # Add more...
]
```

### Change App Title/Icon

Edit `st.set_page_config()`:

```python
st.set_page_config(
    page_title="My Custom Title",
    page_icon="🔬",  # Change emoji
    layout="wide"
)
```

## 📚 Additional Resources

- [Streamlit Documentation](https://docs.streamlit.io/)
- [WebSockets Documentation](https://websockets.readthedocs.io/)
- [Plotly Python Documentation](https://plotly.com/python/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)

## 🆘 Support

If you encounter issues:

1. Check that both backend and frontend are running
2. Verify environment variables are set correctly
3. Check browser console for JavaScript errors
4. Check backend logs for WebSocket errors
5. Ensure your user account exists in the database

---

**Created**: 2025-10-21
**Version**: 1.0.0
**License**: Your License Here
