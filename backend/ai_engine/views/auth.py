"""Accounts: sign-up (with company invites), login, profile, and public pages."""
import logging

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render

from ai_engine.models import Company, CompanyInvite, UserProfile

log = logging.getLogger(__name__)


def _password_problem(password, user):
    """Why AUTH_PASSWORD_VALIDATORS reject this password, or None if it's acceptable."""
    try:
        validate_password(password, user)
    except ValidationError as e:
        return " ".join(e.messages)
    return None


def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    error = None
    token = request.POST.get('invite') or request.GET.get('invite')
    invite = CompanyInvite.objects.select_related('company').filter(token=token).first() if token else None
    if invite and not invite.is_usable:
        invite, error = None, "This invite link has expired or was already used. Ask your teammate for a new one."
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        role = 'recruiter' if invite else request.POST.get('role', 'candidate')
        company_name = request.POST.get('company_name')

        if token and not invite:
            pass  # keep the expired-invite error rather than silently creating a candidate
        elif User.objects.filter(username=username).exists():
            error = "Username already exists."
        elif User.objects.filter(email=email).exists():
            error = "Email already registered."
        elif role == 'recruiter' and not company_name and not invite:
            error = "Company name is required for employers."
        elif (error := _password_problem(password, User(username=username, email=email))):
            pass
        else:
            with transaction.atomic():
                # Lock the invite so two people can't both register with the same link
                if invite:
                    invite = CompanyInvite.objects.select_for_update().get(id=invite.id)
                if invite and not invite.is_usable:
                    error = "This invite link was just used. Ask your teammate for a new one."
                else:
                    user = User.objects.create_user(username=username, email=email, password=password)
                    profile, _ = UserProfile.objects.get_or_create(user=user)
                    profile.role = role
                    if invite:
                        profile.company = invite.company
                        invite.used_by = user
                        invite.save(update_fields=['used_by'])
                    elif role == 'recruiter':
                        # Each registration gets its own company: neither email domains nor typed names prove membership
                        profile.company = Company.objects.create(name=company_name)
                    profile.save()
                    return redirect('login')

    return render(request, 'register.html', {'error': error, 'invite': invite})


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    error = None
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('dashboard')
        else:
            error = "Invalid username or password."

    return render(request, 'login.html', {'error': error})


def logout_view(request):
    logout(request)
    return redirect('login')


def profile_view(request):
    if not request.user.is_authenticated:
        return redirect('login')

    profile, created = UserProfile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'update_profile':
            request.user.email = request.POST.get('email', request.user.email)
            request.user.first_name = request.POST.get('first_name', request.user.first_name)
            request.user.last_name = request.POST.get('last_name', request.user.last_name)
            request.user.save()
            messages.success(request, 'Your profile has been updated successfully.')
            return redirect('profile')

        elif action == 'change_password':
            new_password = request.POST.get('new_password', '')
            if (problem := _password_problem(new_password, request.user)):
                messages.error(request, problem)
            else:
                request.user.set_password(new_password)
                request.user.save()
                update_session_auth_hash(request, request.user)
                messages.success(request, 'Your password was successfully updated.')
            return redirect('profile')

    return render(request, 'profile.html', {
        'has_resume': bool(profile.resume_text)
    })


def home(request):
    return render(request, 'landing.html')


def healthz(request):
    """Uptime probe: 200 when the app can reach its database, 503 when it can't."""
    from django.db import connection
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        log.exception("Health check: database unreachable")
        return JsonResponse({'status': 'error', 'database': 'unreachable'}, status=503)
    return JsonResponse({'status': 'ok', 'database': 'ok'})
