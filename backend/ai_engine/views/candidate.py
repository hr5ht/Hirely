"""Candidate pages: dashboard and marketplace, applying, resume scanner, scores and interview review."""
import logging

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Prefetch, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ai_engine.brain import InterviewBrain
from ai_engine.models import Application, InterviewSession, Job, UserProfile
from ai_engine.views.common import _ai_error, _avg, _breakdown, _pdf_text, rate_limit
from ai_engine.views.recruiter import recruiter_dashboard

log = logging.getLogger(__name__)


def candidate_dashboard(request, profile):
    # Job marketplace plus the candidate's own applications and interviews
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


def dashboard_view(request):
    if not request.user.is_authenticated:
        return redirect('login')

    profile, _ = UserProfile.objects.defer('resume_pdf').get_or_create(user=request.user)
    if profile.role == 'recruiter':
        return recruiter_dashboard(request, profile)
    return candidate_dashboard(request, profile)


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


def resume_scanner_view(request):
    if not request.user.is_authenticated:
        return redirect('login')
    return render(request, 'resume_scanner.html', {'username': request.user.username})


@rate_limit(20)
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


@rate_limit(20)
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


def review_session(request, session_id):
    if not request.user.is_authenticated:
        return redirect('login')
    session = get_object_or_404(InterviewSession.objects.select_related('application__job__company').defer('pdf_report', 'rag_cache'),
                                id=session_id, application__candidate=request.user, session_status='completed')
    return render(request, 'review.html', {'session': session})
