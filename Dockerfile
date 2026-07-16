# ---- builder stage: installs dependencies -------------------------------
FROM python:3.12-slim AS builder

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ---- runtime stage: copies installed deps + app code ---------------------
FROM python:3.12-slim

WORKDIR /app

RUN useradd -m appuser

COPY --from=builder /root/.local /home/appuser/.local
COPY . .

ENV PATH=/home/appuser/.local/bin:$PATH \
    PYTHONUNBUFFERED=1

RUN chown -R appuser:appuser /app /home/appuser/.local

USER appuser

EXPOSE 8000

# Production form — no --reload here. Live reload is added on top via the
# docker-compose.yml `command:` override for local dev only (see D3 in README).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
