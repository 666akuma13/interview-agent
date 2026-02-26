import streamlit as st
import anthropic
import json
import os
from datetime import datetime
import time
import hashlib
import plotly.express as px
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

def load_all_candidates():
    if os.path.exists(RESULTS_FILE):
        try:
            with open(RESULTS_FILE, "r") as f: return json.load(f)
        except: return []
    return []

def load_question_bank():
    if os.path.exists(QUESTION_BANK_FILE):
        try:
            with open(QUESTION_BANK_FILE, "r") as f: return json.load(f)
        except: return {}
    return {}

def save_question_bank(bank):
    with open(QUESTION_BANK_FILE, "w") as f: json.dump(bank, f, indent=2)

def load_schedules():
    if os.path.exists(SCHEDULES_FILE):
        try:
            with open(SCHEDULES_FILE, "r") as f: return json.load(f)
        except: return []
    return []

def save_schedules(schedules):
    with open(SCHEDULES_FILE, "w") as f: json.dump(schedules, f, indent=2)

def generate_interview_token(candidate_name, role, round_name):
    raw = f"{candidate_name}_{role}_{round_name}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    return hashlib.md5(raw.encode()).hexdigest()[:10]

def extract_score(report_text):
    for line in report_text.split("\n"):
        if "Overall" in line and "/10" in line:
            try: return float(line.split(":")[1].strip().replace("/10", ""))
            except: return 0
    return 0

def extract_recommendation(report_text):
    for line in report_text.split("\n"):
        if "HIRE RECOMMENDATION" in line.upper():
            return line.split(":")[1].strip() if ":" in line else "N/A"
    return "N/A"

def extract_weaknesses(report_text):
    weaknesses = []
    capture = False
    for line in report_text.split("\n"):
        if "AREAS FOR IMPROVEMENT" in line.upper():
            capture = True; continue
        if capture:
            if line.strip().startswith("-"): weaknesses.append(line.strip("- ").strip())
            elif line.strip() == "" or "HIRE" in line.upper(): break
    return weaknesses

# ════════════════════════════════════════════════════
# 3. THE AGENTIC INTERVIEWER CLASS
# ════════════════════════════════════════════════════



class InterviewAgent:
    def __init__(self, jd_data, candidate_name, custom_questions=None, round_name="Technical"):
        self.jd_data = jd_data
        self.candidate_name = candidate_name
        self.round_name = round_name
        self.max_questions = 8  # Agent logic usually takes longer, so we cap at 8
        self.question_count = 0
        self.chat_history = []
        self.conversation_log = []
        
        # The Agent's "Persona" and "Reasoning Instructions"
        self.system_prompt = f"""You are an Advanced AI Interviewing Agent. 
        Current Round: {round_name} | Role: {jd_data.get('role', 'Software Engineer')}
        Required Skills: {jd_data.get('technical_skills', 'Python')}
        
        AGENTIC RULES:
        1. REASONING: Before asking a question, briefly evaluate the candidate's last answer in your head.
        2. ADAPTABILITY: If an answer is vague, ask a follow-up 'Why' or 'How' question. 
        3. FLOW: Do not just read from a list. Connect your questions to what the candidate just said.
        4. TERMINATION: After {self.max_questions} primary topics are covered, politely end the interview.
        
        Style: Professional, inquisitive, and warm. Ask ONE question at a time."""

    def call_claude(self, user_msg):
        self.chat_history.append({"role": "user", "content": user_msg})
        try:
            response = client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=1024,
                system=self.system_prompt,
                messages=self.chat_history
            )
            ai_msg = response.content[0].text
            self.chat_history.append({"role": "assistant", "content": ai_msg})
            return ai_msg
        except Exception as e:
            return f"Error: {str(e)}"

    def start_interview(self):
        return self.call_claude(f"Hello, I am {self.candidate_name}. I'm ready to start.")

    def handle_response(self, candidate_text):
        self.question_count += 1
        self.conversation_log.append({"role": "candidate", "content": candidate_text})
        
        # If it's the last question, instruct the agent to wrap up
        msg = candidate_text
        if self.question_count >= self.max_questions:
            msg += " (This is the final response. Please wrap up the interview now.)"
            
        ai_response = self.call_claude(msg)
        self.conversation_log.append({"role": "interviewer", "content": ai_response})
        return ai_response

# ════════════════════════════════════════════════════
# 4. APP UI LOGIC
# ════════════════════════════════════════════════════

st.set_page_config(page_title="Agentic Interviewer", layout="wide")

# Token Detection
token = st.query_params.get("token")
is_candidate = token is not None

if is_candidate:
    # --- CANDIDATE PORTAL ---
    schedules = load_schedules()
    match = next((s for s in schedules if s["token"] == token), None)
    
    if not match:
        st.error("Invalid Interview Token.")
    else:
        st.title(f"Interview: {match['role']}")
        if "agent" not in st.session_state:
            if st.button("Start Interview Session"):
                st.session_state.agent = InterviewAgent(match, match["candidate_name"], round_name=match['round_name'])
                opening = st.session_state.agent.start_interview()
                st.session_state.messages = [{"role": "assistant", "content": opening}]
                st.rerun()
        else:
            for m in st.session_state.messages:
                with st.chat_message(m["role"]): st.write(m["content"])
            
            if st.session_state.agent.question_count < st.session_state.agent.max_questions:
                u_input = st.chat_input("Enter your response...")
                if u_input:
                    st.session_state.messages.append({"role": "user", "content": u_input})
                    with st.spinner("AI is evaluating..."):
                        reply = st.session_state.agent.handle_response(u_input)
                    st.session_state.messages.append({"role": "assistant", "content": reply})
                    st.rerun()
            else:
                st.success("Interview Complete.")

else:
    # --- ADMIN INTERFACE ---
    if not st.session_state.get("logged_in"):
        st.title("Admin Login")
        pw = st.text_input("Password", type="password")
        if st.button("Login") and pw == ADMIN_PASSWORD:
            st.session_state.logged_in = True
            st.rerun()
    else:
        page = st.sidebar.selectbox("Navigate", ["Scheduler", "Question Bank", "Analytics", "Results"])
        
        # --- SCHEDULER ---
        if page == "Scheduler":
            st.title("Interview Scheduler")
            schedules = load_schedules()
            c_name = st.text_input("Candidate Name")
            c_role = st.text_input("Job Role")
            c_round = st.selectbox("Round Type", ["Technical", "HR", "Managerial"])
            if st.button("Generate Agentic Link"):
                new_token = generate_interview_token(c_name, c_role, c_round)
                schedules.append({
                    "candidate_name": c_name, "role": c_role, 
                    "round_name": c_round, "token": new_token, "created": str(datetime.now())
                })
                save_schedules(schedules)
                st.success("Link Generated!")
                st.code(f"/?token={new_token}")

        # --- QUESTION BANK ---
        elif page == "Question Bank":
            st.title("Question Bank")
            bank = load_question_bank()
            role_key = st.text_input("Role Name")
            qs_input = st.text_area("Questions (1 per line)")
            if st.button("Save to Bank"):
                bank[role_key] = [q.strip() for q in qs_input.split("\n") if q.strip()]
                save_question_bank(bank)
                st.rerun()
            for r, qs in bank.items():
                with st.expander(r):
                    for q in qs: st.write(f"- {q}")

        # --- ANALYTICS ---
        elif page == "Analytics":
            st.title("Hiring Analytics")
            all_c = load_all_candidates()
            if all_c:
                reports = [r["report"] for c in all_c for r in c.get("rounds", [])]
                scores = [extract_score(rep) for rep in reports if extract_score(rep) > 0]
                if scores:
                    st.metric("Global Average Score", f"{sum(scores)/len(scores):.1f}/10")
                    st.plotly_chart(px.histogram(x=scores, title="Candidate Score Distribution"))
                else:
                    st.info("Not enough scored data for charts.")
            else:
                st.info("No interview data available.")

        # --- RESULTS ---
        elif page == "Results":
            st.title("Interview Transcripts & Reports")
            all_c = load_all_candidates()
            for c in reversed(all_c):
                with st.expander(f"{c['candidate_name']} - {c['role']}"):
                    for r in c["rounds"]:
                        st.subheader(f"Round: {r['round_name']}")
                        st.text(r["report"])
                        if st.checkbox("Show Full Transcript", key=f"ts_{c['candidate_name']}"):
                            for msg in r["transcript"]:
                                st.write(f"**{msg['role']}:** {msg['content']}")
