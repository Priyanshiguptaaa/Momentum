# Build from monorepo root when Railway Root Directory is unset.
# Prefer setting Root Directory to `health-coach` (uses health-coach/Dockerfile).

FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HC_DATABASE_URL=sqlite:////data/health_coach.db

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY health-coach/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY health-coach/ .

RUN mkdir -p /data

EXPOSE 8000

CMD ["sh", "-c", "uvicorn src.api.main:app --host 0.0.0.0 --port ${PORT:-8000} --app-dir ."]
