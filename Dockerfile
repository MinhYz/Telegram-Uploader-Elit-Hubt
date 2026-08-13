# Multi-stage lightweight Dockerfile for Oracle Cloud 1GB RAM Instance
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

# Install system utilities and python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy framework source code
COPY . .

# Environment Defaults
ENV PYTHONUNBUFFERED=1 \
    HEADLESS=true \
    MAX_BROWSER_CONTEXTS=3

EXPOSE 8000

CMD ["python3", "main.py"]
