# Hirely

An AI recruitment platform: companies post jobs, candidates apply with a resume, and every applicant gets an ATS match score and an AI-led technical interview with live proctoring. Recruiters review scores, transcripts and a PDF report for each candidate.

**Live demo:** https://hirely-hr5ht.vercel.app

## Features

- **ATS resume scoring:** an LLM compares the resume with the job description and returns an overall score, skill and context sub-scores, matched and missing skills, and suggestions.
- **Personalized AI interviews:** five rounds of questions generated from the candidate's own resume and the job description, with feedback, confidence and clarity scores after every answer.
- **RAG:** each round retrieves the most relevant resume and job-description excerpts for its topic and the candidate's last answer, so questions dig into what the candidate actually claimed.
- **Proctoring:** in-browser face and gaze tracking (MediaPipe) plus copy-paste and typing-speed checks; every alert lowers the integrity score and is listed in the report.
- **Reports:** a PDF per interview with scores, a skills-gap analysis, the proctoring audit trail and the full transcript.
- **Voice (optional):** questions read aloud and spoken answers transcribed.

## Tech Stack

| Area | Technology |
|---|---|
| Backend | Django 5.2 (WSGI) |
| LLM | Groq `qwen/qwen3.8-27b` via **LangChain** (`langchain-groq`) |
| RAG embeddings | Google Gemini `gemini-embedding-001` via LangChain (`langchain-google-genai`), with a keyword-ranking fallback |
| Database | PostgreSQL (Neon in production) |
| Speech | Deepgram (speech-to-text), ElevenLabs (text-to-speech) |
| Proctoring | MediaPipe Face Mesh (runs in the browser) |
| Reports | ReportLab |
| Frontend | Django templates, Tailwind CSS |
| Hosting | Vercel (serverless) |

All AI runs on hosted APIs, so the server needs no GPU and very little memory.

## How It Works

1. **Apply:** the resume PDF's text is extracted and scored against the job by the LLM.
2. **Interview:** each step (start, answer, voice answer, proctoring alert, end) is a stateless HTTP request, so the interview runs on serverless hosts and survives page reloads.
3. **Retrieve:** both documents are split into chunks and embedded; the closest resume and job-description chunks go into each question prompt.
4. **Evaluate:** when the interview ends, the LLM scores technical knowledge, behavioral IQ and problem solving, and the PDF report is generated.

## Project Structure

```
backend/
  ai_engine/
    brain.py          LangChain + Groq prompts: questions, feedback, ATS score, evaluation
    rag.py            Chunking, Gemini embeddings, cosine ranking, keyword fallback
    interview.py      Interview steps (start / answer / audio / proctor / end)
    audio_service.py  Deepgram and ElevenLabs clients
    reports.py        Final evaluation and PDF report
    views/            Pages and JSON endpoints: auth, candidate, recruiter, interview
    tests.py          Test suite (AI calls mocked)
  templates/          Django templates
  vercel.json         Vercel config
```

## Local Setup

Requires Python 3.11+ and PostgreSQL.

```bash
cd backend
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Create `backend/.env`:

```ini
DATABASE_URL="postgresql://user:password@localhost:5432/hirely"
GROQ_API_KEY="..."
GOOGLE_API_KEY="..."        # optional: semantic RAG (falls back to keyword ranking)
ELEVENLABS_API_KEY="..."    # optional: spoken questions
DEEPGRAM_API_KEY="..."      # optional: spoken answers
EMAIL_HOST="..."            # optional: SMTP for password resets and notifications (printed to the console if unset)
```

Then:

```bash
python manage.py migrate
python manage.py seed_demo          # optional: demo accounts and job postings
python manage.py runserver          # http://127.0.0.1:8000
python manage.py test ai_engine     # run the tests
```

| Key | Where to get it | Free tier |
|---|---|---|
| `GROQ_API_KEY` | console.groq.com | Yes |
| `GOOGLE_API_KEY` | aistudio.google.com | Yes, resets daily |
| `ELEVENLABS_API_KEY` | elevenlabs.io | Yes |
| `DEEPGRAM_API_KEY` | deepgram.com | Free credits |

## Deployment (Vercel)

Production also needs `SECRET_KEY` (any long random string); the app refuses to start without it.

1. Import the GitHub repo and set **Root Directory** to `backend`.
2. Add the environment variables above. For `DATABASE_URL`, use Neon's pooled connection string (hostname contains `-pooler`).
3. Run migrations once from your machine: `DATABASE_URL="<neon url>" python manage.py migrate`.

Every push to `main` then deploys automatically.
