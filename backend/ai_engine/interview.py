"""Stateless interview steps: every request reloads the session, so this runs on serverless hosts.

The pending question is the last transcript turn without an 'answer'.
"""
import json
import logging
import time
from django.db import transaction
from django.db.models import F
from django.db.models.functions import Greatest

from ai_engine.models import InterviewSession, Application
from ai_engine.brain import InterviewBrain
from ai_engine.audio_service import AudioService
from ai_engine.reports import evaluate_transcript_semantic_gaps, compile_performance_report_pdf
from ai_engine import rag

log = logging.getLogger(__name__)

# Each round retrieves resume/JD chunks for a different topic, so questions move across the candidate's profile;
# interviews longer than this list cycle back through it
ROUND_TOPICS = [
    "core qualifications required skills experience",
    "core technical skills languages frameworks",
    "system architecture databases deployment cloud",
    "testing edge cases collaboration teamwork",
    "scaling performance technical leadership",
]


HEARTBEAT_SECONDS = 30  # the page pings this often while the camera is live
HEARTBEAT_GAP = 90  # three missed pings in a row: the camera (or the page) was off


def _now():
    return int(time.time())


def heartbeat_gaps(beats, until):
    """(start, seconds) for every silence longer than HEARTBEAT_GAP between pings, and from the last ping to `until`."""
    points = sorted(beats) + [until]
    return [(a, b - a) for a, b in zip(points, points[1:]) if b - a > HEARTBEAT_GAP] if beats else []


# Alerts that mean nobody is being watched at all cost as much as a missing face
SEVERE_ALERTS = {"Camera Stopped"}


def _question(text, session):
    job = session.application.job
    remaining = job.answer_time_limit - (_now() - session.transcript[-1].get('asked_at', _now())) if job.answer_time_limit else 0
    return {"type": "interview_message", "message_type": "question", "text": text, "audio": AudioService().text_to_speech(text),
            "round": len(session.transcript), "total_rounds": job.interview_rounds,
            "seconds_left": max(remaining, 1) if job.answer_time_limit else None}


def start(session, data):
    app = session.application
    transcript = session.transcript
    if transcript and 'answer' not in transcript[-1]:
        # Page reload: re-serve the pending question instead of paying for a new one,
        # and flag it so a reload can't be used to escape a question unnoticed
        proctor(session, {"type": "Interview page reloaded"})
        return [_question(transcript[-1]['question'], session)]

    resume_ctx, jd_ctx = rag.retrieve(f"{app.job.title} {ROUND_TOPICS[0]}", app.resume_text, app.job.description,
                                      cache=session.rag_cache)
    question = InterviewBrain().generate_initial_question(app.job.title, jd_ctx, resume_ctx, level=app.job.experience_level)
    session.transcript = transcript + [{"question": question, "context": {"resume": resume_ctx, "jd": jd_ctx}, "asked_at": _now()}]
    session.save(update_fields=['transcript', 'rag_cache'])
    return [_question(question, session)]


def answer(session, data):
    text = data.get('answer', '').strip()
    transcript = session.transcript
    if not text or not transcript or 'answer' in transcript[-1]:
        return []

    app = session.application
    brain = InterviewBrain()
    turn = transcript[-1]
    # The countdown runs in the browser; the server checks it too, with a little slack for the network
    limit = app.job.answer_time_limit
    if limit and 'asked_at' in turn and _now() - turn['asked_at'] > limit + 15:
        proctor(session, {"type": "Answered after the time limit"})
    analysis_raw = brain.get_feedback(turn['question'], text)
    try:
        analysis = json.loads(analysis_raw)
        feedback_text = analysis.get('feedback', analysis_raw)
        insights = {
            'confidence': analysis.get('confidence', 85),
            'clarity': analysis.get('clarity', 90),
            'tone': analysis.get('tone', 'Confident')
        }
    except Exception:
        feedback_text = analysis_raw
        insights = {'confidence': 80, 'clarity': 80, 'tone': 'Detected'}

    turn.update(answer=text, feedback=feedback_text, confidence=insights['confidence'], clarity=insights['clarity'],
                timestamp=time.strftime('%Y-%m-%dT%H:%M:%SZ'))
    messages = [
        {"type": "insights_update", "insights": insights},
        {"type": "interview_message", "message_type": "silent_feedback", "text": feedback_text},
    ]

    if len(transcript) >= app.job.interview_rounds:
        qa = [{k: v for k, v in t.items() if k != 'context'} for t in transcript]  # excerpts would only cost tokens
        summary = brain.get_summary(app.job.title, json.dumps(qa))
        messages.append({"type": "interview_message", "message_type": "summary", "text": summary,
                         "audio": AudioService().text_to_speech(summary)})
    else:
        # Query = this round's topic + what they just said, so follow-ups dig into their own claims
        topic = ROUND_TOPICS[len(transcript) % len(ROUND_TOPICS)]
        resume_ctx, jd_ctx = rag.retrieve(f"{app.job.title} {topic} {text}", app.resume_text, app.job.description,
                                          cache=session.rag_cache)
        next_q = brain.get_next_question(transcript, jd_ctx, resume_ctx, level=app.job.experience_level)
        # Kept with the turn so a reviewer can see what each question was grounded in
        transcript.append({"question": next_q, "context": {"resume": resume_ctx, "jd": jd_ctx}, "asked_at": _now()})
        messages.append(_question(next_q, session))

    session.transcript = transcript
    session.save(update_fields=['transcript', 'rag_cache'])
    return messages


def audio(session, data):
    text = AudioService().transcribe_audio(data.get('audio', ''), data.get('mimeType', 'audio/webm'))
    if not text:
        return [{"type": "transcription_result", "text": "", "error": "Transcription failed"}]
    return [{"type": "transcription_result", "text": text}] + answer(session, {"answer": text})


def proctor(session, data):
    infraction = {"type": data.get('type', 'Gaze Deviation'), "timestamp": data.get('timestamp', time.strftime('%Y-%m-%dT%H:%M:%SZ'))}
    log.warning("Proctor alert on session %s: %s at %s", session.id, infraction['type'], infraction['timestamp'])
    penalty = 15 if "Not Detected" in infraction['type'] or infraction['type'] in SEVERE_ALERTS else 5
    # Alerts can arrive in parallel requests; lock the row so none overwrite each other
    with transaction.atomic():
        locked = InterviewSession.objects.select_for_update().get(id=session.id)
        locked.proctoring_logs = (locked.proctoring_logs or []) + [infraction]
        locked.save(update_fields=['proctoring_logs'])
        Application.objects.filter(id=session.application_id).update(proctoring_score=Greatest(F('proctoring_score') - penalty, 0))
    return []


def heartbeat(session, data):
    # Server time, so a client can't backfill pings it never sent
    with transaction.atomic():
        locked = InterviewSession.objects.select_for_update().get(id=session.id)
        locked.heartbeats = (locked.heartbeats or []) + [_now()]
        locked.save(update_fields=['heartbeats'])
    return []


def end(session, data):
    log.info("Closing session %s and compiling report", session.id)
    session.refresh_from_db(fields=['heartbeats'])
    for start, seconds in heartbeat_gaps(session.heartbeats, _now()):
        proctor(session, {"type": f"Camera heartbeat gap ({seconds} s)",
                          "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(start))})
    transcript = [t for t in session.transcript if 'answer' in t]  # drop the unanswered pending question
    valid_conf = [t['confidence'] for t in transcript if t.get('confidence', 0) > 0]
    valid_clar = [t['clarity'] for t in transcript if t.get('clarity', 0) > 0]

    session.transcript = transcript
    session.session_status = 'completed'
    session.avg_confidence = int(sum(valid_conf) / len(valid_conf)) if valid_conf else 0
    session.avg_clarity = int(sum(valid_clar) / len(valid_clar)) if valid_clar else 0
    session.save(update_fields=['transcript', 'session_status', 'avg_confidence', 'avg_clarity'])
    Application.objects.filter(id=session.application_id).update(status='evaluated')

    log.info(evaluate_transcript_semantic_gaps(session.id))
    log.info(compile_performance_report_pdf(session.id))
    return [{"type": "session_completed", "message": "Interview completed successfully."}]


ACTIONS = {"start": start, "answer": answer, "audio": audio, "proctor": proctor, "heartbeat": heartbeat, "end": end}
