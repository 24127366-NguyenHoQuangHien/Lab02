import time
import streamlit as st
import pyrebase
import firebase_admin
import requests
from firebase_admin import credentials, firestore
from firebase_admin import auth as admin_auth
from collections import deque
from datetime import datetime, timezone
from ollama import Client
from streamlit_extras.stylable_container import stylable_container

st.set_page_config(page_title="Mini-travel application", page_icon="🌏", layout="wide")

MODEL = "gpt-oss:20b"
client = Client(host='https://ojtgl-34-125-220-233.a.free.pinggy.link')

# FIREBASE SETUP
@st.cache_resource
def get_firebase_clients():
    firebase_cfg = st.secrets["firebase_client"]
    firebase_app = pyrebase.initialize_app(firebase_cfg)
    auth = firebase_app.auth()
    
    if not firebase_admin._apps:
        cred = credentials.Certificate(dict(st.secrets["firebase_admin"]))
        firebase_admin.initialize_app(cred)
    db = firestore.client()
    return auth, db

auth, db = get_firebase_clients()


# LLM FUNCTIONS
def generate_itinerary(origin, destination, start_date, end_date, interests, pace):
    """Generate travel itinerary using LLM"""
    prompt = f"""Generate a detailed day-by-day travel itinerary for a trip.

From: {origin}
To: {destination}
Dates: {start_date} to {end_date}
Interests: {', '.join(interests)}
Pace: {pace}

Please provide a structured itinerary with:
- Day-by-day breakdown
- Morning, Afternoon, and Evening activities
- Short explanations for each activity
- Recommendations based on the selected interests

Format the response in a clear, easy-to-read manner."""

    try:
        response = client.chat(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}]
        )
        return response["message"]["content"]
    except requests.RequestException as e:
        return f"❌ Lỗi khi gọi Ollama API: {e}"

def ollama_chat(history_messages: list[dict]):
    """General chat with Ollama"""
    try:
        response = client.chat(
            model=MODEL,
            messages=history_messages
        )
        return response['message']['content']
    except requests.RequestException as e:
        return f"❌ Lỗi kết nối: {e}"


# FIREBASE STORAGE FUNCTIONS
def save_itinerary(uid: str, itinerary_text: str, metadata: dict):
    """Save itinerary to Firebase"""
    doc = {
        "content": itinerary_text,
        "metadata": metadata,
        "timestamp": datetime.now(timezone.utc)
    }
    db.collection("itineraries").document(uid).collection("plans").add(doc)

def load_itineraries(uid: str, limit: int = 5):
    """Load user's itinerary history"""
    q = (db.collection("itineraries").document(uid)
         .collection("plans")
         .order_by("timestamp", direction=firestore.Query.DESCENDING)
         .limit(limit))
    return [d.to_dict() for d in q.stream()]

def save_message(uid: str, role: str, content: str):
    """Save chat message to Firebase"""
    doc = {
        "role": role,
        "content": content,
        "ts": datetime.now(timezone.utc)
    }
    db.collection("chats").document(uid).collection("messages").add(doc)

def load_last_messages(uid: str, limit: int = 8):
    """Load chat history"""
    q = (db.collection("chats").document(uid)
         .collection("messages")
         .order_by("ts", direction=firestore.Query.DESCENDING)
         .limit(limit))
    docs = list(q.stream())
    docs.reverse()
    out = []
    for d in docs:
        data = d.to_dict()
        out.append({"role": data.get("role", "assistant"), "content": data.get("content", "")})
    return out


# SESSION STATE INITIALIZATION
if "user" not in st.session_state:
    st.session_state.user = None
if "messages" not in st.session_state:
    st.session_state.messages = deque([
        {"role": "assistant", "content": "Xin chào 👋! Tôi là trợ lý du lịch AI. Tôi có thể giúp gì cho bạn?"}
    ], maxlen=8)
if "chat_open" not in st.session_state:
    st.session_state.chat_open = False
if "show_signup" not in st.session_state:
    st.session_state.show_signup = False
if "show_login" not in st.session_state:
    st.session_state.show_login = True
if "current_itinerary" not in st.session_state:
    st.session_state.current_itinerary = None

# LOGIN / SIGNUP FORMS
def login_form():
    st.markdown("<h3 style='text-align: center;'>🔐 Đăng nhập</h3>", unsafe_allow_html=True)
    with st.form("login_form", clear_on_submit=False):
        email = st.text_input("Email", key="email_login")
        password = st.text_input("Mật khẩu", type="password", key="password_login")
        
        col1, _, col2 = st.columns([1, 0.5, 1])
        with col1:
            login = st.form_submit_button("Đăng nhập", use_container_width=True)
        with col2:
            goto_signup = st.form_submit_button("Đăng ký", use_container_width=True)
        
        if goto_signup:
            st.session_state.show_signup = True
            st.session_state.show_login = False
            st.rerun()
        
        if login:
            try:
                user = auth.sign_in_with_email_and_password(email, password)
                st.session_state.user = {
                    "email": email,
                    "uid": user["localId"],
                    "idToken": user["idToken"]
                }
                # Load chat history
                msgs = load_last_messages(st.session_state.user["uid"], limit=8)
                if msgs:
                    st.session_state.messages = deque(msgs, maxlen=8)
                st.success("✅ Đăng nhập thành công!")
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"❌ Đăng nhập thất bại: {e}")

def signup_form():
    st.markdown("<h3 style='text-align: center;'>🆕 Đăng ký tài khoản</h3>", unsafe_allow_html=True)
    with st.form("signup_form", clear_on_submit=False):
        email = st.text_input("Email", key="email_signup")
        password = st.text_input("Mật khẩu (≥6 ký tự)", type="password", key="password_signup")
        
        col1, _, col2 = st.columns([1, 0.5, 1])
        with col1:
            signup = st.form_submit_button("Tạo tài khoản", use_container_width=True)
        with col2:
            goto_login = st.form_submit_button("Đã có tài khoản?", use_container_width=True)
        
        if goto_login:
            st.session_state.show_signup = False
            st.session_state.show_login = True
            st.rerun()
        
        if signup:
            try:
                auth.create_user_with_email_and_password(email, password)
                st.success("✅ Tạo tài khoản thành công! Vui lòng đăng nhập.")
                time.sleep(2)
                st.session_state.show_signup = False
                st.session_state.show_login = True
                st.rerun()
            except Exception as e:
                st.error(f"❌ Đăng ký thất bại: {e}")

# CHAT DIALOG
@st.dialog("💬 Trợ lý AI", width="large")
def chat_dialog():
    if not st.session_state.user:
        st.warning("⚠️ Bạn cần đăng nhập để sử dụng chat.")
        return
    
    chat_body = st.container(height=500, border=True)
    
    # Render chat history
    with chat_body:
        for msg in list(st.session_state.messages):
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
    
    # Chat input
    user_input = st.chat_input("Nhập tin nhắn...", key="dialog_input")
    if user_input:
        # Add user message
        st.session_state.messages.append({"role": "user", "content": user_input})
        save_message(st.session_state.user["uid"], "user", user_input)
        
        # Get AI response
        reply = ollama_chat(list(st.session_state.messages))
        st.session_state.messages.append({"role": "assistant", "content": reply})
        save_message(st.session_state.user["uid"], "assistant", reply)
        
        st.rerun()


# MAIN UI
st.markdown("<h1 style='text-align: center; color: #0E86D4;'>🌏 Mini-travel application</h1>", unsafe_allow_html=True)
st.caption("<p style='text-align: center;'>Plan your dream trip with AI-powered itineraries</p>", unsafe_allow_html=True)

# Login/Signup Section
if not st.session_state.user:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.session_state.show_signup:
            signup_form()
        else:
            login_form()
    st.stop()

# LOGGED IN INTERFACE
# Top bar
col1, col2 = st.columns([3, 1])
with col1:
    st.success(f"👤 {st.session_state.user['email']}")
with col2:
    if st.button("🚪 Đăng xuất", use_container_width=True):
        st.session_state.user = None
        st.session_state.current_itinerary = None
        st.session_state.messages = deque([
            {"role": "assistant", "content": "Xin chào 👋! Tôi là trợ lý du lịch AI."}
        ], maxlen=8)
        st.rerun()

st.divider()

# Main layout: Sidebar + Content
with st.sidebar:
    st.header("🧳 Trip Details")
    
    with st.form("trip_form"):
        origin = st.text_input("🛫 Origin City", placeholder="e.g., Ho Chi Minh City")
        destination = st.text_input("🛬 Destination City", placeholder="e.g., Da Nang")
        
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("📅 Start Date")
        with col2:
            end_date = st.date_input("📅 End Date")
        
        interests = st.multiselect(
            "🎯 Interests",
            ["Food", "Museums", "Nature", "Nightlife", "Shopping", "Adventure", "Culture", "Beach"],
            default=["Food", "Nature"]
        )
        
        pace = st.radio("⏱️ Travel Pace", ["Relaxed", "Normal", "Tight"], index=1)
        
        submit = st.form_submit_button("✨ Generate Itinerary", use_container_width=True)
        
        if submit:
            if not origin or not destination:
                st.error("⚠️ Vui lòng nhập đầy đủ thông tin!")
            elif start_date >= end_date:
                st.error("⚠️ Ngày kết thúc phải sau ngày bắt đầu!")
            else:
                with st.spinner("🔄 Đang tạo lịch trình AI..."):
                    itinerary = generate_itinerary(
                        origin, destination, start_date, end_date, interests, pace
                    )
                    st.session_state.current_itinerary = {
                        "content": itinerary,
                        "metadata": {
                            "origin": origin,
                            "destination": destination,
                            "start_date": str(start_date),
                            "end_date": str(end_date),
                            "interests": interests,
                            "pace": pace
                        }
                    }
                    save_itinerary(
                        st.session_state.user["uid"],
                        itinerary,
                        st.session_state.current_itinerary["metadata"]
                    )
                    st.success("✅ Lịch trình đã được tạo!")
                    st.rerun()

# Main content area
if st.session_state.current_itinerary:
    st.subheader("🗓️ Your AI-Generated Itinerary")
    meta = st.session_state.current_itinerary["metadata"]
    
    # Display trip info
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown("**From**") # Dùng markdown để in đậm nhãn
        st.write(meta["origin"])  # Dùng st.write để in giá trị
    with col2:
        st.markdown("**To**")
        st.write(meta["destination"])
    with col3:
        st.markdown("**Duration**")
        st.write(f"{meta['start_date']} → {meta['end_date']}")
    with col4:
        st.markdown("**Pace**")
        st.write(meta["pace"])

    st.divider()
    
    # Display itinerary
    st.markdown(
        f"<div style='background:#f8f9fa; padding:20px; border-radius:10px; "
        f"line-height:1.8; font-size:16px;'>{st.session_state.current_itinerary['content']}</div>",
        unsafe_allow_html=True
    )
else:
    st.info("👈 Nhập thông tin chuyến đi ở sidebar để bắt đầu!")

# History section
st.divider()
with st.expander("📜 Lịch sử lịch trình"):
    history = load_itineraries(st.session_state.user["uid"], limit=5)
    if history:
        for idx, item in enumerate(history):
            ts = item.get("timestamp", "")
            meta = item.get("metadata", {})
            content = item.get("content", "")
            
            st.markdown(f"**#{idx+1} | {meta.get('origin', 'N/A')} → {meta.get('destination', 'N/A')}**")
            st.caption(f"📅 {ts} | Pace: {meta.get('pace', 'N/A')}")
            with st.expander("Xem chi tiết"):
                st.markdown(content)
            st.divider()
    else:
        st.info("Chưa có lịch sử lịch trình.")

# Floating chat button
st.markdown('<div id="fab-anchor"></div>', unsafe_allow_html=True)
with stylable_container(
    "fab-button",
    css_styles="""
    button {
        background-color: #0E86D4;
        color: white;
        border-radius: 50%;
        width: 60px !important;
        height: 60px !important;
        font-size: 24px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    }
    button:hover {
        background-color: #0b6aa0;
        transform: scale(1.05);
    }
    """,
):
    if st.button("💬", key="open_chat_fab", help="Mở chat"):
        st.session_state.chat_open = True
        st.rerun()

if st.session_state.chat_open:
    chat_dialog()


# CUSTOM CSS
st.markdown("""
<style>
/* Tổng thể */
html, body, .stApp {
    background-color: #0f1115 !important;
    color: #EAEAEA !important;
}
            
/* Sidebar */
[data-testid="stSidebar"], section[data-testid="stSidebar"] {
    background-color: #1b1d22 !important;
    color: #EAEAEA !important;
    border-right: 1px solid #2b2d33 !important;
}

/* Phần main view */
[data-testid="stAppViewContainer"],
[data-testid="stVerticalBlock"],
[data-testid="stHorizontalBlock"],
[data-testid="stMainBlockContainer"],
.block-container,
.main {
    background-color: #16181d !important;
    color: #FFFFFF !important;
}

/* Markdown, nội dung text */
.stMarkdown, [data-testid="stMarkdownContainer"], .markdown, .stText, p, li, span {
    background-color: transparent !important;
    color: #F5F5F5 !important;
}

/* Card, expander, container phụ */
div[data-testid="stExpander"],
div[data-testid="stExpanderContent"],
div[data-testid="stExpanderDetails"],
div[data-testid="stVerticalBlock"] > div {
    background-color: #1c1f26 !important;
    color: #FFFFFF !important;
    border-radius: 10px !important;
    border: 1px solid #2e323a !important;
}

/* === SỬA LỖI METRIC PHÓNG TO === */
/* Ghi đè rule ở trên, reset style cho các cột (stMetric) */
[data-testid="stHorizontalBlock"] > [data-testid="stVerticalBlock"] > div {
    background-color: transparent !important;
    border: none !important;
    border-radius: 0 !important;
}
/* ================================ */

/* Bảng */
table, tr, td, th {
    background-color: #20242b !important;
    color: #FFFFFF !important;
    border: 1px solid #444 !important;
}

/* Input và button */
input, textarea, select {
    background-color: #1E1E1E !important;
    color: #FFFFFF !important;
    border: 1px solid #333 !important;
    border-radius: 6px !important;
}

button, .stButton>button {
    background-color: #2c2f36 !important;
    color: #FFFFFF !important;
    border: 1px solid #3a3f48 !important;
    border-radius: 8px !important;
    transition: 0.2s;
}
button:hover, .stButton>button:hover {
    background-color: #3a3f48 !important;
}

/* Header, title */
h1, h2, h3, h4, h5, h6 {
    color: #00BFFF !important;
}

/* Link */
a, a:visited {
    color: #1E90FF !important;
}

/* Scrollbar */
::-webkit-scrollbar {
    width: 8px;
}
::-webkit-scrollbar-track {
    background: #15171b;
}
::-webkit-scrollbar-thumb {
    background: #3c3f46;
    border-radius: 4px;
}
::-webkit-scrollbar-thumb:hover {
    background: #5a5f68;
}

/* Fix đặc biệt cho khối markdown sinh tự động */
[data-testid="stMarkdownContainer"] > div {
    background-color: transparent !important;
    color: #FFFFFF !important;
}

/* Xử lý khối trắng Streamlit sinh ra sau expander */
section.main div[data-testid="stVerticalBlock"] > div:not([data-testid]),
section.main div[data-testid="stVerticalBlock"] > div > div:not([data-testid]) {
    background-color: transparent !important;
}

/* Xử lý trường hợp nền markdown bị reset */
[data-testid="stMarkdownContainer"] pre, code {
    background-color: #101216 !important;
    color: #00ffcc !important;
}
</style>
""", unsafe_allow_html=True)