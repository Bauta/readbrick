# CPU-only Kokoro-82M TTS service. No GPU required; on CPU it runs ~4.4x
# realtime, fast enough for gapless read-along. Model weights + all 28 English
# voices baked into the image (no runtime download, no volume).
FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    HF_HOME=/app/hf_cache \
    HF_HUB_ENABLE_HF_TRANSFER=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        espeak-ng ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-only torch wheels (no CUDA/ROCm) — lean image, zero GPU deps.
RUN pip install --no-cache-dir torch==2.8.0 torchaudio==2.8.0 \
        --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir \
        kokoro==0.9.4 "misaki[en]" soundfile \
        fastapi "uvicorn[standard]" "pydantic>=2" hf_transfer huggingface_hub

# Bake the misaki English G2P spacy model so the container needs no runtime download.
RUN python3 -m spacy download en_core_web_sm

# Bake the Kokoro weights + all English voice packs into the image layer.
COPY kokoro_service/bake_voices.py /tmp/bake_voices.py
RUN python3 /tmp/bake_voices.py

COPY kokoro_service /app/kokoro_service

EXPOSE 8005
HEALTHCHECK --interval=10s --timeout=3s --retries=60 \
    CMD curl -fsS http://localhost:8005/health || exit 1
CMD ["python3", "-m", "uvicorn", "kokoro_service.app:app", "--host", "0.0.0.0", "--port", "8005"]
