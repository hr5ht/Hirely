"""Stateless interview steps: every request reloads the session, so any worker can serve any step.

The pending question is the last transcript turn without an 'answer'.
"""
import asyncio
import json
import logging
import time

from sqlalchemy import func, select, update

from app.services import notify, rag
from app.core.database import save
from app.services.audio import AudioService
from app.services.brain import InterviewBrain
from app.models import Application, InterviewSession
from app.services.reports import compile_performance_report_pdf, evaluate_transcript_semantic_gaps

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


def custom_question_rounds(rounds, questions):
    """{round index: question} for the recruiter's must-ask questions, kept in order.

    Round 0 is always the AI's resume-grounded opener; custom questions take every other round after it,
    then the rounds in between if there are more questions than that.
    """
    slots = list(range(1, rounds, 2)) + list(range(2, rounds, 2))
    return dict(zip(sorted(slots[:len(questions)]), questions))


def _now():
    return int(time.time())


def heartbeat_gaps(beats, until):
    """(start, seconds) for every silence longer than HEARTBEAT_GAP between pings, and from the last ping to `until`."""
    points = sorted(beats) + [until]
    return [(a, b - a) for a, b in zip(points, points[1:]) if b - a > HEARTBEAT_GAP] if beats else []


# Alerts that mean nobody is being watched at all cost as much as a missing face
SEVERE_ALERTS = {"Camera Stopped"}


async def _speech(text, data):
    """Base64 audio for the end-of-interview summary; or, when the caller collects data['speak_later'] (the
    WebSocket), None now and the text is queued, so the summary's text goes out without waiting for its audio."""
    if (later := data.get('speak_later')) is not None:
        later.append(text)
        return None
    return await AudioService().text_to_speech(text)


async def _question(text, session, data):
    job = session.application.job
    remaining = job.answer_time_limit - (_now() - session.transcript[-1].get('asked_at', _now())) if job.answer_time_limit else 0
    # The page plays this URL as it downloads, so speech starts after ElevenLabs' first chunk, not its last.
    # text is always the pending question, transcript[-1]; the URL names it by position, never by text.
    audio_url = f"/ai/interview/{session.id}/speech/{len(session.transcript) - 1}/" if AudioService().speaks else None
    return {"type": "interview_message", "message_type": "question", "text": text, "audio_url": audio_url,
            "round": len(session.transcript), "total_rounds": job.interview_rounds,
            "seconds_left": max(remaining, 1) if job.answer_time_limit else None}


async def start(db, session, data):
    app = session.application
    transcript = session.transcript
    if transcript and 'answer' not in transcript[-1]:
        # Page reload: re-serve the pending question instead of paying for a new one,
        # and flag it so a reload can't be used to escape a question unnoticed
        await proctor(db, session, {"type": "Interview page reloaded"})
        return [await _question(transcript[-1]['question'], session, data)]

    await db.commit()  # frees the DB connection for the AI calls
    resume_ctx, jd_ctx = await rag.retrieve(f"{app.job.title} {ROUND_TOPICS[0]}", app.resume_text, app.job.description,
                                            cache=session.rag_cache)
    question = await InterviewBrain().generate_initial_question(app.job.title, jd_ctx, resume_ctx, level=app.job.experience_level)
    session.transcript = transcript + [{"question": question, "context": {"resume": resume_ctx, "jd": jd_ctx}, "asked_at": _now()}]
    await save(db, session, 'transcript', 'rag_cache')
    return [await _question(question, session, data)]


async def answer(db, session, data):
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
        await proctor(db, session, {"type": "Answered after the time limit"})
    await db.commit()  # frees the DB connection for the AI calls

    turn.update(answer=text, timestamp=time.strftime('%Y-%m-%dT%H:%M:%SZ'))
    is_last = len(transcript) >= app.job.interview_rounds
    custom = None if is_last else custom_question_rounds(app.job.interview_rounds, app.job.custom_questions).get(len(transcript))

    async def follow_up():
        # Query = this round's topic + what they just said, so follow-ups dig into their own claims
        topic = ROUND_TOPICS[len(transcript) % len(ROUND_TOPICS)]
        resume_ctx, jd_ctx = await rag.retrieve(f"{app.job.title} {topic} {text}", app.resume_text, app.job.description,
                                                cache=session.rag_cache)
        return resume_ctx, jd_ctx, await brain.get_next_question(transcript, jd_ctx, resume_ctx, level=app.job.experience_level)

    if is_last or custom:
        analysis_raw, follow = await brain.get_feedback(turn['question'], text), None
    else:
        # Scoring the answer and writing the next question don't depend on each other (the question
        # prompt reads only questions and answers), so they run at the same time
        analysis_raw, follow = await asyncio.gather(brain.get_feedback(turn['question'], text), follow_up())
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

    turn.update(feedback=feedback_text, confidence=insights['confidence'], clarity=insights['clarity'])
    messages = [
        {"type": "insights_update", "insights": insights},
        {"type": "interview_message", "message_type": "silent_feedback", "text": feedback_text},
    ]

    if is_last:
        qa = [{k: v for k, v in t.items() if k != 'context'} for t in transcript]  # excerpts would only cost tokens
        summary = await brain.get_summary(app.job.title, json.dumps(qa))
        messages.append({"type": "interview_message", "message_type": "summary", "text": summary,
                         "audio": await _speech(summary, data)})
    elif custom:
        transcript.append({"question": custom, "custom": True, "asked_at": _now()})
        messages.append(await _question(custom, session, data))
    else:
        resume_ctx, jd_ctx, next_q = follow
        # Kept with the turn so a reviewer can see what each question was grounded in
        transcript.append({"question": next_q, "context": {"resume": resume_ctx, "jd": jd_ctx}, "asked_at": _now()})
        messages.append(await _question(next_q, session, data))

    await save(db, session, 'transcript', 'rag_cache')
    return messages


async def audio(db, session, data):
    await db.commit()  # frees the DB connection for the AI calls
    text = await AudioService().transcribe_audio(data.get('audio', ''), data.get('mimeType', 'audio/webm'))
    if not text:
        return [{"type": "transcription_result", "text": "", "error": "Transcription failed"}]
    return [{"type": "transcription_result", "text": text}] + await answer(db, session, {**data, "answer": text})


async def _locked(db, session):
    """The session row locked for this transaction and reloaded, so parallel alerts/pings can't overwrite each other."""
    stmt = select(InterviewSession).where(InterviewSession.id == session.id).with_for_update()
    return await db.scalar(stmt.execution_options(populate_existing=True))


async def proctor(db, session, data):
    infraction = {"type": data.get('type', 'Gaze Deviation'), "timestamp": data.get('timestamp', time.strftime('%Y-%m-%dT%H:%M:%SZ'))}
    log.warning("Proctor alert on session %s: %s at %s", session.id, infraction['type'], infraction['timestamp'])
    penalty = 15 if "Not Detected" in infraction['type'] or infraction['type'] in SEVERE_ALERTS else 5
    locked = await _locked(db, session)
    locked.proctoring_logs = (locked.proctoring_logs or []) + [infraction]
    await db.execute(update(Application).where(Application.id == session.application_id)
                     .values(proctoring_score=func.greatest(Application.proctoring_score - penalty, 0))
                     .execution_options(synchronize_session=False))
    await db.commit()
    return []


async def heartbeat(db, session, data):
    # Server time, so a client can't backfill pings it never sent
    locked = await _locked(db, session)
    locked.heartbeats = (locked.heartbeats or []) + [_now()]
    await db.commit()
    return []


async def end(db, session, data):
    log.info("Closing session %s and compiling report", session.id)
    await db.refresh(session, ['heartbeats'])
    for start_at, seconds in heartbeat_gaps(session.heartbeats, _now()):
        await proctor(db, session, {"type": f"Camera heartbeat gap ({seconds} s)",
                                    "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(start_at))})
    transcript = [t for t in session.transcript if 'answer' in t]  # drop the unanswered pending question
    valid_conf = [t['confidence'] for t in transcript if t.get('confidence', 0) > 0]
    valid_clar = [t['clarity'] for t in transcript if t.get('clarity', 0) > 0]

    session.transcript = transcript
    session.session_status = 'completed'
    session.avg_confidence = int(sum(valid_conf) / len(valid_conf)) if valid_conf else 0
    session.avg_clarity = int(sum(valid_clar) / len(valid_clar)) if valid_clar else 0
    session.application.status = 'evaluated'
    await save(db, session, 'transcript')
    await db.refresh(session.application, ['proctoring_score'])  # alerts changed it in SQL

    log.info(await evaluate_transcript_semantic_gaps(db, session))
    log.info(await compile_performance_report_pdf(db, session))
    await notify.interview_completed(db, session, data.get('base_url', '') + f"/ai/candidate-detail/{session.application_id}/")
    return [{"type": "session_completed", "message": "Interview completed successfully."}]


ACTIONS = {"start": start, "answer": answer, "audio": audio, "proctor": proctor, "heartbeat": heartbeat, "end": end}
