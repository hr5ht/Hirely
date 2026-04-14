import os
import django
from django.core.asgi import get_asgi_application
import socketio
import time
from ai_engine.brain import InterviewBrain
from ai_engine.audio_service import AudioService
from ai_engine.rag import RAGRetriever
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

# Initialize Django ASGI application
django_asgi_app = get_asgi_application()

# Initialize Socket.io server
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
application = socketio.ASGIApp(sio, django_asgi_app)

@sio.event
async def connect(sid, environ):
    print(f"Client connected: {sid}")

@sio.event
async def disconnect(sid):
    print(f"Client disconnected: {sid}")

@sio.event
async def vision_flag(sid, data):
    print(f"Vision Flag from {sid}: {data.get('flag')}")

@sio.event
async def proctoring_alert(sid, data):
    alert_type = data.get('type')
    timestamp = data.get('timestamp')
    print(f"PROCTORING ALERT from {sid}: {alert_type} at {timestamp}")
    # Here you could save this to a database or flag the session
    if sid in interview_sessions:
        if 'alerts' not in interview_sessions[sid]:
            interview_sessions[sid]['alerts'] = []
        interview_sessions[sid]['alerts'].append(data)

# Interview State Store
interview_sessions = {}
brain = InterviewBrain()
audio_service = AudioService()

@sio.event
async def start_interview(sid, data):
    # Default to 1st Grade Math for testing purposes
    jd = data.get('jd') or '1st Grade Basic Mathematics (Addition, Subtraction, Shapes)'
    role = data.get('role') or '1st Grade Student'
    company = data.get('company') or 'Elementary School'
    resume = data.get('resume') or 'Strong foundation in basics.'
    
    print(f"Starting interview for {sid} - Role: {role} at {company}")
    
    # Initialize RAG for this session
    rag = RAGRetriever()
    rag.build_index(resume, jd)
    
    # Store session context
    interview_sessions[sid] = {
        "jd": jd,
        "role": role,
        "company": company,
        "resume": resume,
        "rag": rag,
        "history": [],
        "last_question": ""
    }
    
    # Generate initial context using the role as query
    initial_context = rag.retrieve(f"{role} key qualifications and experience", top_k=5)
    
    context_prompt = f"Conducting interview for {role} role at {company}. JD: {jd}\nCandidate Context:\n{initial_context}"
    initial_question = await brain.generate_initial_question(context_prompt)
    interview_sessions[sid]["last_question"] = initial_question
    
    # Generate Audio
    audio_b64 = await audio_service.text_to_speech(initial_question)
    
    await sio.emit('interview_message', {
        'type': 'question',
        'text': initial_question,
        'audio': audio_b64
    }, room=sid)

@sio.event
async def submit_answer(sid, data):
    answer = data.get('answer', '')
    session = interview_sessions.get(sid)
    
    if not session:
        return
    
    print(f"Processing answer from {sid}")
    session['history'].append({"q": session['last_question'], "a": answer})
    
    # Get feedback analysis in JSON
    analysis_raw = await brain.get_feedback(session['last_question'], answer)
    
    try:
        analysis = json.loads(analysis_raw)
        feedback_text = analysis.get('feedback', analysis_raw)
        insights = {
            'confidence': analysis.get('confidence', 85),
            'clarity': analysis.get('clarity', 90),
            'tone': analysis.get('tone', 'Professional')
        }
    except Exception as e:
        print(f"Error parsing Brain JSON: {e}")
        feedback_text = analysis_raw
        insights = {
            'confidence': 75,
            'clarity': 80,
            'tone': 'Detected'
        }

    # Remove TTS generation for feedback since it goes to sidebar only
    
    # Emit insights separately for the HUD
    await sio.emit('insights_update', insights, room=sid)

    await sio.emit('interview_message', {
        'type': 'silent_feedback',
        'text': feedback_text
    }, room=sid)

    # Immediately trigger the next question
    await request_next_question(sid, {})

@sio.event
async def request_next_question(sid, data):
    session = interview_sessions.get(sid)
    if not session:
        return

    # Check for ending
    if len(session['history']) >= 5:
        summary_prompt = f"Summarize the performance of the candidate for the {session['role']} role based on this history: {json.dumps(session['history'])}"
        response = await brain.client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are a senior recruiter. Provide a concise, executive summary of the interview."},
                {"role": "user", "content": summary_prompt}
            ],
            model=brain.model
        )
        summary = response.choices[0].message.content
        audio_b64 = await audio_service.text_to_speech(summary)
        
        await sio.emit('interview_message', {
            'type': 'summary',
            'text': summary,
            'audio': audio_b64
        }, room=sid)

        # Print Latency Report for final turn
        turn_start = session.get('turn_start_time')
        if turn_start:
            total_latency = time.perf_counter() - turn_start
            print(f"\n[LATENCY REPORT] Session Finalized")
            print(f"------------------------------------")
            print(f"Total Pipeline Latency: {total_latency:.3f}s")
            print(f"------------------------------------\n")

        del interview_sessions[sid]
    else:
        # Retrieve context from RAG based on the job description/role
        rag = session.get('rag')
        context = ""
        if rag:
            # Shift the semantic search vector dynamically to pull diverse constraints
            round_num = len(session['history'])
            if round_num == 1:
                query = f"Role: {session['role']}. Core technical skills, languages, and frameworks."
            elif round_num == 2:
                query = f"Role: {session['role']}. System architecture, databases, or deployment."
            elif round_num == 3:
                query = f"Role: {session['role']}. Testing, edge cases, collaboration, or teamwork."
            else:
                # Randomize slightly using the previous answer but asking for a new challenge
                query = f"Role: {session['role']}. Leadership, scaling challenges, open source."
            
            context = rag.retrieve(query, top_k=5)
            
        next_q = await brain.get_next_question(session['history'], session['jd'], context)
        session['last_question'] = next_q
        
        audio_b64 = await audio_service.text_to_speech(next_q)
        
        await sio.emit('interview_message', {
            'type': 'question',
            'text': next_q,
            'audio': audio_b64
        }, room=sid)

        # Print Latency Report
        turn_start = session.get('turn_start_time')
        if turn_start:
            total_latency = time.perf_counter() - turn_start
            print(f"\n[LATENCY REPORT] Turnaround Complete")
            print(f"------------------------------------")
            print(f"Total Pipeline Latency: {total_latency:.3f}s")
            print(f"------------------------------------\n")

@sio.event
async def submit_audio(sid, data):
    print(f"\n--- New Turn Started ---")
    start_time = time.perf_counter()
    if sid in interview_sessions:
        interview_sessions[sid]['turn_start_time'] = start_time

    audio_b64 = data.get('audio', '')
    mime_type = data.get('mimeType', 'audio/webm')
    if not audio_b64:
        return

    print(f"Deepgram: Transcribing audio from {sid} (format: {mime_type})")
    transcript = await audio_service.transcribe_audio(audio_b64, mime_type)
    
    if transcript:
        print(f"Deepgram Result: {transcript}")
        # Emit the transcript back to the client so it shows up in their transcript area
        await sio.emit('transcription_result', {'text': transcript}, room=sid)
        # Automatically trigger the answer processing with the transcript
        await submit_answer(sid, {'answer': transcript})
    else:
        print("Deepgram: Failed to transcribe")
        await sio.emit('transcription_result', {'text': '', 'error': 'Transcription failed'}, room=sid)
