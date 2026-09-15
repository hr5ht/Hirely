"""Emails sent when something happens to an application. Failures are logged, never raised:
a mail outage must not undo a hiring decision or lose an interview."""
import logging

from django.core.mail import send_mail

log = logging.getLogger(__name__)


def email(to, subject, body):
    recipients = [address for address in to if address]
    if not recipients:
        return
    try:
        send_mail(subject, body, None, recipients)
    except Exception:
        log.exception("Sending '%s' to %s failed", subject, recipients)


def decision(app):
    """Tell the candidate they were accepted or rejected."""
    job = app.job
    if app.status == 'accepted':
        body = (f"Good news: {job.company.name} would like to move forward with your application for {job.title}. "
                "The hiring team will contact you with next steps.")
    else:
        body = (f"Thank you for interviewing for {job.title} at {job.company.name}. "
                "The team has decided not to move forward with your application this time.")
    email([app.candidate.email], f"Your application for {job.title}", f"Hi {app.candidate.username},\n\n{body}\n\n- Hirely")
