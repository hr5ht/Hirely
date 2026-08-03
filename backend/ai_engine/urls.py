from django.urls import path
from . import views

urlpatterns = [
    path('generate-analysis/', views.generate_interview_analysis, name='generate_analysis'),
    path('generate-session-pdf/', views.generate_session_pdf, name='generate_session_pdf'),
    path('score-resume/', views.score_resume_api, name='score_resume'),
    path('post-job/', views.post_job, name='post_job'),
    path('apply-to-job/', views.apply_to_job, name='apply_to_job'),
    path('candidate-detail/<int:application_id>/', views.candidate_detail, name='candidate_detail'),
    path('candidate-resume/<int:application_id>/', views.download_candidate_resume, name='candidate_resume'),
    path('update-status/<int:application_id>/<str:status_val>/', views.update_application_status, name='update_application_status'),
]

