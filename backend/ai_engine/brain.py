import os
from groq import AsyncGroq
from dotenv import load_dotenv

load_dotenv()

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
        response = await self.client.chat.completions.create(
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ],
            model=self.model,
            max_tokens=150,
        )
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
        response = await self.client.chat.completions.create(
            messages=[
                {"role": "system", "content": self.system_prompt + " You must ONLY output the JSON object."},
                {"role": "user", "content": prompt},
            ],
            model=self.model,
            max_tokens=300,
            response_format={"type": "json_object"}
        )
        return response.choices[0].message.content

    async def get_next_question(self, history, jd):
        history_text = "\n".join([f"Q: {h['q']}\nA: {h['a']}" for h in history])
        prompt = (
            f"Job Description: {jd}\n"
            f"Interview History:\n{history_text}\n\n"
            "Based on the history, ask the next challenging technical or behavioral question. Just the question."
        )
        response = await self.client.chat.completions.create(
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ],
            model=self.model,
            max_tokens=150,
        )
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
        response = await self.client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are a senior technical recruiter analyst. Return ONLY JSON."},
                {"role": "user", "content": prompt},
            ],
            model=self.model,
            max_tokens=400,
            response_format={"type": "json_object"}
        )
        return response.choices[0].message.content

    async def get_resume_score(self, resume_text, jd_text):
        prompt = (
            f"You are an expert Applicant Tracking System (ATS). Analyze the following resume against the Job Description (JD).\n\n"
            f"--- RESUME ---\n{resume_text}\n\n"
            f"--- JOB DESCRIPTION ---\n{jd_text}\n\n"
            "Provide an extremely strict analysis of how well the resume matches the JD.\n"
            "Return ONLY a valid JSON object with the following EXACT keys:\n"
            "{\n"
            "  \"score\": <a dynamic overall ATS score out of 100>,\n"
            "  \"feedback\": \"<a 2-3 sentence brutally honest summary of why they got this score>\",\n"
            "  \"missing_keywords\": [\"keyword1\", \"keyword2\"...],\n"
            "  \"matching_keywords\": [\"keyword1\", \"keyword2\"...]\n"
            "}"
        )
        response = await self.client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are an ATS parsing system. Output purely valid JSON."},
                {"role": "user", "content": prompt},
            ],
            model=self.model,
            max_tokens=500,
            response_format={"type": "json_object"}
        )
        return response.choices[0].message.content
