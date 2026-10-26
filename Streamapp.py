import streamlit as st
from openai import OpenAI
import httpx
import sqlite3
from datetime import datetime

# 1. Page Configuration
st.set_page_config(page_title="Multi-User Free AI Chatbot", page_icon="🤖")
st.title("🤖 Shared AI Assistant (Isolated Workspace)")

# 2. Secure TOML Secret Management (Uses your single shared key)
if "OPENROUTER_API_KEY" in st.secrets:
    api_key = st.secrets["OPENROUTER_API_KEY"]
else:
    st.error("🔑 API Key missing! Please add 'OPENROUTER_API_KEY' to your Streamlit secrets.")
    st.stop()

# 3. Database Utilities (Updated to support user isolation tags)
def init_db():
    conn = sqlite3.connect("chat_history.db")
    c = conn.cursor()
    # Added 'username' column to map messages to specific users
    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            timestamp TEXT,
            role TEXT,
            content TEXT
        )
    ''')
    conn.commit()
    conn.close()

def save_message_to_db(username, role, content):
    conn = sqlite3.connect("chat_history.db")
    c = conn.cursor()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute(
        "INSERT INTO messages (username, timestamp, role, content) VALUES (?, ?, ?, ?)", 
        (username, timestamp, role, content)
    )
    conn.commit()
    conn.close()

def load_chat_history(username):
    conn = sqlite3.connect("chat_history.db")
    c = conn.cursor()
    # Filter rows based strictly on the current active user profile
    c.execute("SELECT role, content FROM messages WHERE username = ? ORDER BY id ASC", (username,))
    rows = c.fetchall()
    conn.close()
    return [{"role": row[0], "content": row[1]} for row in rows]

def clear_user_db(username):
    conn = sqlite3.connect("chat_history.db")
    c = conn.cursor()
    c.execute("DELETE FROM messages WHERE username = ?", (username,))
    conn.commit()
    conn.close()

init_db()

# 4. Sidebar Interface Controls (User Profiles & Model Selector)
with st.sidebar:
    st.header("👤 User Workspace")
    
    # Dynamic profile separator - switching names changes the database context instantly
    current_user = st.text_input("Enter Your Name/Profile ID", value="DefaultUser").strip()
    
    if not current_user:
        st.warning("Please type a workspace name to unlock chat.")
        st.stop()
        
    st.success(f"Workspace: **{current_user}** active.")
    
    st.header("Configuration")
    model_choice = st.selectbox(
        "Choose Free Route",
        options=["openrouter/free", "google/gemini-2.5-flash:free"]
    )
    
    st.header("Database Controls")
    if st.button(f"🗑️ Clear {current_user}'s History", type="primary"):
        clear_user_db(current_user)
        st.session_state.messages = []
        st.success(f"Purged history for {current_user}!")
        st.rerun()

# 5. Load Stored Conversations matching the active profile context
# Reset session tracking if the active user changes
if "last_user" not in st.session_state or st.session_state.last_user != current_user:
    st.session_state.last_user = current_user
    st.session_state.messages = load_chat_history(current_user)

# 6. Render Current User's Chat Messages
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 7. Core Prompt Feeder & Action Framework
if prompt := st.chat_input("What is on your mind?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    save_message_to_db(current_user, "user", prompt)
    
    with st.chat_message("user"):
        st.markdown(prompt)

    # 8. API Engine Run with Content-Type and HTML Verification Interceptors
    with st.chat_message("assistant"):
        try:
            http_client = httpx.Client(timeout=httpx.Timeout(45.0, connect=10.0))
            
            client = OpenAI(
                base_url="https://openrouter.ai",
                api_key=api_key,
                http_client=http_client,
                default_headers={
                    "Accept": "application/json",
                    "HTTP-Referer": "http://localhost:8501", 
                    "X-Title": "Streamlit Free App"      
                }
            )
            
            response = client.chat.completions.create(
                model=model_choice,
                messages=[
                    {"role": m["role"], "content": m["content"]}
                    for m in st.session_state.messages
                ],
                stream=True
            )
            
            def response_generator():
                for chunk in response:
                    if isinstance(chunk, str) and ("<!DOCTYPE" in chunk or "<html" in chunk):
                        raise ValueError("OpenRouter returned an HTML error gateway page instead of structural AI tokens.")
                        
                    if hasattr(chunk, 'choices') and chunk.choices and len(chunk.choices) > 0:
                        first_choice = chunk.choices[0]
                        delta = first_choice.get('delta', None) if isinstance(first_choice, dict) else getattr(first_choice, 'delta', None)
                        if delta:
                            content = delta.get('content', '') if isinstance(delta, dict) else getattr(delta, 'content', '')
                            if content:
                                yield content

            # Stream out the text response live
            full_response = st.write_stream(response_generator())
            
            st.session_state.messages.append({"role": "assistant", "content": full_response})
            save_message_to_db(current_user, "assistant", full_response)
            
        except Exception as e:
            error_msg = str(e)
            if "<!DOCTYPE" in error_msg or "HTML" in error_msg:
                st.error("⚠️ **OpenRouter Connection Blocked (HTML Gateway Error)**")
                st.info("Switch the dropdown route in the sidebar to bypass the block.")
            else:
                st.error(f"Execution Error: {error_msg}")
