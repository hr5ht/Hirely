import os
import time
import json
from groq import AsyncGroq
from dotenv import load_dotenv

from .ats.text_preprocessing import preprocess_text
from .ats.skill_extraction import load_skills, extract_skills
from .ats.similarity import calculate_similarity
from .ats.scorer import calculate_skill_score, generate_final_score, generate_heuristic_suggestions

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SKILLS_PATH = os.path.join(BASE_DIR, 'ats', 'skills_list.txt')
GLOBAL_SKILLS = load_skills(SKILLS_PATH)

class InterviewBrain:
    def __init__(self, model="llama-3.3-70b-versatile"):
        self.client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))
        self.model = model
        self.system_prompt = (
            "You are a 'Brutally Honest' evaluator. "
            "Your goal is to conduct a realistic, high-pressure assessment or interview. "
            "Analyze the provided context or Job Description (JD) and provide contextual, challenging questions. "
            "If the context is technical, focus on architecture and problem-solving without asking for code. "
            "If the context is academic (like 1st Grade Math), be a strict but fair teacher. "
            "After each answer, provide direct, sharp feedback. No fluff. No sugar-coating. "
            "Keep responses concise to ensure low latency for voice conversion."
        )

    async def generate_initial_question(self, jd_text):
        prompt = f"Based on this JD: {jd_text}\n\nGenerate the first tough interview question. Just the question, no intro."
        start_time = time.perf_counter()
        response = await self.client.chat.completions.create(
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ],
            model=self.model,
            max_tokens=150,
        )
        latency = time.perf_counter() - start_time
        print(f"  [Latency] Groq (Initial Q): {latency:.3f}s")
        return response.choices[0].message.content

    async def get_feedback(self, question, answer, non_verbal_flags=None):
        flags_text = f"Non-verbal flags observed: {', '.join(non_verbal_flags)}" if non_verbal_flags else "No non-verbal flags."
        prompt = (
            f"Question: {question}\n"
            f"Candidate Answer: {answer}\n"
            f"{flags_text}\n\n"
            "Provide direct, sharp, brutally honest feedback on this specific answer. Do not ask a new question yet.\n"
            "CRITICAL: You MUST evaluate the confidence and clarity scores DYNAMICALLY based on the quality of the candidate's answer. Do NOT just copy the placeholder values. Evaluate from 0 to 100.\n"
            "Return your response as a valid JSON object with EXACTLY these keys:\n"
            "{\n"
            "  \"feedback\": \"Your sharp feedback here\",\n"
            "  \"confidence\": <calculate a dynamic number 0-100 based on answer assertiveness>,\n"
            "  \"clarity\": <calculate a dynamic number 0-100 based on answer structure>,\n"
            "  \"tone\": \"<describe their tone in 2-3 words, e.g. Hesitant, Confident, Rambling>\"\n"
            "}"
        )
        start_time = time.perf_counter()
        response = await self.client.chat.completions.create(
            messages=[
                {"role": "system", "content": self.system_prompt + " You must ONLY output the JSON object."},
                {"role": "user", "content": prompt},
            ],
            model=self.model,
            max_tokens=300,
            response_format={"type": "json_object"}
        )
        latency = time.perf_counter() - start_time
        print(f"  [Latency] Groq (Feedback): {latency:.3f}s")
        return response.choices[0].message.content

    async def get_next_question(self, history, jd, context=""):
        history_text = "\n".join([f"Q: {h['q']}\nA: {h['a']}" for h in history])
        context_string = f"Relevant Candidate Context:\n{context}\n\n" if context else ""
        prompt = (
            f"Job Description: {jd}\n"
            f"{context_string}"
            f"Interview History:\n{history_text}\n\n"
            "Based on the history and relevant candidate context, ask the next challenging technical or behavioral question. "
            "CRITICAL: Do NOT ask about the exact same project from the immediate previous question. Explicitly shift the focus to a NEW project, language, or concept mentioned in the 'Relevant Candidate Context'. "
            "Just the question."
        )
        start_time = time.perf_counter()
        response = await self.client.chat.completions.create(
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ],
            model=self.model,
            max_tokens=150,
        )
        latency = time.perf_counter() - start_time
        print(f"  [Latency] Groq (Next Q): {latency:.3f}s")
        return response.choices[0].message.content

    async def generate_analysis(self, company, role, jd):
        prompt = (
            f"Analyze the following job application context:\n"
            f"Company: {company}\n"
            f"Role: {role}\n"
            f"Job Description: {jd}\n\n"
            "Provide a summary analysis as a JSON object with EXACTLY these keys:\n"
            "{\n"
            "  \"company_focus\": \"e.g., 70% DSA, 30% System Design\",\n"
            "  \"role_summary\": \"A short professional summary of the role expectations\",\n"
            "  \"company_vibe\": \"A short description of the company's interview culture\"\n"
            "}"
        )
        start_time = time.perf_counter()
        response = await self.client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are a senior technical recruiter analyst. Return ONLY JSON."},
                {"role": "user", "content": prompt},
            ],
            model=self.model,
            max_tokens=400,
            response_format={"type": "json_object"}
        )
        latency = time.perf_counter() - start_time
        print(f"  [Latency] Groq (Analysis): {latency:.3f}s")
        return response.choices[0].message.content

    async def get_resume_score(self, resume_text, jd_text):
        start_time = time.perf_counter()
        
        resume_clean = preprocess_text(resume_text)
        jd_clean = preprocess_text(jd_text)
        
        resume_skills_found = extract_skills(resume_clean, GLOBAL_SKILLS)
        jd_skills_found = extract_skills(jd_clean, GLOBAL_SKILLS)
        
        matched_skills = sorted(list(resume_skills_found.intersection(jd_skills_found)))
        missing_skills = sorted(list(jd_skills_found - resume_skills_found))
        
        semantic_score = calculate_similarity(resume_clean, jd_clean)
        skill_score = calculate_skill_score(jd_skills_found, resume_skills_found)
        final_score = generate_final_score(semantic_score, skill_score)
        
        improvement_suggestions = generate_heuristic_suggestions(missing_skills, semantic_score, final_score)
            
        latency = time.perf_counter() - start_time
        print(f"  [Latency] Native ATS Heuristics (Resume Score): {latency:.3f}s")
        
        result_dict = {
            "score": final_score,
            "feedback": " ".join(improvement_suggestions),
            "missing_keywords": missing_skills,
            "matching_keywords": matched_skills,
            "semantic_score": semantic_score,
            "skill_score": skill_score,
            "improvement_suggestions": improvement_suggestions
        }
        return json.dumps(result_dict)

    async def get_session_skills(self, transcript):
        prompt = (
            f"Review the following interview transcript:\n{transcript}\n\n"
            "Evaluate the candidate holistically across the entire session out of 100 on these three metrics. "
            "Return ONLY a valid JSON object with EXACT keys:\n"
            "{\n"
            "  \"tech_knowledge\": <0-100 score>,\n"
            "  \"behavioral_iq\": <0-100 score>,\n"
            "  \"problem_solving\": <0-100 score>\n"
            "}"
        )
        start_time = time.perf_counter()
        response = await self.client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are a senior technical evaluator. Output purely valid JSON."},
                {"role": "user", "content": prompt},
            ],
            model=self.model,
            max_tokens=200,
            response_format={"type": "json_object"}
        )
        latency = time.perf_counter() - start_time
        print(f"  [Latency] Groq (Session Skills): {latency:.3f}s")
        return response.choices[0].message.content
