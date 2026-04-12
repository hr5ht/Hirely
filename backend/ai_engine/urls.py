from django.urls import path
from . import views

urlpatterns = [
    path('generate-analysis/', views.generate_interview_analysis, name='generate_analysis'),
    path('generate-session-pdf/', views.generate_session_pdf, name='generate_session_pdf'),
    path('score-resume/', views.score_resume_api, name='score_resume'),
]
