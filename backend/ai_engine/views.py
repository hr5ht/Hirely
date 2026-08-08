from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib import messages
from django.db.models import Avg
from django.views.decorators.http import require_POST
import json
import PyPDF2

from ai_engine.models import Company, UserProfile, Job, Application, InterviewSession
from ai_engine.brain import InterviewBrain
from ai_engine import interview


def _pdf_text(f):
    f.seek(0)
    return "\n".join(page.extract_text() or "" for page in PyPDF2.PdfReader(f).pages)


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
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        role = request.POST.get('role', 'candidate')
        company_name = request.POST.get('company_name')

        if User.objects.filter(username=username).exists():
            error = "Username already exists."
        elif User.objects.filter(email=email).exists():
            error = "Email already registered."
        elif role == 'recruiter' and not company_name:
            error = "Company name is required for employers."
        else:
            user = User.objects.create_user(username=username, email=email, password=password)
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.role = role

            if role == 'recruiter':
                # Each registration gets its own company: neither email domains nor typed names prove membership
                profile.company = Company.objects.create(name=company_name)

            profile.save()
            return redirect('login')

    return render(request, 'register.html', {'error': error})

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

def dashboard_view(request):
    if not request.user.is_authenticated:
        return redirect('login')

    profile, created = UserProfile.objects.get_or_create(user=request.user)

    if profile.role == 'recruiter':
        company = profile.company
        if not company:
            # Never fall back to a shared company: that would expose other recruiters' applicants
            company = profile.company = Company.objects.create(name=f"{request.user.username}'s company")
            profile.save()

        jobs = Job.objects.filter(company=company).order_by('-created_at')
        applications = Application.objects.filter(job__company=company).order_by('-ats_match_score')

        # Calculate average integrity score
        completed_sessions = InterviewSession.objects.filter(application__job__company=company, session_status='completed')
        avg_proctoring = _avg(completed_sessions, 'application__proctoring_score') if completed_sessions.exists() else None

        return render(request, 'recruiter_dashboard.html', {
            'company': company,
            'jobs': jobs,
            'applications': applications,
            'total_jobs': jobs.count(),
            'total_candidates': applications.count(),
            'avg_proctoring_score': avg_proctoring
        })
    else:
        # Candidate Dashboard with Job Marketplace
        applications = Application.objects.filter(candidate=request.user).order_by('-created_at')
        applied_jobs = [app.job.id for app in applications]
        # Exclude already applied positions from the active marketplace list
        active_jobs = Job.objects.filter(is_active=True).exclude(id__in=applied_jobs).order_by('-created_at')

        all_sessions = InterviewSession.objects.filter(application__candidate=request.user).order_by('-created_at')

        return render(request, 'dashboard.html', {
            'username': request.user.username,
            'has_resume': bool(profile.resume_text),
            'recent_sessions': all_sessions[:5],
            'total_interviews': all_sessions.count(),
            'global_avg_conf': _avg(all_sessions, 'avg_confidence'),
            'global_avg_clar': _avg(all_sessions, 'avg_clarity'),
            'applications': applications,
            'jobs': active_jobs,
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
        try:
            profile.resume_text = _pdf_text(resume_file)
            profile.save()

            if request.POST.get('redirect_to') == 'profile':
                messages.success(request, 'Resume successfully verified and parsed.')
                return redirect('profile')
            return JsonResponse({"status": "success", "message": "Resume uploaded successfully."})
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=400)
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
        return JsonResponse({'error': str(e)}, status=500)

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
                experience_level=request.POST.get('experience_level')
            )
    return redirect('dashboard')

def apply_to_job(request):
    if request.method == 'POST' and request.user.is_authenticated and 'resume' in request.FILES:
        resume_file = request.FILES['resume']
        try:
            job = Job.objects.get(id=request.POST.get('job_id'))
            resume_bytes = resume_file.read()
            resume_text = _pdf_text(resume_file)

            ats_score = InterviewBrain().get_resume_score(resume_text, job.description)['score']

            app = Application.objects.create(
                job=job,
                candidate=request.user,
                resume_pdf=resume_bytes,
                resume_text=resume_text,
                ats_match_score=ats_score
            )

            return JsonResponse({
                'success': True,
                'app_id': app.id,
                'ats_score': float(ats_score),
                'job_title': job.title,
                'company_name': job.company.name
            })
        except Exception as e:
            print(f"Error applying to job: {e}")
            return JsonResponse({'success': False, 'error': str(e)}, status=400)

    return JsonResponse({'success': False, 'error': 'Invalid request'}, status=400)

def candidate_detail(request, application_id):
    if not request.user.is_authenticated:
        return redirect('login')

    try:
        # Recruiter permissions check
        profile = request.user.profile
        if profile.role == 'recruiter' and profile.company:
            app = Application.objects.get(id=application_id, job__company=profile.company)
            return render(request, 'candidate_detail.html', {
                'application': app,
                'session': InterviewSession.objects.filter(application=app).first()
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
        print(f"[Interview Error] {action} failed on session {session_id}: {e!r}")
        return JsonResponse({'error': f'AI service error: {e}'}, status=502)
