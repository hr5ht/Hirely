# Hirely

An AI recruitment platform: companies post jobs, candidates apply with a resume, and every applicant gets an ATS match score and an AI-led technical interview with live proctoring. Recruiters review scores, transcripts and a PDF report for each candidate.

## Features

- **ATS resume scoring:** an LLM compares the resume with the job description and returns an overall score, skill and context sub-scores, matched and missing skills, and suggestions.
- **Personalized AI interviews:** questions generated from the candidate's own resume and the job description, with feedback, confidence and clarity scores after every answer. Per job, recruiters set the number of questions (1–10, default 5), must-ask questions, a time limit per answer and how much each score counts.
- **RAG:** each round retrieves the most relevant resume and job-description excerpts for its topic and the candidate's last answer, so questions dig into what the candidate actually claimed.
- **Proctoring:** in-browser face and gaze tracking (MediaPipe) plus copy-paste and typing-speed checks; every alert lowers the integrity score and is listed in the report.
- **Reports:** a PDF per interview with scores, a skills-gap analysis, the proctoring audit trail and the full transcript.
- **Recruiter tools:** filter applicants by job, status and ATS score; compare up to three side by side; keep private notes; export to CSV; re-score every applicant after editing a job; allow a retake.
- **Teams:** recruiters invite teammates to their company with a single-use link; each company sees only its own jobs and applicants.
- **Accounts:** sign-up, sign-in and password resets built in; passwords are hashed with PBKDF2 (the same format Django uses).
- **Voice (optional):** questions read aloud and spoken answers transcribed.

## Tech Stack

| Area | Technology |
|---|---|
| Backend | FastAPI (async) on Uvicorn |
| Database | PostgreSQL, via async SQLAlchemy 2 and asyncpg |
| LLM | Groq `qwen/qwen3.8-27b` via **LangChain** (`langchain-groq`) |
| RAG embeddings | Google Gemini `gemini-embedding-001` via LangChain (`langchain-google-genai`), with a keyword-ranking fallback |
| Auth | Built in: PBKDF2 password hashes, signed session cookie, CSRF tokens |
| Speech | Deepgram (speech-to-text), ElevenLabs (text-to-speech) |
| Proctoring | MediaPipe Face Mesh (runs in the browser) |
| Reports | ReportLab |
| Admin | sqladmin at `/admin/` |
| Frontend | Jinja2 templates, plain HTML/CSS/JavaScript (one stylesheet), Lucide icons |
| Running | Docker Compose (Postgres + backend) |

All AI runs on hosted APIs, so the server needs no GPU and very little memory.

## How It Works

1. **Sign in:** the password is checked against its PBKDF2 hash, and a signed session cookie keeps the user signed in.
2. **Apply:** the resume PDF's text is extracted and scored against the job by the LLM.
3. **Interview:** the page opens a WebSocket for its steps (start, answer, voice answer, proctoring alert, end); each step reloads the session from the database, so the interview survives page reloads, and every step also works as a plain HTTP POST if the socket can't connect.
4. **Speak:** while the candidate talks, the microphone streams over the socket to Deepgram's live transcription, so the transcript is ready about 0.3 s after they stop. The next question's text is sent as soon as it's written and its audio follows separately.
5. **Retrieve:** both documents are split into chunks and embedded; the closest resume and job-description chunks go into each question prompt.
6. **Answer:** scoring the answer and writing the next question run at the same time, and the database connection is released while the AI calls run, so slow AI calls don't tie up the connection pool.
7. **Evaluate:** when the interview ends, the LLM scores technical knowledge, behavioral IQ and problem solving, and the PDF report is generated.

## Project Structure

```
compose.yaml          Postgres + backend
backend/
  app/
    main.py           FastAPI app: middleware, routers, static files, admin
    models.py         SQLAlchemy models
    admin.py          /admin/ views (staff only)
    core/
      config.py       Settings from the environment
      database.py     Async engine, connection pool, session dependency
      security.py     Passwords, sessions, CSRF, rate limits, flash messages
      templating.py   Jinja2 setup and Django-style filters
    routers/          Pages and JSON endpoints: auth, candidate, recruiter, interview
    services/
      brain.py        LangChain + Groq prompts: questions, feedback, ATS score, evaluation
      rag.py          Chunking, Gemini embeddings, cosine ranking, keyword fallback
      interview.py    Interview steps (start / answer / audio / proctor / heartbeat / end)
      audio.py        Deepgram and ElevenLabs clients
      reports.py      Final evaluation and PDF report
      notify.py       Emails (SMTP, or printed to the log)
    templates/        Jinja2 templates
    static/           Logo and hirely.css, the app's only stylesheet
  scripts/
    seed_demo.py      Sample recruiters, jobs and a candidate
  pyproject.toml      Dependencies (uv); uv.lock pins exact versions
  Dockerfile          Backend image
```

## Setup

Requires Docker. Dependencies are managed with [uv](https://docs.astral.sh/uv/).

### 1. Environment

Create `backend/.env` (it's git-ignored):

```ini
SECRET_KEY="..."            # any long random string; can stay empty while DEBUG=1
GROQ_API_KEY="..."
GOOGLE_API_KEY="..."        # optional: semantic RAG (falls back to keyword ranking)
ELEVENLABS_API_KEY="..."    # optional: spoken questions
DEEPGRAM_API_KEY="..."      # optional: spoken answers
EMAIL_HOST="..."            # optional: SMTP for notifications and reset links (printed to the backend's log if unset)
```

| Key | Where to get it | Free tier |
|---|---|---|
| `GROQ_API_KEY` | console.groq.com | Yes |
| `GOOGLE_API_KEY` | aistudio.google.com | Yes, resets daily |
| `ELEVENLABS_API_KEY` | elevenlabs.io | Yes |
| `DEEPGRAM_API_KEY` | deepgram.com | Free credits |

### 2. Run

```bash
docker compose up --build           # Postgres + backend at http://127.0.0.1:8000
```

Compose sets `DATABASE_URL` to its own Postgres and `DEBUG=1`, and the backend reloads when you edit code. Tables are created on startup. If port 8000 is taken, run `PORT=8001 docker compose up`.

Each start also seeds demo data, adding only what's missing (it needs the database, so it runs when the container starts, not while the image builds):

| Username | Role | Notes |
|---|---|---|
| `demo_admin` | Admin | Staff access to `/admin/` |
| `demo_recruiter` | Recruiter | Northwind Labs, with 8 job openings |
| `demo_candidate` | Candidate | Sees the 8 openings |

All three use the password `hirely-demo-123`. On the login page, **Use demo credentials** opens a popup that signs you in as the demo candidate or the demo recruiter. Both the seed and the button only exist with `DEBUG=1`, so a production login page never shows the demo password.

Sign up at `/register/` as a candidate, or as a recruiter with a company name.

To add a dependency, run `uv add <name>` in `backend/`, then `docker compose up --build`.

### Admin access

`/admin/` has no password form of its own: it sends you to the normal sign-in page. Locally, sign in as `demo_admin`. To make another account an admin, run:

```bash
docker compose exec db psql -U hirely -c "update auth_user set is_staff = true where email = 'you@example.com'"
```

### Running without debug

With `DEBUG` off, the app needs `SECRET_KEY` and `DATABASE_URL`, and session cookies are sent over HTTPS only, so put it behind an HTTPS proxy.

## Performance

### Voice turns over the WebSocket

Measured in November 2026 with 5 voice turns from Docker on a laptop, against the live APIs on their free tiers. Each turn streamed a 12-second spoken answer at real-time pace. Times are counted from the moment the candidate stops speaking:

| | Median | Range |
|---|---|---|
| Transcript ready (Deepgram live) | 0.3 s | 0.30–0.37 s |
| Next question text on screen | 1.5 s | 1.3–2.8 s |
| Next question audio ready | 2.6 s | 2.1–3.7 s |

Inside each turn, Groq scored the answer in 0.4–0.8 s while the excerpt lookup and the next question (Groq, 0.3–0.5 s) ran alongside it, and ElevenLabs took 0.7–1.5 s.

### Before (HTTP, Django)

The same kind of turn over HTTP, measured earlier with 20 runs, took 4.5–7 s when Groq wasn't throttled (10.3 s median and 15.2 s p95 with free-tier throttling). The answer was uploaded whole and transcribed afterwards (about 2.3 s), and every step ran one after another.

Groq's free tier allows 1,000 output tokens a minute, so turns closer together than about 20 s get throttled and slow down. Concurrent sessions haven't been load-tested on FastAPI yet.

## Known Limits

- **No migrations:** tables are created on startup, and existing tables are never altered. Add Alembic before changing a column.
- **Question audio isn't streamed:** it's made in one piece after the text is sent, so it starts playing about 1 s after the question appears. Over the HTTP fallback, answers are uploaded whole and the audio arrives inside the reply.
- **Upload size:** requests over 10 MB are refused by `Content-Length`; chunked uploads without one aren't capped, so put a proxy with a body limit in front if the app is public.

## Security

- **Passwords:** PBKDF2-SHA256 with a million iterations, checked off the event loop. Sign-up and password changes apply Django's default rules (length, common passwords, all-numeric, similarity to the username or email).
- **Sessions:** a signed, HTTP-only cookie (SameSite=Lax). Changing the password signs out every other session.
- **CSRF:** every POST must carry the session's token, as a form field or an `X-CSRFToken` header.
- **Rate limits:** login, sign-up and password resets are limited per visitor IP and per account, in 15-minute windows. The AI endpoints are also capped per user per hour.
- **Third-party scripts:** pinned to exact versions with integrity hashes, so a changed file is refused instead of run.
- **Company data:** each company only sees its own jobs, applicants, resumes and reports.
