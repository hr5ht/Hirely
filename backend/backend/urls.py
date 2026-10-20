from django.contrib import admin
from django.contrib.auth.views import redirect_to_login
from django.urls import include, path

from ai_engine import views as ai_views

# The admin has no password form of its own: staff sign in through Supabase like everyone else
admin.site.login = lambda request, extra_context=None: redirect_to_login(request.GET.get('next', '/admin/'), '/login/')

urlpatterns = [
    path('', ai_views.home, name='home'),
    path('healthz', ai_views.healthz, name='healthz'),
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
    path('password-reset/', ai_views.password_reset, name='password_reset'),
    path('admin/', admin.site.urls),
    path('ai/', include('ai_engine.urls')),
]
