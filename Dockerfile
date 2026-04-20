FROM python:3.10-slim

# Install system dependencies if required by postgres/psycopg2
RUN apt-get update && apt-get install -y libpq-dev gcc && rm -rf /var/lib/apt/lists/*

# Hugging Face Spaces require running as a non-root user with UID 1000
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

WORKDIR $HOME/app

# Copy requirement files first for better layer caching
COPY --chown=user backend/requirements.txt $HOME/app/backend/requirements.txt

# Install dependencies using --no-cache-dir to keep image size small
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy the rest of the application
COPY --chown=user . $HOME/app

# Pre-compile static files and put them into the 'staticfiles' directory
# (We pass dummy env variables so settings.py doesn't crash during this build step)
RUN cd backend && SECRET_KEY=dummy HF_SPACE=1 python manage.py collectstatic --no-input --traceback

# Expose port 7860 as requested by huggingface
EXPOSE 7860

# The startup command triggers migrations and then starts the app via purely python uvicorn
CMD cd backend && python manage.py migrate && uvicorn backend.asgi:application --host 0.0.0.0 --port 7860
