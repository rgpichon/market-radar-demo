"""Production WSGI entry for Market Radar."""

from app import app, init_db

init_db()

# Gunicorn / cloud hosts import `wsgi:app`
application = app
