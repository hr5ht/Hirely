"""The interview page, its stateless JSON steps, and report downloads."""
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import undefer

from app.core.database import DB
from app.core.security import CurrentUser, over_hourly_limit
from app.core.templating import base_url, redirect, render
from app.models import Application, InterviewSession, Job
from app.routers.common import ai_error, recruiter_company_id, safe_filename, too_many_response
from app.services import interview

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


@router.post('/ai/interview/{session_id}/{action}/')
async def interview_action(request: Request, session_id: int, action: str, db: DB, user: CurrentUser):
    if action in AI_ACTIONS and await over_hourly_limit(user, 'interview_action', 60):
        return too_many_response()
    if not user:
        return JSONResponse({'error': 'Authentication required'}, status_code=401)
    if action not in interview.ACTIONS:
        return JSONResponse({'error': 'Unknown action'}, status_code=404)

    session = await db.scalar(select(InterviewSession).join(Application).options(undefer(InterviewSession.rag_cache))
                              .where(InterviewSession.id == session_id, Application.candidate_id == user.id))
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
