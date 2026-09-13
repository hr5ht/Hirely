import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.utils import timezone
from django.db.models import Avg, Count, Prefetch, Q
from django.views.decorators.http import require_POST
import csv
import json
from collections import Counter
import groq
import PyPDF2

from ai_engine.models import Company, CompanyInvite, UserProfile, Job, Application, InterviewSession
from ai_engine.brain import InterviewBrain
from ai_engine import interview

log = logging.getLogger(__name__)


MAX_RESUME_BYTES = 4 * 1024 * 1024  # Vercel rejects request bodies over 4.5 MB before Django sees them


def _pdf_text(f):
    """Text of an uploaded resume. Raises ValueError with a message safe to show the user."""
    if f.size > MAX_RESUME_BYTES:
        raise ValueError("Resume is larger than 4 MB. Please upload a smaller PDF.")
    f.seek(0)
    if f.read(5) != b'%PDF-':
        raise ValueError("That file isn't a PDF. Please upload your resume as a PDF.")
    f.seek(0)
    try:
        reader = PyPDF2.PdfReader(f)
        if reader.is_encrypted:
            raise ValueError("This PDF is password-protected. Please upload an unlocked copy.")
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except PyPDF2.errors.PdfReadError:
        raise ValueError("This PDF couldn't be read. Try exporting it again from your editor.")
    if len(text.split()) < 20:
        # Scanned resumes are images: without text the ATS score would silently be ~0
        raise ValueError("No text found in this PDF (it may be a scanned image). Please upload a text-based PDF.")
    return text


def _ai_error(e):
    """What the user sees when an AI call fails; the real exception goes to the log."""
    if isinstance(e, groq.RateLimitError):
        return "AI service error: too many requests right now. Please try again in a minute."
    return "AI service error: something went wrong. Please try again."


def _avg(qs, field):
    return int(qs.aggregate(v=Avg(field))['v'] or 0)


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


def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    error = None
    token = request.POST.get('invite') or request.GET.get('invite')
    invite = CompanyInvite.objects.select_related('company').filter(token=token).first() if token else None
    if invite and not invite.is_usable:
        invite, error = None, "This invite link has expired or was already used. Ask your teammate for a new one."
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        role = 'recruiter' if invite else request.POST.get('role', 'candidate')
        company_name = request.POST.get('company_name')

        if token and not invite:
            pass  # keep the expired-invite error rather than silently creating a candidate
        elif User.objects.filter(username=username).exists():
            error = "Username already exists."
        elif User.objects.filter(email=email).exists():
            error = "Email already registered."
        elif role == 'recruiter' and not company_name and not invite:
            error = "Company name is required for employers."
        else:
            with transaction.atomic():
                # Lock the invite so two people can't both register with the same link
                if invite:
                    invite = CompanyInvite.objects.select_for_update().get(id=invite.id)
                if invite and not invite.is_usable:
                    error = "This invite link was just used. Ask your teammate for a new one."
                else:
                    user = User.objects.create_user(username=username, email=email, password=password)
                    profile, _ = UserProfile.objects.get_or_create(user=user)
                    profile.role = role
                    if invite:
                        profile.company = invite.company
                        invite.used_by = user
                        invite.save(update_fields=['used_by'])
                    elif role == 'recruiter':
                        # Each registration gets its own company: neither email domains nor typed names prove membership
                        profile.company = Company.objects.create(name=company_name)
                    profile.save()
                    return redirect('login')

    return render(request, 'register.html', {'error': error, 'invite': invite})

def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    error = None
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('dashboard')
        else:
            error = "Invalid username or password."

    return render(request, 'login.html', {'error': error})

def logout_view(request):
    logout(request)
    return redirect('login')

@require_POST
def delete_session(request, session_id):
    if not request.user.is_authenticated:
        return redirect('login')

    try:
        # Recruiters delete by application, candidates delete their own
        if hasattr(request.user, 'profile') and request.user.profile.role == 'recruiter':
            session = InterviewSession.objects.get(id=session_id, application__job__company=request.user.profile.company)
        else:
            session = InterviewSession.objects.get(id=session_id, application__candidate=request.user)
        session.delete()
    except InterviewSession.DoesNotExist:
        pass

    return redirect('dashboard')

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


def compare_candidates(request):
    profile = getattr(request.user, 'profile', None)
    if not request.user.is_authenticated or not profile or profile.role != 'recruiter' or not profile.company:
        return redirect('dashboard')
    ids = [i for i in request.GET.getlist('ids') if i.isdigit()][:3]
    apps = Application.objects.filter(id__in=ids, job__company=profile.company).select_related('job', 'candidate') \
        .defer('resume_pdf', 'resume_text').prefetch_related(Prefetch('sessions', InterviewSession.objects.defer('pdf_report', 'rag_cache')))
    rows = [(app, app.sessions.all()[0] if app.sessions.all() else None) for app in apps]
    return render(request, 'compare.html', {'rows': rows})


def export_applicants(request):
    profile = getattr(request.user, 'profile', None)
    if not request.user.is_authenticated or not profile or profile.role != 'recruiter' or not profile.company:
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


def dashboard_view(request):
    if not request.user.is_authenticated:
        return redirect('login')

    profile, created = UserProfile.objects.defer('resume_pdf').get_or_create(user=request.user)

    if profile.role == 'recruiter':
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
    else:
        # Candidate Dashboard with Job Marketplace
        applications = Application.objects.filter(candidate=request.user).select_related('job__company') \
            .defer('resume_pdf', 'resume_text').prefetch_related(Prefetch('sessions', InterviewSession.objects.defer('pdf_report', 'rag_cache'))) \
            .order_by('-created_at')
        applied_jobs = [app.job.id for app in applications]
        # Exclude already applied positions from the active marketplace list
        active_jobs = Job.objects.filter(is_active=True).exclude(id__in=applied_jobs).select_related('company').order_by('-created_at')
        query = request.GET.get('q', '').strip()
        if query:  # skills live in the description
            active_jobs = active_jobs.filter(Q(title__icontains=query) | Q(company__name__icontains=query) | Q(description__icontains=query))
        level = request.GET.get('level', '')
        if level:
            active_jobs = active_jobs.filter(experience_level=level)
        # Levels are free text typed by recruiters, so offer the ones actually in use
        levels = Job.objects.filter(is_active=True).exclude(experience_level='').order_by('experience_level') \
            .values_list('experience_level', flat=True).distinct()

        all_sessions = InterviewSession.objects.filter(application__candidate=request.user) \
            .select_related('application__job__company').defer('pdf_report', 'rag_cache').order_by('-created_at')

        return render(request, 'dashboard.html', {
            'username': request.user.username,
            'has_resume': bool(profile.resume_text),
            'recent_sessions': all_sessions[:5],
            'total_interviews': all_sessions.count(),
            'global_avg_conf': _avg(all_sessions, 'avg_confidence'),
            'global_avg_clar': _avg(all_sessions, 'avg_clarity'),
            'applications': applications,
            'jobs': Paginator(active_jobs, 10).get_page(request.GET.get('page')),
            'query': query,
            'level': level,
            'levels': levels,
            'applied_jobs': applied_jobs
        })

def profile_view(request):
    if not request.user.is_authenticated:
        return redirect('login')

    profile, created = UserProfile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'update_profile':
            request.user.email = request.POST.get('email', request.user.email)
            request.user.first_name = request.POST.get('first_name', request.user.first_name)
            request.user.last_name = request.POST.get('last_name', request.user.last_name)
            request.user.save()
            messages.success(request, 'Your profile has been updated successfully.')
            return redirect('profile')

        elif action == 'change_password':
            new_password = request.POST.get('new_password')
            if new_password and len(new_password) >= 6:
                request.user.set_password(new_password)
                request.user.save()
                update_session_auth_hash(request, request.user)
                messages.success(request, 'Your password was successfully updated.')
            else:
                messages.error(request, 'Password must be at least 6 characters.')
            return redirect('profile')

    return render(request, 'profile.html', {
        'has_resume': bool(profile.resume_text)
    })

def upload_profile_resume(request):
    if request.method == 'POST' and request.user.is_authenticated and 'resume' in request.FILES:
        resume_file = request.FILES['resume']
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        profile.resume_pdf = resume_file.read()
        to_profile = request.POST.get('redirect_to') == 'profile'
        try:
            profile.resume_text = _pdf_text(resume_file)
        except ValueError as e:
            if to_profile:
                messages.error(request, str(e))
                return redirect('profile')
            return JsonResponse({"status": "error", "message": str(e)}, status=400)
        profile.save()

        if to_profile:
            messages.success(request, 'Resume successfully verified and parsed.')
            return redirect('profile')
        return JsonResponse({"status": "success", "message": "Resume uploaded successfully."})
    return JsonResponse({"status": "error", "message": "Invalid request"}, status=400)

def scores_view(request):
    if not request.user.is_authenticated:
        return redirect('login')

    all_sessions = InterviewSession.objects.filter(application__candidate=request.user)

    return render(request, 'scores.html', {
        'total_count': all_sessions.count(),
        'global_avg_conf': _avg(all_sessions, 'avg_confidence'),
        'global_avg_clar': _avg(all_sessions, 'avg_clarity'),
        'global_tech': _avg(all_sessions, 'tech_knowledge'),
        'global_behav': _avg(all_sessions, 'behavioral_iq'),
        'global_prob': _avg(all_sessions, 'problem_solving'),
        'trend': all_sessions.filter(session_status='completed').select_related('application__job__company')
            .only('created_at', 'tech_knowledge', 'behavioral_iq', 'problem_solving',
                  'application__job__title', 'application__job__company__name').order_by('created_at'),
    })

def home(request):
    return render(request, 'landing.html')

def session_view(request):
    if not request.user.is_authenticated:
        return redirect('login')

    try:
        app = Application.objects.get(id=request.GET.get('app_id'), candidate=request.user)
        # Redirect to dashboard if application is already evaluated
        if app.status == 'evaluated':
            return redirect('dashboard')

        # Fetch or create stateful InterviewSession
        session, created = InterviewSession.objects.get_or_create(
            application=app,
            defaults={'session_status': 'active'}
        )

        # Redirect to dashboard if session is already completed
        if session.session_status == 'completed':
            return redirect('dashboard')

        if session.session_status == 'pending':
            session.session_status = 'active'
            session.save()

        return render(request, 'session.html', {
            'session_id': session.id,
            'resume_text': app.resume_text,
            'role': app.job.title,
            'company': app.job.company.name,
            'jd': app.job.description
        })
    except (Application.DoesNotExist, ValueError):
        return redirect('dashboard')

def resume_scanner_view(request):
    if not request.user.is_authenticated:
        return redirect('login')
    return render(request, 'resume_scanner.html', {'username': request.user.username})

def score_resume_api(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)

    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    resume_text = profile.resume_text

    if not resume_text:
        return JsonResponse({'error': 'No resume uploaded to your profile.'}, status=400)

    jd_text = request.POST.get('jd', 'No JD provided.')
    try:
        return JsonResponse(InterviewBrain().get_resume_score(resume_text, jd_text))
    except Exception as e:
        log.exception("Resume scan failed")
        return JsonResponse({'error': _ai_error(e)}, status=502)

def review_session(request, session_id):
    if not request.user.is_authenticated:
        return redirect('login')
    session = get_object_or_404(InterviewSession.objects.select_related('application__job__company').defer('pdf_report', 'rag_cache'),
                                id=session_id, application__candidate=request.user, session_status='completed')
    return render(request, 'review.html', {'session': session})

def download_session_pdf(request, session_id):
    if not request.user.is_authenticated:
        return redirect('login')

    try:
        # Check permissions: candidate owns the session or recruiter employs it
        if hasattr(request.user, 'profile') and request.user.profile.role == 'recruiter':
            session = InterviewSession.objects.get(id=session_id, application__job__company=request.user.profile.company)
        else:
            session = InterviewSession.objects.get(id=session_id, application__candidate=request.user)

        if session.pdf_report:
            response = HttpResponse(session.pdf_report, content_type='application/pdf')
            safe_company = ''.join(c for c in session.application.job.company.name if c.isalnum() or c in ' _-').strip().replace(' ', '_')
            safe_role = ''.join(c for c in session.application.job.title if c.isalnum() or c in ' _-').strip().replace(' ', '_')
            response['Content-Disposition'] = f'attachment; filename="Hirely_{safe_company}_{safe_role}_Report.pdf"'
            return response
    except InterviewSession.DoesNotExist:
        pass
    return redirect('dashboard')

# --- B2B MARKETPLACE RECRUITER / CANDIDATE ACTIONS ---

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


def _breakdown(ats):
    """The parts of an ATS result worth keeping on the application, besides the score itself."""
    return {k: v for k, v in ats.items() if k not in ('score', 'feedback')}


def _company_job(request, job_id):
    """The job if the user is a recruiter at the company that posted it, else None."""
    profile = getattr(request.user, 'profile', None)
    if not request.user.is_authenticated or not profile or profile.role != 'recruiter' or not profile.company:
        return None
    return Job.objects.filter(id=job_id, company=profile.company).first()


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

def apply_to_job(request):
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'error': 'Please log in to apply.'}, status=401)
    if request.method == 'POST' and 'resume' in request.FILES:
        resume_file = request.FILES['resume']
        job_id = request.POST.get('job_id', '')
        job = Job.objects.filter(id=job_id).first() if job_id.isdigit() else None
        if not job or not job.is_active:
            return JsonResponse({'success': False, 'error': 'This job is no longer accepting applications.'}, status=400)
        try:
            resume_bytes = resume_file.read()
            resume_text = _pdf_text(resume_file)

            ats = InterviewBrain().get_resume_score(resume_text, job.description)
            ats_score = ats['score']

            app = Application.objects.create(
                job=job,
                candidate=request.user,
                resume_pdf=resume_bytes,
                resume_text=resume_text,
                ats_match_score=ats_score,
                ats_breakdown=_breakdown(ats)
            )

            return JsonResponse({
                'success': True,
                'app_id': app.id,
                'ats_score': float(ats_score),
                'job_title': job.title,
                'company_name': job.company.name,
                'missing_keywords': ats.get('missing_keywords', []),
                'improvement_suggestions': ats.get('improvement_suggestions', []),
            })
        except ValueError as e:  # unreadable resume; the message is written for the user
            return JsonResponse({'success': False, 'error': str(e)}, status=400)
        except Exception as e:
            log.exception("Applying to job %s failed", job.id)
            return JsonResponse({'success': False, 'error': _ai_error(e)}, status=502)

    return JsonResponse({'success': False, 'error': 'Invalid request'}, status=400)

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
            if status_val in ['accepted', 'rejected', 'evaluated']:
                app.status = status_val
                app.save()
    except Application.DoesNotExist:
        pass

    return redirect('candidate_detail', application_id=application_id)


def _company_application(request, application_id):
    """The application if the user is a recruiter at the hiring company, else None."""
    profile = getattr(request.user, 'profile', None)
    if not request.user.is_authenticated or not profile or profile.role != 'recruiter' or not profile.company:
        return None
    return Application.objects.filter(id=application_id, job__company=profile.company).first()


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


@require_POST
def interview_action(request, session_id, action):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    if action not in interview.ACTIONS:
        return JsonResponse({'error': 'Unknown action'}, status=404)

    session = get_object_or_404(InterviewSession.objects.select_related('application__job__company'),
                                id=session_id, application__candidate=request.user)
    if session.session_status == 'completed':
        return JsonResponse({'messages': [{'type': 'session_completed'}]})

    data = json.loads(request.body) if request.content_type == 'application/json' else {}
    try:
        return JsonResponse({'messages': interview.ACTIONS[action](session, data)})
    except Exception as e:
        log.exception("Interview %s failed on session %s", action, session_id)
        return JsonResponse({'error': _ai_error(e)}, status=502)
