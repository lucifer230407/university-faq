FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY backend/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY backend/app /app/app
COPY backend/data /app/data
COPY backend/scripts /app/scripts
COPY frontend /app/frontend

# Serve the frontend from the same origin so the browser never hits CORS.
ENV STATIC_DIR=/app/frontend

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]