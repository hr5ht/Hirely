"""Passwords (Django-compatible hashes), sign-in sessions, CSRF, rate limits and flash messages."""
import base64
import gzip
import hashlib
import hmac
import random
import re
import secrets
import string
import time
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from starlette.concurrency import run_in_threadpool

from app.core import config
from app.core.database import DB, SessionLocal
from app.models import RateLimit, User, UserProfile

ITERATIONS = 1_000_000  # Django 5.2's default, so hashes made here and there verify in both


# ---- Passwords -------------------------------------------------------------------------------

def _pbkdf2(raw, salt, iterations):
    return base64.b64encode(hashlib.pbkdf2_hmac('sha256', raw.encode(), salt.encode(), iterations)).decode()


def _make_password(raw):
    salt = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(22))
    return f"pbkdf2_sha256${ITERATIONS}${salt}${_pbkdf2(raw, salt, ITERATIONS)}"


def _check_password(raw, encoded):
    try:
        algorithm, iterations, salt, digest = encoded.split('$', 3)
    except ValueError:
        return False  # unusable ('!...') or malformed
    return algorithm == 'pbkdf2_sha256' and hmac.compare_digest(_pbkdf2(raw, salt, int(iterations)), digest)


# A million PBKDF2 rounds take ~0.5 s of CPU: off the event loop, or every request waits
async def hash_password(raw):
    return await run_in_threadpool(_make_password, raw)


async def verify_password(raw, encoded):
    return await run_in_threadpool(_check_password, raw or '', encoded or '')


@lru_cache(1)
def dummy_hash():
    """Checked when no user matches, so a missing account takes as long as a wrong password."""
    return _make_password(secrets.token_hex(8))


@lru_cache(1)
def _common_passwords():
    with gzip.open(Path(__file__).with_name('common-passwords.txt.gz'), 'rt') as f:  # Django's list of 20k
        return {line.strip() for line in f}


def _too_similar(password, value):
    """Django's UserAttributeSimilarityValidator test, max similarity 0.7."""
    for part in re.split(r'\W+', value) + [value]:
        if len(password) >= 10 * len(part) and len(part) < 0.7 / 2 * len(password):
            continue  # part is far shorter than the password
        if SequenceMatcher(a=password, b=part).quick_ratio() >= 0.7:
            return True
    return False


def password_problem(password, username='', email='', first_name='', last_name=''):
    """Why Django's four default validators would reject this password, or None if it's acceptable."""
    problems = []
    lowered = password.lower()
    for label, value in (('username', username), ('first name', first_name), ('last name', last_name), ('email address', email)):
        if value and _too_similar(lowered, value.lower()):
            problems.append(f"The password is too similar to the {label}.")
            break
    if len(password) < 8:
        problems.append("This password is too short. It must contain at least 8 characters.")
    if lowered.strip() in _common_passwords():
        problems.append("This password is too common.")
    if password.isdigit():
        problems.append("This password is entirely numeric.")
    return " ".join(problems) or None


# ---- Sessions --------------------------------------------------------------------------------

def session_hash(user):
    """Changes whenever the password does, which signs out every other session (as Django did)."""
    return hmac.new(config.SECRET_KEY.encode(), user.password.encode(), hashlib.sha256).hexdigest()


def login(request, user):
    request.session.clear()
    request.session.update(uid=user.id, auth=session_hash(user))


def logout(request):
    request.session.clear()


async def get_user(request: Request, db: DB):
    """The signed-in user (with profile and company loaded) or None; also kept on request.state for templates."""
    user = None
    uid = request.session.get('uid')
    if uid:
        user = await db.get(User, uid)
        if not user or not user.is_active or not hmac.compare_digest(request.session.get('auth', ''), session_hash(user)):
            request.session.clear()
            user = None
    request.state.user = user
    return user


CurrentUser = Annotated[User | None, Depends(get_user)]


async def ensure_profile(db, user):
    if user.profile is None:
        user.profile = UserProfile(user=user)
        await db.commit()
    return user.profile


# ---- CSRF ------------------------------------------------------------------------------------

def csrf_token(request):
    token = request.session.get('csrf')
    if not token:
        token = request.session['csrf'] = secrets.token_urlsafe(32)
    return token


async def csrf_protect(request: Request):
    """Every POST carries the session's token: forms as csrfmiddlewaretoken, fetch() as X-CSRFToken."""
    if request.method in ('GET', 'HEAD', 'OPTIONS'):
        return
    sent = request.headers.get('x-csrftoken')
    if not sent and request.headers.get('content-type', '').startswith(('application/x-www-form-urlencoded', 'multipart/form-data')):
        sent = (await request.form()).get('csrfmiddlewaretoken')  # Starlette caches the parsed form for the endpoint
    expected = request.session.get('csrf')
    if not (expected and isinstance(sent, str) and hmac.compare_digest(sent, expected)):
        raise HTTPException(403, "CSRF check failed. Reload the page and try again.")


# ---- Rate limits -----------------------------------------------------------------------------

def client_ip(request):
    # Uvicorn serves directly (no proxy), so the socket address is the real client and can't be spoofed by a header
    return request.client.host if request.client else ''


async def too_many(bucket, limit, window):
    """Count one attempt in `bucket` (fixed window, seconds); True once there were more than `limit`."""
    now = time.time()
    key = f"rl:{bucket}:{int(now // window)}"
    expires = datetime.fromtimestamp((now // window + 1) * window, timezone.utc)
    stmt = insert(RateLimit).values(key=key[:200], count=1, expires_at=expires)
    stmt = stmt.on_conflict_do_update(index_elements=['key'], set_={'count': RateLimit.count + 1}).returning(RateLimit.count)
    async with SessionLocal() as db:  # own transaction: atomic increment, unlike the old cache.incr
        count = (await db.execute(stmt)).scalar_one()
        if random.random() < 0.01:  # sweep old windows now and then
            await db.execute(delete(RateLimit).where(RateLimit.expires_at < datetime.now(timezone.utc) - timedelta(hours=1)))
        await db.commit()
    return count > limit


async def throttled(request, action, per_ip, account=None, per_account=None):
    """True once this IP, or this username/email, has tried `action` too often in the last 15 minutes."""
    if await too_many(f"{action}:ip:{client_ip(request)}", per_ip, 900):
        return True
    if account:
        digest = hashlib.sha256(account.strip().lower().encode()).hexdigest()  # safe key for any input
        return await too_many(f"{action}:acct:{digest}", per_account, 900)
    return False


async def over_hourly_limit(user, name, per_hour):
    """Per-user cap on an AI endpoint (fixed hourly window)."""
    return bool(user) and await too_many(f"{name}:{user.id}", per_hour, 3600)


# ---- Flash messages --------------------------------------------------------------------------

class Message:
    def __init__(self, tags, text):
        self.tags, self.text = tags, text

    def __str__(self):
        return self.text


def flash(request, level, text):
    request.session['flash'] = request.session.get('flash', []) + [[level, text]]


def pop_messages(request):
    return [Message(level, text) for level, text in request.session.pop('flash', [])]
