FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN addgroup --system tutor \
    && adduser --system --ingroup tutor --home /app tutor

COPY apps/api/pyproject.toml ./pyproject.toml
COPY apps/api/src ./src

RUN pip install --no-cache-dir . \
    && chown -R tutor:tutor /app

USER tutor

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=10 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2)"]

CMD ["uvicorn", "tutor_api.main:app", "--host", "0.0.0.0", "--port", "8000"]

