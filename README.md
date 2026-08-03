---
title: Hirely
emoji: 💼
colorFrom: blue
colorTo: indigo
sdk: docker
pinned: false
---

# Hirely

Hirely is a multi-tenant B2B AI-powered recruitment marketplace and live conversational assessment platform. The project enables companies to list technical job openings and screen candidates using real-time conversational AI voice interviews. It features low-latency, stateful audio pipelines over WebSockets and client-side browser proctoring (gaze/face tracking) to verify candidate integrity during evaluations.

---

## 🛠️ Tech Stack

* **Backend Framework**: Django & Django Channels (ASGI)
* **ASGI Server**: Uvicorn
* **Database**: Serverless PostgreSQL (Neon DB / configured via `dj_database_url`)
* **Real-time Pipeline**: HTML5 WebSockets
* **Speech-to-Text (STT)**: Deepgram Streaming API
* **Large Language Model (LLM)**: Groq API (LLaMA)
* **Text-to-Speech (TTS)**: ElevenLabs Streaming API
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
ELEVENLABS_API_KEY="your_elevenlabs_key"
DEEPGRAM_API_KEY="your_deepgram_key"
GROQ_API_KEY="your_groq_key"
DATABASE_URL="postgresql://user:password@host/dbname?sslmode=require"
```

### 2. Database Migration
Initialize the database tables and schema in your PostgreSQL database:

```bash
# Activate your virtual environment
source venv/bin/activate  # Or venv\Scripts\activate on Windows

# Run migrations
python manage.py migrate
```

### 3. Start the Application
Boot the local ASGI server:
```bash
uvicorn backend.asgi:application --reload --port 8000
```
The application will run locally at `http://127.0.0.1:8000`.
