from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt
import json
import io
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

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    safe_company = ''.join(c for c in company if c.isalnum() or c in ' _-').strip().replace(' ', '_')
    safe_role = ''.join(c for c in role if c.isalnum() or c in ' _-').strip().replace(' ', '_')
    response['Content-Disposition'] = f'attachment; filename="MockHire_{safe_company}_{safe_role}_Report.pdf"'
    return response

def health_check(request):
    return JsonResponse({"status": "healthy", "engine": "Django-AI"})

@api_view(['POST'])
def upload_jd(request):
    return Response({"status": "success", "message": "JD processed via Django"})

@api_view(['POST'])
def check_resume(request):
    return Response({
        "status": "success", 
        "score": 82, 
        "feedback": "Great focus on technical skills. Consider adding more quantifiable achievements."
    })

@api_view(['POST'])
def match_resume(request):
    resume = request.FILES.get('resume')
    jd = request.data.get('jd')
    return Response({
        "status": "success",
        "score": 75,
        "feedback": f"Your resume matches 75% of the JD. Focus more on {jd[:20]}... specific keywords mentioned."
    })

@api_view(['POST'])
def generate_interview_analysis(request):
    from ai_engine.brain import InterviewBrain
    import json
    from asgiref.sync import async_to_sync
    
    company = request.data.get('company', 'Tech Company')
    role = request.data.get('role', 'Candidate')
    jd = request.data.get('jd', 'General Job Description')
    
    brain = InterviewBrain()
    # Run the async analysis method safely
    analysis_json = async_to_sync(brain.generate_analysis)(company, role, jd)
    analysis = json.loads(analysis_json)
    
    return Response(analysis)

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

def dashboard_view(request):
    if not request.user.is_authenticated:
        return redirect('login')
    return render(request, 'dashboard.html', {'username': request.user.username})

def scores_view(request):
    if not request.user.is_authenticated:
        return redirect('login')
    return render(request, 'scores.html')

def home(request):
    return render(request, 'landing.html')

def session_view(request):
    if not request.user.is_authenticated:
        return redirect('login')
    return render(request, 'session.html')

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
    import PyPDF2
    from django.http import JsonResponse

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    if 'resume' not in request.FILES:
        return JsonResponse(
            {'score': 0, 'feedback': 'No resume uploaded.', 'missing_keywords': [], 'matching_keywords': []}, 
            status=400
        )
    
    resume_file = request.FILES['resume']
    jd_text = request.POST.get('jd', 'No JD provided.')
    
    resume_text = ""
    try:
        reader = PyPDF2.PdfReader(resume_file)
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                resume_text += extracted + "\n"
    except Exception as e:
        return Response(
            {'score': 0, 'feedback': f"PDF Parsing Error: {str(e)}", 'missing_keywords': [], 'matching_keywords': []}, 
            status=400
        )

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
