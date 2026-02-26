import streamlit as st
import anthropic
import json
import os
from datetime import datetime
import time
import hashlib
import plotly.express as px
from fpdf import FPDF

client = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])

RESULTS_FILE = "candidates.json"
QUESTION_BANK_FILE = "question_bank.json"
SCHEDULES_FILE = "schedules.json"
ADMIN_PASSWORD = "admin123"  # 👈 change this to your own password

def chat_with_claude(system_prompt, messages):
    response = client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=1024,
        system=system_prompt,
        messages=messages
    )
    return response.content[0].text

def generate_report(transcript, jd_data, round_name="Technical"):
    formatted = "\n".join([f"{msg['role'].upper()}: {msg['content']}" for msg in transcript])
    system = "You are a senior hiring manager. Evaluate interview transcripts objectively and provide detailed assessments."
    prompt = f"Evaluate this {round_name} round interview.\n"
    prompt += f"Role: {jd_data['job_title']}\n"
    prompt += f"Technical Skills: {jd_data['technical_skills']}\n"
    prompt += f"Soft Skills: {jd_data['soft_skills']}\n"
    prompt += f"Difficulty Level: {jd_data.get('difficulty', 'Mid')}\n"
    prompt += f"TRANSCRIPT:\n{formatted}\n"
    prompt += "Provide scores out of 10 for: Technical Knowledge, Communication, Problem Solving, Confidence, Overall.\n"
    prompt += "List Strengths, Areas for Improvement, Hire Recommendation, and a Summary."
    return chat_with_claude(system, [{"role": "user", "content": prompt}])

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

def save_candidate_result(candidate_name, jd_data, report, transcript, round_name, anticheat_flags):
    all_results = load_all_candidates()
    existing = next((c for c in all_results if c["candidate_name"] == candidate_name and c["role"] == jd_data["job_title"]), None)
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
            "role": jd_data["job_title"],
            "technical_skills": jd_data["technical_skills"],
            "soft_skills": jd_data["soft_skills"],
            "experience_required": jd_data["experience_required"],
            "difficulty": jd_data.get("difficulty", "Mid"),
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "rounds": [new_round]
        })
    with open(RESULTS_FILE, "w") as f:
        json.dump(all_results, f, indent=2)

def load_all_candidates():
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE, "r") as f:
            return json.load(f)
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

def generate_interview_token(candidate_name, role, round_name):
    raw = f"{candidate_name}_{role}_{round_name}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    return hashlib.md5(raw.encode()).hexdigest()[:10]

def extract_score(report_text):
    for line in report_text.split("\n"):
        if "Overall" in line and "/10" in line:
            try:
                return float(line.split(":")[1].strip().replace("/10", "").strip())
            except:
                return 0
    return 0

def extract_recommendation(report_text):
    for line in report_text.split("\n"):
        if "HIRE RECOMMENDATION" in line.upper():
            try:
                return line.split(":")[1].strip()
            except:
                return "N/A"
    return "N/A"

def extract_all_scores(report_text):
    scores = {}
    categories = ["Technical Knowledge", "Communication", "Problem Solving", "Confidence", "Overall"]
    for line in report_text.split("\n"):
        for cat in categories:
            if cat in line and "/10" in line:
                try:
                    scores[cat] = float(line.split(":")[1].strip().replace("/10", "").strip())
                except:
                    scores[cat] = 0
    return scores

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
            elif line.strip() == "" or any(k in line.upper() for k in ["HIRE", "SUMMARY", "STRENGTH"]):
                break
    return weaknesses

def analyze_anticheat(conversation_log, response_times):
    flags = []
    for i, msg in enumerate(conversation_log):
        if msg["role"] == "candidate":
            answer = msg["content"]
            word_count = len(answer.split())
            response_time = response_times.get(i, 999)
            if word_count < 5:
                flags.append(f"Q{i+1}: Very short answer ({word_count} words)")
            if response_time < 3 and word_count > 50:
                flags.append(f"Q{i+1}: Fast response ({response_time}s) for long answer — possible copy-paste")
            if word_count > 200:
                flags.append(f"Q{i+1}: Very long answer ({word_count} words) — possible pre-written")
    return flags if flags else ["No suspicious activity detected"]

class InterviewAgent:
    def __init__(self, jd_data, candidate_name, custom_questions=None, round_name="Technical Round"):
        self.jd_data = jd_data
        self.candidate_name = candidate_name
        self.question_count = 0
        self.max_questions = 10
        self.conversation_log = []
        self.chat_history = []
        self.custom_questions = custom_questions or []
        self.round_name = round_name
        self.response_times = {}
        self.last_question_time = time.time()
        self._initialize_agent()

def _initialize_agent(self):
    difficulty = self.jd_data.get("difficulty", "Mid")
    if difficulty == "Junior":
        diff_instruction = "Ask basic beginner-friendly questions. Be extra encouraging."
    elif difficulty == "Senior":
        diff_instruction = "Ask deep advanced questions. Expect detailed expert-level answers."
    else:
        diff_instruction = "Ask moderate questions for a mid-level professional."
    round_instructions = {
        "HR Round": "Focus on cultural fit, salary expectations, notice period, and career goals.",
        "Technical Round": "Focus on technical skills, coding concepts, system design, and problem solving.",
        "Managerial Round": "Focus on leadership, team management, conflict resolution, and strategic thinking."
    }
    round_focus = round_instructions.get(self.round_name, "Cover technical and behavioral questions.")
    
    self.system_prompt = f"You are conducting the {self.round_name} of a job interview. "
    self.system_prompt += f"Candidate: {self.candidate_name}. "
    self.system_prompt += f"Role: {self.jd_data['job_title']}. "
    self.system_prompt += f"Technical Skills to assess: {self.jd_data['technical_skills']}. "
    self.system_prompt += f"Soft Skills to assess: {self.jd_data['soft_skills']}. "
    self.system_prompt += f"Experience Required: {self.jd_data['experience_required']}. "
    self.system_prompt += f"Difficulty: {difficulty}. {diff_instruction} "
    self.system_prompt += f"Round Focus: {round_focus} "
    if self.custom_questions:
        self.system_prompt += f"You MUST include these questions: {self.custom_questions}. "
    self.system_prompt += "Rules: Ask ONE question at a time. Be warm and professional. "
    self.system_prompt += "Never reveal scores during interview. "
    self.system_prompt += f"After {self.max_questions} questions wrap up politely. "
    self.system_prompt += f"Start by greeting {self.candidate_name}, mention this is the {self.round_name}, and ask them to introduce themselves."
    
    # Start conversation with opening message
    opening_prompt = "Begin the interview now by greeting the candidate and asking them to introduce themselves."
    self.chat_history.append({"role": "user", "content": opening_prompt})
    response = chat_with_claude(self.system_prompt, self.chat_history)
    self.chat_history.append({"role": "assistant", "content": response})

def respond(self, candidate_message):
    response_time = round(time.time() - self.last_question_time, 1)
    self.response_times[self.question_count] = response_time
    self.question_count += 1
    self.conversation_log.append({"role": "candidate", "content": candidate_message})
    if self.question_count >= self.max_questions - 1:
        candidate_message += " [Last question, wrap up professionally]"
    self.chat_history.append({"role": "user", "content": candidate_message})
    response = chat_with_claude(self.system_prompt, self.chat_history)
    self.chat_history.append({"role": "assistant", "content": response})
    self.conversation_log.append({"role": "interviewer", "content": response})
    self.last_question_time = time.time()
    return response

    def is_interview_complete(self):
        return self.question_count >= self.max_questions

    def get_full_transcript(self):
        return self.conversation_log

    def get_response_times(self):
        return self.response_times


# ════════════════════════════════════════════════════
# APP START — DETECT MODE
# ════════════════════════════════════════════════════
st.set_page_config(page_title="AI Interview Agent", page_icon="🤖", layout="wide")

query_params = st.query_params
token_from_url = query_params.get("token", None)
mode = query_params.get("mode", None)

schedules = load_schedules()
matched_schedule = None
if token_from_url:
    matched_schedule = next((s for s in schedules if s["token"] == token_from_url and not s.get("used", False)), None)

# ════════════════════════════════════════════════════
# CANDIDATE MODE — triggered by token in URL
# ════════════════════════════════════════════════════
if token_from_url or mode == "candidate":
    st.title("🤖 AI Interview Agent")
    st.caption("Welcome to your interview session")

    if not matched_schedule and token_from_url:
        st.error("Invalid or expired interview link. Please contact HR for a new link.")
        st.stop()

    if "agent" not in st.session_state:
        if matched_schedule:
            st.info(f"Welcome **{matched_schedule['candidate_name']}** — You are interviewing for **{matched_schedule['role']}** | Round: **{matched_schedule['round_name']}**")
            st.markdown("---")
            st.markdown("**Instructions:**")
            st.markdown("- Answer each question honestly and clearly")
            st.markdown("- Take your time before responding")
            st.markdown("- The interview will have 10 questions")
            st.markdown("- Click Start when you are ready")

            if st.button("Start My Interview"):
                jd_data = {
                    "job_title": matched_schedule["role"],
                    "technical_skills": matched_schedule.get("technical_skills", []),
                    "soft_skills": matched_schedule.get("soft_skills", []),
                    "experience_required": matched_schedule.get("experience_required", ""),
                    "difficulty": matched_schedule.get("difficulty", "Mid")
                }
                with st.spinner("Setting up your interview..."):
                    agent = InterviewAgent(jd_data, matched_schedule["candidate_name"], [], matched_schedule["round_name"])
                    opening = agent.respond("Hello, I am ready for the interview.")
                    st.session_state.agent = agent
                    st.session_state.jd_data = jd_data
                    st.session_state.candidate_name = matched_schedule["candidate_name"]
                    st.session_state.round_name = matched_schedule["round_name"]
                    st.session_state.messages = [{"role": "assistant", "content": opening}]
                    st.session_state.interview_done = False
                    for s in schedules:
                        if s["token"] == token_from_url:
                            s["used"] = True
                    save_schedules(schedules)
                st.rerun()

    elif not st.session_state.get("interview_done"):
        progress = min(st.session_state.agent.question_count / 10, 1.0)
        st.progress(progress, text=f"Question {st.session_state.agent.question_count} of 10")

        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])

        if st.session_state.agent.is_interview_complete():
            st.success("You have completed the interview!")
            if st.button("Submit Interview"):
                st.session_state.interview_done = True
                st.rerun()
        else:
            user_input = st.chat_input("Type your answer here...")
            if user_input:
                st.session_state.messages.append({"role": "user", "content": user_input})
                response = st.session_state.agent.respond(user_input)
                st.session_state.messages.append({"role": "assistant", "content": response})
                st.rerun()

    else:
        with st.spinner("Submitting your interview..."):
            report = generate_report(
                st.session_state.agent.get_full_transcript(),
                st.session_state.jd_data,
                st.session_state.round_name
            )
            anticheat_flags = analyze_anticheat(
                st.session_state.agent.get_full_transcript(),
                st.session_state.agent.get_response_times()
            )
            save_candidate_result(
                st.session_state.candidate_name,
                st.session_state.jd_data,
                report,
                st.session_state.agent.get_full_transcript(),
                st.session_state.round_name,
                anticheat_flags
            )
        st.balloons()
        st.success("Your interview has been submitted successfully!")
        st.info("Thank you for your time. Our HR team will get back to you shortly.")
        st.stop()

# ════════════════════════════════════════════════════
# COMPANY/ADMIN MODE — default view
# ════════════════════════════════════════════════════
else:
    # ── ADMIN LOGIN ──────────────────────────────────
    if not st.session_state.get("admin_logged_in"):
        st.title("🏢 AI Interview Platform")
        st.subheader("Company Login")
        st.markdown("---")
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            password = st.text_input("Enter Admin Password", type="password")
            if st.button("Login", use_container_width=True):
                if password == ADMIN_PASSWORD:
                    st.session_state.admin_logged_in = True
                    st.rerun()
                else:
                    st.error("Incorrect password. Please try again.")
        st.stop()

    # ── ADMIN PANEL ──────────────────────────────────
    col1, col2 = st.columns([8, 1])
    with col1:
        st.title("🏢 AI Interview Platform — Admin Panel")
    with col2:
        if st.button("Logout"):
            st.session_state.admin_logged_in = False
            st.rerun()

    page = st.sidebar.selectbox("Navigation", [
        "Conduct Interview",
        "Admin Dashboard",
        "Comparison View",
        "Question Bank Manager",
        "Interview Scheduler",
        "Analytics"
    ])

    # ── PAGE 1 — CONDUCT INTERVIEW ───────────────────
    if page == "Conduct Interview":
        st.title("Conduct New Interview")

        if "agent" not in st.session_state:
            st.subheader("Candidate Details")
            candidate_name = st.text_input("Candidate Name")
            st.subheader("Job Details")
            job_title = st.text_input("Job Title", placeholder="e.g. Data Scientist, Frontend Developer...")
            technical_skills = st.text_input("Technical Skills (comma separated)", placeholder="e.g. Python, SQL")
            soft_skills = st.text_input("Soft Skills (comma separated)", placeholder="e.g. communication, leadership")
            experience = st.text_input("Experience Required", placeholder="e.g. 2 years, Fresher")
            difficulty = st.radio("Difficulty Level", ["Junior", "Mid", "Senior"], index=1, horizontal=True)
            round_name = st.selectbox("Interview Round", ["HR Round", "Technical Round", "Managerial Round"])

            st.subheader("Custom Must-Ask Questions (Optional)")
            question_bank = load_question_bank()
            role_questions = question_bank.get(job_title, []) if job_title else []
            custom_questions = []
            if role_questions:
                st.info(f"Found {len(role_questions)} saved questions for '{job_title}'")
                if st.checkbox("Include saved questions", value=True):
                    custom_questions = role_questions
            extra_q = st.text_area("Extra must-ask questions (one per line)")
            if extra_q:
                custom_questions += [q.strip() for q in extra_q.split("\n") if q.strip()]

            if st.button("Start Interview"):
                if not candidate_name:
                    st.error("Please enter candidate name.")
                elif not job_title:
                    st.error("Please enter a job title.")
                else:
                    jd_data = {
                        "job_title": job_title,
                        "technical_skills": [s.strip() for s in technical_skills.split(",")],
                        "soft_skills": [s.strip() for s in soft_skills.split(",")],
                        "experience_required": experience,
                        "difficulty": difficulty
                    }
                    with st.spinner("Setting up interview..."):
                        agent = InterviewAgent(jd_data, candidate_name, custom_questions, round_name)
                        opening = agent.respond("Hello, I am ready for the interview.")
                        st.session_state.agent = agent
                        st.session_state.jd_data = jd_data
                        st.session_state.candidate_name = candidate_name
                        st.session_state.round_name = round_name
                        st.session_state.messages = [{"role": "assistant", "content": opening}]
                        st.session_state.interview_done = False
                    st.rerun()

        elif not st.session_state.get("interview_done"):
            st.caption(f"Candidate: {st.session_state.candidate_name} | Role: {st.session_state.jd_data['job_title']} | Round: {st.session_state.round_name} | Level: {st.session_state.jd_data.get('difficulty','Mid')}")
            progress = min(st.session_state.agent.question_count / 10, 1.0)
            st.progress(progress, text=f"Question {st.session_state.agent.question_count} of 10")
            for msg in st.session_state.messages:
                with st.chat_message(msg["role"]):
                    st.write(msg["content"])
            if st.session_state.agent.is_interview_complete():
                st.success("Interview Complete!")
                if st.button("Generate Evaluation Report"):
                    st.session_state.interview_done = True
                    st.rerun()
            else:
                user_input = st.chat_input("Type candidate answer here...")
                if user_input:
                    st.session_state.messages.append({"role": "user", "content": user_input})
                    response = st.session_state.agent.respond(user_input)
                    st.session_state.messages.append({"role": "assistant", "content": response})
                    st.rerun()

        else:
            st.header("Evaluation Report")
            round_name = st.session_state.round_name
            with st.spinner("Generating report..."):
                report = generate_report(st.session_state.agent.get_full_transcript(), st.session_state.jd_data, round_name)
                anticheat_flags = analyze_anticheat(st.session_state.agent.get_full_transcript(), st.session_state.agent.get_response_times())
                save_candidate_result(st.session_state.candidate_name, st.session_state.jd_data, report, st.session_state.agent.get_full_transcript(), round_name, anticheat_flags)
            st.text(report)
            st.subheader("Anti-Cheat Analysis")
            for flag in anticheat_flags:
                if "No suspicious" in flag:
                    st.success(flag)
                else:
                    st.warning(flag)
            col1, col2 = st.columns(2)
            with col1:
                st.download_button(label="Download TXT", data=report, file_name=f"{st.session_state.candidate_name}_{st.session_state.jd_data['job_title']}_{round_name}_report.txt", mime="text/plain")
            with col2:
                pdf_path = generate_pdf(st.session_state.candidate_name, st.session_state.jd_data['job_title'], datetime.now().strftime("%Y-%m-%d %H:%M"), report, round_name)
                with open(pdf_path, "rb") as f:
                    st.download_button(label="Download PDF", data=f, file_name=f"{st.session_state.candidate_name}_{st.session_state.jd_data['job_title']}_{round_name}_report.pdf", mime="application/pdf")
            if st.button("Start New Interview"):
                for key in list(st.session_state.keys()):
                    if key != "admin_logged_in":
                        del st.session_state[key]
                st.rerun()

    # ── PAGE 2 — ADMIN DASHBOARD ─────────────────────
    elif page == "Admin Dashboard":
        st.title("Admin Dashboard")
        all_candidates = load_all_candidates()
        if not all_candidates:
            st.info("No candidates interviewed yet.")
        else:
            total = len(all_candidates)
            roles = list(set([c["role"] for c in all_candidates]))
            all_reports = [r["report"] for c in all_candidates for r in c.get("rounds", [])]
            hired = sum(1 for r in all_reports if "Yes" in extract_recommendation(r))
            scores = [extract_score(r) for r in all_reports if extract_score(r) > 0]
            avg_score = round(sum(scores) / len(scores), 1) if scores else 0
            col1, col2, col3, col4, col5 = st.columns(5)
            col1.metric("Total Candidates", total)
            col2.metric("Roles", len(roles))
            col3.metric("Recommended", hired)
            col4.metric("Not Recommended", total - hired)
            col5.metric("Avg Score", f"{avg_score}/10")
            st.divider()
            col1, col2 = st.columns(2)
            with col1:
                selected_role = st.selectbox("Filter by Role", ["All Roles"] + roles)
            with col2:
                selected_diff = st.selectbox("Filter by Difficulty", ["All", "Junior", "Mid", "Senior"])
            filtered = all_candidates
            if selected_role != "All Roles":
                filtered = [c for c in filtered if c["role"] == selected_role]
            if selected_diff != "All":
                filtered = [c for c in filtered if c.get("difficulty", "Mid") == selected_diff]
            st.markdown(f"Showing **{len(filtered)}** candidate(s)")
            st.divider()
            for candidate in reversed(filtered):
                rounds = candidate.get("rounds", [])
                latest_report = rounds[-1]["report"] if rounds else ""
                score = extract_score(latest_report)
                rec = extract_recommendation(latest_report)
                badge = "🟢" if "Yes" in str(rec) else ("🔴" if "No" in str(rec) else "🟡")
                rounds_done = ", ".join([r["round_name"] for r in rounds])
                with st.expander(f"{badge} {candidate['candidate_name']} — {candidate['role']} — {rounds_done} — Score: {score}/10"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown(f"**Candidate:** {candidate['candidate_name']}")
                        st.markdown(f"**Role:** {candidate['role']}")
                        st.markdown(f"**Difficulty:** {candidate.get('difficulty','Mid')}")
                        st.markdown(f"**Rounds:** {rounds_done}")
                    with col2:
                        st.markdown(f"**Technical Skills:** {', '.join(candidate['technical_skills'])}")
                        st.markdown(f"**Experience:** {candidate['experience_required']}")
                        st.markdown(f"**Last Updated:** {candidate.get('last_updated', candidate['date'])}")
                    for rnd in rounds:
                        st.divider()
                        st.markdown(f"### {rnd['round_name']} — {rnd['date']}")
                        st.text(rnd["report"])
                        st.markdown("**Anti-Cheat Flags:**")
                        for flag in rnd.get("anticheat_flags", []):
                            if "No suspicious" in flag:
                                st.success(flag)
                            else:
                                st.warning(flag)
                        col1, col2 = st.columns(2)
                        with col1:
                            st.download_button(label=f"Download TXT", data=rnd["report"], file_name=f"{candidate['candidate_name']}_{rnd['round_name']}_report.txt", mime="text/plain", key=f"txt_{candidate['candidate_name']}_{rnd['round_name']}_{rnd['date']}")
                        with col2:
                            pdf_path = generate_pdf(candidate["candidate_name"], candidate["role"], rnd["date"], rnd["report"], rnd["round_name"])
                            with open(pdf_path, "rb") as f:
                                st.download_button(label=f"Download PDF", data=f, file_name=f"{candidate['candidate_name']}_{rnd['round_name']}_report.pdf", mime="application/pdf", key=f"pdf_{candidate['candidate_name']}_{rnd['round_name']}_{rnd['date']}")
                        if st.checkbox("Show Transcript", key=f"t_{candidate['candidate_name']}_{rnd['round_name']}_{rnd['date']}"):
                            for msg in rnd["transcript"]:
                                label = "🤖 Interviewer" if msg["role"] == "interviewer" else "👤 Candidate"
                                st.markdown(f"**{label}:** {msg['content']}")

    # ── PAGE 3 — COMPARISON VIEW ─────────────────────
    elif page == "Comparison View":
        st.title("Candidate Comparison")
        all_candidates = load_all_candidates()
        if len(all_candidates) < 2:
            st.info("You need at least 2 interviewed candidates to compare.")
        else:
            roles = list(set([c["role"] for c in all_candidates]))
            selected_role = st.selectbox("Select Role", roles)
            role_candidates = [c for c in all_candidates if c["role"] == selected_role]
            if len(role_candidates) < 2:
                st.warning(f"Only {len(role_candidates)} candidate for this role. Need at least 2.")
            else:
                names = [c["candidate_name"] for c in role_candidates]
                selected_names = st.multiselect("Select Candidates", names, default=names[:2])
                selected_candidates = [c for c in role_candidates if c["candidate_name"] in selected_names]
                round_options = list(set([r["round_name"] for c in selected_candidates for r in c.get("rounds", [])]))
                selected_round = st.selectbox("Select Round", round_options) if round_options else None
                if len(selected_candidates) >= 2 and selected_round:
                    st.divider()
                    cols = st.columns(len(selected_candidates))
                    for i, candidate in enumerate(selected_candidates):
                        round_data = next((r for r in candidate.get("rounds", []) if r["round_name"] == selected_round), None)
                        with cols[i]:
                            if round_data:
                                scores = extract_all_scores(round_data["report"])
                                rec = extract_recommendation(round_data["report"])
                                badge = "🟢" if "Yes" in str(rec) else ("🔴" if "No" in str(rec) else "🟡")
                                st.markdown(f"### {badge} {candidate['candidate_name']}")
                                st.markdown(f"**Recommendation:** {rec}")
                                st.divider()
                                for category, score in scores.items():
                                    st.metric(category, f"{score}/10")
                            else:
                                st.markdown(f"### {candidate['candidate_name']}")
                                st.warning(f"No {selected_round} data.")
                    st.divider()
                    cols2 = st.columns(len(selected_candidates))
                    for i, candidate in enumerate(selected_candidates):
                        round_data = next((r for r in candidate.get("rounds", []) if r["round_name"] == selected_round), None)
                        with cols2[i]:
                            st.markdown(f"**{candidate['candidate_name']}**")
                            if round_data:
                                st.text(round_data["report"])

    # ── PAGE 4 — QUESTION BANK ───────────────────────
    elif page == "Question Bank Manager":
        st.title("Question Bank Manager")
        question_bank = load_question_bank()
        new_role = st.text_input("Role Name", placeholder="e.g. Data Scientist, HR Manager")
        new_questions = st.text_area("Questions (one per line)")
        if st.button("Save Questions"):
            if new_role and new_questions:
                questions_list = [q.strip() for q in new_questions.split("\n") if q.strip()]
                question_bank[new_role] = question_bank.get(new_role, []) + questions_list
                save_question_bank(question_bank)
                st.success(f"Saved {len(questions_list)} questions for '{new_role}'")
                st.rerun()
            else:
                st.error("Please enter both role and questions.")
        st.divider()
        if not question_bank:
            st.info("No questions saved yet.")
        else:
            for role, questions in question_bank.items():
                with st.expander(f"{role} — {len(questions)} questions"):
                    for i, q in enumerate(questions, 1):
                        col1, col2 = st.columns([5, 1])
                        with col1:
                            st.markdown(f"{i}. {q}")
                        with col2:
                            if st.button("Delete", key=f"del_{role}_{i}"):
                                question_bank[role].pop(i - 1)
                                save_question_bank(question_bank)
                                st.rerun()
                    if st.button(f"Delete All for '{role}'", key=f"delall_{role}"):
                        del question_bank[role]
                        save_question_bank(question_bank)
                        st.rerun()

    # ── PAGE 5 — INTERVIEW SCHEDULER ─────────────────
    elif page == "Interview Scheduler":
        st.title("Interview Scheduler")
        schedules = load_schedules()
        st.subheader("Schedule a New Interview")
        st.info("Generate a unique link for each candidate. They only see the interview chat — no admin features.")
        col1, col2 = st.columns(2)
        with col1:
            sch_candidate = st.text_input("Candidate Name")
            sch_role = st.text_input("Job Title")
            sch_experience = st.text_input("Experience Required")
        with col2:
            sch_technical = st.text_input("Technical Skills (comma separated)")
            sch_soft = st.text_input("Soft Skills (comma separated)")
            sch_difficulty = st.selectbox("Difficulty", ["Junior", "Mid", "Senior"])
            sch_round = st.selectbox("Round", ["HR Round", "Technical Round", "Managerial Round"])
        if st.button("Generate Interview Link"):
            if sch_candidate and sch_role:
                token = generate_interview_token(sch_candidate, sch_role, sch_round)
                schedules.append({
                    "candidate_name": sch_candidate,
                    "role": sch_role,
                    "technical_skills": [s.strip() for s in sch_technical.split(",")],
                    "soft_skills": [s.strip() for s in sch_soft.split(",")],
                    "experience_required": sch_experience,
                    "difficulty": sch_difficulty,
                    "round_name": sch_round,
                    "token": token,
                    "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "used": False
                })
                save_schedules(schedules)
                app_url = "https://interview-agent-plbbbrhpuubpaixuv2ejgz.streamlit.app"
                full_link = f"{app_url}/?token={token}"
                st.success("Interview link generated!")
                st.markdown("**Send this link to the candidate:**")
                st.code(full_link)
                st.rerun()
            else:
                st.error("Please fill candidate name and job title.")
        st.divider()
        st.subheader("All Scheduled Interviews")
        if not schedules:
            st.info("No interviews scheduled yet.")
        else:
            for s in reversed(schedules):
                status = "✅ Used" if s.get("used") else "⏳ Pending"
                with st.expander(f"{status} — {s['candidate_name']} — {s['role']} — {s['round_name']} — {s['created']}"):
                    st.markdown(f"**Candidate:** {s['candidate_name']}")
                    st.markdown(f"**Role:** {s['role']}")
                    st.markdown(f"**Round:** {s['round_name']}")
                    st.markdown(f"**Status:** {status}")

    # ── PAGE 6 — ANALYTICS ───────────────────────────
    elif page == "Analytics":
        st.title("Analytics Dashboard")
        all_candidates = load_all_candidates()
        if not all_candidates:
            st.info("No data yet. Run some interviews first!")
        else:
            all_rounds = [r for c in all_candidates for r in c.get("rounds", [])]
            if not all_rounds:
                st.info("No completed rounds yet.")
            else:
                total_candidates = len(all_candidates)
                total_interviews = len(all_rounds)
                all_scores = [extract_score(r["report"]) for r in all_rounds if extract_score(r["report"]) > 0]
                avg_score = round(sum(all_scores) / len(all_scores), 1) if all_scores else 0
                pass_count = sum(1 for r in all_rounds if "Yes" in extract_recommendation(r["report"]))
                pass_rate = round((pass_count / total_interviews) * 100, 1) if total_interviews > 0 else 0
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Total Candidates", total_candidates)
                col2.metric("Total Interviews", total_interviews)
                col3.metric("Avg Score", f"{avg_score}/10")
                col4.metric("Pass Rate", f"{pass_rate}%")
                st.divider()
                if all_scores:
                    st.subheader("Score Distribution")
                    fig = px.histogram(x=all_scores, nbins=10, labels={"x": "Score", "y": "Count"}, color_discrete_sequence=["#4F8BF9"])
                    st.plotly_chart(fig, use_container_width=True)
                role_scores = {}
                for c in all_candidates:
                    for r in c.get("rounds", []):
                        score = extract_score(r["report"])
                        if score > 0:
                            role_scores.setdefault(c["role"], []).append(score)
                if role_scores:
                    st.subheader("Average Score by Role")
                    avg_by_role = {role: round(sum(s)/len(s), 1) for role, s in role_scores.items()}
                    fig2 = px.bar(x=list(avg_by_role.keys()), y=list(avg_by_role.values()), labels={"x": "Role", "y": "Avg Score"}, color_discrete_sequence=["#4F8BF9"])
                    st.plotly_chart(fig2, use_container_width=True)
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
                fig3 = px.pie(values=list(rec_counts.values()), names=list(rec_counts.keys()), color_discrete_sequence=["#2ecc71", "#e74c3c", "#f39c12"])
                st.plotly_chart(fig3, use_container_width=True)
                all_weaknesses = []
                for r in all_rounds:
                    all_weaknesses += extract_weaknesses(r["report"])
                if all_weaknesses:
                    st.subheader("Most Common Weak Areas")
                    weakness_counts = {}
                    for w in all_weaknesses:
                        key = w[:50]
                        weakness_counts[key] = weakness_counts.get(key, 0) + 1
                    sorted_weaknesses = sorted(weakness_counts.items(), key=lambda x: x[1], reverse=True)[:10]
                    for w, count in sorted_weaknesses:
                        st.markdown(f"- **{w}** — {count} time(s)")
