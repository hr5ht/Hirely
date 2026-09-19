"""Recruiter pages: dashboard, jobs, applicants, notes, exports, comparisons and invites."""
import csv
import logging
from collections import Counter

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Prefetch, Q
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ai_engine import notify
from ai_engine.brain import InterviewBrain
from ai_engine.models import Application, Company, CompanyInvite, InterviewSession, Job
from ai_engine.views.common import _avg, _breakdown, _company_application, _company_job, rate_limit

log = logging.getLogger(__name__)


def recruiter_dashboard(request, profile):
    company = profile.company
    if not company:
        # Never fall back to a shared company: that would expose other recruiters' applicants
        company = profile.company = Company.objects.create(name=f"{request.user.username}'s company")
        profile.save()

    jobs = Job.objects.filter(company=company).annotate(
        applicant_count=Count('applications'),
        avg_ats=Avg('applications__ats_match_score'),
        avg_integrity=Avg('applications__proctoring_score', filter=Q(applications__status__in=['evaluated', 'accepted', 'rejected'])),
    ).order_by('-created_at')
    applications, selected_job = _filtered_applications(request, company)
    status, min_score = request.GET.get('status', ''), request.GET.get('min_score', '')

    # Calculate average integrity score
    completed_sessions = InterviewSession.objects.filter(application__job__company=company, session_status='completed')
    avg_proctoring = _avg(completed_sessions, 'application__proctoring_score') if completed_sessions.exists() else None

    return render(request, 'recruiter_dashboard.html', {
        'company': company,
        'jobs': jobs,
        'applications': Paginator(applications, 20).get_page(request.GET.get('page')),
        'selected_job': selected_job,
        'statuses': Application.STATUS_CHOICES,
        'status': status,
        'min_score': min_score,
        'total_jobs': jobs.count(),
        'total_candidates': Application.objects.filter(job__company=company).count(),
        'avg_proctoring_score': avg_proctoring,
        'max_applicants': max((j.applicant_count for j in jobs), default=0) or 1,
        'open_invites': [(i, request.build_absolute_uri(f"/register/?invite={i.token}")) for i in
                         company.invites.filter(used_by=None, expires_at__gt=timezone.now()).order_by('-created_at')],
        'weight_inputs': [(f, label, Job._meta.get_field(f).default) for f, label in
                          zip(WEIGHT_FIELDS, ('Technical', 'Behavioral', 'Problem solving'))],
    })


def _filtered_applications(request, company):
    """The company's applications narrowed by the dashboard's ?job, ?status and ?min_score filters."""
    # List pages never need the resume/report blobs, which can be megabytes per row
    applications = Application.objects.filter(job__company=company).select_related('job', 'candidate') \
        .defer('resume_pdf', 'resume_text').order_by('-ats_match_score') \
        .prefetch_related(Prefetch('sessions', InterviewSession.objects.defer('pdf_report', 'rag_cache', 'transcript')))
    status = request.GET.get('status', '')
    if status in dict(Application.STATUS_CHOICES):
        applications = applications.filter(status=status)
    min_score = request.GET.get('min_score', '')
    if min_score.isdigit():
        applications = applications.filter(ats_match_score__gte=int(min_score))
    job_id = request.GET.get('job', '')
    selected_job = Job.objects.filter(id=job_id, company=company).first() if job_id.isdigit() else None
    if selected_job:
        applications = applications.filter(job=selected_job)
    return applications, selected_job


def download_candidate_resume(request, application_id):
    """Allow recruiters to download the PDF resume submitted by a candidate for a specific application."""
    if not request.user.is_authenticated:
        return redirect('login')

    try:
        profile = request.user.profile
        if profile.role == 'recruiter' and profile.company:
            app = Application.objects.get(id=application_id, job__company=profile.company)

            if app.resume_pdf:
                pdf_bytes = bytes(app.resume_pdf)
                safe_name = ''.join(
                    c for c in app.candidate.username if c.isalnum() or c in '_-'
                ).strip()
                response = HttpResponse(pdf_bytes, content_type='application/pdf')
                response['Content-Disposition'] = (
                    f'attachment; filename="Resume_{safe_name}_{app.job.title.replace(" ", "_")}.pdf"'
                )
                return response

            # Fallback: return resume text as a plain-text download
            if app.resume_text:
                response = HttpResponse(app.resume_text, content_type='text/plain; charset=utf-8')
                response['Content-Disposition'] = (
                    f'attachment; filename="Resume_{app.candidate.username}.txt"'
                )
                return response

    except Application.DoesNotExist:
        pass

    return redirect('dashboard')


def compare_candidates(request):
    if not request.user.is_authenticated:
        return redirect('login')
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role != 'recruiter' or not profile.company:
        return redirect('dashboard')
    ids = [i for i in request.GET.getlist('ids') if i.isdigit()][:3]
    apps = Application.objects.filter(id__in=ids, job__company=profile.company).select_related('job', 'candidate') \
        .defer('resume_pdf', 'resume_text').prefetch_related(Prefetch('sessions', InterviewSession.objects.defer('pdf_report', 'rag_cache')))
    rows = [(app, app.sessions.all()[0] if app.sessions.all() else None) for app in apps]
    return render(request, 'compare.html', {'rows': rows})


def export_applicants(request):
    if not request.user.is_authenticated:
        return redirect('login')
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role != 'recruiter' or not profile.company:
        return redirect('dashboard')
    applications, _ = _filtered_applications(request, profile.company)
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="hirely_applicants.csv"'
    writer = csv.writer(response)
    writer.writerow(['Candidate', 'Email', 'Job', 'Applied', 'Status', 'ATS score', 'Integrity score', 'Missing skills'])
    for app in applications:
        row = [app.candidate.username, app.candidate.email, app.job.title, app.created_at.date().isoformat(),
               app.get_status_display(), app.ats_match_score, app.proctoring_score,
               '; '.join(app.ats_breakdown.get('missing_keywords', []))]
        # A cell starting with = + - @ runs as a formula in Excel/Sheets
        writer.writerow(["'" + c if isinstance(c, str) and c[:1] in ('=', '+', '-', '@') else c for c in row])
    return response


def post_job(request):
    if request.method == 'POST' and request.user.is_authenticated:
        profile = request.user.profile

        if profile.role == 'recruiter' and profile.company:
            Job.objects.create(
                company=profile.company,
                title=request.POST.get('title'),
                description=request.POST.get('description'),
                experience_level=request.POST.get('experience_level', ''),
                interview_rounds=_rounds(request),
                answer_time_limit=_time_limit(request),
                custom_questions=_custom_questions(request),
                **_weights(request),
            )
    return redirect('dashboard')


def _rounds(request):
    """Interview length from the job form, kept to 1-10 questions."""
    value = request.POST.get('interview_rounds', '')
    return min(max(int(value), 1), 10) if value.isdigit() else 5


def _time_limit(request):
    """Seconds per question from the job form; 0 (no limit) or 30 s to 10 min."""
    value = request.POST.get('answer_time_limit', '')
    return min(max(int(value), 30), 600) if value.isdigit() and int(value) else 0


def _custom_questions(request):
    """Must-ask questions from the job form: one per line, at most 10, each trimmed to 500 characters."""
    lines = (line.strip()[:500] for line in request.POST.get('custom_questions', '').splitlines())
    return [line for line in lines if line][:10]


WEIGHT_FIELDS = ('weight_tech', 'weight_behavioral', 'weight_problem_solving')


def _weights(request):
    """Score weights from the job form, 0-100 each; all zero falls back to the defaults."""
    values = {f: min(int(v), 100) if (v := request.POST.get(f, '')).isdigit() else Job._meta.get_field(f).default
              for f in WEIGHT_FIELDS}
    return values if any(values.values()) else {f: Job._meta.get_field(f).default for f in WEIGHT_FIELDS}


@require_POST
def edit_job(request, job_id):
    job = _company_job(request, job_id)
    if job and request.POST.get('title') and request.POST.get('description'):
        job.title = request.POST['title']
        job.description = request.POST['description']
        job.experience_level = request.POST.get('experience_level', '')
        job.interview_rounds = _rounds(request)
        job.answer_time_limit = _time_limit(request)
        job.custom_questions = _custom_questions(request)
        for field, value in _weights(request).items():
            setattr(job, field, value)
        job.save(update_fields=['title', 'description', 'experience_level', 'interview_rounds', 'answer_time_limit',
                                'custom_questions', *WEIGHT_FIELDS])
    return redirect('dashboard')


@require_POST
def toggle_job(request, job_id):
    # Closed jobs drop out of the marketplace and refuse new applications; existing ones are kept
    job = _company_job(request, job_id)
    if job:
        job.is_active = not job.is_active
        job.save(update_fields=['is_active'])
    return redirect('dashboard')


@require_POST
@rate_limit(5)
def rescore_job(request, job_id):
    job = _company_job(request, job_id)
    if job:
        brain = InterviewBrain()
        # ponytail: one LLM call per applicant inside the request; move to a queue if jobs get dozens of applicants
        for app in job.applications.exclude(resume_text=''):
            try:
                ats = brain.get_resume_score(app.resume_text, job.description)
            except Exception:
                log.exception("Re-scoring application %s failed", app.id)
                break
            app.ats_match_score = ats['score']
            app.ats_breakdown = _breakdown(ats)
            app.save(update_fields=['ats_match_score', 'ats_breakdown'])
    return redirect('dashboard')


def candidate_detail(request, application_id):
    if not request.user.is_authenticated:
        return redirect('login')

    try:
        # Recruiter permissions check
        profile = request.user.profile
        if profile.role == 'recruiter' and profile.company:
            app = Application.objects.get(id=application_id, job__company=profile.company)
            session = InterviewSession.objects.filter(application=app).first()
            return render(request, 'candidate_detail.html', {
                'application': app,
                'session': session,
                'alert_counts': Counter(log.get('type') for log in session.proctoring_logs).most_common() if session else [],
            })
    except Application.DoesNotExist:
        pass

    return redirect('dashboard')


@require_POST
def update_application_status(request, application_id, status_val):
    if not request.user.is_authenticated:
        return redirect('login')

    try:
        profile = request.user.profile
        if profile.role == 'recruiter' and profile.company:
            app = Application.objects.get(id=application_id, job__company=profile.company)
            if status_val in ['accepted', 'rejected', 'evaluated'] and app.status != status_val:
                app.status = status_val
                app.save()
                if status_val in ('accepted', 'rejected'):
                    notify.decision(app)
    except Application.DoesNotExist:
        pass

    return redirect('candidate_detail', application_id=application_id)


@require_POST
def create_invite(request):
    profile = getattr(request.user, 'profile', None)
    if request.user.is_authenticated and profile and profile.role == 'recruiter' and profile.company:
        invite = CompanyInvite.objects.create(company=profile.company, created_by=request.user)
        link = request.build_absolute_uri(f"/register/?invite={invite.token}")
        messages.success(request, f"Invite link (single use, expires in 7 days): {link}")
    return redirect('dashboard')


@require_POST
def revoke_invite(request, invite_id):
    profile = getattr(request.user, 'profile', None)
    if request.user.is_authenticated and profile and profile.role == 'recruiter' and profile.company:
        CompanyInvite.objects.filter(id=invite_id, company=profile.company, used_by=None).delete()
    return redirect('dashboard')


@require_POST
def save_notes(request, application_id):
    app = _company_application(request, application_id)
    if app:
        app.recruiter_notes = request.POST.get('notes', '')
        app.save(update_fields=['recruiter_notes'])
    return redirect('candidate_detail', application_id=application_id)


@require_POST
def allow_retake(request, application_id):
    app = _company_application(request, application_id)
    if app and app.status not in ('accepted', 'rejected'):
        # One session per application: the old one goes, with its alerts and score, so the retake starts clean
        app.sessions.all().delete()
        app.status = 'applied'
        app.proctoring_score = 100
        app.save(update_fields=['status', 'proctoring_score'])
    return redirect('candidate_detail', application_id=application_id)
