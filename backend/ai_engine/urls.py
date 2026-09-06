from django.urls import path
from . import views

urlpatterns = [
    path('score-resume/', views.score_resume_api, name='score_resume'),
    path('post-job/', views.post_job, name='post_job'),
    path('edit-job/<int:job_id>/', views.edit_job, name='edit_job'),
    path('toggle-job/<int:job_id>/', views.toggle_job, name='toggle_job'),
    path('rescore-job/<int:job_id>/', views.rescore_job, name='rescore_job'),
    path('apply-to-job/', views.apply_to_job, name='apply_to_job'),
    path('candidate-detail/<int:application_id>/', views.candidate_detail, name='candidate_detail'),
    path('candidate-resume/<int:application_id>/', views.download_candidate_resume, name='candidate_resume'),
    path('interview/<int:session_id>/<str:action>/', views.interview_action, name='interview_action'),
    path('update-status/<int:application_id>/<str:status_val>/', views.update_application_status, name='update_application_status'),
    path('allow-retake/<int:application_id>/', views.allow_retake, name='allow_retake'),
]

