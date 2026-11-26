"""Emails sent when something happens to an application. Failures are logged, never raised:
a mail outage must not undo a hiring decision or lose an interview."""
import logging
import smtplib
from email.message import EmailMessage

from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.core import config
from app.models import User, UserProfile

log = logging.getLogger(__name__)


def _send(recipients, subject, body):
    msg = EmailMessage()
    msg['Subject'], msg['From'], msg['To'] = subject, config.DEFAULT_FROM_EMAIL, ', '.join(recipients)
    msg.set_content(body)
    if not config.EMAIL_HOST:  # no SMTP configured: print it, like Django's console backend
        log.info("Email (console, EMAIL_HOST unset):\n%s", msg)
        return
    with smtplib.SMTP(config.EMAIL_HOST, config.EMAIL_PORT, timeout=10) as smtp:  # a slow server must not hang a request
        if config.EMAIL_USE_TLS:
            smtp.starttls()
        if config.EMAIL_HOST_USER:
            smtp.login(config.EMAIL_HOST_USER, config.EMAIL_HOST_PASSWORD)
        smtp.send_message(msg)


async def email(to, subject, body):
    recipients = [address for address in to if address]
    if not recipients:
        return
    try:
        await run_in_threadpool(_send, recipients, subject, body)
    except Exception:
        log.exception("Sending '%s' to %s failed", subject, recipients)


async def decision(app):
    """Tell the candidate they were accepted or rejected."""
    job = app.job
    if app.status == 'accepted':
        body = (f"Good news: {job.company.name} would like to move forward with your application for {job.title}. "
                "The hiring team will contact you with next steps.")
    else:
        body = (f"Thank you for interviewing for {job.title} at {job.company.name}. "
                "The team has decided not to move forward with your application this time.")
    await email([app.candidate.email], f"Your application for {job.title}", f"Hi {app.candidate.username},\n\n{body}\n\n- Hirely")


async def interview_completed(db, session, link):
    """Tell the hiring company's recruiters that a candidate finished their interview."""
    app = session.application
    job = app.job
    recruiters = (await db.scalars(select(User.email).join(UserProfile, UserProfile.user_id == User.id)
                                   .where(UserProfile.role == 'recruiter', UserProfile.company_id == job.company_id))).all()
    await email(list(recruiters), f"{app.candidate.username} completed the {job.title} interview",
                f"{app.candidate.username} finished their AI interview for {job.title}.\n"
                f"Integrity score: {app.proctoring_score}%. Review the scores, transcript and report:\n{link}\n\n- Hirely")
