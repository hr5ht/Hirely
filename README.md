# Hirely

An AI recruitment platform: companies post jobs, candidates apply with a resume, and every applicant gets an ATS match score and an AI-led technical interview with live proctoring. Recruiters review scores, transcripts and a PDF report for each candidate.

**Live demo:** https://hirely-hr5ht.vercel.app

## Features

- **ATS resume scoring:** an LLM compares the resume with the job description and returns an overall score, skill and context sub-scores, matched and missing skills, and suggestions.
- **Personalized AI interviews:** five rounds of questions generated from the candidate's own resume and the job description, with feedback, confidence and clarity scores after every answer.
- **RAG:** each round retrieves the most relevant resume and job-description excerpts for its topic and the candidate's last answer, so questions dig into what the candidate actually claimed.
- **Proctoring:** in-browser face and gaze tracking (MediaPipe) plus copy-paste and typing-speed checks; every alert lowers the integrity score and is listed in the report.
- **Reports:** a PDF per interview with scores, a skills-gap analysis, the proctoring audit trail and the full transcript.
- **Teams:** recruiters invite teammates to their company with a single-use link; each company sees only its own jobs and applicants.
- **Accounts:** sign-up, sign-in and password resets run on Supabase Auth, and the app's own database stores no passwords.
- **Voice (optional):** questions read aloud and spoken answers transcribed.

## Tech Stack

| Area | Technology |
|---|---|
| Backend | Django 5.2 (WSGI) |
| LLM | Groq `qwen/qwen3.8-27b` via **LangChain** (`langchain-groq`) |
| RAG embeddings | Google Gemini `gemini-embedding-001` via LangChain (`langchain-google-genai`), with a keyword-ranking fallback |
| Database | PostgreSQL on Neon (the same database locally and in production) |
| Auth | Supabase Auth (email and password), with Django sessions |
| Speech | Deepgram (speech-to-text), ElevenLabs (text-to-speech) |
| Proctoring | MediaPipe Face Mesh (runs in the browser) |
| Reports | ReportLab |
| Frontend | Django templates, Tailwind CSS, Lucide icons |
| Hosting | Vercel (serverless) |

All AI runs on hosted APIs, so the server needs no GPU and very little memory.

## How It Works

1. **Sign in:** Supabase checks the email and password. Hirely then finds the matching user in its own database, with their role and company, and starts a normal Django session.
2. **Apply:** the resume PDF's text is extracted and scored against the job by the LLM.
3. **Interview:** each step (start, answer, voice answer, proctoring alert, end) is a stateless HTTP request, so the interview runs on serverless hosts and survives page reloads.
4. **Retrieve:** both documents are split into chunks and embedded; the closest resume and job-description chunks go into each question prompt.
5. **Evaluate:** when the interview ends, the LLM scores technical knowledge, behavioral IQ and problem solving, and the PDF report is generated.

## Project Structure

```
backend/
  ai_engine/
    brain.py          LangChain + Groq prompts: questions, feedback, ATS score, evaluation
    rag.py            Chunking, Gemini embeddings, cosine ranking, keyword fallback
    interview.py      Interview steps (start / answer / audio / proctor / end)
    audio_service.py  Deepgram and ElevenLabs clients
    reports.py        Final evaluation and PDF report
    views/            Pages and JSON endpoints: auth (Supabase), candidate, recruiter, interview
    static/ai_engine/ Logo and vendored scripts (Tailwind)
  templates/          Django templates
  vercel.json         Vercel config
```

## Local Setup

Requires Python 3.11+, plus two free accounts: a **Neon** database and a **Supabase** project. No local PostgreSQL is needed.

### 1. Install

```bash
cd backend
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Database (Neon)

1. Create a project at neon.tech.
2. Copy the **pooled** connection string (its hostname contains `-pooler`).

Local runs and the live site use this same database, so anything you change locally changes real data.

### 3. Auth (Supabase)

The app won't start without Supabase. Supabase only checks passwords and sends the account emails; users, roles, companies and everything else stay in Neon.

1. Create a project at supabase.com.
2. **Project URL:** copy it from Project Settings → Data API. It looks like `https://<project>.supabase.co`, without `/rest/v1/`.
3. **Key:** go to Project Settings → API Keys and copy the **publishable** key (`sb_publishable_…`), or the legacy **anon** key. Never use the secret or `service_role` key.
4. **Redirect URLs:** go to Authentication → URL Configuration. Set the Site URL to `http://127.0.0.1:8000/login/`, and add `http://127.0.0.1:8000/**` and `https://<your-app>.vercel.app/**` to the redirect URLs.
5. **Emails:** Supabase's built-in mailer only delivers to your project team's addresses, and only about 2 emails an hour.
   - For local testing, you can turn off "Confirm email" under Authentication → Sign In / Providers → Email.
   - For real users, keep "Confirm email" on and set up your own sender under Authentication → Emails → SMTP Settings. Gmail with an app password, Resend and Brevo all work.

### 4. Environment

Create `backend/.env` (it's git-ignored):

```ini
SECRET_KEY="..."            # any long random string
DATABASE_URL="postgresql://..."                # Neon pooled connection string
SUPABASE_URL="https://<project>.supabase.co"
SUPABASE_ANON_KEY="sb_publishable_..."
GROQ_API_KEY="..."
GOOGLE_API_KEY="..."        # optional: semantic RAG (falls back to keyword ranking)
ELEVENLABS_API_KEY="..."    # optional: spoken questions
DEEPGRAM_API_KEY="..."      # optional: spoken answers
EMAIL_HOST="..."            # optional: SMTP for application and interview notifications (printed to the console if unset)
```

| Key | Where to get it | Free tier |
|---|---|---|
| `DATABASE_URL` | neon.tech → Connection Details (pooled) | Yes |
| `SUPABASE_URL`, `SUPABASE_ANON_KEY` | supabase.com → Project Settings | Yes |
| `GROQ_API_KEY` | console.groq.com | Yes |
| `GOOGLE_API_KEY` | aistudio.google.com | Yes, resets daily |
| `ELEVENLABS_API_KEY` | elevenlabs.io | Yes |
| `DEEPGRAM_API_KEY` | deepgram.com | Free credits |

### 5. Run

```bash
python manage.py migrate            # creates the tables in Neon (also the production migration)
python manage.py runserver          # http://127.0.0.1:8000
```

Sign up at `/register/` as a candidate, or as a recruiter with a company name.

### Admin access

`/admin/` has no password form of its own: it sends you to the normal sign-in page. To make your account an admin, sign up first, then run:

```bash
python manage.py shell -c "from django.contrib.auth.models import User; User.objects.filter(email='you@example.com').update(is_staff=True, is_superuser=True)"
```

## Security

- **Passwords:** checked by Supabase only. User rows in Neon have no usable password.
- **Rate limits:** login, sign-up and password resets are limited per visitor IP and per account, in 15-minute windows. This matters because Supabase's own per-IP limits see only Vercel's servers. The AI endpoints are also capped per user per hour.
- **Third-party scripts:** pinned to exact versions with integrity hashes, so a changed file is refused instead of run. Tailwind's CDN doesn't allow integrity checks, so its script is served from `static/ai_engine/vendor/`.
- **Company data:** each company only sees its own jobs, applicants, resumes and reports.

## Deployment (Vercel)

1. Import the GitHub repo and set **Root Directory** to `backend`.
2. Add the environment variables from `.env`, with a different `SECRET_KEY` for production. The app refuses to start without `SECRET_KEY`, `DATABASE_URL`, `SUPABASE_URL` and `SUPABASE_ANON_KEY`.
3. Add `https://<your-app>.vercel.app/**` to Supabase's redirect URLs (Authentication → URL Configuration).
4. Vercel doesn't run migrations. After a change to the models, run `python manage.py migrate` from your machine **before** pushing.

Every push to `main` then deploys automatically.
