"""
URL configuration for backend project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include

from ai_engine import views as ai_views

from django.http import HttpResponse

def dummy_favicon(request):
    return HttpResponse(status=204)

urlpatterns = [
    path('favicon.ico', dummy_favicon),
    path('', ai_views.home, name='home'),
    path('login/', ai_views.login_view, name='login'),
    path('register/', ai_views.register_view, name='register'),
    path('logout/', ai_views.logout_view, name='logout'),
    path('setup/', ai_views.setup_view, name='setup'),
    path('dashboard/', ai_views.dashboard_view, name='dashboard'),
    path('delete-session/<int:session_id>/', ai_views.delete_session, name='delete_session'),
    path('download-session/<int:session_id>/', ai_views.download_session_pdf, name='download_session'),
    path('profile/', ai_views.profile_view, name='profile'),
    path('scores/', ai_views.scores_view, name='scores'),
    path('session/', ai_views.session_view, name='session'),
    path('resume-scanner/', ai_views.resume_scanner_view, name='resume_scanner'),
    path('upload-profile-resume/', ai_views.upload_profile_resume, name='upload_profile_resume'),
    path('admin/', admin.site.urls),
    path('ai/', include('ai_engine.urls')),
]
