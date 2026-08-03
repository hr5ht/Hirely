from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt
import json
from datetime import datetime


@csrf_exempt
def generate_session_pdf(request):
    """Generate a PDF report of the interview session."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    def sanitize(text):
        if not isinstance(text, str):
            return str(text)
        replacements = {
            '\u2018': "'", '\u2019': "'",
            '\u201c': '"', '\u201d': '"',
            '\u2013': '-', '\u2014': '--',
            '\u2026': '...', '\u00A0': ' '
        }
        for search, replace in replacements.items():
            text = text.replace(search, replace)
        return text.encode('latin-1', 'replace').decode('latin-1')

    company = sanitize(data.get('company', 'Company'))
    role = sanitize(data.get('role', 'Candidate'))
    conversations = data.get('conversations', [])
    proctoring_events = data.get('proctoring_events', [])
    timestamp = sanitize(datetime.now().strftime('%B %d, %Y at %I:%M %p'))

    from fpdf import FPDF

    class SessionPDF(FPDF):
        def header(self):
            self.set_font('Helvetica', 'B', 20)
            self.cell(0, 15, 'Hirely', ln=1, align='C')
            self.set_font('Helvetica', '', 10)
            self.cell(0, 6, 'AI Interview Session Report', ln=1, align='C')
            self.ln(4)
            self.set_line_width(0.5)
            self.line(10, self.get_y(), 200, self.get_y())
            self.ln(8)

        def footer(self):
            self.set_y(-15)
            self.set_font('Helvetica', 'I', 8)
            self.cell(0, 10, f'Page {self.page_no()}/{{nb}}', align='C')

    pdf = SessionPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # Session Info
    pdf.set_font('Helvetica', 'B', 12)
    pdf.cell(0, 8, 'Session Details', ln=1)
    pdf.set_font('Helvetica', '', 10)
    pdf.cell(40, 7, 'Company:', ln=0)
    pdf.set_font('Helvetica', 'B', 10)
    pdf.cell(0, 7, company, ln=1)
    pdf.set_font('Helvetica', '', 10)
    pdf.cell(40, 7, 'Role:', ln=0)
    pdf.set_font('Helvetica', 'B', 10)
    pdf.cell(0, 7, role, ln=1)
    pdf.set_font('Helvetica', '', 10)
    pdf.cell(40, 7, 'Date:', ln=0)
    pdf.set_font('Helvetica', 'B', 10)
    pdf.cell(0, 7, timestamp, ln=1)
    pdf.cell(40, 7, 'Questions:', ln=0)
    pdf.cell(0, 7, str(len(conversations)), ln=1)
    pdf.ln(6)

    # Conversation Rounds
    for i, conv in enumerate(conversations, 1):
        question = sanitize(conv.get('question', 'N/A'))
        answer = sanitize(conv.get('answer', 'N/A'))
        feedback = sanitize(conv.get('feedback', 'N/A'))

        # Round header
        pdf.set_font('Helvetica', 'B', 11)
        pdf.cell(0, 8, f'Round {i}', ln=1)
        pdf.ln(1)

        # Question
        pdf.set_font('Helvetica', 'B', 10)
        pdf.cell(0, 6, 'AI Question:', ln=1)
        pdf.set_font('Helvetica', '', 10)
        pdf.multi_cell(0, 6, question)
        pdf.ln(2)

        # Answer
        pdf.set_font('Helvetica', 'B', 10)
        pdf.cell(0, 6, 'Your Answer:', ln=1)
        pdf.set_font('Helvetica', '', 10)
        pdf.multi_cell(0, 6, answer if answer else '(No answer provided)')
        pdf.ln(2)

        # Feedback
        pdf.set_font('Helvetica', 'B', 10)
        pdf.cell(0, 6, 'AI Feedback:', ln=1)
        pdf.set_font('Helvetica', '', 10)
        pdf.multi_cell(0, 6, feedback if feedback else '(No feedback)')
        pdf.ln(4)

        # Separator line between rounds
        if i < len(conversations):
            pdf.set_line_width(0.2)
            pdf.line(15, pdf.get_y(), 195, pdf.get_y())
            pdf.ln(4)

    # Proctoring / Face Detection Log
    pdf.add_page()
    pdf.set_font('Helvetica', 'B', 14)
    pdf.cell(0, 10, 'Security & Face Detection Log', ln=1)
    pdf.ln(2)
    
    pdf.set_font('Helvetica', '', 10)
    pdf.multi_cell(0, 6, f"Critical Alerts: {len(proctoring_events)} times.")
    pdf.ln(4)
    
    if proctoring_events:
        pdf.set_font('Helvetica', 'B', 10)
        pdf.cell(60, 8, 'Timestamp', border=1, ln=0, align='C')
        pdf.cell(0, 8, 'Security Alert Event', border=1, ln=1, align='C')
        
        pdf.set_font('Helvetica', '', 10)
        for event in proctoring_events:
            event_time = sanitize(event.get('timestamp', '').replace('T', ' ')[:19])
            event_type = sanitize(event.get('type', 'Unknown Alert'))
            pdf.cell(60, 8, event_time, border=1, ln=0, align='C')
            pdf.cell(0, 8, event_type, border=1, ln=1, align='C')
    else:
        pdf.set_font('Helvetica', 'I', 10)
        pdf.cell(0, 8, 'No suspicious activity detected. All security checks passed.', ln=1)

    # Generate PDF bytes
    pdf_output = pdf.output(dest='S')
    pdf_bytes = pdf_output.encode('latin-1') if isinstance(pdf_output, str) else pdf_output

    if request.user.is_authenticated:
        from ai_engine.models import InterviewSession
        
        valid_conf = [c.get('confidence', 0) for c in conversations if c.get('confidence', 0) > 0]
        avg_conf = int(sum(valid_conf) / len(valid_conf)) if valid_conf else 0
        
        valid_clar = [c.get('clarity', 0) for c in conversations if c.get('clarity', 0) > 0]
        avg_clarity = int(sum(valid_clar) / len(valid_clar)) if valid_clar else 0
        
        transcript = "\n".join([f"Q: {c.get('question')}\nA: {c.get('answer')}" for c in conversations])
        tech_k = 0
        behav = 0
        prob = 0
        
        if transcript:
            from ai_engine.brain import InterviewBrain
            from asgiref.sync import async_to_sync
            brain = InterviewBrain()
            try:
                skills_json = async_to_sync(brain.get_session_skills)(transcript)
                skills = json.loads(skills_json)
                tech_k = skills.get('tech_knowledge', 0)
                behav = skills.get('behavioral_iq', 0)
                prob = skills.get('problem_solving', 0)
            except:
                pass

        InterviewSession.objects.create(
            user=request.user,
            company=company,
            role=role,
            pdf_report=pdf_bytes,
            avg_confidence=avg_conf,
            avg_clarity=avg_clarity,
            tech_knowledge=tech_k,
            behavioral_iq=behav,
            problem_solving=prob
        )

    return JsonResponse({"status": "success", "message": "PDF saved to database successfully"})

def download_session_pdf(request, session_id):
    if not request.user.is_authenticated:
        return redirect('login')
    
    from ai_engine.models import InterviewSession
    try:
        session = InterviewSession.objects.get(id=session_id, user=request.user)
        if session.pdf_report:
            response = HttpResponse(session.pdf_report, content_type='application/pdf')
            safe_company = ''.join(c for c in session.company if c.isalnum() or c in ' _-').strip().replace(' ', '_')
            safe_role = ''.join(c for c in session.role if c.isalnum() or c in ' _-').strip().replace(' ', '_')
            response['Content-Disposition'] = f'attachment; filename="Hirely_{safe_company}_{safe_role}_Report.pdf"'
            return response
    except InterviewSession.DoesNotExist:
        pass
    return redirect('dashboard')


def download_candidate_resume(request, application_id):
    """Allow recruiters to download the PDF resume submitted by a candidate for a specific application."""
    if not request.user.is_authenticated:
        return redirect('login')

    from ai_engine.models import Application

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


from django.views.decorators.csrf import csrf_exempt


@csrf_exempt
def generate_interview_analysis(request):
    from ai_engine.brain import InterviewBrain
    import json
    from asgiref.sync import async_to_sync
    
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    
    company = data.get('company', 'Tech Company')
    role = data.get('role', 'Candidate')
    jd = data.get('jd', 'General Job Description')
    
    brain = InterviewBrain()
    # Run the async analysis method safely
    analysis_json = async_to_sync(brain.generate_analysis)(company, role, jd)
    analysis = json.loads(analysis_json)
    
    return JsonResponse(analysis)

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
        
        from ai_engine.models import Company, UserProfile
        
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
                # Automatically extract domain from email or construct domain from company name
                domain = email.split('@')[-1] if '@' in email else f"{company_name.lower().replace(' ', '')}.com"
                company, _ = Company.objects.get_or_create(domain=domain, defaults={'name': company_name})
                profile.company = company
                
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

def delete_session(request, session_id):
    if not request.user.is_authenticated:
        return redirect('login')
    
    from ai_engine.models import InterviewSession
    
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
        
    from ai_engine.models import UserProfile, Company, Job, Application, InterviewSession
    profile, created = UserProfile.objects.get_or_create(user=request.user)
    
    if profile.role == 'recruiter':
        company = profile.company
        if not company:
            # Fallback if company is missing
            company, _ = Company.objects.get_or_create(domain='default.com', defaults={'name': 'General Business'})
            profile.company = company
            profile.save()
            
        jobs = Job.objects.filter(company=company).order_by('-created_at')
        applications = Application.objects.filter(job__company=company).order_by('-ats_match_score')
        
        total_jobs = jobs.count()
        total_candidates = applications.count()
        
        # Calculate average integrity score
        completed_sessions = InterviewSession.objects.filter(application__job__company=company, session_status='completed')
        avg_proctoring = int(sum(s.application.proctoring_score for s in completed_sessions) / completed_sessions.count()) if completed_sessions.exists() else None
        
        return render(request, 'recruiter_dashboard.html', {
            'company': company,
            'jobs': jobs,
            'applications': applications,
            'total_jobs': total_jobs,
            'total_candidates': total_candidates,
            'avg_proctoring_score': avg_proctoring
        })
    else:
        # Candidate Dashboard with Job Marketplace
        from ai_engine.models import Job
        applications = Application.objects.filter(candidate=request.user).order_by('-created_at')
        applied_jobs = [app.job.id for app in applications]
        # Exclude already applied positions from the active marketplace list
        active_jobs = Job.objects.filter(is_active=True).exclude(id__in=applied_jobs).order_by('-created_at')
        
        all_sessions = InterviewSession.objects.filter(application__candidate=request.user).order_by('-created_at')
        recent_sessions = all_sessions[:5]
        
        total_count = all_sessions.count()
        if total_count > 0:
            global_avg_conf = int(sum(s.avg_confidence for s in all_sessions) / total_count)
            global_avg_clar = int(sum(s.avg_clarity for s in all_sessions) / total_count)
        else:
            global_avg_conf = 0
            global_avg_clar = 0
            
        return render(request, 'dashboard.html', {
            'username': request.user.username,
            'has_resume': bool(profile.resume_text),
            'recent_sessions': recent_sessions,
            'total_interviews': total_count,
            'global_avg_conf': global_avg_conf,
            'global_avg_clar': global_avg_clar,
            'applications': applications,
            'jobs': active_jobs,
            'applied_jobs': applied_jobs
        })

def profile_view(request):
    if not request.user.is_authenticated:
        return redirect('login')
        
    from ai_engine.models import UserProfile
    from django.contrib import messages
    from django.contrib.auth import update_session_auth_hash
    
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
    # Backward compatibility helper for standard profile resume
    if request.method == 'POST' and request.user.is_authenticated:
        if 'resume' in request.FILES:
            resume_file = request.FILES['resume']
            from ai_engine.models import UserProfile
            import PyPDF2
            
            profile, _ = UserProfile.objects.get_or_create(user=request.user)
            profile.resume_pdf = resume_file.read()
            
            resume_text = ""
            try:
                resume_file.seek(0)
                reader = PyPDF2.PdfReader(resume_file)
                for page in reader.pages:
                    extracted = page.extract_text()
                    if extracted:
                        resume_text += extracted + "\n"
                profile.resume_text = resume_text
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
        
    from ai_engine.models import InterviewSession
    all_sessions = InterviewSession.objects.filter(application__candidate=request.user)
    total_count = all_sessions.count()
    
    if total_count > 0:
        global_avg_conf = int(sum(s.avg_confidence for s in all_sessions) / total_count)
        global_avg_clar = int(sum(s.avg_clarity for s in all_sessions) / total_count)
        global_tech = int(sum(s.tech_knowledge for s in all_sessions) / total_count)
        global_behav = int(sum(s.behavioral_iq for s in all_sessions) / total_count)
        global_prob = int(sum(s.problem_solving for s in all_sessions) / total_count)
    else:
        global_avg_conf = global_avg_clar = global_tech = global_behav = global_prob = 0

    return render(request, 'scores.html', {
        'total_count': total_count,
        'global_avg_conf': global_avg_conf,
        'global_avg_clar': global_avg_clar,
        'global_tech': global_tech,
        'global_behav': global_behav,
        'global_prob': global_prob
    })

def home(request):
    return render(request, 'landing.html')

def session_view(request):
    if not request.user.is_authenticated:
        return redirect('login')
    
    from ai_engine.models import Application, InterviewSession
    app_id = request.GET.get('app_id')
    
    if not app_id:
        # Fallback to B2C single session setup if no application exists
        return redirect('setup')
        
    try:
        app = Application.objects.get(id=app_id, candidate=request.user)
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
    except Application.DoesNotExist:
        return redirect('dashboard')

def setup_view(request):
    if not request.user.is_authenticated:
        return redirect('login')
    return render(request, 'setup.html')

def resume_scanner_view(request):
    if not request.user.is_authenticated:
        return redirect('login')
    return render(request, 'resume_scanner.html', {'username': request.user.username})

@csrf_exempt
def score_resume_api(request):
    from ai_engine.brain import InterviewBrain
    from asgiref.sync import async_to_sync
    import json
    
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
        
    from ai_engine.models import UserProfile
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    resume_text = profile.resume_text
    
    if not resume_text:
        return JsonResponse({'error': 'No resume uploaded to your profile.'}, status=400)
        
    jd_text = request.POST.get('jd', 'No JD provided.')
    brain = InterviewBrain()
    try:
        analysis_json = async_to_sync(brain.get_resume_score)(resume_text, jd_text)
        return JsonResponse(json.loads(analysis_json))
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

def download_session_pdf(request, session_id):
    if not request.user.is_authenticated:
        return redirect('login')
    
    from ai_engine.models import InterviewSession
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

def jobs_feed(request):
    if not request.user.is_authenticated:
        return redirect('login')
        
    from ai_engine.models import Job, Application
    active_jobs = Job.objects.filter(is_active=True).order_by('-created_at')
    applications = Application.objects.filter(candidate=request.user)
    applied_jobs = [app.job.id for app in applications]
    
    return render(request, 'jobs_feed.html', {
        'jobs': active_jobs,
        'applications': applications,
        'applied_jobs': applied_jobs
    })

def post_job(request):
    if request.method == 'POST' and request.user.is_authenticated:
        from ai_engine.models import UserProfile, Job
        profile = request.user.profile
        
        if profile.role == 'recruiter' and profile.company:
            title = request.POST.get('title')
            description = request.POST.get('description')
            exp = request.POST.get('experience_level')
            
            Job.objects.create(
                company=profile.company,
                title=title,
                description=description,
                experience_level=exp
            )
    return redirect('dashboard')

def apply_to_job(request):
    if request.method == 'POST' and request.user.is_authenticated:
        if 'resume' in request.FILES:
            job_id = request.POST.get('job_id')
            resume_file = request.FILES['resume']
            
            from ai_engine.models import Job, Application
            import PyPDF2
            
            try:
                job = Job.objects.get(id=job_id)
                resume_bytes = resume_file.read()
                
                # Parse PDF text
                resume_file.seek(0)
                reader = PyPDF2.PdfReader(resume_file)
                resume_text = ""
                for page in reader.pages:
                    extracted = page.extract_text()
                    if extracted:
                        resume_text += extracted + "\n"
                
                # Run ATS scoring
                from ai_engine.brain import InterviewBrain
                from asgiref.sync import async_to_sync
                
                brain = InterviewBrain()
                ats_json_raw = async_to_sync(brain.get_resume_score)(resume_text, job.description)
                ats_data = json.loads(ats_json_raw)
                ats_score = ats_data.get('score', 75)
                
                # Create Application
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
        
    from ai_engine.models import Application, InterviewSession
    
    try:
        # Recruiter permissions check
        profile = request.user.profile
        if profile.role == 'recruiter' and profile.company:
            app = Application.objects.get(id=application_id, job__company=profile.company)
            session = InterviewSession.objects.filter(application=app).first()
            
            return render(request, 'candidate_detail.html', {
                'application': app,
                'session': session
            })
    except Application.DoesNotExist:
        pass
        
    return redirect('dashboard')

def update_application_status(request, application_id, status_val):
    if not request.user.is_authenticated:
        return redirect('login')
    
    from ai_engine.models import Application
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

