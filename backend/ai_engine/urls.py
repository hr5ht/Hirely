from django.urls import path
from . import views

urlpatterns = [
    path('health/', views.health_check, name='health_check'),
    path('upload-jd/', views.upload_jd, name='upload_jd'),
    path('check-resume/', views.check_resume, name='check_resume'),
    path('match-resume/', views.match_resume, name='match_resume'),
    path('generate-analysis/', views.generate_interview_analysis, name='generate_analysis'),
    path('generate-session-pdf/', views.generate_session_pdf, name='generate_session_pdf'),
    path('score-resume/', views.score_resume_api, name='score_resume'),
]
