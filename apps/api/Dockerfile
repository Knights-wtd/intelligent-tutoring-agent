# Keep the readable tag; update its digest deliberately with each version bump.
FROM python:3.12-slim-bookworm@sha256:a116514e19457bcb7af7efe9c3dd0b9b71e85b317694e7882a1c52aa15a78134 AS build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

COPY apps/api/build-requirements.lock ./build-requirements.lock
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r build-requirements.lock

COPY apps/api/pyproject.toml ./pyproject.toml
COPY apps/api/src ./src
RUN python -m pip wheel --no-build-isolation --no-deps --wheel-dir /wheels .

FROM python:3.12-slim-bookworm@sha256:a116514e19457bcb7af7efe9c3dd0b9b71e85b317694e7882a1c52aa15a78134 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    API_HOST=0.0.0.0 \
    API_PORT=8000

WORKDIR /app

RUN addgroup --system tutor \
    && adduser --system --ingroup tutor --home /app tutor

COPY apps/api/requirements.lock ./requirements.lock
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.lock

COPY apps/api/alembic.ini ./alembic.ini
COPY apps/api/migrations ./migrations

COPY --from=build /wheels /wheels
RUN pip install --no-deps /wheels/*.whl \
    && chown -R tutor:tutor /app

USER tutor

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=10 \
    CMD ["python", "-c", "import os, urllib.request; port = int(os.environ.get('API_PORT', '8000')); urllib.request.urlopen(f'http://127.0.0.1:{port}/api/v1/health', timeout=2)"]

CMD ["sh", "-c", "python -m alembic -c alembic.ini upgrade head && exec uvicorn tutor_api.main:app --host \"$API_HOST\" --port \"$API_PORT\""]
