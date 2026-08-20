from django.db import models
from django.contrib.auth.models import User

class Company(models.Model):
    name = models.CharField(max_length=255)
    domain = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

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
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='applied')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['job', 'candidate'], name='unique_job_candidate')
        ]

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
    created_at = models.DateTimeField(auto_now_add=True)


    def __str__(self):
        return f"Session for {self.application.candidate.username} - {self.application.job.title}"

