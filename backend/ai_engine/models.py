import secrets
from datetime import timedelta

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

class Company(models.Model):
    name = models.CharField(max_length=255)
    domain = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

def _invite_token():
    return secrets.token_urlsafe(24)


def _invite_expiry():
    return timezone.now() + timedelta(days=7)


class CompanyInvite(models.Model):
    """A one-time link that lets a new recruiter register into an existing company."""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='invites')
    token = models.CharField(max_length=64, unique=True, default=_invite_token)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=_invite_expiry)
    used_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    @property
    def is_usable(self):
        return self.used_by_id is None and self.expires_at > timezone.now()


class UserProfile(models.Model):
    ROLE_CHOICES = (
        ('candidate', 'Candidate'),
        ('recruiter', 'Recruiter'),
        ('admin', 'Admin'),
    )
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=50, choices=ROLE_CHOICES, default='candidate')
    company = models.ForeignKey(Company, on_delete=models.SET_NULL, blank=True, null=True, related_name='employees')
    # Default resume saved on profile
    resume_pdf = models.BinaryField(blank=True, null=True)
    resume_text = models.TextField(blank=True, default='')

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"

class Job(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='jobs')
    title = models.CharField(max_length=255)
    description = models.TextField()
    experience_level = models.CharField(max_length=50, blank=True, default='')
    interview_rounds = models.PositiveSmallIntegerField(default=5)
    answer_time_limit = models.PositiveSmallIntegerField(default=0)  # seconds per question, 0 = no limit
    custom_questions = models.JSONField(default=list, blank=True)  # recruiter's must-ask questions, in order
    # How much each interview score counts toward the overall score (relative weights, need not sum to 100)
    weight_tech = models.PositiveSmallIntegerField(default=40)
    weight_behavioral = models.PositiveSmallIntegerField(default=30)
    weight_problem_solving = models.PositiveSmallIntegerField(default=30)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} at {self.company.name}"

class Application(models.Model):
    STATUS_CHOICES = (
        ('applied', 'Applied'),
        ('interviewing', 'Interviewing'),
        ('evaluated', 'Evaluated'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
    )
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='applications')
    candidate = models.ForeignKey(User, on_delete=models.CASCADE, related_name='applications')
    resume_pdf = models.BinaryField(blank=True, null=True)
    resume_text = models.TextField(blank=True, default='')
    ats_match_score = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    # skill/semantic sub-scores, matching/missing keywords and suggestions from the ATS scan
    ats_breakdown = models.JSONField(default=dict, blank=True)
    proctoring_score = models.IntegerField(default=100)
    recruiter_notes = models.TextField(blank=True, default='')  # private to the hiring company
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='applied')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['job', 'candidate'], name='unique_job_candidate')
        ]

    @property
    def interview_score(self):
        """Overall interview score using the job's weights, or None before the interview is completed.

        Reads self.sessions.all(), so list views should prefetch sessions.
        """
        session = next((s for s in self.sessions.all() if s.session_status == 'completed'), None)
        if not session:
            return None
        weights = (self.job.weight_tech, self.job.weight_behavioral, self.job.weight_problem_solving)
        scores = (session.tech_knowledge, session.behavioral_iq, session.problem_solving)
        return round(sum(w * s for w, s in zip(weights, scores)) / (sum(weights) or 1))

    def __str__(self):
        return f"{self.candidate.username} for {self.job.title}"

class InterviewSession(models.Model):
    SESSION_STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('disconnected', 'Disconnected'),
    )
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='sessions')
    session_status = models.CharField(max_length=50, choices=SESSION_STATUS_CHOICES, default='pending')
    transcript = models.JSONField(default=list, blank=True)
    proctoring_logs = models.JSONField(default=list, blank=True)
    pdf_report = models.BinaryField(blank=True, null=True)
    avg_confidence = models.IntegerField(default=0)
    avg_clarity = models.IntegerField(default=0)
    tech_knowledge = models.IntegerField(default=0)
    behavioral_iq = models.IntegerField(default=0)
    problem_solving = models.IntegerField(default=0)
    gap_analysis = models.TextField(blank=True, default='')
    rag_cache = models.JSONField(default=dict, blank=True)  # embedded resume/JD chunks, see rag.retrieve
    heartbeats = models.JSONField(default=list, blank=True)  # server epoch seconds of each live-camera ping
    created_at = models.DateTimeField(auto_now_add=True)


    @property
    def trend_bars(self):
        """(label, score, bar colour) rows for the candidate's score trend."""
        return [("Technical", self.tech_knowledge, "bg-blue-500"), ("Behavioral", self.behavioral_iq, "bg-purple-500"),
                ("Problem solving", self.problem_solving, "bg-pink-500")]

    def __str__(self):
        return f"Session for {self.application.candidate.username} - {self.application.job.title}"

