# ---- Build Stage ----
FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ---- Runtime Stage ----
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PATH="/home/nimpilot/.local/bin:${PATH}"

RUN useradd -m -s /bin/bash nimpilot

COPY --from=builder /root/.local /home/nimpilot/.local

WORKDIR /app

COPY --chown=nimpilot:nimpilot . .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

USER nimpilot

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]