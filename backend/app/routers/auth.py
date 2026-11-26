"""Accounts: sign-up (with company invites), login, password resets, profile, and public pages.

Passwords are checked here, hashed the way Django did; sign-in state lives in a signed session cookie.
"""
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError

from app import __version__
from app.core import config
from app.core.database import DB
from app.core.security import (CurrentUser, dummy_hash, ensure_profile, flash, hash_password, login, logout,
                               password_problem, session_hash, throttled, verify_password)
from app.core.templating import base_url, redirect, render
from app.models import Company, CompanyInvite, User, UserProfile, now
from app.services import notify

log = logging.getLogger(__name__)
router = APIRouter()

TOO_MANY = "Too many attempts. Please wait 15 minutes and try again."
RESET_MAX_AGE = 3600
_reset_tokens = URLSafeTimedSerializer(config.SECRET_KEY, salt='password-reset')


def _safe_next(url):
    """Only same-site paths, so ?next= can't send people to another site after signing in."""
    return url.startswith('/') and not url.startswith(('//', '/\\'))


async def _find_invite(db, token):
    """(invite, error) for an invite token; invite is None if there's no token or it can't be used."""
    invite = await db.scalar(select(CompanyInvite).where(CompanyInvite.token == token)) if token else None
    if invite and not invite.is_usable:
        return None, "This invite link has expired or was already used. Ask your teammate for a new one."
    return invite, None


async def _create_account(db, username, email, role, company_name, invite, password):
    """Create the user and profile, using up the invite if any. Returns (user, error)."""
    password_hash = await hash_password(password)  # before taking the invite lock: hashing takes ~0.5 s
    if invite:
        # Lock the invite so two people can't both register with the same link
        invite = await db.scalar(select(CompanyInvite).where(CompanyInvite.id == invite.id).with_for_update()
                                 .execution_options(populate_existing=True))
        if not invite.is_usable:
            await db.rollback()
            return None, "This invite link was just used. Ask your teammate for a new one."
    user = User(username=username, email=email, password=password_hash)
    profile = UserProfile(user=user, role=role)
    db.add_all([user, profile])
    if invite:
        profile.company_id = invite.company_id
        await db.flush()
        invite.used_by_id = user.id
    elif role == 'recruiter':
        # Each registration gets its own company: neither email domains nor typed names prove membership
        profile.company = Company(name=company_name)
    try:
        await db.commit()
    except IntegrityError:  # someone took the username in the meantime
        await db.rollback()
        return None, "Username already exists."
    return user, None


@router.api_route('/register/', methods=['GET', 'POST'])
async def register_view(request: Request, db: DB, user: CurrentUser):
    if user:
        return redirect('/dashboard/')

    form = await request.form() if request.method == 'POST' else {}
    token = form.get('invite') or request.query_params.get('invite')
    invite, error = await _find_invite(db, token)
    if request.method == 'POST':
        username = form.get('username') or ''
        email = (form.get('email') or '').strip()
        password = form.get('password') or ''
        role = 'recruiter' if invite else form.get('role', 'candidate')
        if role not in ('candidate', 'recruiter'):
            role = 'candidate'  # admin can't be self-chosen
        company_name = form.get('company_name')

        if token and not invite:
            pass  # keep the expired-invite error rather than silently creating a candidate
        elif await db.scalar(select(User.id).where(User.username == username)):
            error = "Username already exists."
        elif await db.scalar(select(User.id).where(func.upper(User.email) == email.upper())):
            error = "Email already registered."
        elif role == 'recruiter' and not company_name and not invite:
            error = "Company name is required for employers."
        elif (error := password_problem(password, username=username, email=email)):
            pass
        elif await throttled(request, 'register', 5, email, 3):
            error = TOO_MANY
        else:
            new_user, error = await _create_account(db, username, email, role, company_name, invite, password)
            if new_user:
                login(request, new_user)
                return redirect('/dashboard/')

    return render(request, 'register.html', {'error': error, 'invite': invite})


@router.api_route('/login/', methods=['GET', 'POST'])
async def login_view(request: Request, db: DB, user: CurrentUser):
    if user:
        return redirect('/dashboard/')

    error = None
    if request.method == 'POST':
        form = await request.form()
        identifier = (form.get('username') or '').strip()
        password = form.get('password') or ''
        if await throttled(request, 'login', 20, identifier, 10):
            return render(request, 'login.html', {'error': TOO_MANY}, status=429)
        found = await db.scalar(select(User).where(or_(User.username == identifier, func.upper(User.email) == identifier.upper()))
                                .order_by(User.id).limit(1))
        # A missing user still costs one hash check, so response time doesn't reveal which accounts exist
        password_ok = await verify_password(password, found.password if found else dummy_hash())
        if found and password_ok and found.is_active:
            login(request, found)
            found.last_login = now()
            await db.commit()
            nxt = request.query_params.get('next', '')  # e.g. /admin/ sends people here to sign in
            return redirect(nxt if _safe_next(nxt) else '/dashboard/')
        error = "Invalid username or password."

    return render(request, 'login.html', {'error': error})


@router.api_route('/password-reset/', methods=['GET', 'POST'])
async def password_reset(request: Request, db: DB):
    """Forgot password: email a signed link that works once (it embeds a hash of the current password) for an hour."""
    if request.method == 'POST':
        email = ((await request.form()).get('email') or '').strip()
        if await throttled(request, 'reset', 10, email, 3):
            return render(request, 'registration/password_reset_form.html', {'error': TOO_MANY}, status=429)
        if '@' not in email:
            return render(request, 'registration/password_reset_form.html', {'error': "Enter a valid email address."})
        users = (await db.scalars(select(User).where(func.upper(User.email) == email.upper(), User.is_active,
                                                     ~User.password.startswith('!')))).all()
        for u in users:
            token = _reset_tokens.dumps({'u': u.id, 'h': session_hash(u)[:16]})
            await notify.email([u.email], "Password reset on Hirely",
                               f"Hi {u.username},\n\nChoose a new password here (the link works once, for an hour):\n"
                               f"{base_url(request)}/password-reset/{token}/\n\nIf you didn't ask for this, ignore this email.\n\n- Hirely")
        return render(request, 'registration/password_reset_done.html')  # same reply whether or not the email exists
    return render(request, 'registration/password_reset_form.html')


async def _reset_user(db, token):
    try:
        data = _reset_tokens.loads(token, max_age=RESET_MAX_AGE)
    except BadSignature:  # also covers expired links
        return None
    user = await db.get(User, data.get('u'))
    return user if user and user.is_active and session_hash(user)[:16] == data.get('h') else None


@router.api_route('/password-reset/{token}/', methods=['GET', 'POST'])
async def password_reset_confirm(request: Request, token: str, db: DB):
    user = await _reset_user(db, token)
    if not user:
        return render(request, 'registration/password_reset_confirm.html', {'validlink': False})
    error = None
    if request.method == 'POST':
        form = await request.form()
        new1, new2 = form.get('new_password1') or '', form.get('new_password2') or ''
        if new1 != new2:
            error = "The two password fields didn’t match."
        elif not (error := password_problem(new1, user.username, user.email, user.first_name, user.last_name)):
            user.password = await hash_password(new1)
            await db.commit()
            flash(request, 'success', "Password updated. Sign in with your new password.")
            return redirect('/login/')
    return render(request, 'registration/password_reset_confirm.html', {'validlink': True, 'error': error})


@router.get('/logout/')
async def logout_view(request: Request):
    logout(request)
    return redirect('/login/')


@router.api_route('/profile/', methods=['GET', 'POST'])
async def profile_view(request: Request, db: DB, user: CurrentUser):
    if not user:
        return redirect('/login/')

    profile = await ensure_profile(db, user)

    if request.method == 'POST':
        form = await request.form()
        action = form.get('action')
        if action == 'update_profile':
            user.first_name = form.get('first_name', user.first_name)
            user.last_name = form.get('last_name', user.last_name)
            await db.commit()
            flash(request, 'success', 'Your profile has been updated successfully.')
        elif action == 'change_password':
            new_password = form.get('new_password', '')
            if (problem := password_problem(new_password, user.username, user.email, user.first_name, user.last_name)):
                flash(request, 'error', problem)
            else:
                user.password = await hash_password(new_password)
                await db.commit()
                request.session['auth'] = session_hash(user)  # stay signed in here; other sessions are signed out
                flash(request, 'success', 'Your password was successfully updated.')
        return redirect('/profile/')

    return render(request, 'profile.html', {'has_resume': bool(profile.resume_text)})


@router.get('/')
async def home(request: Request, user: CurrentUser):
    return render(request, 'landing.html')


@router.get('/healthz')
async def healthz(db: DB):
    """Uptime probe: 200 when the app can reach its database, 503 when it can't."""
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        log.exception("Health check: database unreachable")
        return JSONResponse({'status': 'error', 'database': 'unreachable'}, status_code=503)
    return {'status': 'ok', 'database': 'ok', 'version': __version__}  # which build is live
