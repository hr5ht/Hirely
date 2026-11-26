"""Hirely: FastAPI app. Run with: uvicorn app.main:app"""
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.admin import setup_admin
from app.core import config
from app.core.config import BASE_DIR
from app.core.database import create_tables
from app.core.security import csrf_protect
from app.routers import auth, candidate, interview, recruiter

logging.basicConfig(format='%(levelname)s %(name)s: %(message)s')
logging.getLogger('app').setLevel(config.LOG_LEVEL)

MAX_BODY_BYTES = 10 * 1024 * 1024  # resumes are capped at 4 MB; voice answers arrive as base64 JSON


@asynccontextmanager
async def lifespan(app):
    await create_tables()
    yield


app = FastAPI(title="Hirely", lifespan=lifespan, dependencies=[Depends(csrf_protect)],
              docs_url=None, redoc_url=None, openapi_url=None)  # HTML app, not a public API


@app.middleware('http')
async def security_headers(request: Request, call_next):
    # shortcut: trusts Content-Length; a chunked upload with no length isn't capped here, put a proxy limit in front if exposed
    if int(request.headers.get('content-length') or 0) > MAX_BODY_BYTES:
        return PlainTextResponse("Request too large.", status_code=413)
    response = await call_next(request)
    # What Django's security and clickjacking middleware sent
    response.headers.setdefault('X-Frame-Options', 'DENY')
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('Referrer-Policy', 'same-origin')
    return response


SESSION_COOKIE = dict(session_cookie='sessionid', max_age=14 * 24 * 3600, same_site='lax', https_only=not config.DEBUG)
app.add_middleware(SessionMiddleware, secret_key=config.SECRET_KEY, **SESSION_COOKIE)

app.mount('/static', StaticFiles(directory=BASE_DIR / 'static'), name='static')
for module in (auth, candidate, recruiter, interview):
    app.include_router(module.router)
setup_admin(app, SESSION_COOKIE)
