"""Settings from the environment: backend/.env locally; compose sets DATABASE_URL and DEBUG."""
import os
import re
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/app: templates/ and static/ live here
load_dotenv(BASE_DIR.parent / '.env')

DEBUG = os.environ.get('DEBUG', '').lower() in ('1', 'true')

# The dev fallback only applies with DEBUG on; anything else must set SECRET_KEY or startup fails
SECRET_KEY = os.environ.get('SECRET_KEY') or ('dev-insecure-key-do-not-use-in-production' if DEBUG else None)
if not SECRET_KEY:
    raise ValueError("SECRET_KEY environment variable is required when DEBUG is off.")

DATABASE_URL = os.environ.get('DATABASE_URL', '')
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is required.")
# Same postgres:// URL as before; SQLAlchemy needs the async driver named
DATABASE_URL = re.sub(r'^postgres(ql)?://', 'postgresql+asyncpg://', DATABASE_URL)

LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')

# Demo accounts: created by scripts/seed_demo.py and offered on the login page, only with DEBUG on
DEMO_PASSWORD = 'hirely-demo-123'
DEMO_CANDIDATE = 'demo_candidate'
DEMO_RECRUITER = 'demo_recruiter'

# Email: SMTP when EMAIL_HOST is set, otherwise messages are printed to the log
EMAIL_HOST = os.environ.get('EMAIL_HOST', '')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT') or 587)
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'true').lower() == 'true'
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'Hirely <no-reply@hirely.local>')
