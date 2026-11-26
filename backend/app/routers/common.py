"""Helpers shared by the route modules."""
import io
import logging

import groq
import PyPDF2
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from app.models import Application, Job

log = logging.getLogger(__name__)

MAX_RESUME_BYTES = 4 * 1024 * 1024
TOO_MANY_JSON = {'success': False, 'error': 'Too many requests. Please wait a while and try again.'}


def too_many_response():
    return JSONResponse(TOO_MANY_JSON, status_code=429)


def pdf_text(data):
    """Text of an uploaded resume (bytes). Raises ValueError with a message safe to show the user. CPU-bound: run in a thread."""
    if len(data) > MAX_RESUME_BYTES:
        raise ValueError("Resume is larger than 4 MB. Please upload a smaller PDF.")
    if data[:5] != b'%PDF-':
        raise ValueError("That file isn't a PDF. Please upload your resume as a PDF.")
    try:
        reader = PyPDF2.PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ValueError("This PDF is password-protected. Please upload an unlocked copy.")
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except PyPDF2.errors.PdfReadError:
        raise ValueError("This PDF couldn't be read. Try exporting it again from your editor.") from None
    if len(text.split()) < 20:
        # Scanned resumes are images: without text the ATS score would silently be ~0
        raise ValueError("No text found in this PDF (it may be a scanned image). Please upload a text-based PDF.")
    return text


def ai_error(e):
    """What the user sees when an AI call fails; the real exception goes to the log."""
    if isinstance(e, groq.RateLimitError):
        return "AI service error: too many requests right now. Please try again in a minute."
    return "AI service error: something went wrong. Please try again."


async def avg(db, stmt, column):
    """int(AVG(column)) over a statement's rows, 0 when there are none (Django's _avg)."""
    rows = stmt.subquery()
    return int(await db.scalar(select(func.avg(rows.c[column.key]))) or 0)


def breakdown(ats):
    """The parts of an ATS result worth keeping on the application, besides the score itself."""
    return {k: v for k, v in ats.items() if k not in ('score', 'feedback')}


def recruiter_company_id(user):
    """The user's company id if they are a recruiter with a company, else None."""
    profile = user.profile if user else None
    return profile.company_id if profile and profile.role == 'recruiter' and profile.company_id else None


async def company_job(db, user, job_id):
    """The job if the user is a recruiter at the company that posted it, else None."""
    company_id = recruiter_company_id(user)
    return await db.scalar(select(Job).where(Job.id == job_id, Job.company_id == company_id)) if company_id else None


async def company_application(db, user, application_id):
    """The application if the user is a recruiter at the hiring company, else None."""
    company_id = recruiter_company_id(user)
    if not company_id:
        return None
    return await db.scalar(select(Application).join(Job).where(Application.id == application_id, Job.company_id == company_id))


def safe_filename(text, keep=' _-'):
    return ''.join(c for c in text if c.isalnum() or c in keep).strip().replace(' ', '_')
