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
            self.cell(0, 15, 'MockHire', ln=1, align='C')
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
            response['Content-Disposition'] = f'attachment; filename="MockHire_{safe_company}_{safe_role}_Report.pdf"'
            return response
    except InterviewSession.DoesNotExist:
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
        
        if User.objects.filter(username=username).exists():
            error = "Username already exists."
        elif User.objects.filter(email=email).exists():
            error = "Email already registered."
        else:
            User.objects.create_user(username=username, email=email, password=password)
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
        session = InterviewSession.objects.get(id=session_id, user=request.user)
        session.delete()
    except InterviewSession.DoesNotExist:
        pass
        
    return redirect('dashboard')

def dashboard_view(request):
    if not request.user.is_authenticated:
        return redirect('login')
        
    from ai_engine.models import UserProfile, InterviewSession
    profile, created = UserProfile.objects.get_or_create(user=request.user)
    
    all_sessions = InterviewSession.objects.filter(user=request.user).order_by('-date_completed')
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
        'global_avg_clar': global_avg_clar
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

@csrf_exempt
def upload_profile_resume(request):
    if request.method == 'POST' and request.user.is_authenticated:
        if 'resume' in request.FILES:
            resume_file = request.FILES['resume']
            
            from ai_engine.models import UserProfile
            import PyPDF2
            
            profile, _ = UserProfile.objects.get_or_create(user=request.user)
            profile.resume_pdf = resume_file.read()
            
            # Extract Text
            resume_text = ""
            try:
                # Seek back to 0 because we just read it to save the binary output
                resume_file.seek(0)
                reader = PyPDF2.PdfReader(resume_file)
                for page in reader.pages:
                    extracted = page.extract_text()
                    if extracted:
                        resume_text += extracted + "\n"
                profile.resume_text = resume_text
                profile.save()
                
                if request.POST.get('redirect_to') == 'profile':
                    from django.contrib import messages
                    messages.success(request, 'Resume successfully verified and parsed.')
                    return redirect('profile')
                return JsonResponse({"status": "success", "message": "Resume uploaded and parsed successfully."})
            except Exception as e:
                if request.POST.get('redirect_to') == 'profile':
                    from django.contrib import messages
                    messages.error(request, f'Failed to process PDF: {str(e)}')
                    return redirect('profile')
                return JsonResponse({"status": "error", "message": str(e)}, status=400)
    
    return JsonResponse({"status": "error", "message": "Invalid request"}, status=400)

def scores_view(request):
    if not request.user.is_authenticated:
        return redirect('login')
        
    from ai_engine.models import InterviewSession
    
    all_sessions = InterviewSession.objects.filter(user=request.user)
    total_count = all_sessions.count()
    
    if total_count > 0:
        global_avg_conf = int(sum(s.avg_confidence for s in all_sessions) / total_count)
        global_avg_clar = int(sum(s.avg_clarity for s in all_sessions) / total_count)
        global_tech = int(sum(s.tech_knowledge for s in all_sessions) / total_count)
        global_behav = int(sum(s.behavioral_iq for s in all_sessions) / total_count)
        global_prob = int(sum(s.problem_solving for s in all_sessions) / total_count)
    else:
        global_avg_conf = 0
        global_avg_clar = 0
        global_tech = 0
        global_behav = 0
        global_prob = 0

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
    
    from ai_engine.models import UserProfile
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    
    return render(request, 'session.html', {
        'resume_text': profile.resume_text
    })

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
    from django.http import JsonResponse
    from ai_engine.models import UserProfile

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)

    profile, created = UserProfile.objects.get_or_create(user=request.user)
    resume_text = profile.resume_text

    if not resume_text:
        return JsonResponse(
            {'score': 0, 'feedback': 'No resume uploaded to your profile. Please upload one first.', 'missing_keywords': [], 'matching_keywords': []}, 
            status=400
        )
    
    jd_text = request.POST.get('jd', 'No JD provided.')

    brain = InterviewBrain()
    try:
        analysis_json = async_to_sync(brain.get_resume_score)(resume_text, jd_text)
        analysis = json.loads(analysis_json)
        return JsonResponse(analysis)
    except Exception as e:
        return JsonResponse(
            {'score': 0, 'feedback': f"AI Error: {str(e)}", 'missing_keywords': [], 'matching_keywords': []}, 
            status=500
        )
