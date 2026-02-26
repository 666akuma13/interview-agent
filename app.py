import streamlit as st
from groq import Groq
import json
import os
from datetime import datetime
import time
import hashlib
import plotly.express as px
from fpdf import FPDF

if "GROQ_API_KEY" in st.secrets:
    client = Groq(api_key=st.secrets["GROQ_API_KEY"])
else:
    st.error("Missing GROQ_API_KEY. Please add it to your Streamlit Secrets.")
    st.stop()

RESULTS_FILE = "candidates.json"
QUESTION_BANK_FILE = "question_bank.json"
SCHEDULES_FILE = "schedules.json"
ADMIN_PASSWORD = "admin123"

def load_all_candidates():
    if os.path.exists(RESULTS_FILE):
        try:
            with open(RESULTS_FILE, "r") as f:
                return json.load(f)
        except:
            return []
    return []

def save_candidate_result(candidate_name, jd_data, report, transcript, round_name, anticheat_flags):
    all_results = load_all_candidates()
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
    with open(RESULTS_FILE, "w") as f:
        json.dump(all_results, f, indent=2)

def load_question_bank():
    if os.path.exists(QUESTION_BANK_FILE):
        try:
            with open(QUESTION_BANK_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_question_bank(bank):
    with open(QUESTION_BANK_FILE, "w") as f:
        json.dump(bank, f, indent=2)

def load_schedules():
    if os.path.exists(SCHEDULES_FILE):
        try:
            with open(SCHEDULES_FILE, "r") as f:
                return json.load(f)
        except:
            return []
    return []

def save_schedules(schedules):
    with open(SCHEDULES_FILE, "w") as f:
        json.dump(schedules, f, indent=2)

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

def extract_weaknesses(report_text):
    weaknesses = []
    capture = False
    for line in report_text.split("\n"):
        if "AREAS FOR IMPROVEMENT" in line.upper():
            capture = True
            continue
        if capture:
            if line.strip().startswith("-"):
                weaknesses.append(line.strip("- ").strip())
            elif line.strip() == "" or "HIRE" in line.upper():
                break
    return weaknesses

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
    system = "You are a senior hiring manager. Evaluate interview transcripts objectively."
    prompt = f"Evaluate this {round_name} round interview.\n"
    prompt += f"Role: {jd_data.get('role', '')}\n"
    prompt += f"Required Skills: {jd_data.get('technical_skills', '')}\n"
    prompt += f"TRANSCRIPT:\n{formatted}\n"
    prompt += "Provide scores out of 10 for: Technical Knowledge, Communication, Problem Solving, Confidence, Overall.\n"
    prompt += "List Strengths, Areas for Improvement, Hire Recommendation, and a Summary."
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


class InterviewAgent:
    def __init__(self, jd_data, candidate_name, custom_questions=None, round_name="Technical"):
        self.jd_data = jd_data
        self.candidate_name = candidate_name
        self.round_name = round_name
        self.max_questions = 8
        self.question_count = 0
        self.chat_history = []
        self.conversation_log = []
        self.system_prompt = f"""You are an Advanced AI Interviewing Agent.
Current Round: {round_name} | Role: {jd_data.get('role', 'Software Engineer')}
Required Skills: {jd_data.get('technical_skills', 'Python')}

AGENTIC RULES:
1. REASONING: Before asking a question, briefly evaluate the candidate's last answer.
2. ADAPTABILITY: If an answer is vague, ask a follow-up Why or How question.
3. FLOW: Connect your questions to what the candidate just said.
4. TERMINATION: After {self.max_questions} primary topics are covered, politely end the interview.

Style: Professional, inquisitive, and warm. Ask ONE question at a time."""

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
        return self.call_groq(f"Hello, I am {self.candidate_name}. I am ready to start.")

    def handle_response(self, candidate_text):
        self.question_count += 1
        self.conversation_log.append({"role": "candidate", "content": candidate_text})
        msg = candidate_text
        if self.question_count >= self.max_questions:
            msg += " (This is the final response. Please wrap up the interview now.)"
        ai_response = self.call_groq(msg)
        self.conversation_log.append({"role": "interviewer", "content": ai_response})
        return ai_response

    def is_complete(self):
        return self.question_count >= self.max_questions

    def get_transcript(self):
        return self.conversation_log


# ════════════════════════════════════════════════════
# APP START
# ════════════════════════════════════════════════════
st.set_page_config(page_title="AI Interview Agent", page_icon="🤖", layout="wide")

token = st.query_params.get("token")
is_candidate = token is not None

# Hide sidebar completely for candidates
if is_candidate:
    st.markdown("""
        <style>
            [data-testid="stSidebar"] {display: none;}
            [data-testid="collapsedControl"] {display: none;}
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
        </style>
    """, unsafe_allow_html=True)
# ════════════════════════════════════════════════════
# CANDIDATE PORTAL
# ════════════════════════════════════════════════════
if is_candidate:
    schedules = load_schedules()
    match = next((s for s in schedules if s["token"] == token and not s.get("used", False)), None)

    if not match:
        st.error("Invalid or expired interview link. Please contact HR.")
        st.stop()

    st.title("🤖 AI Interview Agent")
    st.caption(f"Role: {match['role']} | Round: {match['round_name']}")

    if "agent" not in st.session_state:
        st.info(f"Welcome **{match['candidate_name']}**! You are interviewing for **{match['role']}**.")
        st.markdown("**Instructions:**")
        st.markdown("- Answer each question honestly and clearly")
        st.markdown("- Take your time before responding")
        st.markdown("- The interview will have 8 questions")
        if st.button("Start Interview Session"):
            agent = InterviewAgent(match, match["candidate_name"], round_name=match["round_name"])
            opening = agent.start_interview()
            st.session_state.agent = agent
            st.session_state.messages = [{"role": "assistant", "content": opening}]
            st.session_state.interview_done = False
            for s in schedules:
                if s["token"] == token:
                    s["used"] = True
            save_schedules(schedules)
            st.rerun()

    elif not st.session_state.get("interview_done"):
        progress = min(st.session_state.agent.question_count / 8, 1.0)
        st.progress(progress, text=f"Question {st.session_state.agent.question_count} of 8")

        for m in st.session_state.messages:
            with st.chat_message(m["role"]):
                st.write(m["content"])

        if st.session_state.agent.is_complete():
            st.success("You have completed the interview!")
            if st.button("Submit Interview"):
                st.session_state.interview_done = True
                st.rerun()
        else:
            u_input = st.chat_input("Type your answer here...")
            if u_input:
                st.session_state.messages.append({"role": "user", "content": u_input})
                with st.spinner("AI is thinking..."):
                    reply = st.session_state.agent.handle_response(u_input)
                st.session_state.messages.append({"role": "assistant", "content": reply})
                st.rerun()

    else:
        with st.spinner("Submitting and generating report..."):
            report = generate_report(
                st.session_state.agent.get_transcript(),
                match,
                match["round_name"]
            )
            anticheat_flags = analyze_anticheat(st.session_state.agent.get_transcript())
            save_candidate_result(
                match["candidate_name"],
                match,
                report,
                st.session_state.agent.get_transcript(),
                match["round_name"],
                anticheat_flags
            )
        st.balloons()
        st.success("Interview submitted successfully!")
        st.info("Thank you! Our HR team will get back to you shortly.")
        st.stop()

# ════════════════════════════════════════════════════
# ADMIN PORTAL
# ════════════════════════════════════════════════════
else:
    if not st.session_state.get("logged_in"):
        st.title("🏢 AI Interview Platform")
        st.subheader("Admin Login")
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            pw = st.text_input("Password", type="password")
            if st.button("Login", use_container_width=True):
                if pw == ADMIN_PASSWORD:
                    st.session_state.logged_in = True
                    st.rerun()
                else:
                    st.error("Incorrect password.")
        st.stop()

    col1, col2 = st.columns([8, 1])
    with col1:
        st.title("🏢 AI Interview Platform — Admin Panel")
    with col2:
        if st.button("Logout"):
            st.session_state.logged_in = False
            st.rerun()

    page = st.sidebar.selectbox("Navigate", ["Conduct Interview", "Scheduler", "Question Bank", "Results", "Analytics"])

    # ── CONDUCT INTERVIEW ────────────────────────────
    if page == "Conduct Interview":
        st.title("Conduct New Interview")

        if "agent" not in st.session_state:
            candidate_name = st.text_input("Candidate Name")
            job_role = st.text_input("Job Role", placeholder="e.g. Data Scientist, Backend Developer")
            technical_skills = st.text_input("Technical Skills", placeholder="e.g. Python, SQL, React")
            round_name = st.selectbox("Round", ["Technical", "HR", "Managerial"])

            if st.button("Start Interview"):
                if not candidate_name or not job_role:
                    st.error("Please fill in candidate name and job role.")
                else:
                    jd_data = {"role": job_role, "technical_skills": technical_skills}
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
            st.caption(f"Candidate: {st.session_state.candidate_name} | Role: {st.session_state.jd_data['role']} | Round: {st.session_state.round_name}")
            progress = min(st.session_state.agent.question_count / 8, 1.0)
            st.progress(progress, text=f"Question {st.session_state.agent.question_count} of 8")

            for m in st.session_state.messages:
                with st.chat_message(m["role"]):
                    st.write(m["content"])

            if st.session_state.agent.is_complete():
                st.success("Interview Complete!")
                if st.button("Generate Report"):
                    st.session_state.interview_done = True
                    st.rerun()
            else:
                u_input = st.chat_input("Type candidate answer here...")
                if u_input:
                    st.session_state.messages.append({"role": "user", "content": u_input})
                    with st.spinner("AI is thinking..."):
                        reply = st.session_state.agent.handle_response(u_input)
                    st.session_state.messages.append({"role": "assistant", "content": reply})
                    st.rerun()

        else:
            st.header("Evaluation Report")
            with st.spinner("Generating report..."):
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
            st.subheader("Anti-Cheat Analysis")
            for flag in anticheat_flags:
                if "No suspicious" in flag:
                    st.success(flag)
                else:
                    st.warning(flag)
            col1, col2 = st.columns(2)
            with col1:
                st.download_button("Download TXT", data=report, file_name=f"{st.session_state.candidate_name}_report.txt", mime="text/plain")
            with col2:
                pdf_path = generate_pdf(st.session_state.candidate_name, st.session_state.jd_data["role"], datetime.now().strftime("%Y-%m-%d"), report, st.session_state.round_name)
                with open(pdf_path, "rb") as f:
                    st.download_button("Download PDF", data=f, file_name=f"{st.session_state.candidate_name}_report.pdf", mime="application/pdf")
            if st.button("Start New Interview"):
                for key in list(st.session_state.keys()):
                    if key != "logged_in":
                        del st.session_state[key]
                st.rerun()

    # ── SCHEDULER ────────────────────────────────────
    elif page == "Scheduler":
        st.title("Interview Scheduler")
        st.info("Generate a unique link for each candidate. They only see the interview — no admin features.")
        schedules = load_schedules()

        c_name = st.text_input("Candidate Name")
        c_role = st.text_input("Job Role")
        c_skills = st.text_input("Technical Skills", placeholder="e.g. Python, SQL")
        c_round = st.selectbox("Round Type", ["Technical", "HR", "Managerial"])

        if st.button("Generate Interview Link"):
            if c_name and c_role:
                new_token = generate_interview_token(c_name, c_role, c_round)
                schedules.append({
                    "candidate_name": c_name,
                    "role": c_role,
                    "technical_skills": c_skills,
                    "round_name": c_round,
                    "token": new_token,
                    "created": str(datetime.now()),
                    "used": False
                })
                save_schedules(schedules)
                st.success("Interview link generated!")
                st.markdown("**Send this link to the candidate:**")
                st.code(f"https://interview-agent-plbbbrhpuubpaixuv2ejgz.streamlit.app/?token={new_token}")
            else:
                st.error("Please enter candidate name and job role.")

        st.divider()
        st.subheader("All Scheduled Interviews")
        if not schedules:
            st.info("No interviews scheduled yet.")
        else:
            for s in reversed(schedules):
                status = "✅ Used" if s.get("used") else "⏳ Pending"
                with st.expander(f"{status} — {s['candidate_name']} — {s['role']} — {s['round_name']}"):
                    st.markdown(f"**Candidate:** {s['candidate_name']}")
                    st.markdown(f"**Role:** {s['role']}")
                    st.markdown(f"**Round:** {s['round_name']}")
                    st.markdown(f"**Status:** {status}")
                    st.code(f"https://interview-agent-plbbbrhpuubpaixuv2ejgz.streamlit.app/?token={s['token']}")

    # ── QUESTION BANK ─────────────────────────────────
    elif page == "Question Bank":
        st.title("Question Bank")
        bank = load_question_bank()
        role_key = st.text_input("Role Name", placeholder="e.g. Data Scientist")
        qs_input = st.text_area("Questions (1 per line)")
        if st.button("Save to Bank"):
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
                with st.expander(f"{r} — {len(qs)} questions"):
                    for q in qs:
                        st.write(f"- {q}")
                    if st.button(f"Delete all for '{r}'", key=f"del_{r}"):
                        del bank[r]
                        save_question_bank(bank)
                        st.rerun()

    # ── RESULTS ───────────────────────────────────────
    elif page == "Results":
        st.title("Interview Results & Reports")
        all_c = load_all_candidates()
        if not all_c:
            st.info("No interview data yet.")
        else:
            for c in reversed(all_c):
                rounds = c.get("rounds", [])
                latest = rounds[-1] if rounds else {}
                score = extract_score(latest.get("report", ""))
                rec = extract_recommendation(latest.get("report", ""))
                badge = "🟢" if "Yes" in str(rec) else ("🔴" if "No" in str(rec) else "🟡")
                with st.expander(f"{badge} {c['candidate_name']} — {c['role']} — Score: {score}/10"):
                    for rnd in rounds:
                        st.markdown(f"### {rnd['round_name']} — {rnd['date']}")
                        st.text(rnd["report"])
                        st.markdown("**Anti-Cheat:**")
                        for flag in rnd.get("anticheat_flags", []):
                            if "No suspicious" in flag:
                                st.success(flag)
                            else:
                                st.warning(flag)
                        col1, col2 = st.columns(2)
                        with col1:
                            st.download_button("Download TXT", data=rnd["report"], file_name=f"{c['candidate_name']}_{rnd['round_name']}_report.txt", mime="text/plain", key=f"txt_{c['candidate_name']}_{rnd['round_name']}_{rnd['date']}")
                        with col2:
                            pdf_path = generate_pdf(c["candidate_name"], c["role"], rnd["date"], rnd["report"], rnd["round_name"])
                            with open(pdf_path, "rb") as f:
                                st.download_button("Download PDF", data=f, file_name=f"{c['candidate_name']}_{rnd['round_name']}_report.pdf", mime="application/pdf", key=f"pdf_{c['candidate_name']}_{rnd['round_name']}_{rnd['date']}")
                        if st.checkbox("Show Transcript", key=f"ts_{c['candidate_name']}_{rnd['round_name']}_{rnd['date']}"):
                            for msg in rnd["transcript"]:
                                label = "🤖 Interviewer" if msg["role"] == "interviewer" else "👤 Candidate"
                                st.markdown(f"**{label}:** {msg['content']}")

    # ── ANALYTICS ─────────────────────────────────────
    elif page == "Analytics":
        st.title("Hiring Analytics")
        all_c = load_all_candidates()
        if not all_c:
            st.info("No interview data available yet.")
        else:
            all_rounds = [r for c in all_c for r in c.get("rounds", [])]
            reports = [r["report"] for r in all_rounds]
            scores = [extract_score(rep) for rep in reports if extract_score(rep) > 0]
            if scores:
                col1, col2, col3 = st.columns(3)
                col1.metric("Total Candidates", len(all_c))
                col2.metric("Total Interviews", len(all_rounds))
                col3.metric("Average Score", f"{sum(scores)/len(scores):.1f}/10")
                st.divider()
                st.subheader("Score Distribution")
                st.plotly_chart(px.histogram(x=scores, nbins=10, labels={"x": "Score", "y": "Count"}, color_discrete_sequence=["#4F8BF9"]), use_container_width=True)
                rec_counts = {"Recommended": 0, "Not Recommended": 0, "Hold": 0}
                for r in all_rounds:
                    rec = extract_recommendation(r["report"])
                    if "Yes" in str(rec):
                        rec_counts["Recommended"] += 1
                    elif "No" in str(rec):
                        rec_counts["Not Recommended"] += 1
                    else:
                        rec_counts["Hold"] += 1
                st.subheader("Hire Recommendation Breakdown")
                st.plotly_chart(px.pie(values=list(rec_counts.values()), names=list(rec_counts.keys()), color_discrete_sequence=["#2ecc71", "#e74c3c", "#f39c12"]), use_container_width=True)
            else:
                st.info("Not enough scored data for charts yet.")
