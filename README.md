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
4. **Speak:** while the candidate talks, the microphone streams over the socket to Deepgram's live transcription, so the transcript is ready about 0.3 s after they stop. The next question's text is sent as soon as it's written, with a link to its audio, which the browser plays while ElevenLabs is still streaming it (first sound in about 0.2 s).
5. **Retrieve:** both documents are split into chunks and embedded; the closest resume and job-description chunks go into each question prompt.
6. **Answer:** scoring the answer and writing the next question run at the same time, and the database connection is released while the AI calls run, so slow AI calls don't tie up the connection pool. If Groq rate-limits or fails a call, it's retried at once on a smaller model (`openai/gpt-oss-20b`, which Groq limits separately) instead of waiting out the limit.
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

Measured in November 2026 from Docker on a laptop, against the live APIs on their free tiers, with a 6-second spoken answer streamed at real-time pace. Times are counted from the moment the candidate stops speaking.

20 turns:

| | Median | p95 |
|---|---|---|
| Transcript ready (Deepgram live) | 0.39 s | 0.49 s |
| Next question text on screen | 1.56 s | 2.25 s |

The 8 turns that also played the question's audio (ElevenLabs' free quota ran out after them), stage by stage:

| Stage | Median | p95 (slowest of 8) |
|---|---|---|
| Deepgram speech-to-text, after speech ends | 365 ms | 870 ms |
| Groq: score the answer | 373 ms | 421 ms |
| Gemini excerpt lookup | 782 ms | 1,232 ms |
| Groq: write the next question | 384 ms | 463 ms |
| ElevenLabs: audio stream starts | 550 ms | 914 ms |
| **Total: next question on screen** | **1.65 s** | **2.27 s** |
| **Total: question's voice starts** | **2.37 s** | **2.86 s** |

Scoring runs alongside the lookup and the next question, so the slower of the two branches counts, not their sum. No turn needed the Groq fallback model.

### Concurrent sessions

One uvicorn process (one asyncio event loop) with the AI calls replaced by waits of their measured length, so a turn can't finish in under 1.05 s. Every socket was a separate candidate, repeating: stream 10 s of microphone chunks, wait for the next question, send a heartbeat.

| Open sockets | Turns in 60 s | p50 | p95 | Errors |
|---|---|---|---|---|
| 100 | 541 | 1.08 s | 1.11 s | 0 |
| 500 | 2,668 | 1.15 s | 1.37 s | 0 |
| 1,000 | 4,513 | 3.17 s | 6.39 s | 0 |
| 2,000 | 4,648 | 19.1 s | 32.9 s | 0.5% (database pool timeouts) |

One process holds about 500 live interviews with little slowdown; past that it tops out near 75 turns a second. This was on a laptop, with the load generator on the same machine; real AI providers' rate limits (Groq's free tier especially) would cap concurrency long before this.

### Before (HTTP, Django)

The same kind of turn over HTTP, measured earlier with 20 runs, took 4.5–7 s when Groq wasn't throttled (10.3 s median and 15.2 s p95 with free-tier throttling). The answer was uploaded whole and transcribed afterwards (about 2.3 s), and every step ran one after another.

Groq's free tier allows 1,000 output tokens a minute. Throttled calls used to wait and retry (the 10 s+ turns above); they now switch to the fallback model at once (1.2 s for a score and a question in testing).

## Known Limits

- **No migrations:** tables are created on startup, and existing tables are never altered. Add Alembic before changing a column.
- **Question audio isn't cached:** reloading the page asks ElevenLabs to read the question again. Over the HTTP fallback, spoken answers are uploaded whole instead of streamed.
- **Fallback answers:** when Groq throttles the main model, scores and questions come from a smaller model, so their quality can dip during busy minutes.
- **Upload size:** requests over 10 MB are refused by `Content-Length`; chunked uploads without one aren't capped, so put a proxy with a body limit in front if the app is public.

## Security

- **Passwords:** PBKDF2-SHA256 with a million iterations, checked off the event loop. Sign-up and password changes apply Django's default rules (length, common passwords, all-numeric, similarity to the username or email).
- **Sessions:** a signed, HTTP-only cookie (SameSite=Lax). Changing the password signs out every other session.
- **CSRF:** every POST must carry the session's token, as a form field or an `X-CSRFToken` header.
- **Rate limits:** login, sign-up and password resets are limited per visitor IP and per account, in 15-minute windows. The AI endpoints are also capped per user per hour.
- **Third-party scripts:** pinned to exact versions with integrity hashes, so a changed file is refused instead of run.
- **Company data:** each company only sees its own jobs, applicants, resumes and reports.
