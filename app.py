import streamlit as st
from groq import Groq
import json
import os
import requests
from datetime import datetime
import hashlib
import plotly.express as px
from fpdf import FPDF

# ════════════════════════════════════════════════════
# CLIENT SETUP
# ════════════════════════════════════════════════════
if "GROQ_API_KEY" in st.secrets:
    client = Groq(api_key=st.secrets["GROQ_API_KEY"])
else:
    st.error("Missing GROQ_API_KEY in Streamlit Secrets.")
    st.stop()

ADMIN_PASSWORD = "admin123"
APP_URL = "https://interview-agent-hdyuwl2pijewxvdbgkw7xu.streamlit.app"
JSONBIN_API = "https://api.jsonbin.io/v3"

# ════════════════════════════════════════════════════
# DATABASE FUNCTIONS (JSONBin - persistent across users)
# ════════════════════════════════════════════════════
def get_headers():
    return {
        "X-Master-Key": st.secrets["JSONBIN_API_KEY"],
        "Content-Type": "application/json"
    }

def load_db():
    bin_id = st.secrets.get("JSONBIN_BIN_ID", "")
    if not bin_id:
        return {"candidates": [], "schedules": [], "question_bank": {}}
    try:
        res = requests.get(f"{JSONBIN_API}/b/{bin_id}/latest", headers=get_headers(), timeout=10)
        return res.json().get("record", {"candidates": [], "schedules": [], "question_bank": {}})
    except:
        return {"candidates": [], "schedules": [], "question_bank": {}}

def save_db(data):
    bin_id = st.secrets.get("JSONBIN_BIN_ID", "")
    if not bin_id:
        try:
            res = requests.post(
                f"{JSONBIN_API}/b",
                headers=get_headers(),
                json=data,
                timeout=10
            )
            new_id = res.json()["metadata"]["id"]
            st.warning(f"⚠️ Add this to Streamlit Secrets and reboot: JSONBIN_BIN_ID = \"{new_id}\"")
        except Exception as e:
            st.error(f"Failed to create bin: {e}")
        return
    try:
        requests.put(f"{JSONBIN_API}/b/{bin_id}", headers=get_headers(), json=data, timeout=10)
    except:
        pass

def load_schedules():
    return load_db().get("schedules", [])

def save_schedules(schedules):
    db = load_db()
    db["schedules"] = schedules
    save_db(db)

def load_all_candidates():
    return load_db().get("candidates", [])

def save_candidate_result(candidate_name, jd_data, report, transcript, round_name, anticheat_flags):
    db = load_db()
    all_results = db.get("candidates", [])
    existing = next((c for c in all_results if c["candidate_name"] == candidate_name and c["role"] == jd_data.get("role", "")), None)
    new_round = {
        "round_name": round_name,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "report": report,
        "transcript": transcript,
        "anticheat_flags": anticheat_flags
    }
    if existing:
        existing["rounds"] = existing.get("rounds", [])
        existing["rounds"].append(new_round)
        existing["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    else:
        all_results.append({
            "candidate_name": candidate_name,
            "role": jd_data.get("role", ""),
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "rounds": [new_round]
        })
    db["candidates"] = all_results
    save_db(db)

def load_question_bank():
    return load_db().get("question_bank", {})

def save_question_bank(bank):
    db = load_db()
    db["question_bank"] = bank
    save_db(db)

# ════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ════════════════════════════════════════════════════
def generate_interview_token(candidate_name, role, round_name):
    raw = f"{candidate_name}_{role}_{round_name}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    return hashlib.md5(raw.encode()).hexdigest()[:10]

def extract_score(report_text):
    for line in report_text.split("\n"):
        if "Overall" in line and "/10" in line:
            try:
                return float(line.split(":")[1].strip().replace("/10", ""))
            except:
                return 0
    return 0

def extract_recommendation(report_text):
    for line in report_text.split("\n"):
        if "HIRE RECOMMENDATION" in line.upper():
            return line.split(":")[1].strip() if ":" in line else "N/A"
    return "N/A"

def extract_all_scores(report_text):
    scores = {}
    categories = ["Technical Knowledge", "Communication", "Problem Solving", "Confidence", "Overall"]
    for line in report_text.split("\n"):
        for cat in categories:
            if cat in line and "/10" in line:
                try:
                    scores[cat] = float(line.split(":")[1].strip().replace("/10", ""))
                except:
                    scores[cat] = 0
    return scores

def analyze_anticheat(conversation_log):
    flags = []
    for i, msg in enumerate(conversation_log):
        if msg["role"] == "candidate":
            word_count = len(msg["content"].split())
            if word_count < 5:
                flags.append(f"Q{i+1}: Very short answer ({word_count} words)")
            if word_count > 200:
                flags.append(f"Q{i+1}: Very long answer ({word_count} words) — possible pre-written")
    return flags if flags else ["No suspicious activity detected"]

def generate_report(transcript, jd_data, round_name):
    formatted = "\n".join([f"{msg['role'].upper()}: {msg['content']}" for msg in transcript])
    system = "You are a senior hiring manager. Evaluate interview transcripts objectively and provide detailed assessments."
    prompt = f"Evaluate this {round_name} round interview.\n"
    prompt += f"Role: {jd_data.get('role', '')}\n"
    prompt += f"Required Skills: {jd_data.get('technical_skills', '')}\n"
    prompt += f"TRANSCRIPT:\n{formatted}\n"
    prompt += "Provide scores out of 10 for: Technical Knowledge, Communication, Problem Solving, Confidence, Overall.\n"
    prompt += "List Strengths, Areas for Improvement, Hire Recommendation (Yes/No/Hold), and a Summary."
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Report generation failed: {str(e)}"

def generate_pdf(candidate_name, role, date, report_text, round_name="Interview"):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, "AI Interview Evaluation Report", ln=True, align="C")
    pdf.ln(3)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, f"Candidate: {candidate_name}", ln=True)
    pdf.cell(0, 10, f"Role: {role}", ln=True)
    pdf.cell(0, 10, f"Round: {round_name}", ln=True)
    pdf.cell(0, 10, f"Date: {date}", ln=True)
    pdf.ln(5)
    pdf.set_font("Arial", "", 11)
    for line in report_text.split("\n"):
        try:
            pdf.multi_cell(0, 8, line.encode('latin-1', 'replace').decode('latin-1'))
        except:
            pdf.multi_cell(0, 8, line)
    pdf_path = f"/tmp/{candidate_name}_{role}_{round_name}_report.pdf"
    pdf.output(pdf_path)
    return pdf_path

# ════════════════════════════════════════════════════
# AI INTERVIEW AGENT
# ════════════════════════════════════════════════════
class InterviewAgent:
    def __init__(self, jd_data, candidate_name, round_name="Technical"):
        self.jd_data = jd_data
        self.candidate_name = candidate_name
        self.round_name = round_name
        self.max_questions = 8
        self.question_count = 0
        self.chat_history = []
        self.conversation_log = []
        self.system_prompt = f"""You are an Advanced AI Interviewing Agent conducting a real job interview.
Current Round: {round_name} | Role: {jd_data.get('role', 'Software Engineer')}
Required Skills: {jd_data.get('technical_skills', '')}

YOUR BEHAVIOUR:
1. Greet the candidate warmly by name and introduce yourself as the AI interviewer.
2. Ask ONE question at a time — never multiple questions together.
3. Listen carefully to each answer and ask intelligent follow-up questions based on what they said.
4. If an answer is vague or incomplete, dig deeper with "Can you elaborate?" or "Can you give an example?"
5. Cover technical skills, problem solving, communication, and confidence naturally through conversation.
6. After {self.max_questions} exchanges, thank the candidate warmly and close the interview professionally.

Tone: Professional, warm, and encouraging. Make the candidate feel comfortable."""

    def call_groq(self, user_msg):
        self.chat_history.append({"role": "user", "content": user_msg})
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "system", "content": self.system_prompt}] + self.chat_history,
                temperature=0.7
            )
            ai_msg = response.choices[0].message.content
            self.chat_history.append({"role": "assistant", "content": ai_msg})
            return ai_msg
        except Exception as e:
            return f"Error: {str(e)}"

    def start_interview(self):
        return self.call_groq(f"Hello, I am {self.candidate_name} and I am ready for my interview.")

    def handle_response(self, candidate_text):
        self.question_count += 1
        self.conversation_log.append({"role": "candidate", "content": candidate_text})
        msg = candidate_text
        if self.question_count >= self.max_questions:
            msg += " [Note: This is the candidate's final response. Please wrap up the interview warmly.]"
        ai_response = self.call_groq(msg)
        self.conversation_log.append({"role": "interviewer", "content": ai_response})
        return ai_response

    def is_complete(self):
        return self.question_count >= self.max_questions

    def get_transcript(self):
        return self.conversation_log


# ════════════════════════════════════════════════════
# PAGE CONFIG
# ════════════════════════════════════════════════════
st.set_page_config(page_title="AI Interview Agent", page_icon="🤖", layout="wide")

token = st.query_params.get("token")
is_candidate = token is not None

# ════════════════════════════════════════════════════
# CANDIDATE VIEW — completely stripped down
# ════════════════════════════════════════════════════
if is_candidate:
    st.markdown("""
        <style>
            [data-testid="stSidebar"] {display: none !important;}
            [data-testid="collapsedControl"] {display: none !important;}
            #MainMenu {visibility: hidden !important;}
            footer {visibility: hidden !important;}
            header {visibility: hidden !important;}
        </style>
    """, unsafe_allow_html=True)

    schedules = load_schedules()

    # ✅ FIX 1 — find match regardless of used status
    match = next((s for s in schedules if s["token"] == token), None)

    # ✅ FIX 2 — separate invalid vs already used
    if not match:
        st.markdown("""
            <div style='text-align:center; padding: 80px 20px;'>
                <h1>❌ Invalid Link</h1>
                <p style='font-size:18px; color:gray;'>This interview link is invalid.<br>Please contact HR for a new link.</p>
            </div>
        """, unsafe_allow_html=True)
        st.stop()

    if match.get("used", False) and "agent" not in st.session_state:
        st.markdown("""
            <div style='text-align:center; padding: 80px 20px;'>
                <h1>⚠️ Interview Already Completed</h1>
                <p style='font-size:18px; color:gray;'>This interview has already been submitted.<br>Please contact HR if you think this is a mistake.</p>
            </div>
        """, unsafe_allow_html=True)
        st.stop()

    # ── BEFORE STARTING ──
    if "agent" not in st.session_state:
        st.markdown(f"""
            <div style='max-width:600px; margin:60px auto; text-align:center;'>
                <h1>🤖 AI Interview Agent</h1>
                <h3>Welcome, <b>{match['candidate_name']}</b>!</h3>
                <p style='font-size:16px;'>You have been invited to interview for the position of</p>
                <h2 style='color:#4F8BF9;'>{match['role']}</h2>
                <p style='font-size:15px; color:gray;'>Round: {match['round_name']}</p>
            </div>
        """, unsafe_allow_html=True)

        st.divider()
        col1, col2, col3 = st.columns(3)
        col1.info("📋 **8 Questions**\nThe AI will ask you 8 questions")
        col2.info("⏱️ **Take Your Time**\nThink before answering")
        col3.info("🎯 **Be Honest**\nAnswer clearly and genuinely")
        st.divider()

        if st.button("🚀 Start My Interview", use_container_width=True, type="primary"):
            with st.spinner("Setting up your interview..."):
                agent = InterviewAgent(match, match["candidate_name"], round_name=match["round_name"])
                opening = agent.start_interview()
            st.session_state.agent = agent
            st.session_state.match = match
            st.session_state.messages = [{"role": "assistant", "content": opening}]
            st.session_state.interview_done = False
            for s in schedules:
                if s["token"] == token:
                    s["used"] = True
            save_schedules(schedules)
            st.rerun()

    # ── DURING INTERVIEW ──
    elif not st.session_state.get("interview_done"):
        st.markdown(f"<h3 style='text-align:center'>🤖 Interview in Progress — {match['role']} | {match['round_name']}</h3>", unsafe_allow_html=True)
        progress = min(st.session_state.agent.question_count / 8, 1.0)
        st.progress(progress, text=f"Question {st.session_state.agent.question_count} of 8")
        st.divider()

        for m in st.session_state.messages:
            with st.chat_message(m["role"]):
                st.write(m["content"])

        if st.session_state.agent.is_complete():
            st.success("✅ You have completed all questions!")
            st.info("Click Submit below to send your interview for evaluation.")
            if st.button("📤 Submit Interview", type="primary", use_container_width=True):
                st.session_state.interview_done = True
                st.rerun()
        else:
            u_input = st.chat_input("Type your answer here and press Enter...")
            if u_input:
                st.session_state.messages.append({"role": "user", "content": u_input})
                with st.spinner("AI is thinking..."):
                    reply = st.session_state.agent.handle_response(u_input)
                st.session_state.messages.append({"role": "assistant", "content": reply})
                st.rerun()

    # ── AFTER SUBMITTING ──
    else:
        with st.spinner("Submitting your interview and generating evaluation..."):
            report = generate_report(
                st.session_state.agent.get_transcript(),
                st.session_state.match,
                st.session_state.match["round_name"]
            )
            anticheat_flags = analyze_anticheat(st.session_state.agent.get_transcript())
            save_candidate_result(
                st.session_state.match["candidate_name"],
                st.session_state.match,
                report,
                st.session_state.agent.get_transcript(),
                st.session_state.match["round_name"],
                anticheat_flags
            )
        st.balloons()
        st.markdown("""
            <div style='text-align:center; padding:60px;'>
                <h1>🎉 Interview Submitted!</h1>
                <p style='font-size:18px;'>Thank you for completing the interview.</p>
                <p style='color:gray;'>Our HR team will review your responses and get back to you shortly.</p>
            </div>
        """, unsafe_allow_html=True)
        st.stop()

# ════════════════════════════════════════════════════
# ADMIN/INTERVIEWER VIEW — full dashboard
# ════════════════════════════════════════════════════
else:
    if not st.session_state.get("logged_in"):
        st.markdown("""
            <div style='text-align:center; padding:40px;'>
                <h1>🏢 AI Interview Platform</h1>
                <p style='color:gray;'>Admin Login — Interviewers Only</p>
            </div>
        """, unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            pw = st.text_input("Enter Admin Password", type="password")
            if st.button("Login", use_container_width=True, type="primary"):
                if pw == ADMIN_PASSWORD:
                    st.session_state.log
