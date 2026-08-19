import logging
import os
import json
import time
from langchain_groq import ChatGroq
from dotenv import load_dotenv

log = logging.getLogger(__name__)

load_dotenv()

class InterviewBrain:
    def __init__(self, model="qwen/qwen3.8-27b"):
        # Reasoning tokens count toward max_tokens and can leave short answers empty; "none" turns thinking off.
        # The Groq SDK retries 429/5xx with backoff (honouring Retry-After); one retry and a timeout
        # keep a slow call inside the serverless function's time limit.
        self.llm = ChatGroq(model=model, api_key=os.getenv("GROQ_API_KEY"), reasoning_effort="none",
                            max_retries=1, timeout=20)
        self.system_prompt = (
            "You are a 'Brutally Honest' evaluator. "
            "Your goal is to conduct a realistic, high-pressure assessment or interview. "
            "Analyze the provided context or Job Description (JD) and provide contextual, challenging questions. "
            "If the context is technical, focus on architecture and problem-solving without asking for code. "
            "If the context is academic (like 1st Grade Math), be a strict but fair teacher. "
            "After each answer, provide direct, sharp feedback. No fluff. No sugar-coating. "
            "Keep responses concise to ensure low latency for voice conversion."
        )

    def _chat(self, label, system, prompt, max_tokens=None, json_mode=False):
        llm = self.llm.bind(max_tokens=max_tokens) if max_tokens else self.llm
        if json_mode:  # JSON calls are the scoring/evaluation ones: the same answer should get the same score
            llm = llm.bind(response_format={"type": "json_object"}, temperature=0)
        start_time = time.perf_counter()
        response = llm.invoke([("system", system), ("human", prompt)])
        log.info("Groq %s took %.3fs", label, time.perf_counter() - start_time)
        return response.content

    def generate_initial_question(self, role, jd_excerpts, resume_excerpts=""):
        prompt = (
            f"Role: {role}\n"
            f"Relevant Job Description excerpts:\n{jd_excerpts or 'Not provided.'}\n\n"
            f"Relevant Candidate Resume excerpts:\n{resume_excerpts or 'Not provided.'}\n\n"
            "Generate the first tough interview question, tied to something specific in these excerpts. Just the question, no intro."
        )
        return self._chat("Initial Q", self.system_prompt, prompt, max_tokens=150)

    def get_feedback(self, question, answer, non_verbal_flags=None):
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
        return self._chat("Feedback", self.system_prompt + " You must ONLY output the JSON object.", prompt, max_tokens=300, json_mode=True)

    def get_next_question(self, history, jd_excerpts, resume_excerpts=""):
        history_text = "\n".join([f"Q: {h.get('question', h.get('q', 'N/A'))}\nA: {h.get('answer', h.get('a', 'N/A'))}" for h in history])
        resume_string = f"Candidate Resume Claims (relevant excerpts):\n{resume_excerpts}\n\n" if resume_excerpts else ""

        prompt = (
            f"Job Description (relevant excerpts): {jd_excerpts}\n"
            f"{resume_string}"
            f"Interview History:\n{history_text}\n\n"
            "Based on the job description, interview history, and candidate resume claims, ask the next challenging cross-examination question. "
            "CRITICAL SKILLS CROSS-EXAMINATION RULES:\n"
            "1. Read the candidate's resume claims. Identify explicit technical skills or frameworks listed (e.g., Docker, Django, React, Redis).\n"
            "2. Pick one of these explicit claims and construct a highly realistic, advanced debugging scenario or system constraint (e.g., 'Since you listed Docker, explain how you would resolve a bridge networking anomaly where a container exit-loops...').\n"
            "3. Do NOT ask a generic question. Shift focus dynamically to test if they can contextually validate their explicit CV claims.\n"
            "Just the question, no introductory fluff."
        )
        return self._chat("Next Q - Skills Cross-Exam", self.system_prompt, prompt, max_tokens=150)

    def get_summary(self, role, transcript_json):
        prompt = f"Summarize the performance of the candidate for the {role} role based on history: {transcript_json}"
        return self._chat("Summary", "You are a senior recruiter. Provide a concise, executive summary of the interview.", prompt)

    def get_resume_score(self, resume_text, jd_text):
        prompt = (
            f"Job Description:\n{jd_text}\n\nResume:\n{resume_text}\n\n"
            "Score this resume against the job description the way an ATS would.\n"
            "Return ONLY a valid JSON object with EXACT keys:\n"
            "{\n"
            "  \"skill_score\": <0-100, share of the JD's required skills/tools present in the resume>,\n"
            "  \"semantic_score\": <0-100, how well the experience and context match the role>,\n"
            "  \"score\": <0-100 overall match>,\n"
            "  \"matching_keywords\": [required skills/tools found in the resume],\n"
            "  \"missing_keywords\": [required skills/tools missing from the resume],\n"
            "  \"improvement_suggestions\": [up to 3 short, actionable suggestions]\n"
            "}"
        )
        result = json.loads(self._chat("ATS Resume Score", "You are an ATS resume screener. Output purely valid JSON.", prompt, max_tokens=700, json_mode=True))
        for key in ("score", "semantic_score", "skill_score"):
            result[key] = round(min(max(float(result.get(key) or 0), 0), 100), 2)
        suggestions = result.setdefault("improvement_suggestions", [])[:3]
        result["improvement_suggestions"] = suggestions
        result["feedback"] = " ".join(suggestions)
        result.setdefault("matching_keywords", [])
        result.setdefault("missing_keywords", [])
        return result

    def get_session_skills(self, transcript, jd=""):
        jd_prompt = f" and target Job Description:\n{jd}\n" if jd else ""
        prompt = (
            f"Review the following interview transcript:\n{transcript}\n{jd_prompt}\n"
            "Evaluate the candidate holistically across the entire session out of 100 on these three metrics. "
            "Additionally, isolate specific talent gaps and produce an Explainable AI (XAI) Gap Analysis Map showing exact areas where their answers lacked technical depth or keyword coverage (e.g. system partitioning, thread pooling) and suggest specific distributed systems/technical resources to study.\n"
            "Return ONLY a valid JSON object with EXACT keys:\n"
            "{\n"
            "  \"tech_knowledge\": <0-100 score>,\n"
            "  \"behavioral_iq\": <0-100 score>,\n"
            "  \"problem_solving\": <0-100 score>,\n"
            "  \"gap_analysis\": \"A detailed paragraph providing the structured talent gap analysis and recommended learning resources\"\n"
            "}"
        )
        return self._chat("Session Skills & XAI Gap", "You are a senior technical evaluator. Output purely valid JSON.", prompt, max_tokens=600, json_mode=True)
