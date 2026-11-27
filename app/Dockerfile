# Booking API image (commit 13). Build from the repo root so the code keeps its
# package name and runs as `app.main:app`:
#   docker build -f app/Dockerfile -t booking-api:dev .

# --- build stage: install dependencies into a venv -------------------------
FROM python:3.11-slim AS build

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /venv
COPY app/requirements.txt /tmp/requirements.txt
RUN /venv/bin/pip install -r /tmp/requirements.txt

# --- test stage: runtime deps + pytest; `make test` mounts the source -------
FROM build AS test
COPY app/requirements-dev.txt /tmp/requirements-dev.txt
RUN /venv/bin/pip install -r /tmp/requirements-dev.txt
ENV PATH="/venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /src
CMD ["pytest"]

# --- runtime stage (default target): venv + code only, non-root ------------------------------
FROM python:3.11-slim

ARG APP_VERSION=dev
ENV PATH="/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_VERSION=$APP_VERSION

RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

COPY --from=build /venv /venv
WORKDIR /srv
COPY --chown=app:app app/ ./app/

USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"

# One worker per pod: the search limiter, metrics and faults live in one process.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
