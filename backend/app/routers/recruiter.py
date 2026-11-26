"""Recruiter pages: dashboard, jobs, applicants, notes, exports, comparisons and invites."""
import csv
import io
import logging
from collections import Counter

from fastapi import APIRouter, Request
from fastapi.responses import Response
from sqlalchemy import case, delete, func, select
from sqlalchemy.orm import undefer

from app.core.database import DB
from app.core.security import CurrentUser, flash, over_hourly_limit
from app.core.templating import base_url, paginate, redirect, render
from app.models import WEIGHT_DEFAULTS, Application, Company, CompanyInvite, InterviewSession, Job, now
from app.routers.common import breakdown, company_application, company_job, recruiter_company_id, safe_filename
from app.services import notify
from app.services.brain import InterviewBrain

log = logging.getLogger(__name__)
router = APIRouter(prefix='/ai')

WEIGHT_FIELDS = tuple(WEIGHT_DEFAULTS)


async def recruiter_dashboard(request, db, user, profile):
    company = profile.company
    if not company:
        # Never fall back to a shared company: that would expose other recruiters' applicants
        company = profile.company = Company(name=f"{user.username}'s company")
        await db.commit()

    done = ('evaluated', 'accepted', 'rejected')
    rows = await db.execute(
        select(Job, func.count(Application.id), func.avg(Application.ats_match_score),
               func.avg(case((Application.status.in_(done), Application.proctoring_score))))
        .outerjoin(Application, Application.job_id == Job.id).where(Job.company_id == company.id)
        .group_by(Job.id).order_by(Job.created_at.desc()))
    jobs = []
    for job, applicant_count, avg_ats, avg_integrity in rows.all():
        job.applicant_count, job.avg_ats, job.avg_integrity = applicant_count, avg_ats, avg_integrity
        jobs.append(job)

    applications, selected_job = await _filtered_applications(request, db, company.id)
    completed, avg_score = (await db.execute(
        select(func.count(), func.avg(Application.proctoring_score)).select_from(InterviewSession).join(Application).join(Job)
        .where(Job.company_id == company.id, InterviewSession.session_status == 'completed'))).one()
    invites = (await db.scalars(select(CompanyInvite).where(CompanyInvite.company_id == company.id, CompanyInvite.used_by_id.is_(None),
                                                            CompanyInvite.expires_at > now())
                                .order_by(CompanyInvite.created_at.desc()))).all()

    return render(request, 'recruiter_dashboard.html', {
        'company': company,
        'jobs': jobs,
        'applications': await paginate(db, applications, request.query_params.get('page'), 20),
        'selected_job': selected_job,
        'statuses': Application.STATUS_CHOICES,
        'status': request.query_params.get('status', ''),
        'min_score': request.query_params.get('min_score', ''),
        'total_jobs': len(jobs),
        'total_candidates': await db.scalar(select(func.count(Application.id)).join(Job).where(Job.company_id == company.id)),
        'avg_proctoring_score': int(avg_score or 0) if completed else None,
        'max_applicants': max((j.applicant_count for j in jobs), default=0) or 1,
        'open_invites': [(i, f"{base_url(request)}/register/?invite={i.token}") for i in invites],
        'weight_inputs': [(f, label, WEIGHT_DEFAULTS[f]) for f, label in zip(WEIGHT_FIELDS, ('Technical', 'Behavioral', 'Problem solving'))],
    })


async def _filtered_applications(request, db, company_id):
    """The company's applications narrowed by the dashboard's ?job, ?status and ?min_score filters."""
    stmt = select(Application).join(Job).where(Job.company_id == company_id).order_by(Application.ats_match_score.desc())
    status = request.query_params.get('status', '')
    if status in dict(Application.STATUS_CHOICES):
        stmt = stmt.where(Application.status == status)
    min_score = request.query_params.get('min_score', '')
    if min_score.isdigit():
        stmt = stmt.where(Application.ats_match_score >= int(min_score))
    job_id = request.query_params.get('job', '')
    selected_job = await db.scalar(select(Job).where(Job.id == int(job_id), Job.company_id == company_id)) if job_id.isdigit() else None
    if selected_job:
        stmt = stmt.where(Application.job_id == selected_job.id)
    return stmt, selected_job


@router.get('/candidate-resume/{application_id}/')
async def download_candidate_resume(application_id: int, db: DB, user: CurrentUser):
    """Allow recruiters to download the PDF resume submitted by a candidate for a specific application."""
    if not user:
        return redirect('/login/')
    company_id = recruiter_company_id(user)
    app = company_id and await db.scalar(select(Application).join(Job).options(undefer(Application.resume_pdf))
                                         .where(Application.id == application_id, Job.company_id == company_id))
    if app and app.resume_pdf:
        name = f"Resume_{safe_filename(app.candidate.username, '_-')}_{safe_filename(app.job.title)}.pdf"
        return Response(bytes(app.resume_pdf), media_type='application/pdf',
                        headers={'Content-Disposition': f'attachment; filename="{name}"'})
    if app and app.resume_text:  # Fallback: the resume text as a plain-text download
        return Response(app.resume_text, media_type='text/plain; charset=utf-8',
                        headers={'Content-Disposition': f'attachment; filename="Resume_{safe_filename(app.candidate.username, "_-")}.txt"'})
    return redirect('/dashboard/')


@router.get('/compare/')
async def compare_candidates(request: Request, db: DB, user: CurrentUser):
    if not user:
        return redirect('/login/')
    company_id = recruiter_company_id(user)
    if not company_id:
        return redirect('/dashboard/')
    ids = [int(i) for i in request.query_params.getlist('ids') if i.isdigit()][:3]
    apps = (await db.scalars(select(Application).join(Job).where(Application.id.in_(ids), Job.company_id == company_id))).all()
    rows = [(app, app.sessions[0] if app.sessions else None) for app in apps]
    return render(request, 'compare.html', {'rows': rows})


@router.get('/export-applicants/')
async def export_applicants(request: Request, db: DB, user: CurrentUser):
    if not user:
        return redirect('/login/')
    company_id = recruiter_company_id(user)
    if not company_id:
        return redirect('/dashboard/')
    stmt, _ = await _filtered_applications(request, db, company_id)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(['Candidate', 'Email', 'Job', 'Applied', 'Status', 'ATS score', 'Integrity score', 'Missing skills'])
    for app in (await db.scalars(stmt)).all():
        row = [app.candidate.username, app.candidate.email, app.job.title, app.created_at.date().isoformat(),
               app.status_display, app.ats_match_score, app.proctoring_score,
               '; '.join(app.ats_breakdown.get('missing_keywords', []))]
        # A cell starting with = + - @ runs as a formula in Excel/Sheets
        writer.writerow(["'" + c if isinstance(c, str) and c[:1] in ('=', '+', '-', '@') else c for c in row])
    return Response(out.getvalue(), media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="hirely_applicants.csv"'})


def _rounds(form):
    """Interview length from the job form, kept to 1-10 questions."""
    value = form.get('interview_rounds', '')
    return min(max(int(value), 1), 10) if value.isdigit() else 5


def _time_limit(form):
    """Seconds per question from the job form; 0 (no limit) or 30 s to 10 min."""
    value = form.get('answer_time_limit', '')
    return min(max(int(value), 30), 600) if value.isdigit() and int(value) else 0


def _custom_questions(form):
    """Must-ask questions from the job form: one per line, at most 10, each trimmed to 500 characters."""
    lines = (line.strip()[:500] for line in form.get('custom_questions', '').splitlines())
    return [line for line in lines if line][:10]


def _weights(form):
    """Score weights from the job form, 0-100 each; all zero falls back to the defaults."""
    values = {f: min(int(v), 100) if (v := form.get(f, '')).isdigit() else WEIGHT_DEFAULTS[f] for f in WEIGHT_FIELDS}
    return values if any(values.values()) else dict(WEIGHT_DEFAULTS)


def _job_fields(form):
    return dict(title=form.get('title'), description=form.get('description'), experience_level=form.get('experience_level', ''),
                interview_rounds=_rounds(form), answer_time_limit=_time_limit(form), custom_questions=_custom_questions(form),
                **_weights(form))


@router.post('/post-job/')
async def post_job(request: Request, db: DB, user: CurrentUser):
    form = await request.form()
    company_id = recruiter_company_id(user)
    if company_id and form.get('title') and form.get('description'):
        db.add(Job(company_id=company_id, **_job_fields(form)))
        await db.commit()
    return redirect('/dashboard/')


@router.post('/edit-job/{job_id}/')
async def edit_job(request: Request, job_id: int, db: DB, user: CurrentUser):
    form = await request.form()
    job = await company_job(db, user, job_id)
    if job and form.get('title') and form.get('description'):
        for field, value in _job_fields(form).items():
            setattr(job, field, value)
        await db.commit()
    return redirect('/dashboard/')


@router.post('/toggle-job/{job_id}/')
async def toggle_job(job_id: int, db: DB, user: CurrentUser):
    # Closed jobs drop out of the marketplace and refuse new applications; existing ones are kept
    job = await company_job(db, user, job_id)
    if job:
        job.is_active = not job.is_active
        await db.commit()
    return redirect('/dashboard/')


@router.post('/rescore-job/{job_id}/')
async def rescore_job(job_id: int, db: DB, user: CurrentUser):
    if await over_hourly_limit(user, 'rescore_job', 5):
        return redirect('/dashboard/')
    job = await company_job(db, user, job_id)
    if job:
        brain = InterviewBrain()
        apps = (await db.scalars(select(Application).where(Application.job_id == job.id, Application.resume_text != ''))).all()
        await db.commit()  # frees the DB connection for the AI calls
        # shortcut: one LLM call per applicant inside the request, in turn (Groq's rate limit); move to a queue if jobs get dozens
        for app in apps:
            try:
                ats = await brain.get_resume_score(app.resume_text, job.description)
            except Exception:
                log.exception("Re-scoring application %s failed", app.id)
                break
            app.ats_match_score, app.ats_breakdown = ats['score'], breakdown(ats)
            await db.commit()
    return redirect('/dashboard/')


@router.get('/candidate-detail/{application_id}/')
async def candidate_detail(request: Request, application_id: int, db: DB, user: CurrentUser):
    if not user:
        return redirect('/login/')
    app = await company_application(db, user, application_id)
    if not app:
        return redirect('/dashboard/')
    session = app.sessions[0] if app.sessions else None
    return render(request, 'candidate_detail.html', {
        'application': app,
        'session': session,
        'alert_counts': Counter(entry.get('type') for entry in session.proctoring_logs).most_common() if session else [],
    })


@router.post('/update-status/{application_id}/{status_val}/')
async def update_application_status(application_id: int, status_val: str, db: DB, user: CurrentUser):
    if not user:
        return redirect('/login/')
    app = await company_application(db, user, application_id)
    if app and status_val in ('accepted', 'rejected', 'evaluated') and app.status != status_val:
        app.status = status_val
        await db.commit()
        if status_val in ('accepted', 'rejected'):
            await notify.decision(app)
    return redirect(f'/ai/candidate-detail/{application_id}/')


@router.post('/invites/')
async def create_invite(request: Request, db: DB, user: CurrentUser):
    company_id = recruiter_company_id(user)
    if company_id:
        invite = CompanyInvite(company_id=company_id, created_by_id=user.id)
        db.add(invite)
        await db.commit()
        flash(request, 'success', f"Invite link (single use, expires in 7 days): {base_url(request)}/register/?invite={invite.token}")
    return redirect('/dashboard/')


@router.post('/invites/{invite_id}/revoke/')
async def revoke_invite(invite_id: int, db: DB, user: CurrentUser):
    company_id = recruiter_company_id(user)
    if company_id:
        await db.execute(delete(CompanyInvite).where(CompanyInvite.id == invite_id, CompanyInvite.company_id == company_id,
                                                     CompanyInvite.used_by_id.is_(None)))
        await db.commit()
    return redirect('/dashboard/')


@router.post('/application-notes/{application_id}/')
async def save_notes(request: Request, application_id: int, db: DB, user: CurrentUser):
    form = await request.form()
    app = await company_application(db, user, application_id)
    if app:
        app.recruiter_notes = form.get('notes', '')
        await db.commit()
    return redirect(f'/ai/candidate-detail/{application_id}/')


@router.post('/allow-retake/{application_id}/')
async def allow_retake(application_id: int, db: DB, user: CurrentUser):
    app = await company_application(db, user, application_id)
    if app and app.status not in ('accepted', 'rejected'):
        # One session per application: the old one goes, with its alerts and score, so the retake starts clean
        await db.execute(delete(InterviewSession).where(InterviewSession.application_id == app.id))
        app.status, app.proctoring_score = 'applied', 100
        await db.commit()
    return redirect(f'/ai/candidate-detail/{application_id}/')
