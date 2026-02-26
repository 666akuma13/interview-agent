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
    # Hide ALL admin UI elements
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
    match = next((s for s in schedules if s["token"] == token and not s.get("used", False)), None)

    if not match:
        st.markdown("""
            <div style='text-align:center; padding: 80px 20px;'>
                <h1>❌ Invalid Link</h1>
                <p style='font-size:18px; color:gray;'>This interview link is invalid or has already been used.<br>Please contact HR for a new link.</p>
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

        st.markdown("<div style='text-align:center'>", unsafe_allow_html=True)
        if st.button("🚀 Start My Interview", use_container_width=True, type="primary"):
            with st.spinner("Setting up your interview..."):
                agent = InterviewAgent(match, match["candidate_name"], round_name=match["round_name"])
                opening = agent.start_interview()
            st.session_state.agent = agent
            st.session_state.match = match
            st.session_state.messages = [{"role": "assistant", "content": opening}]
            st.session_state.interview_done = False
            # Mark token as used
            for s in schedules:
                if s["token"] == token:
                    s["used"] = True
            save_schedules(schedules)
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

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
    # ── LOGIN ──
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
                    st.session_state.logged_in = True
                    st.rerun()
                else:
                    st.error("Incorrect password.")
        st.stop()

    # ── ADMIN HEADER ──
    col1, col2 = st.columns([8, 1])
    with col1:
        st.title("🏢 AI Interview Platform — Admin Panel")
    with col2:
        if st.button("Logout"):
            st.session_state.logged_in = False
            st.rerun()

    page = st.sidebar.selectbox("📌 Navigation", [
        "📅 Scheduler",
        "🎤 Conduct Interview",
        "📊 Results & Reports",
        "🔍 Compare Candidates",
        "📚 Question Bank",
        "📈 Analytics"
    ])

    # ════════════════════════════════════════════════
    # PAGE: SCHEDULER
    # ════════════════════════════════════════════════
    if page == "📅 Scheduler":
        st.title("📅 Interview Scheduler")
        st.info("Generate a unique interview link for each candidate. They will only see the interview chat — nothing else.")

        with st.form("schedule_form"):
            col1, col2 = st.columns(2)
            with col1:
                c_name = st.text_input("Candidate Full Name")
                c_role = st.text_input("Job Role", placeholder="e.g. Data Scientist")
                c_skills = st.text_input("Required Skills", placeholder="e.g. Python, SQL, Machine Learning")
            with col2:
                c_round = st.selectbox("Interview Round", ["Technical", "HR", "Managerial"])
                c_exp = st.text_input("Experience Required", placeholder="e.g. 2 years, Fresher")
            submitted = st.form_submit_button("🔗 Generate Interview Link", use_container_width=True, type="primary")

        if submitted:
            if c_name and c_role:
                schedules = load_schedules()
                new_token = generate_interview_token(c_name, c_role, c_round)
                schedules.append({
                    "candidate_name": c_name,
                    "role": c_role,
                    "technical_skills": c_skills,
                    "experience": c_exp,
                    "round_name": c_round,
                    "token": new_token,
                    "created": str(datetime.now()),
                    "used": False
                })
                save_schedules(schedules)
                st.success(f"✅ Interview link generated for {c_name}!")
                st.markdown("**📋 Send this link to the candidate:**")
                full_link = f"{APP_URL}/?token={new_token}"
                st.code(full_link)
                st.caption("The candidate will see only the interview chat. No admin features are visible to them.")
            else:
                st.error("Please fill in candidate name and job role.")

        st.divider()
        st.subheader("All Scheduled Interviews")
        schedules = load_schedules()
        if not schedules:
            st.info("No interviews scheduled yet.")
        else:
            for s in reversed(schedules):
                status = "✅ Completed" if s.get("used") else "⏳ Pending"
                with st.expander(f"{status} — {s['candidate_name']} — {s['role']} — {s['round_name']} — {s['created'][:10]}"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown(f"**Candidate:** {s['candidate_name']}")
                        st.markdown(f"**Role:** {s['role']}")
                        st.markdown(f"**Round:** {s['round_name']}")
                        st.markdown(f"**Status:** {status}")
                    with col2:
                        st.markdown(f"**Skills:** {s.get('technical_skills', 'N/A')}")
                        st.markdown(f"**Experience:** {s.get('experience', 'N/A')}")
                        st.markdown(f"**Created:** {s['created'][:16]}")
                    st.markdown("**Interview Link:**")
                    st.code(f"{APP_URL}/?token={s['token']}")

    # ════════════════════════════════════════════════
    # PAGE: CONDUCT INTERVIEW (admin does it manually)
    # ════════════════════════════════════════════════
    elif page == "🎤 Conduct Interview":
        st.title("🎤 Conduct Interview Manually")
        st.caption("Use this to conduct an interview directly in admin view — type the candidate's answers yourself.")

        if "agent" not in st.session_state:
            with st.form("interview_form"):
                col1, col2 = st.columns(2)
                with col1:
                    candidate_name = st.text_input("Candidate Name")
                    job_role = st.text_input("Job Role")
                with col2:
                    technical_skills = st.text_input("Technical Skills")
                    round_name = st.selectbox("Round", ["Technical", "HR", "Managerial"])
                start = st.form_submit_button("▶️ Start Interview", use_container_width=True, type="primary")

            if start:
                if not candidate_name or not job_role:
                    st.error("Please fill in candidate name and job role.")
                else:
                    jd_data = {"role": job_role, "technical_skills": technical_skills}
                    with st.spinner("Setting up interview..."):
                        agent = InterviewAgent(jd_data, candidate_name, round_name=round_name)
                        opening = agent.start_interview()
                    st.session_state.agent = agent
                    st.session_state.jd_data = jd_data
                    st.session_state.candidate_name = candidate_name
                    st.session_state.round_name = round_name
                    st.session_state.messages = [{"role": "assistant", "content": opening}]
                    st.session_state.interview_done = False
                    st.rerun()

        elif not st.session_state.get("interview_done"):
            st.caption(f"**Candidate:** {st.session_state.candidate_name} | **Role:** {st.session_state.jd_data['role']} | **Round:** {st.session_state.round_name}")
            progress = min(st.session_state.agent.question_count / 8, 1.0)
            st.progress(progress, text=f"Question {st.session_state.agent.question_count} of 8")

            for m in st.session_state.messages:
                with st.chat_message(m["role"]):
                    st.write(m["content"])

            if st.session_state.agent.is_complete():
                st.success("Interview Complete!")
                if st.button("📊 Generate Evaluation Report", type="primary"):
                    st.session_state.interview_done = True
                    st.rerun()
            else:
                u_input = st.chat_input("Type candidate's answer here...")
                if u_input:
                    st.session_state.messages.append({"role": "user", "content": u_input})
                    with st.spinner("AI is thinking..."):
                        reply = st.session_state.agent.handle_response(u_input)
                    st.session_state.messages.append({"role": "assistant", "content": reply})
                    st.rerun()

        else:
            st.header("📊 Evaluation Report")
            with st.spinner("Generating AI evaluation..."):
                report = generate_report(
                    st.session_state.agent.get_transcript(),
                    st.session_state.jd_data,
                    st.session_state.round_name
                )
                anticheat_flags = analyze_anticheat(st.session_state.agent.get_transcript())
                save_candidate_result(
                    st.session_state.candidate_name,
                    st.session_state.jd_data,
                    report,
                    st.session_state.agent.get_transcript(),
                    st.session_state.round_name,
                    anticheat_flags
                )
            st.text(report)
            st.subheader("🔍 Anti-Cheat Analysis")
            for flag in anticheat_flags:
                st.success(flag) if "No suspicious" in flag else st.warning(flag)
            col1, col2 = st.columns(2)
            with col1:
                st.download_button("⬇️ Download TXT", data=report, file_name=f"{st.session_state.candidate_name}_report.txt", mime="text/plain")
            with col2:
                pdf_path = generate_pdf(st.session_state.candidate_name, st.session_state.jd_data["role"], datetime.now().strftime("%Y-%m-%d"), report, st.session_state.round_name)
                with open(pdf_path, "rb") as f:
                    st.download_button("⬇️ Download PDF", data=f, file_name=f"{st.session_state.candidate_name}_report.pdf", mime="application/pdf")
            if st.button("🔄 Start New Interview"):
                for key in list(st.session_state.keys()):
                    if key != "logged_in":
                        del st.session_state[key]
                st.rerun()

    # ════════════════════════════════════════════════
    # PAGE: RESULTS & REPORTS
    # ════════════════════════════════════════════════
    elif page == "📊 Results & Reports":
        st.title("📊 Results & Reports")
        all_c = load_all_candidates()
        if not all_c:
            st.info("No interview data yet. Candidates need to complete their interviews first.")
        else:
            roles = list(set([c["role"] for c in all_c]))
            col1, col2 = st.columns(2)
            with col1:
                filter_role = st.selectbox("Filter by Role", ["All Roles"] + roles)
            with col2:
                filter_rec = st.selectbox("Filter by Recommendation", ["All", "Recommended", "Not Recommended", "Hold"])

            filtered = all_c
            if filter_role != "All Roles":
                filtered = [c for c in filtered if c["role"] == filter_role]

            st.markdown(f"Showing **{len(filtered)}** candidate(s)")
            st.divider()

            for c in reversed(filtered):
                rounds = c.get("rounds", [])
                latest = rounds[-1] if rounds else {}
                score = extract_score(latest.get("report", ""))
                rec = extract_recommendation(latest.get("report", ""))
                badge = "🟢" if "Yes" in str(rec) else ("🔴" if "No" in str(rec) else "🟡")
                rounds_done = ", ".join([r["round_name"] for r in rounds])

                with st.expander(f"{badge} {c['candidate_name']} — {c['role']} — {rounds_done} — Score: {score}/10"):
                    col1, col2, col3 = st.columns(3)
                    col1.metric("Overall Score", f"{score}/10")
                    col2.metric("Rounds Completed", len(rounds))
                    col3.metric("Recommendation", rec)
                    st.divider()

                    for rnd in rounds:
                        st.markdown(f"### 📋 {rnd['round_name']} — {rnd['date']}")
                        st.text(rnd["report"])
                        st.markdown("**🔍 Anti-Cheat Flags:**")
                        for flag in rnd.get("anticheat_flags", []):
                            st.success(flag) if "No suspicious" in flag else st.warning(flag)
                        col1, col2 = st.columns(2)
                        with col1:
                            st.download_button("⬇️ TXT", data=rnd["report"], file_name=f"{c['candidate_name']}_{rnd['round_name']}.txt", mime="text/plain", key=f"txt_{c['candidate_name']}_{rnd['round_name']}_{rnd['date']}")
                        with col2:
                            pdf_path = generate_pdf(c["candidate_name"], c["role"], rnd["date"], rnd["report"], rnd["round_name"])
                            with open(pdf_path, "rb") as f:
                                st.download_button("⬇️ PDF", data=f, file_name=f"{c['candidate_name']}_{rnd['round_name']}.pdf", mime="application/pdf", key=f"pdf_{c['candidate_name']}_{rnd['round_name']}_{rnd['date']}")
                        if st.checkbox("Show Full Transcript", key=f"ts_{c['candidate_name']}_{rnd['round_name']}_{rnd['date']}"):
                            for msg in rnd["transcript"]:
                                label = "🤖 Interviewer" if msg["role"] == "interviewer" else "👤 Candidate"
                                st.markdown(f"**{label}:** {msg['content']}")

    # ════════════════════════════════════════════════
    # PAGE: COMPARE CANDIDATES
    # ════════════════════════════════════════════════
    elif page == "🔍 Compare Candidates":
        st.title("🔍 Compare Candidates")
        all_c = load_all_candidates()
        if len(all_c) < 2:
            st.info("You need at least 2 interviewed candidates to compare.")
        else:
            roles = list(set([c["role"] for c in all_c]))
            selected_role = st.selectbox("Select Role to Compare", roles)
            role_candidates = [c for c in all_c if c["role"] == selected_role]

            if len(role_candidates) < 2:
                st.warning(f"Only {len(role_candidates)} candidate(s) for this role. Need at least 2.")
            else:
                names = [c["candidate_name"] for c in role_candidates]
                selected_names = st.multiselect("Select Candidates to Compare", names, default=names[:2])
                selected_candidates = [c for c in role_candidates if c["candidate_name"] in selected_names]

                if len(selected_candidates) >= 2:
                    st.divider()
                    cols = st.columns(len(selected_candidates))
                    for i, candidate in enumerate(selected_candidates):
                        rounds = candidate.get("rounds", [])
                        latest = rounds[-1] if rounds else {}
                        report = latest.get("report", "")
                        scores = extract_all_scores(report)
                        rec = extract_recommendation(report)
                        badge = "🟢" if "Yes" in str(rec) else ("🔴" if "No" in str(rec) else "🟡")
                        with cols[i]:
                            st.markdown(f"### {badge} {candidate['candidate_name']}")
                            st.markdown(f"**Recommendation:** {rec}")
                            st.divider()
                            for cat, score in scores.items():
                                st.metric(cat, f"{score}/10")

    # ════════════════════════════════════════════════
    # PAGE: QUESTION BANK
    # ════════════════════════════════════════════════
    elif page == "📚 Question Bank":
        st.title("📚 Question Bank")
        st.caption("Save must-ask questions per role. These will be used during AI interviews.")
        bank = load_question_bank()

        with st.form("qbank_form"):
            role_key = st.text_input("Role Name", placeholder="e.g. Data Scientist, Backend Developer")
            qs_input = st.text_area("Questions (one per line)")
            save_q = st.form_submit_button("💾 Save Questions", use_container_width=True)

        if save_q:
            if role_key and qs_input:
                bank[role_key] = bank.get(role_key, []) + [q.strip() for q in qs_input.split("\n") if q.strip()]
                save_question_bank(bank)
                st.success(f"Saved questions for '{role_key}'")
                st.rerun()
            else:
                st.error("Please enter role name and questions.")

        st.divider()
        if not bank:
            st.info("No questions saved yet.")
        else:
            for r, qs in bank.items():
                with st.expander(f"📝 {r} — {len(qs)} questions"):
                    for q in qs:
                        st.write(f"- {q}")
                    if st.button(f"🗑️ Delete all for '{r}'", key=f"del_{r}"):
                        del bank[r]
                        save_question_bank(bank)
                        st.rerun()

    # ════════════════════════════════════════════════
    # PAGE: ANALYTICS
    # ════════════════════════════════════════════════
    elif page == "📈 Analytics":
        st.title("📈 Hiring Analytics")
        all_c = load_all_candidates()
        if not all_c:
            st.info("No interview data available yet.")
        else:
            all_rounds = [r for c in all_c for r in c.get("rounds", [])]
            scores = [extract_score(r["report"]) for r in all_rounds if extract_score(r["report"]) > 0]
            pass_count = sum(1 for r in all_rounds if "Yes" in extract_recommendation(r["report"]))

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Total Candidates", len(all_c))
            col2.metric("Total Interviews", len(all_rounds))
            col3.metric("Avg Score", f"{sum(scores)/len(scores):.1f}/10" if scores else "N/A")
            col4.metric("Recommended", pass_count)
            st.divider()

            if scores:
                col1, col2 = st.columns(2)
                with col1:
                    st.subheader("Score Distribution")
                    st.plotly_chart(px.histogram(x=scores, nbins=10, labels={"x": "Score", "y": "Count"}, color_discrete_sequence=["#4F8BF9"]), use_container_width=True)
                with col2:
                    rec_counts = {"Recommended": 0, "Not Recommended": 0, "Hold": 0}
                    for r in all_rounds:
                        rec = extract_recommendation(r["report"])
                        if "Yes" in str(rec): rec_counts["Recommended"] += 1
                        elif "No" in str(rec): rec_counts["Not Recommended"] += 1
                        else: rec_counts["Hold"] += 1
                    st.subheader("Hire Recommendation")
                    st.plotly_chart(px.pie(values=list(rec_counts.values()), names=list(rec_counts.keys()), color_discrete_sequence=["#2ecc71", "#e74c3c", "#f39c12"]), use_container_width=True)

                role_scores = {}
                for c in all_c:
                    for r in c.get("rounds", []):
                        s = extract_score(r["report"])
                        if s > 0:
                            role_scores.setdefault(c["role"], []).append(s)
                if role_scores:
                    st.subheader("Average Score by Role")
                    avg_by_role = {role: round(sum(s)/len(s), 1) for role, s in role_scores.items()}
                    st.plotly_chart(px.bar(x=list(avg_by_role.keys()), y=list(avg_by_role.values()), labels={"x": "Role", "y": "Avg Score"}, color_discrete_sequence=["#4F8BF9"]), use_container_width=True)
