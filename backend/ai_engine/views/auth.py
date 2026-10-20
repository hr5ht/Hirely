"""Accounts: sign-up (with company invites), login, password resets, profile, and public pages.

Supabase Auth checks passwords and sends confirmation and reset emails. Users, roles and everything
else stay in our own database (Neon); Django sessions keep people logged in. No passwords are stored here.
"""
import base64
import hashlib
import logging
import secrets

import httpx
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from ai_engine import __version__
from ai_engine.models import Company, CompanyInvite, UserProfile
from ai_engine.views.common import client_ip, too_many

log = logging.getLogger(__name__)


def _password_problem(password, user):
    """Why AUTH_PASSWORD_VALIDATORS reject this password, or None if it's acceptable."""
    try:
        validate_password(password, user)
    except ValidationError as e:
        return " ".join(e.messages)
    return None


def _supabase(path, payload, token=None, method='POST', **params):
    """Call Supabase Auth's REST API. Returns (data, None) on success or (None, message) on failure."""
    headers = {'apikey': settings.SUPABASE_ANON_KEY}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    try:
        resp = httpx.request(method, f"{settings.SUPABASE_URL}/auth/v1/{path}", params=params,
                             json=payload, headers=headers, timeout=10)
        data = resp.json() if resp.content else {}
    except (httpx.HTTPError, ValueError):
        log.exception("Supabase %s unreachable", path)
        return None, "The sign-in service is unreachable. Please try again in a minute."
    if resp.is_error:
        msg = data.get('msg') or data.get('error_description') or data.get('message') or 'Request failed.'
        log.warning("Supabase %s failed (%s): %s", path, resp.status_code, msg)
        return None, msg
    return data, None


def _throttled(request, action, per_ip, account=None, per_account=None):
    """True once this IP, or this username/email, has tried `action` too often in the last 15 minutes.
    Supabase also limits per IP, but it sees only Vercel's servers, so without this one visitor
    could use up everyone's allowance."""
    if too_many(f"{action}:ip:{client_ip(request)}", per_ip, 900):
        return True
    if account:
        digest = hashlib.sha256(account.strip().lower().encode()).hexdigest()  # safe cache key for any input
        return too_many(f"{action}:acct:{digest}", per_account, 900)
    return False


TOO_MANY = "Too many attempts. Please wait 15 minutes and try again."


def _pkce_pair():
    """(verifier, challenge) for a Supabase PKCE flow."""
    verifier = secrets.token_urlsafe(64)
    return verifier, base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()


def _keep_refresh_token(request, data):
    """Remember the Supabase refresh token so the profile page can change the password later."""
    if data.get('refresh_token'):
        request.session['sb_refresh'] = data['refresh_token']


def _find_invite(token):
    """(invite, error) for an invite token; invite is None if there's no token or it can't be used."""
    invite = CompanyInvite.objects.select_related('company').filter(token=token).first() if token else None
    if invite and not invite.is_usable:
        return None, "This invite link has expired or was already used. Ask your teammate for a new one."
    return invite, None


def _create_account(username, email, role, company_name, invite, supabase_id):
    """Create the user and profile, using up the invite if any. Returns (user, error).
    The user gets no Django password: Supabase checks it."""
    with transaction.atomic():
        # Lock the invite so two people can't both register with the same link
        if invite:
            invite = CompanyInvite.objects.select_for_update().get(id=invite.id)
            if not invite.is_usable:
                return None, "This invite link was just used. Ask your teammate for a new one."
        user = User.objects.create_user(username=username, email=email)  # unusable password
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.role = role
        profile.supabase_id = supabase_id
        if invite:
            profile.company = invite.company
            invite.used_by = user
            invite.save(update_fields=['used_by'])
        elif role == 'recruiter':
            # Each registration gets its own company: neither email domains nor typed names prove membership
            profile.company = Company.objects.create(name=company_name)
        profile.save()
    return user, None


def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    token = request.POST.get('invite') or request.GET.get('invite')
    invite, error = _find_invite(token)
    if request.method == 'POST':
        username = request.POST.get('username')
        email = (request.POST.get('email') or '').strip()
        password = request.POST.get('password')
        role = 'recruiter' if invite else request.POST.get('role', 'candidate')
        if role not in ('candidate', 'recruiter'):
            role = 'candidate'  # admin can't be self-chosen
        company_name = request.POST.get('company_name')

        if token and not invite:
            pass  # keep the expired-invite error rather than silently creating a candidate
        elif User.objects.filter(username=username).exists():
            error = "Username already exists."
        elif User.objects.filter(email__iexact=email).exists():
            error = "Email already registered."
        elif role == 'recruiter' and not company_name and not invite:
            error = "Company name is required for employers."
        elif (error := _password_problem(password, User(username=username, email=email))):
            pass
        elif _throttled(request, 'register', 5, email, 3):
            error = TOO_MANY
        else:
            data, error = _supabase('signup', {'email': email, 'password': password},
                                    redirect_to=request.build_absolute_uri(reverse('login')))
            sb_user = (data.get('user') or data) if data else {}
            if data and sb_user.get('identities') == []:
                error = "Email already registered."  # Supabase hides existing emails behind a fake user
            elif data:
                # ponytail: if the invite is taken between these two calls, the Supabase user is orphaned; harmless, sign-up with that email then says "already registered" at Supabase
                user, error = _create_account(username, email, role, company_name, invite, sb_user['id'])
                if user and data.get('access_token'):  # "Confirm email" is off in Supabase
                    login(request, user)
                    _keep_refresh_token(request, data)
                    return redirect('dashboard')
                if user:
                    messages.info(request, "Check your inbox and confirm your email, then sign in.")
                    return redirect('login')

    return render(request, 'register.html', {'error': error, 'invite': invite})


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    error = None
    if request.method == 'POST':
        identifier = (request.POST.get('username') or '').strip()
        password = request.POST.get('password')
        if _throttled(request, 'login', 20, identifier, 10):
            return render(request, 'login.html', {'error': TOO_MANY}, status=429)
        found = User.objects.filter(Q(username=identifier) | Q(email__iexact=identifier)).order_by('id').first()
        sb_id = UserProfile.objects.filter(user=found).values_list('supabase_id', flat=True).first() if found else None

        data, user = None, None
        if sb_id:
            data, msg = _supabase('token', {'email': found.email, 'password': password}, grant_type='password')
            user = found if data and data.get('user', {}).get('id') == sb_id else None
            if msg and 'confirm' in msg.lower():
                error = msg  # "Email not confirmed" helps; other failures stay generic

        if user is not None and user.is_active:
            login(request, user)
            _keep_refresh_token(request, data)
            nxt = request.GET.get('next', '')  # e.g. /admin/ sends people here to sign in
            if url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
                return redirect(nxt)
            return redirect('dashboard')
        error = error or "Invalid username or password."

    return render(request, 'login.html', {'error': error})


def password_reset(request):
    """Forgot password: Supabase emails a link (PKCE), then the new password is set at Supabase."""
    if (request.method == 'POST' or request.GET.get('code')) and _throttled(
            request, 'reset', 10, request.POST.get('email'), 3):
        return render(request, 'registration/password_reset_form.html',
                      {'form': PasswordResetForm(), 'error': TOO_MANY}, status=429)
    if request.method == 'GET' and request.GET.get('code'):
        # Back from the email link. The verifier is in this browser's session, so the link must open here.
        verifier = request.session.pop('sb_reset_verifier', None)
        data, _ = (_supabase('token', {'auth_code': request.GET['code'], 'code_verifier': verifier}, grant_type='pkce')
                   if verifier else (None, None))
        if data:
            request.session['sb_reset_token'] = data['access_token']
        return render(request, 'registration/password_reset_confirm.html',
                      {'validlink': bool(data), 'form': SetPasswordForm(None)})

    if request.method == 'POST' and 'sb_reset_token' in request.session:
        form = SetPasswordForm(None, request.POST)
        if form.is_valid():
            _, msg = _supabase('user', {'password': form.cleaned_data['new_password1']},
                               token=request.session['sb_reset_token'], method='PUT')
            if not msg:
                del request.session['sb_reset_token']
                messages.success(request, "Password updated. Sign in with your new password.")
                return redirect('login')
            form.add_error(None, msg)
        return render(request, 'registration/password_reset_confirm.html', {'validlink': True, 'form': form})

    form = PasswordResetForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        verifier, challenge = _pkce_pair()
        request.session['sb_reset_verifier'] = verifier
        _supabase('recover', {'email': form.cleaned_data['email'], 'code_challenge': challenge,
                              'code_challenge_method': 's256'},
                  redirect_to=request.build_absolute_uri(reverse('password_reset')))
        return render(request, 'registration/password_reset_done.html')  # same reply whether or not the email exists
    return render(request, 'registration/password_reset_form.html', {'form': form})


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
                fresh, msg = (_supabase('token', {'refresh_token': request.session['sb_refresh']}, grant_type='refresh_token')
                              if 'sb_refresh' in request.session else (None, None))
                if fresh:
                    _keep_refresh_token(request, fresh)
                    fresh, msg = _supabase('user', {'password': new_password}, token=fresh['access_token'], method='PUT')
                if fresh:
                    messages.success(request, 'Your password was successfully updated.')
                else:
                    messages.error(request, msg or 'Please sign out and back in, then try again.')
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
    return JsonResponse({'status': 'ok', 'database': 'ok', 'version': __version__})  # which build is live
