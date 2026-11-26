"""The interview page, its stateless JSON steps, and report downloads."""
import asyncio
import json
import logging
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request, WebSocket
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import undefer

from app.core.database import DB, SessionLocal
from app.core.security import CurrentUser, get_user, over_hourly_limit
from app.core.templating import base_url, redirect, render
from app.models import Application, InterviewSession, Job
from app.routers.common import TOO_MANY_JSON, ai_error, recruiter_company_id, safe_filename, too_many_response
from app.services import interview
from app.services.audio import AudioService

log = logging.getLogger(__name__)
router = APIRouter()

AI_ACTIONS = {'start', 'answer', 'audio'}  # the steps that call paid AI APIs are capped per user


@router.get('/session/')
async def session_view(request: Request, db: DB, user: CurrentUser):
    if not user:
        return redirect('/login/')
    app_id = request.query_params.get('app_id', '')
    app = await db.scalar(select(Application).where(Application.id == int(app_id), Application.candidate_id == user.id)) \
        if app_id.isdigit() else None
    # Back to the dashboard if there's no such application or it's already evaluated
    if not app or app.status == 'evaluated':
        return redirect('/dashboard/')

    session = app.sessions[0] if app.sessions else None
    if session is None:
        session = InterviewSession(application=app, session_status='active')
        db.add(session)
    elif session.session_status == 'completed':
        return redirect('/dashboard/')
    elif session.session_status == 'pending':
        session.session_status = 'active'
    await db.commit()

    return render(request, 'session.html', {
        'session_id': session.id,
        'resume_text': app.resume_text,
        'role': app.job.title,
        'company': app.job.company.name,
        'jd': app.job.description,
    })


def _own_session(db, user, session_id):
    return db.scalar(select(InterviewSession).join(Application).options(undefer(InterviewSession.rag_cache))
                     .where(InterviewSession.id == session_id, Application.candidate_id == user.id))


@router.post('/ai/interview/{session_id}/{action}/')
async def interview_action(request: Request, session_id: int, action: str, db: DB, user: CurrentUser):
    if action in AI_ACTIONS and await over_hourly_limit(user, 'interview_action', 60):
        return too_many_response()
    if not user:
        return JSONResponse({'error': 'Authentication required'}, status_code=401)
    if action not in interview.ACTIONS:
        return JSONResponse({'error': 'Unknown action'}, status_code=404)

    session = await _own_session(db, user, session_id)
    if not session:
        raise HTTPException(404)
    if session.session_status == 'completed':
        return {'messages': [{'type': 'session_completed'}]}

    data = {}
    if request.headers.get('content-type', '').startswith('application/json'):
        try:
            data = json.loads(await request.body())
        except ValueError:
            return JSONResponse({'error': 'Invalid JSON'}, status_code=400)
    data['base_url'] = base_url(request)  # for links in emails; never from the client
    try:
        return {'messages': await interview.ACTIONS[action](db, session, data)}
    except Exception as e:
        log.exception("Interview %s failed on session %s", action, session_id)
        await db.rollback()
        return JSONResponse({'error': ai_error(e)}, status_code=502)


@router.get('/ai/interview/{session_id}/speech/{index}/')
async def question_speech(session_id: int, index: int, db: DB, user: CurrentUser):
    """A question's audio, relayed from ElevenLabs as it streams. Only questions already in the candidate's own
    transcript can be spoken, so the endpoint can't be used to synthesize arbitrary text on our account."""
    if not user:
        return JSONResponse({'error': 'Authentication required'}, status_code=401)
    if await over_hourly_limit(user, 'question_speech', 120):
        return too_many_response()
    session = await _own_session(db, user, session_id)
    question = session.transcript[index].get('question') if session and 0 <= index < len(session.transcript) else None
    await db.commit()  # frees the DB connection while the audio streams
    if not question:
        raise HTTPException(404)
    # shortcut: every request synthesizes again (a reload replays the question); cache the bytes if that costs too much
    upstream = await AudioService().open_speech_stream(question)
    if upstream is None:
        return Response(status_code=502)

    async def relay():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
    return StreamingResponse(relay(), media_type='audio/mpeg')


@router.websocket('/ws/interview/{session_id}/')
async def interview_socket(ws: WebSocket, session_id: int):
    """The same interview steps over one connection, plus live speech-to-text.

    Client frames: JSON {"action": <step>, "id": n, ...}; "audio_start", then the recording as binary
    chunks while the candidate speaks, then "audio_end". The server replies with the step's messages,
    then {"type": "done", "id": n}, then each question's audio as {"type": "audio"} once it's ready.
    """
    # Browsers attach cookies to WebSocket handshakes from any site, so only our own pages may connect
    if urlparse(ws.headers.get('origin', '')).netloc != ws.headers.get('host'):
        await ws.close(code=1008)
        return
    async with SessionLocal() as db:
        user = await get_user(ws, db)
    if not user:
        await ws.close(code=1008)
        return
    await ws.accept()
    site = f"{'https' if ws.url.scheme == 'wss' else 'http'}://{ws.headers['host']}"  # for links in emails
    steps = set()  # running steps; each has its own DB session, like separate HTTP requests

    async def step(action, msg, transcriber=None):
        later, ok = [], False
        try:
            if action in AI_ACTIONS and await over_hourly_limit(user, 'interview_action', 60):
                await ws.send_json({'type': 'error', 'message': TOO_MANY_JSON['error']})
                return
            async with SessionLocal() as db:
                session = await _own_session(db, user, session_id)
                if not session:
                    await ws.send_json({'type': 'error', 'message': 'Interview not found.'})
                    return
                if session.session_status == 'completed':
                    messages = [{'type': 'session_completed'}]
                else:
                    data = {**msg, 'speak_later': later, 'base_url': site}  # base_url never from the client
                    if transcriber:
                        text = await transcriber.finish()
                        # Their own words appear right away (~0.3 s), before the AI has read them
                        await ws.send_json({'type': 'transcription_result', 'text': text or '', **({} if text else {'error': 'Transcription failed'})})
                        messages = await interview.answer(db, session, {**data, 'answer': text}) if text else []
                    else:
                        messages = await interview.ACTIONS[action](db, session, data)
            for message in messages:
                await ws.send_json(message)
            ok = True
        except Exception as e:
            log.exception("Interview %s failed on session %s (socket)", action, session_id)
            await ws.send_json({'type': 'error', 'message': ai_error(e)})
        finally:
            await ws.send_json({'type': 'done', 'id': msg.get('id'), 'ok': ok})
        for text in later:  # after "done", so the page can take the next answer while the audio is made
            if (audio := await AudioService().text_to_speech(text)):
                await ws.send_json({'type': 'audio', 'audio': audio})

    def run(coro):
        task = asyncio.create_task(coro)
        steps.add(task)
        task.add_done_callback(steps.discard)

    transcriber = None
    try:
        while True:
            frame = await ws.receive()
            if frame['type'] == 'websocket.disconnect':
                break
            if frame.get('bytes') is not None:
                if transcriber:
                    transcriber.feed(frame['bytes'])
                continue
            try:
                msg = json.loads(frame.get('text') or '')
            except ValueError:
                continue
            action = msg.get('action')
            if action == 'audio_start':
                if transcriber:
                    transcriber.cancel()
                transcriber = AudioService().live_transcription()
            elif action == 'audio_end':
                if transcriber:
                    run(step('audio', msg, transcriber))
                else:
                    await ws.send_json({'type': 'transcription_result', 'text': '', 'error': 'Transcription failed'})
                    await ws.send_json({'type': 'done', 'id': msg.get('id'), 'ok': False})
                transcriber = None
            elif action in interview.ACTIONS and action != 'audio':
                run(step(action, msg))
    finally:
        if transcriber:
            transcriber.cancel()
        for task in steps:
            task.cancel()


@router.get('/download-session/{session_id}/')
async def download_session_pdf(session_id: int, db: DB, user: CurrentUser):
    if not user:
        return redirect('/login/')
    # Candidates get their own reports, recruiters their company's
    stmt = select(InterviewSession).join(Application).options(undefer(InterviewSession.pdf_report)).where(InterviewSession.id == session_id)
    if user.profile and user.profile.role == 'recruiter':
        stmt = stmt.join(Job).where(Job.company_id == recruiter_company_id(user))
    else:
        stmt = stmt.where(Application.candidate_id == user.id)
    session = await db.scalar(stmt)
    if not session or not session.pdf_report:
        return redirect('/dashboard/')
    job = session.application.job
    name = f"Hirely_{safe_filename(job.company.name)}_{safe_filename(job.title)}_Report.pdf"
    return Response(bytes(session.pdf_report), media_type='application/pdf',
                    headers={'Content-Disposition': f'attachment; filename="{name}"'})
