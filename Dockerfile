# Reader app server (FastAPI). Light, pure-Python image — TTS runs in the
# separate kokoro-tts service and is reached over HTTP, so no torch/ML deps here.
# Books + the SQLite DB live in the /data volume.
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    READER_HOST=0.0.0.0 \
    READER_DATA_DIR=/data \
    READER_KOKORO_URL=http://kokoro-tts:8005 \
    READER_KOKORO_MANAGED=1

WORKDIR /app

# Install deps via an editable install so `server` stays at /app/server — the
# app resolves web/ as `Path(__file__).parent.parent / "web"`, which only works
# if the package isn't copied off into site-packages.
COPY pyproject.toml ./
COPY server ./server
COPY web ./web
RUN pip install --no-cache-dir -e .

EXPOSE 8000
VOLUME ["/data"]
CMD ["python", "-m", "server.app"]
