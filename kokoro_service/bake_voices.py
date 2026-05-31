"""Build-time: download the Kokoro model + all English voices into the image.

Runs during `docker build` so the running container needs no network. Weights
and voice packs land under HF_HOME (=/app/hf_cache), baked into the image layer
(this service mounts no volume there).
"""
from kokoro import KPipeline

# Keep in sync with kokoro_service/synthesizer.py ENGLISH_VOICES.
VOICES = [
    "af_alloy", "af_aoede", "af_bella", "af_heart", "af_jessica", "af_kore",
    "af_nicole", "af_nova", "af_river", "af_sarah", "af_sky",
    "am_adam", "am_echo", "am_eric", "am_fenrir", "am_liam", "am_michael",
    "am_onyx", "am_puck", "am_santa",
    "bf_alice", "bf_emma", "bf_isabella", "bf_lily",
    "bm_daniel", "bm_fable", "bm_george", "bm_lewis",
]

for lc in ("a", "b"):
    pipe = KPipeline(lang_code=lc)
    for v in [x for x in VOICES if x[0] == lc]:
        try:
            pipe.load_voice(v)
        except Exception:
            # Fallback: a one-word synth forces the voice pack download.
            list(pipe("ok", voice=v))
        print("baked", v, flush=True)
print("bake complete", flush=True)
