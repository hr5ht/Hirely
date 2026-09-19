"""The interview page, its stateless JSON steps, and report downloads."""
import json
import logging

from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ai_engine import interview
from ai_engine.models import Application, InterviewSession
from ai_engine.views.common import _ai_error, rate_limit

log = logging.getLogger(__name__)


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


@require_POST
@rate_limit(60, actions={'start', 'answer', 'audio'})
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
    data['base_url'] = request.build_absolute_uri('/').rstrip('/')  # for links in emails; never from the client
    try:
        return JsonResponse({'messages': interview.ACTIONS[action](session, data)})
    except Exception as e:
        log.exception("Interview %s failed on session %s", action, session_id)
        return JsonResponse({'error': _ai_error(e)}, status=502)


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
