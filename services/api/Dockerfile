FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY services/api .
COPY ml ./ml
COPY data ./data

# Run Celery worker
CMD ["celery", "-A", "tasks", "worker", "--loglevel=info"]
