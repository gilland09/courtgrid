web: cd backend && gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 3 --timeout 60
compute: cd availability_service && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8001}
