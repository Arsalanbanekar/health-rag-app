# Backend-only Docker image for Hugging Face Spaces (Docker SDK).
# Built from the repo root because HF Spaces uses the repo root as the build
# context; the frontend/ directory is simply not copied into the image.
FROM python:3.11-slim

# HF Spaces containers run as a non-root user by convention (UID 1000) —
# skipping this causes filesystem-permission errors at runtime on their infra.
RUN useradd -m -u 1000 appuser
WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

USER appuser
ENV HOME=/home/appuser

# HF Spaces expects the container to listen on this port (see app_port in
# README.md's Space metadata block, which must match).
EXPOSE 7860
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
