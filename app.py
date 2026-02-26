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

def chat_with_claude(messages, system_prompt="You are a professional interviewer."):
    try:
        api_messages = [msg for msg in messages if msg["role"] in ["user", "assistant"]]
        response = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=1024,
            system=system_prompt,
            messages=api_messages
        )
        return response.content[0].text
    except Exception as e:
        st.error(f"Claude API Error: {e}")
        return "I apologize, I'm having trouble connecting. Could you repeat that?"

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

def extract_all_scores(report_text):
    scores = {}
    cats = ["Technical Knowledge", "Communication", "Problem Solving", "Confidence", "Overall"]
    for line in report_text.split("\n"):
        for cat in cats:
            if cat in line and "/10" in line:
                try: scores[cat] = float(line.split(":")[1].strip().replace("/10", ""))
                except: scores[cat] = 0
    return scores

def extract_weaknesses(report_text):
    weaknesses = []
    capture = False
    for line in report_text.split("\n"):
        if "AREAS FOR IMPROVEMENT" in line.upper() or "WEAKNESS" in line.upper():
            capture = True
            continue
        if capture:
            if line.strip().startswith("-"): weaknesses.append(line.strip("- ").strip())
            elif line.strip() == "" or any(k in line.upper() for k in ["HIRE", "SUMMARY"]): break
    return weaknesses

def generate_report(transcript, jd_data, round_name="Technical"):
    formatted = "\n".join([f"{msg['role'].upper()}: {msg['content']}" for msg in transcript])
    prompt = f"Evaluate this {round_name} interview for {jd_data['job_title']}.\nTranscript:\n{formatted}"
    return chat_with_claude([{"role": "user", "content": prompt}], "You are a senior hiring manager.")

def generate_pdf(candidate_name, role, date, report_text, round_name="Interview"):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, "Interview Evaluation Report", ln=True, align="C")
    pdf.set_font("Arial", "", 12)
    clean_text = report_text.encode('latin-1', 'replace').decode('latin-1')
    pdf.multi_cell(0, 10, clean_text)
    pdf_path = f"/tmp/{candidate_name}_report.pdf"
    pdf.output(pdf_path)
    return pdf_path

def save_candidate_result(candidate_name, jd_data, report, transcript, round_name, anticheat_flags):
    all_results = load_all_candidates()
    new_round = {"round_name": round_name, "date": datetime.now().strftime("%Y-%m-%d %H:%M"), "report": report, "transcript": transcript, "anticheat_flags": anticheat_flags}
    
    match = next((c for c in all_results if c["candidate_name"] == candidate_name and c["role"] == jd_data["job_title"]), None)
    if match:
        match["rounds"].append(new_round)
    else:
        all_results.append({"candidate_name": candidate_name, "role": jd_data["job_title"], "technical_skills": jd_data.get("technical_skills", []), "rounds": [new_round]})
    
    with open(RESULTS_FILE, "w") as f: json.dump(all_results, f, indent=2)

def analyze_anticheat(conversation_log, response_times):
    flags = []
    for i, msg in enumerate(conversation_log):
        if msg["role"] == "candidate":
            if len(msg["content"].split()) > 250: flags.append(f"Q{i+1}: Extremely long answer.")
    return flags if flags else ["No suspicious activity detected"]

# ════════════════════════════════════════════════════
# 3. INTERVIEW AGENT CLASS
# ════════════════════════════════════════════════════

class InterviewAgent:
    def __init__(self, jd_data, candidate_name, custom_questions=None, round_name="Technical"):
        self.jd_data = jd_data
        self.candidate_name = candidate_name
        self.round_name = round_name
        self.max_questions = 10
        self.question_count = 0
        self.chat_history = []
        self.conversation_log = []
        self.system_prompt = f"You are interviewing {candidate_name} for {jd_data['job_title']}. Round: {round_name}. Ask 1 question at a time."

    def start(self):
        self.chat_history.append({"role": "user", "content": "Start the interview."})
        res = chat_with_claude(self.chat_history, self.system_prompt)
        self.chat_history.append({"role": "assistant", "content": res})
        self.conversation_log.append({"role": "interviewer", "content": res})
        return res

    def respond(self, text):
        self.question_count += 1
        self.conversation_log.append({"role": "candidate", "content": text})
        self.chat_history.append({"role": "user", "content": text})
        res = chat_with_claude(self.chat_history, self.system_prompt)
        self.chat_history.append({"role": "assistant", "content": res})
        self.conversation_log.append({"role": "interviewer", "content": res})
        return res

    def is_complete(self): return self.question_count >= self.max_questions

# ════════════════════════════════════════════════════
# 4. APP UI LOGIC
# ════════════════════════════════════════════════════

st.set_page_config(page_title="AI Interview Platform", layout="wide")

token = st.query_params.get("token")
is_candidate = token is not None

if is_candidate:
    # --- CANDIDATE INTERFACE ---
    schedules = load_schedules()
    match = next((s for s in schedules if s["token"] == token), None)
    
    if not match:
        st.error("Invalid Interview Link.")
    else:
        st.title(f"Interview for {match['role']}")
        if "agent" not in st.session_state:
            if st.button("Begin"):
                st.session_state.agent = InterviewAgent(match, match["candidate_name"])
                opening = st.session_state.agent.start()
                st.session_state.messages = [{"role": "assistant", "content": opening}]
                st.rerun()
        else:
            for m in st.session_state.messages:
                with st.chat_message(m["role"]): st.write(m["content"])
            
            if not st.session_state.agent.is_complete():
                u_input = st.chat_input("Answer...")
                if u_input:
                    st.session_state.messages.append({"role": "user", "content": u_input})
                    reply = st.session_state.agent.respond(u_input)
                    st.session_state.messages.append({"role": "assistant", "content": reply})
                    st.rerun()
            else:
                if st.button("Finish"):
                    report = generate_report(st.session_state.agent.conversation_log, match)
                    save_candidate_result(match["candidate_name"], match, report, st.session_state.agent.conversation_log, match["round_name"], [])
                    st.success("Submitted!")

else:
    # --- ADMIN INTERFACE ---
    if not st.session_state.get("logged_in"):
        pw = st.text_input("Admin Password", type="password")
        if st.button("Login") and pw == ADMIN_PASSWORD:
            st.session_state.logged_in = True
            st.rerun()
    else:
        page = st.sidebar.selectbox("Menu", ["Admin Dashboard", "Question Bank Manager", "Interview Scheduler", "Analytics"])
        
        # --- ADMIN DASHBOARD ---
        if page == "Admin Dashboard":
            st.title("Results")
            cands = load_all_candidates()
            for c in reversed(cands):
                with st.expander(f"{c['candidate_name']} - {c['role']}"):
                    for r in c["rounds"]:
                        st.markdown(f"### {r['round_name']}")
                        st.text(r["report"])

        # --- QUESTION BANK ---
        elif page == "Question Bank Manager":
            st.title("Question Bank Manager")
            bank = load_question_bank()
            new_role = st.text_input("Role")
            new_qs = st.text_area("Questions (1 per line)")
            if st.button("Save"):
                bank[new_role] = [q.strip() for q in new_qs.split("\n") if q.strip()]
                save_question_bank(bank)
                st.rerun()
            for role, qs in bank.items():
                with st.expander(role):
                    for q in qs: st.write(f"- {q}")

        # --- SCHEDULER ---
        elif page == "Interview Scheduler":
            st.title("Interview Scheduler")
            schedules = load_schedules()
            c_name = st.text_input("Candidate Name")
            c_role = st.text_input("Role")
            if st.button("Generate Link"):
                tok = generate_interview_token(c_name, c_role, "Technical")
                schedules.append({"candidate_name": c_name, "role": c_role, "token": tok, "round_name": "Technical", "created": str(datetime.now())})
                save_schedules(schedules)
                st.code(f"/?token={tok}")

        # --- ANALYTICS ---
        elif page == "Analytics":
            st.title("Analytics")
            all_c = load_all_candidates()
            if all_c:
                all_r = [r for c in all_c for r in c.get("rounds", [])]
                scores = [extract_score(r["report"]) for r in all_r]
                st.metric("Avg Score", f"{sum(scores)/len(scores):.1f}/10")
                fig = px.histogram(x=scores, title="Score Distribution")
                st.plotly_chart(fig)
