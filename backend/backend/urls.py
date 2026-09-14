from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path, include

from ai_engine import views as ai_views

urlpatterns = [
    path('', ai_views.home, name='home'),
    path('login/', ai_views.login_view, name='login'),
    path('register/', ai_views.register_view, name='register'),
    path('logout/', ai_views.logout_view, name='logout'),
    path('dashboard/', ai_views.dashboard_view, name='dashboard'),
    path('delete-session/<int:session_id>/', ai_views.delete_session, name='delete_session'),
    path('download-session/<int:session_id>/', ai_views.download_session_pdf, name='download_session'),
    path('review/<int:session_id>/', ai_views.review_session, name='review_session'),
    path('profile/', ai_views.profile_view, name='profile'),
    path('scores/', ai_views.scores_view, name='scores'),
    path('session/', ai_views.session_view, name='session'),
    path('resume-scanner/', ai_views.resume_scanner_view, name='resume_scanner'),
    path('upload-profile-resume/', ai_views.upload_profile_resume, name='upload_profile_resume'),
    path('password-reset/', auth_views.PasswordResetView.as_view(), name='password_reset'),
    path('password-reset/sent/', auth_views.PasswordResetDoneView.as_view(), name='password_reset_done'),
    path('password-reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('password-reset/complete/', auth_views.PasswordResetCompleteView.as_view(), name='password_reset_complete'),
    path('admin/', admin.site.urls),
    path('ai/', include('ai_engine.urls')),
]
