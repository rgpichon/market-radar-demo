FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY backend ./backend
COPY frontend ./frontend

# Demo SQLite DBs ship with the image when present locally at build time.
# Secrets and caches are excluded via .dockerignore.

ENV HOST=0.0.0.0
ENV PORT=5001
ENV FLASK_DEBUG=0
WORKDIR /app/backend

EXPOSE 5001
CMD ["gunicorn", "wsgi:app", "--bind", "0.0.0.0:5001", "--workers", "2", "--timeout", "120"]
