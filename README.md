# Hirely

Hirely is a multi-tenant B2B AI-powered recruitment marketplace and live conversational assessment platform. The project enables companies to list technical job openings and screen candidates using conversational AI voice interviews, with client-side browser proctoring (gaze/face tracking) to verify candidate integrity during evaluations. All AI runs on hosted APIs, so the app deploys to serverless hosts such as Vercel.

---

## 🛠️ Tech Stack

* **Backend Framework**: Django (WSGI; gunicorn in production)
* **Database**: Serverless PostgreSQL (Neon DB / configured via `dj_database_url`)
* **Interview Pipeline**: stateless HTTP requests (start / answer / audio / proctor / end)
* **Large Language Model (LLM)**: Groq API via LangChain (`qwen/qwen3.8-27b`) — interview questions, feedback and ATS resume scoring
* **RAG**: Gemini embeddings (`gemini-embedding-001`) over resume and job description chunks, with keyword-ranking fallback
* **Speech-to-Text (STT)**: Deepgram API
* **Text-to-Speech (TTS)**: ElevenLabs API
* **Client-side Proctoring**: MediaPipe Face Mesh (Edge gaze tracking/face anomaly detection)

---

## ⚡ Installation & Setup Guide

### 1. Environment Setup
Navigate to the `backend` folder and create a `.env` file containing your credentials:

```bash
cd backend
touch .env
```

Define the required API keys and the PostgreSQL connection string in `.env`:
```ini
GROQ_API_KEY="your_groq_key"
GOOGLE_API_KEY="your_google_key"
ELEVENLABS_API_KEY="your_elevenlabs_key"
DEEPGRAM_API_KEY="your_deepgram_key"
DATABASE_URL="postgresql://user:password@host/dbname?sslmode=require"
```

### 2. Install & Migrate

```bash
python3 -m venv venv
source venv/bin/activate  # Or venv\Scripts\activate on Windows
pip install -r requirements.txt
python manage.py migrate
```

### 3. Start the Application
```bash
python manage.py runserver
```
The application will run locally at `http://127.0.0.1:8000`. Run the tests with `python manage.py test ai_engine`.

---

## 🚀 Deployment

Production needs `SECRET_KEY` set in addition to the keys above.

* **Vercel**: import the repo with Root Directory `backend` (`vercel.json` is included). Use Neon's pooled connection string for `DATABASE_URL`, and run `python manage.py migrate` against it once from your machine.
* **Render**: create a Blueprint from the repo; `render.yaml` runs migrations and gunicorn automatically.
