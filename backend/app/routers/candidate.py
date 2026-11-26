"""Candidate pages: dashboard and marketplace, applying, resume scanner, scores and interview review."""
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, true
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from app.core.database import DB
from app.core.security import CurrentUser, ensure_profile, flash, over_hourly_limit
from app.core.templating import paginate, redirect, render
from app.models import Application, Company, InterviewSession, Job
from app.routers.common import ai_error, avg, breakdown, pdf_text, recruiter_company_id, too_many_response
from app.routers.recruiter import recruiter_dashboard
from app.services.brain import InterviewBrain

log = logging.getLogger(__name__)
router = APIRouter()


def _own_sessions(user):
    return select(InterviewSession).join(Application).where(Application.candidate_id == user.id)


async def candidate_dashboard(request, db, user, profile):
    # Job marketplace plus the candidate's own applications and interviews
    applications = (await db.scalars(select(Application).where(Application.candidate_id == user.id)
                                     .order_by(Application.created_at.desc()))).all()
    applied_jobs = [app.job_id for app in applications]
    # Exclude already applied positions from the active marketplace list
    jobs = select(Job).where(Job.is_active, Job.id.not_in(applied_jobs) if applied_jobs else true()).order_by(Job.created_at.desc())
    query = request.query_params.get('q', '').strip()
    if query:  # skills live in the description
        jobs = jobs.join(Company).where(Job.title.icontains(query, autoescape=True) | Company.name.icontains(query, autoescape=True)
                                        | Job.description.icontains(query, autoescape=True))
    level = request.query_params.get('level', '')
    if level:
        jobs = jobs.where(Job.experience_level == level)
    # Levels are free text typed by recruiters, so offer the ones actually in use
    levels = (await db.scalars(select(Job.experience_level).where(Job.is_active, Job.experience_level != '').distinct()
                               .order_by(Job.experience_level))).all()

    sessions = _own_sessions(user)
    return render(request, 'dashboard.html', {
        'username': user.username,
        'has_resume': bool(profile.resume_text),
        'recent_sessions': (await db.scalars(sessions.order_by(InterviewSession.created_at.desc()).limit(5))).all(),
        'total_interviews': len((await db.scalars(sessions.with_only_columns(InterviewSession.id))).all()),
        'global_avg_conf': await avg(db, sessions, InterviewSession.avg_confidence),
        'global_avg_clar': await avg(db, sessions, InterviewSession.avg_clarity),
        'applications': applications,
        'jobs': await paginate(db, jobs, request.query_params.get('page'), 10),
        'query': query,
        'level': level,
        'levels': levels,
        'applied_jobs': applied_jobs,
    })


@router.get('/dashboard/')
async def dashboard_view(request: Request, db: DB, user: CurrentUser):
    if not user:
        return redirect('/login/')
    profile = await ensure_profile(db, user)
    if profile.role == 'recruiter':
        return await recruiter_dashboard(request, db, user, profile)
    return await candidate_dashboard(request, db, user, profile)


@router.post('/upload-profile-resume/')
async def upload_profile_resume(request: Request, db: DB, user: CurrentUser):
    form = await request.form()
    resume_file = form.get('resume')
    if not user or not isinstance(resume_file, UploadFile):
        return JSONResponse({"status": "error", "message": "Invalid request"}, status_code=400)
    profile = await ensure_profile(db, user)
    data = await resume_file.read()
    to_profile = form.get('redirect_to') == 'profile'
    try:
        text = await run_in_threadpool(pdf_text, data)
    except ValueError as e:
        if to_profile:
            flash(request, 'error', str(e))
            return redirect('/profile/')
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)
    profile.resume_pdf, profile.resume_text = data, text
    await db.commit()

    if to_profile:
        flash(request, 'success', 'Resume successfully verified and parsed.')
        return redirect('/profile/')
    return JSONResponse({"status": "success", "message": "Resume uploaded successfully."})


@router.post('/delete-session/{session_id}/')
async def delete_session(session_id: int, db: DB, user: CurrentUser):
    if not user:
        return redirect('/login/')
    # Recruiters delete by application, candidates delete their own
    stmt = select(InterviewSession).join(Application).where(InterviewSession.id == session_id)
    if user.profile and user.profile.role == 'recruiter':
        stmt = stmt.join(Job).where(Job.company_id == recruiter_company_id(user))  # no company: matches nothing
    else:
        stmt = stmt.where(Application.candidate_id == user.id)
    if (session := await db.scalar(stmt)):
        await db.delete(session)
        await db.commit()
    return redirect('/dashboard/')


@router.get('/scores/')
async def scores_view(request: Request, db: DB, user: CurrentUser):
    if not user:
        return redirect('/login/')
    sessions = _own_sessions(user)
    return render(request, 'scores.html', {
        'total_count': len((await db.scalars(sessions.with_only_columns(InterviewSession.id))).all()),
        'global_avg_conf': await avg(db, sessions, InterviewSession.avg_confidence),
        'global_avg_clar': await avg(db, sessions, InterviewSession.avg_clarity),
        'global_tech': await avg(db, sessions, InterviewSession.tech_knowledge),
        'global_behav': await avg(db, sessions, InterviewSession.behavioral_iq),
        'global_prob': await avg(db, sessions, InterviewSession.problem_solving),
        'trend': (await db.scalars(sessions.where(InterviewSession.session_status == 'completed')
                                   .order_by(InterviewSession.created_at))).all(),
    })


@router.get('/resume-scanner/')
async def resume_scanner_view(request: Request, user: CurrentUser):
    if not user:
        return redirect('/login/')
    return render(request, 'resume_scanner.html', {'username': user.username})


@router.post('/ai/score-resume/')
async def score_resume_api(request: Request, db: DB, user: CurrentUser):
    if await over_hourly_limit(user, 'score_resume_api', 20):
        return too_many_response()
    if not user:
        return JSONResponse({'error': 'Authentication required'}, status_code=401)
    profile = await ensure_profile(db, user)
    if not profile.resume_text:
        return JSONResponse({'error': 'No resume uploaded to your profile.'}, status_code=400)
    jd_text = (await request.form()).get('jd', 'No JD provided.')
    await db.commit()  # frees the DB connection for the AI call
    try:
        return await InterviewBrain().get_resume_score(profile.resume_text, jd_text)
    except Exception as e:
        log.exception("Resume scan failed")
        return JSONResponse({'error': ai_error(e)}, status_code=502)


@router.post('/ai/apply-to-job/')
async def apply_to_job(request: Request, db: DB, user: CurrentUser):
    if await over_hourly_limit(user, 'apply_to_job', 20):
        return too_many_response()
    if not user:
        return JSONResponse({'success': False, 'error': 'Please log in to apply.'}, status_code=401)
    form = await request.form()
    resume_file = form.get('resume')
    if not isinstance(resume_file, UploadFile):
        return JSONResponse({'success': False, 'error': 'Invalid request'}, status_code=400)
    job_id = form.get('job_id', '')
    job = await db.get(Job, int(job_id)) if job_id.isdigit() else None
    if not job or not job.is_active:
        return JSONResponse({'success': False, 'error': 'This job is no longer accepting applications.'}, status_code=400)
    try:
        resume_bytes = await resume_file.read()
        resume_text = await run_in_threadpool(pdf_text, resume_bytes)
        await db.commit()  # frees the DB connection for the AI call
        ats = await InterviewBrain().get_resume_score(resume_text, job.description)
        app = Application(job=job, candidate_id=user.id, resume_pdf=resume_bytes, resume_text=resume_text,
                          ats_match_score=ats['score'], ats_breakdown=breakdown(ats))
        db.add(app)
        await db.commit()
        return {
            'success': True,
            'app_id': app.id,
            'ats_score': float(ats['score']),
            'job_title': job.title,
            'company_name': job.company.name,
            'missing_keywords': ats.get('missing_keywords', []),
            'improvement_suggestions': ats.get('improvement_suggestions', []),
        }
    except ValueError as e:  # unreadable resume; the message is written for the user
        return JSONResponse({'success': False, 'error': str(e)}, status_code=400)
    except IntegrityError:
        await db.rollback()
        return JSONResponse({'success': False, 'error': 'You already applied to this role.'}, status_code=400)
    except Exception as e:
        log.exception("Applying to job %s failed", job.id)
        return JSONResponse({'success': False, 'error': ai_error(e)}, status_code=502)


@router.get('/review/{session_id}/')
async def review_session(request: Request, session_id: int, db: DB, user: CurrentUser):
    if not user:
        return redirect('/login/')
    session = await db.scalar(_own_sessions(user).where(InterviewSession.id == session_id,
                                                        InterviewSession.session_status == 'completed'))
    if not session:
        raise HTTPException(404)
    return render(request, 'review.html', {'session': session})
