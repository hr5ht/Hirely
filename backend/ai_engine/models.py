from django.db import models
from django.contrib.auth.models import User

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    resume_pdf = models.BinaryField(blank=True, null=True)
    resume_text = models.TextField(blank=True, default='')

    def __str__(self):
        return f"{self.user.username}'s Profile"

class InterviewSession(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sessions')
    company = models.CharField(max_length=255)
    role = models.CharField(max_length=255)
    date_completed = models.DateTimeField(auto_now_add=True)
    pdf_report = models.BinaryField(blank=True, null=True)
    avg_confidence = models.IntegerField(default=0)
    avg_clarity = models.IntegerField(default=0)
    tech_knowledge = models.IntegerField(default=0)
    behavioral_iq = models.IntegerField(default=0)
    problem_solving = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.role} at {self.company} - {self.user.username}"
