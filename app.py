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

def chat_with_claude(messages):
    response = client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=1024,
        messages=messages
    )
    return response.content[0].text

def generate_report(transcript, jd_data, round_name="Technical"):
    formatted = "\n".join([f"{msg['role'].upper()}: {msg['content']}" for msg in transcript])
    prompt = f"You are a senior hiring manager evaluating a {round_name} round interview.\n"
    prompt += f"Role: {jd_data['job_title']}\n"
    prompt += f"Technical Skills: {jd_data['technical_skills']}\n"
    prompt += f"Soft Skills: {jd_data['soft_skills']}\n"
    prompt += f"Difficulty Level: {jd_data.get('difficulty', 'Mid')}\n"
    prompt += f"TRANSCRIPT:\n{formatted}\n"
    prompt += "Provide scores out of 10 for: Technical Knowledge, Communication, Problem Solving, Confidence, Overall.\n"
    prompt += "List Strengths, Areas for Improvement, Hire Recommendation, and a Summary."
    return chat_with_claude([{"role": "user", "content": prompt}])

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
    wi
