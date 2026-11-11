FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app app

WORKDIR /app
COPY requirements.txt ./
# CPU-only PyTorch keeps the image free from unused NVIDIA/CUDA runtime packages.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.8.0 \
    && pip install --no-cache-dir -r requirements.txt
COPY requirements-phase3.txt ./
RUN pip install --no-cache-dir -r requirements-phase3.txt
COPY --chown=app:app app ./app
COPY --chown=app:app .claude/skills/dakwah-content-discovery/schemas/content-proposal.schema.json ./.claude/skills/dakwah-content-discovery/schemas/content-proposal.schema.json
COPY --chown=app:app .claude/skills/dakwah-content-discovery/scripts/validate-proposal.py ./.claude/skills/dakwah-content-discovery/scripts/validate-proposal.py
COPY --chown=app:app tests ./tests
COPY pytest.ini ./
USER app

EXPOSE 8000
