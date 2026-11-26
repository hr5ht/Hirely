# Hirely

An AI recruitment platform. Companies post jobs, candidates apply with a resume, and every applicant gets an ATS match score and an AI-led voice interview with live proctoring. Recruiters review the scores, transcripts and a PDF report for each candidate.

## Features

- **ATS scoring:** an LLM compares the resume with the job description and returns a score, matched and missing skills, and suggestions.
- **AI interviews:** questions built from the candidate's resume and the job, using RAG over both. Each answer gets feedback and confidence and clarity scores. Recruiters set the number of rounds, must-ask questions and time limits.
- **Voice:** spoken answers stream to Deepgram while the candidate talks, and questions are read aloud by ElevenLabs.
- **Proctoring:** face and gaze tracking in the browser (MediaPipe), plus copy-paste and typing-speed checks.
- **Reports:** a PDF per interview with scores, a skills-gap analysis, proctoring alerts and the transcript.
- **Recruiter tools:** filter, compare and export candidates, keep notes, and invite teammates. Each company sees only its own data.

## Tech Stack

| Area | Technology |
|---|---|
| Backend | FastAPI (async), Uvicorn, WebSockets |
| Database | PostgreSQL, async SQLAlchemy 2, asyncpg |
| AI | Groq (`qwen/qwen3.8-27b`, `openai/gpt-oss-20b` as fallback) via LangChain, Gemini embeddings for RAG |
| Speech | Deepgram (live speech-to-text), ElevenLabs (streamed text-to-speech) |
| Frontend | Jinja2 templates, plain HTML, CSS and JavaScript, MediaPipe |
| Reports | ReportLab |
| Tooling | uv, Docker Compose |

## Quick Start

You need Docker installed.

1. **Add your keys** in `backend/.env`. The file is git-ignored.

   ```ini
   GROQ_API_KEY="..."        # required
   GOOGLE_API_KEY="..."      # optional: semantic RAG (falls back to keyword ranking)
   DEEPGRAM_API_KEY="..."    # optional: spoken answers
   ELEVENLABS_API_KEY="..."  # optional: spoken questions
   SECRET_KEY="..."          # required when DEBUG is off
   EMAIL_HOST="..."          # optional: SMTP (emails print to the log if unset)
   ```

2. **Start the app:**

   ```bash
   docker compose up --build
   ```

   This starts Postgres and the backend at http://127.0.0.1:8000. The backend creates the tables and reloads when you edit code. If port 8000 is taken, use `PORT=8001 docker compose up`.

### Demo accounts

When `DEBUG=1` (the Compose default), each start adds these accounts if they're missing. All three use the password `hirely-demo-123`.

| Username | Role |
|---|---|
| `demo_admin` | Admin (opens `/admin/`) |
| `demo_recruiter` | Recruiter at Northwind Labs, with 8 open jobs |
| `demo_candidate` | Candidate |

On the login page, **Use demo credentials** signs you in as the candidate or the recruiter. The seed and the button only exist in debug mode.

## Project Structure

```
compose.yaml                Postgres + backend
backend/
├── Dockerfile
├── pyproject.toml          Dependencies (uv); uv.lock pins versions
├── scripts/
│   └── seed_demo.py        Demo accounts and jobs
└── app/
    ├── main.py             App setup: middleware, routers, static files
    ├── models.py           SQLAlchemy models
    ├── admin.py            /admin/ (staff only)
    ├── core/
    │   ├── config.py       Settings from the environment
    │   ├── database.py     Async engine and sessions
    │   ├── security.py     Passwords, sessions, CSRF, rate limits
    │   └── templating.py   Jinja2 setup and filters
    ├── routers/
    │   ├── auth.py         Sign-up, login, password reset, profile
    │   ├── candidate.py    Candidate dashboard and applications
    │   ├── recruiter.py    Jobs, candidates, compare, export
    │   ├── interview.py    Interview page, WebSocket, speech, PDF download
    │   └── common.py       Shared helpers
    ├── services/
    │   ├── brain.py        LLM prompts: questions, feedback, scoring
    │   ├── rag.py          Chunking, embeddings, retrieval
    │   ├── interview.py    Interview steps: start, answer, proctor, end
    │   ├── audio.py        Deepgram and ElevenLabs clients
    │   ├── reports.py      Final evaluation and PDF report
    │   └── notify.py       Emails
    ├── templates/          Jinja2 pages
    └── static/             CSS and logo
```

## Performance

Measured over the WebSocket against the live APIs, timed from when the candidate stops speaking:

| | Median | p95 |
|---|---|---|
| Transcript ready (Deepgram) | 0.39 s | 0.49 s |
| Next question on screen | 1.56 s | 2.25 s |
| Question audio starts | 2.37 s | 2.86 s |

Scoring an answer and writing the next question run in parallel. If Groq rate-limits a call, it is retried at once on the fallback model.

**Load (one Uvicorn process, AI calls simulated at their measured latency):** about 500 concurrent interviews with a p95 of 1.37 s per answer and no errors. Past about 1,000 interviews, the 30-connection database pool becomes the bottleneck. With real AI, the providers' rate limits apply well before that.

## Security

- PBKDF2-SHA256 password hashes, signed HTTP-only session cookies and CSRF tokens on every POST.
- Rate limits on login, sign-up, password resets and the AI endpoints.
- WebSocket connections are accepted only from the app's own origin.
- Third-party scripts are pinned with integrity hashes.

## Known Limits

- **No migrations:** tables are created on startup and never altered. Add Alembic before changing a column.
- **Question audio isn't cached:** reloading the page synthesizes it again.
- **Upload limit:** requests over 10 MB are refused, based on `Content-Length`. Put a proxy with a body limit in front if the app is public.
