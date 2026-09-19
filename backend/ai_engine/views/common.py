"""Helpers shared by the view modules."""
import logging
import time
from functools import wraps

import groq
import PyPDF2
from django.core.cache import cache
from django.db.models import Avg
from django.http import JsonResponse

from ai_engine.models import Application, Job

log = logging.getLogger(__name__)


MAX_RESUME_BYTES = 4 * 1024 * 1024  # Vercel rejects request bodies over 4.5 MB before Django sees them


def rate_limit(per_hour, actions=None):
    """Per-user cap on an AI endpoint (fixed hourly window). `actions` limits only those interview steps.

    ponytail: DB-cache incr isn't atomic, so a burst can overshoot by a few; fine for cost control.
    """
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.user.is_authenticated and (actions is None or kwargs.get('action') in actions):
                key = f"rl:{view.__name__}:{request.user.id}:{int(time.time() // 3600)}"
                cache.add(key, 0, 3600)
                if cache.incr(key) > per_hour:
                    return JsonResponse({'success': False, 'error': 'Too many requests. Please wait a while and try again.'},
                                        status=429)
            return view(request, *args, **kwargs)
        return wrapped
    return decorator


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
        raise ValueError("This PDF couldn't be read. Try exporting it again from your editor.") from None
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


def _breakdown(ats):
    """The parts of an ATS result worth keeping on the application, besides the score itself."""
    return {k: v for k, v in ats.items() if k not in ('score', 'feedback')}


def _company_job(request, job_id):
    """The job if the user is a recruiter at the company that posted it, else None."""
    profile = getattr(request.user, 'profile', None)
    if not request.user.is_authenticated or not profile or profile.role != 'recruiter' or not profile.company:
        return None
    return Job.objects.filter(id=job_id, company=profile.company).first()


def _company_application(request, application_id):
    """The application if the user is a recruiter at the hiring company, else None."""
    profile = getattr(request.user, 'profile', None)
    if not request.user.is_authenticated or not profile or profile.role != 'recruiter' or not profile.company:
        return None
    return Application.objects.filter(id=application_id, job__company=profile.company).first()
