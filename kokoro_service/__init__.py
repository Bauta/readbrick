"""CPU Kokoro-82M TTS container service.

A lightweight, always-up sibling of tts_service that speaks the same HTTP
synthesis contract but runs Kokoro-82M on the CPU (no GPU, no aligner). Kokoro
emits native per-word timestamps, so the reading pill is driven straight off
the model's duration predictor.
"""
