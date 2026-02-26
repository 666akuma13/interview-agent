import streamlit as st
import anthropic
import json
import os
from datetime import datetime
import time
import hashlib
from fpdf import FPDF

# ════════════════════════════════════════════════════
# 1. INITIALIZATION & CLIENT
# ════════════════════════════════════════════════════
if "ANTHROPIC_API_KEY" in st.secrets:
    client = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
else:
    st.error("Missing ANTHROPIC_API_KEY. Please add it to your Streamlit Secrets.")
    st.stop()

RESULTS_FILE = "candidates.json"
QUESTION_BANK_FILE = "question_bank.json"
SCHEDULES_FILE = "schedules.json"
ADMIN_PASSWORD = "admin123" 

# ════════════════════════════════════════════════════
# 2. UTILITY FUNCTIONS
# ════════════════════════════════════════════════════

def chat_with_claude(system_prompt, chat_history):
    if not chat_history:
        chat_history = [{"role": "user", "content": "Let's begin."}]
    try:
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1500,
            system=system_prompt,
            messages=chat_history
        )
        return response.content[0].text
    except Exception as e:
        st.error(f"Claude API Error: {e}")
        return None

def load_all_candidates():
    if os.path.exists(RESULTS_FILE):
        try:
            with open(RESULTS_FILE, "r") as f:
                return json.load(f)
        except: return []
    return []

def load_question_bank():
    if os.path.exists(QUESTION_BANK_FILE):
        with open(QUESTION_BANK_FILE, "r") as f:
            return json.load(f)
    return {}

def save_question_bank(bank):
    with open(QUESTION_BANK_FILE, "w") as f:
        json.dump(bank, f, indent=2)

def load_schedules():
    if os.path.exists(SCHEDULES_FILE):
        with open(SCHEDULES_FILE, "r") as f:
            return json.load(f)
    return []

def save_schedules(schedules):
    with open(SCHEDULES_FILE, "w") as f:
        json.dump(schedules, f, indent=2)

def generate_report(transcript, jd_data, round_name="Technical"):
    formatted = "\n".join([f"{msg['role'].upper()}: {msg['content']}" for msg in transcript])
    system = "You are a senior hiring manager. Evaluate transcripts objectively."
    prompt = f"Evaluate this {round_name} interview for {jd_data['job_title']}.\nTranscript:\n{formatted}"
    return chat_with_claude(system, [{"role": "user", "content": prompt}])

def generate_pdf(candidate_name, role, date, report_text, round_name="Interview"):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, "Interview Evaluation Report", ln=True, align="C")
    pdf.set_font("Arial", "", 12)
    pdf.multi_cell(0, 10, report_text.encode('latin-1', 'replace').decode('latin-1'))
    pdf_path = f"/tmp/{candidate_name}_report.pdf"
    pdf.output(pdf_path)
    return pdf_path

def save_candidate_result(candidate_name, jd_data, report, transcript, round_name, anticheat_flags):
    all_results = load_all_candidates()
    new_entry = {
        "candidate_name": candidate_name,
        "role": jd_data["job_title"],
        "rounds": [{"round_name": round_name, "report": report, "transcript": transcript, "anticheat_flags": anticheat_flags}]
    }
    all_results.append(new_entry)
    with open(RESULTS_FILE, "w") as f:
        json.dump(all_results, f, indent=2)

def analyze_anticheat(conversation_log, response_times):
    flags = []
    for i, msg in enumerate(conversation_log):
        if msg["role"] == "candidate":
            word_count = len(msg["content"].split())
            if word_count > 200:
                flags.append(f"Q{i}: Long response ({word_count} words)")
    return flags if flags else ["No suspicious activity detected"]

# ════════════════════════════════════════════════════
# 3. THE INTERVIEW AGENT CLASS
# ════════════════════════════════════════════════════



class InterviewAgent:
    def __init__(self, jd_data, candidate_name, custom_questions, round_name):
        self.jd_data = jd_data
        self.candidate_name = candidate_name
        self.custom_questions = custom_questions
        self.round_name = round_name
        self.chat_history = []
        self.conversation_log = []
        self.response_times = {}
        self.question_count = 0
        self.max_questions = 10
        self.last_question_time = time.time()
        
        self.system_prompt = self._generate_system_prompt()
        self._initialize_agent()

    def _generate_system_prompt(self):
        return f"You are an expert interviewer for a {self.round_name} role. The candidate is {self.candidate_name}."

    def _initialize_agent(self):
        if not self.chat_history:
            self.chat_history.append({"role": "user", "content": "Start the interview."})
        response = chat_with_claude(self.system_prompt, self.chat_history)
        if response:
            self.chat_history.append({"role": "assistant", "content": response})
            self.conversation_log.append({"role": "interviewer", "content": response})

    def respond(self, candidate_message):
        self.question_count += 1
        self.conversation_log.append({"role": "candidate", "content": candidate_message})
        self.chat_history.append({"role": "user", "content": candidate_message})
        
        response = chat_with_claude(self.system_prompt, self.chat_history)
        if response:
            self.chat_history.append({"role": "assistant", "content": response})
            self.conversation_log.append({"role": "interviewer", "content": response})
        return response

    def is_interview_complete(self):
        return self.question_count >= self.max_questions

    def get_full_transcript(self):
        return self.conversation_log

    def get_response_times(self):
        return self.response_times

# ════════════════════════════════════════════════════
# 4. APP UI LOGIC
# ════════════════════════════════════════════════════

st.set_page_config(page_title="AI Interview Agent", page_icon="🤖", layout="wide")

# Determine Mode
token_from_url = st.query_params.get("token", None)
mode = st.query_params.get("mode", None)

if token_from_url or mode == "candidate":
    # CANDIDATE UI CODE...
    st.title("Interview Session")
    if "agent" not in st.session_state:
        if st.button("Begin Interview"):
            jd_data = {"job_title": "Software Engineer", "technical_skills": [], "experience_required": ""}
            st.session_state.agent = InterviewAgent(jd_data, "Candidate", [], "Technical")
            st.session_state.messages = [{"role": "assistant", "content": "Welcome! Let's start."}]
            st.rerun()
    else:
        # Chat loop
        for msg in st.session_state.get("messages", []):
            with st.chat_message(msg["role"]): st.write(msg["content"])
        
        user_input = st.chat_input("Your answer...")
        if user_input:
            st.session_state.messages.append({"role": "user", "content": user_input})
            res = st.session_state.agent.respond(user_input)
            st.session_state.messages.append({"role": "assistant", "content": res})
            st.rerun()

else:
    # ADMIN UI CODE...
    if not st.session_state.get("admin_logged_in"):
        st.title("Admin Login")
        pwd = st.text_input("Password", type="password")
        if st.button("Login") and pwd == ADMIN_PASSWORD:
            st.session_state.admin_logged_in = True
            st.rerun()
    else:
        st.sidebar.title("Admin Panel")
        if st.sidebar.button("Logout"):
            st.session_state.admin_logged_in = False
            st.rerun()
        st.write("Welcome to the Admin Dashboard. Select an option from the sidebar.")
