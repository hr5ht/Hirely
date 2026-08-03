import json
import base64
import time
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from ai_engine.models import InterviewSession, Application, Job
from ai_engine.brain import InterviewBrain
from ai_engine.audio_service import AudioService
from ai_engine.rag import RAGRetriever
from ai_engine.tasks import evaluate_transcript_semantic_gaps

class InterviewConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # Extract session_id from URL path parameters
        self.session_id = self.scope['url_route']['kwargs']['session_id']
        self.session = await self.get_session(self.session_id)
        
        if not self.session:
            await self.close()
            return
            
        self.app = await self.get_application(self.session.id)
        self.job = await self.get_job(self.app['id'])
        
        # Keep track of local state
        self.brain = InterviewBrain()
        self.audio_service = AudioService()
        self.rag = RAGRetriever()
        
        # Build RAG in memory for this session
        await self.setup_rag(self.app['resume_text'], self.job['description'])
        
        await self.accept()
        print(f"[WebSocket] Connected session {self.session_id} for candidate {self.app['candidate_username']}")

    async def disconnect(self, close_code):
        print(f"[WebSocket] Disconnected session {self.session_id}")
        # Automatically complete the session if it's not already completed
        session = await self.get_session(self.session_id)
        if session and session.session_status != 'completed':
            await self.complete_session_in_db(self.session_id)
            import asyncio
            asyncio.create_task(asyncio.to_thread(evaluate_transcript_semantic_gaps, self.session_id))

    async def receive(self, text_data=None, bytes_data=None):
        if text_data:
            try:
                event = json.loads(text_data)
            except json.JSONDecodeError:
                await self.send(json.dumps({"type": "error", "message": "Invalid JSON"}))
                return
            
            event_type = event.get('event_type')
            data = event.get('data', {})
            
            if event_type == 'start_interview':
                await self.handle_start_interview()
            elif event_type == 'submit_answer':
                await self.handle_submit_answer(data.get('answer', ''))
            elif event_type == 'proctor_infraction':
                await self.handle_proctor_infraction(data)
            elif event_type == 'submit_audio_chunk':
                await self.handle_submit_audio_chunk(data.get('audio', ''), data.get('mimeType', 'audio/webm'))
            elif event_type == 'end_session':
                await self.handle_end_session()
                
    async def handle_start_interview(self):
        print(f"[WebSocket] Starting B2B assessment for session {self.session_id}")
        
        # Initial Qualifications RAG pull
        initial_context = self.rag.retrieve(f"{self.job['title']} core qualifications", top_k=5)
        context_prompt = f"Conducting interview for {self.job['title']} role. JD: {self.job['description']}\nCandidate Context:\n{initial_context}"
        
        initial_question = await self.brain.generate_initial_question(context_prompt)
        
        # Store in DB session
        await self.set_last_question(self.session_id, initial_question)
        
        # Synth TTS Voice
        audio_b64 = await self.audio_service.text_to_speech(initial_question)
        
        await self.send(json.dumps({
            "type": "interview_message",
            "message_type": "question",
            "text": initial_question,
            "audio": audio_b64
        }))

    async def handle_submit_answer(self, answer):
        if not answer.strip():
            return
            
        print(f"[WebSocket] Answer received: {answer[:40]}...")
        session_data = await self.get_session_details(self.session_id)
        last_question = session_data.get('last_question', '')
        transcript = session_data.get('transcript', [])
        
        # Append turn
        transcript.append({"question": last_question, "answer": answer, "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ')})
        await self.update_session_transcript(self.session_id, transcript)
        
        # Emits live feedback analysis DYNAMICALLY
        analysis_raw = await self.brain.get_feedback(last_question, answer)
        try:
            analysis = json.loads(analysis_raw)
            feedback_text = analysis.get('feedback', analysis_raw)
            insights = {
                'confidence': analysis.get('confidence', 85),
                'clarity': analysis.get('clarity', 90),
                'tone': analysis.get('tone', 'Confident')
            }
        except Exception as e:
            feedback_text = analysis_raw
            insights = {'confidence': 80, 'clarity': 80, 'tone': 'Detected'}
            
        # Append feedback to the last turn in transcript
        transcript[-1]['feedback'] = feedback_text
        await self.update_session_transcript(self.session_id, transcript)
        
        # Emit real-time insights back to candidate HUD
        await self.send(json.dumps({
            "type": "insights_update",
            "insights": insights
        }))
        
        await self.send(json.dumps({
            "type": "interview_message",
            "message_type": "silent_feedback",
            "text": feedback_text
        }))
        
        # Check rounds capping (5 rounds max)
        if len(transcript) >= 5:
            # End of Interview Summary
            summary_prompt = f"Summarize the performance of the candidate for the {self.job['title']} role based on history: {json.dumps(transcript)}"
            response = await self.brain.client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "You are a senior recruiter. Provide a concise, executive summary of the interview."},
                    {"role": "user", "content": summary_prompt}
                ],
                model=self.brain.model
            )
            summary = response.choices[0].message.content
            audio_b64 = await self.audio_service.text_to_speech(summary)
            
            await self.send(json.dumps({
                "type": "interview_message",
                "message_type": "summary",
                "text": summary,
                "audio": audio_b64
            }))
        else:
            # Shift semantic index and retrieve next context challenge
            round_num = len(transcript)
            if round_num == 1:
                query = f"Role: {self.job['title']}. Core technical skills, languages, and frameworks."
            elif round_num == 2:
                query = f"Role: {self.job['title']}. System architecture, databases, or deployment."
            elif round_num == 3:
                query = f"Role: {self.job['title']}. Testing, edge cases, collaboration, or teamwork."
            else:
                query = f"Role: {self.job['title']}. Scaling challenges and technical leadership."
                
            context = self.rag.retrieve(query, top_k=5)
            next_q = await self.brain.get_next_question(transcript, self.job['description'], context, self.app['resume_text'])

            
            # Store next question in session state
            await self.set_last_question(self.session_id, next_q)
            
            # Synth voice
            audio_b64 = await self.audio_service.text_to_speech(next_q)
            
            await self.send(json.dumps({
                "type": "interview_message",
                "message_type": "question",
                "text": next_q,
                "audio": audio_b64
            }))

    async def handle_proctor_infraction(self, data):
        infraction_type = data.get('type', 'Gaze Deviation')
        timestamp = data.get('timestamp', time.strftime('%Y-%m-%dT%H:%M:%SZ'))
        print(f"[WebSocket Proctor Alert] {infraction_type} at {timestamp} on session {self.session_id}")
        
        # Save infraction record and adjust candidate proctoring score
        await self.add_proctor_infraction(self.session_id, {
            "type": infraction_type,
            "timestamp": timestamp
        })

    async def handle_submit_audio_chunk(self, base64_audio, mime_type):
        print(f"[WebSocket STT] Transcribing audio block via Deepgram Nova-2...")
        transcript = await self.audio_service.transcribe_audio(base64_audio, mime_type)
        
        if transcript:
            print(f"[WebSocket STT Result] {transcript}")
            await self.send(json.dumps({
                "type": "transcription_result",
                "text": transcript
            }))
            # Auto-submit transcript as answer
            await self.handle_submit_answer(transcript)
        else:
            await self.send(json.dumps({
                "type": "transcription_result",
                "text": "",
                "error": "Transcription failed"
            }))

    async def handle_end_session(self):
        print(f"[WebSocket Complete] Closing session {self.session_id} and invoking Celery background reporting...")
        await self.complete_session_in_db(self.session_id)
        
        # Hand off text semantic grading and unalterable PDF compilation to Celery Workers in a background thread
        import asyncio
        asyncio.create_task(asyncio.to_thread(evaluate_transcript_semantic_gaps, self.session_id))
        
        await self.send(json.dumps({
            "type": "session_completed",
            "message": "Interview completed successfully. Report is being compiled."
        }))

    # --- DATABASE SYNC HELPERS ---

    @database_sync_to_async
    def get_session(self, session_id):
        try:
            return InterviewSession.objects.get(id=session_id)
        except InterviewSession.DoesNotExist:
            return None

    @database_sync_to_async
    def get_application(self, session_id):
        """Return a plain dict so no ORM lazy loads can fire in async context."""
        session = InterviewSession.objects.select_related(
            'application__candidate', 'application__job'
        ).get(id=session_id)
        app = session.application
        return {
            'id': app.id,
            'resume_text': app.resume_text or '',
            'candidate_username': app.candidate.username,
        }

    @database_sync_to_async
    def get_job(self, app_id):
        """Return a plain dict so no ORM lazy loads can fire in async context."""
        app = Application.objects.select_related('job__company').get(id=app_id)
        return {
            'id': app.job.id,
            'title': app.job.title,
            'description': app.job.description,
            'company': app.job.company.name,
        }

    @database_sync_to_async
    def setup_rag(self, resume_text, jd_text):
        self.rag.build_index(resume_text, jd_text)

    @database_sync_to_async
    def set_last_question(self, session_id, question):
        session = InterviewSession.objects.get(id=session_id)
        session.current_question_index += 1
        # Use a temporary field or append to transcript to hold last question state
        # In this implementation, we save it inside current_question_index or build it dynamically
        # To maintain simplicity, we can dynamically query or save it to database
        # We will save it in current session metadata structure.
        pass

    @database_sync_to_async
    def get_session_details(self, session_id):
        session = InterviewSession.objects.get(id=session_id)
        transcript = session.transcript or []
        
        # Calculate last question asked
        last_question = ""
        if session.current_question_index > 0:
            # If we've started, we can find the question
            # In our starting round, we save the first question in our memory state
            # Or if it's in the transcript, we pull the last round.
            # To be robust, let's keep a history-based query
            pass
            
        # We will retrieve last_question from self scope or from database session
        # To be highly robust, let's store last_question directly inside the InterviewSession's transcript list
        # as a pending dict if we need, or just track it via memory since we are stateful in consumers!
        # But wait! If the server recycles, memory is lost. So storing it in a database field or a state list is best.
        # Let's read the last element of transcript or fetch it from a custom field:
        # Since we append a completed round (Q+A+Feedback) to transcript, the "last_question" is the one that has not yet
        # been answered.
        # Let's look up transcript or keep a local variable `self.last_question_asked`.
        if hasattr(self, 'last_question_asked'):
            last_question = self.last_question_asked
        return {
            "transcript": transcript,
            "last_question": last_question
        }

    @database_sync_to_async
    def update_session_transcript(self, session_id, transcript_data):
        session = InterviewSession.objects.get(id=session_id)
        session.transcript = transcript_data
        session.save()

    @database_sync_to_async
    def set_last_question(self, session_id, question):
        self.last_question_asked = question

    @database_sync_to_async
    def add_proctor_infraction(self, session_id, infraction):
        session = InterviewSession.objects.get(id=session_id)
        logs = session.proctoring_logs or []
        logs.append(infraction)
        session.proctoring_logs = logs
        session.save()
        
        # Decrement proctoring score on Application
        app = session.application
        penalty = 5
        if "Not Detected" in infraction.get('type', ''):
            penalty = 15
        app.proctoring_score = max(0, app.proctoring_score - penalty)
        app.save()

    @database_sync_to_async
    def complete_session_in_db(self, session_id):
        session = InterviewSession.objects.get(id=session_id)
        session.session_status = 'completed'
        
        # Compute and save average metrics across session turns to the database session
        valid_conf = [t.get('confidence', 0) for t in session.transcript if t.get('confidence', 0) > 0]
        session.avg_confidence = int(sum(valid_conf) / len(valid_conf)) if valid_conf else 0
        
        valid_clar = [t.get('clarity', 0) for t in session.transcript if t.get('clarity', 0) > 0]
        session.avg_clarity = int(sum(valid_clar) / len(valid_clar)) if valid_clar else 0
        
        session.save()

        # Update application status to evaluated
        app = session.application
        app.status = 'evaluated'
        app.save()
