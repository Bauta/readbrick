"""Start the always-up Kokoro container and wait until it's ready.

The Kokoro container is CPU-only and holds no VRAM, so it
runs with restart: unless-stopped and never self-exits. This module only needs
to bring it up the first time (fresh boot / after `docker compose down`). Seams
(_health_ok, _start_container) are module-level so tests can monkeypatch them.
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# Repo-root-anchored default so `docker compose -f` works regardless of the
# reader process's CWD (e.g. when launched from a systemd unit).
_DEFAULT_COMPOSE = str(Path(__file__).resolve().parent.parent / "docker-compose.yml")


def _base_url() -> str:
    return os.environ.get("READER_KOKORO_URL", "http://127.0.0.1:8005")


def _compose_file() -> str:
    return os.environ.get("READER_KOKORO_COMPOSE", _DEFAULT_COMPOSE)


def _service() -> str:
    return os.environ.get("READER_KOKORO_SERVICE", "kokoro-tts")


def _health_ok() -> bool:
    try:
        r = httpx.get(_base_url() + "/health", timeout=2.0)
        return r.status_code == 200 and bool(r.json().get("loaded"))
    except Exception as e:
        # Poll function: any error (connection refused, timeout, bad JSON) means
        # "not ready yet". Swallow it but log at debug to aid startup-hang triage.
        logger.debug("kokoro health check not ready: %s", e)
        return False


def _start_container() -> None:
    subprocess.run(
        ["docker", "compose", "-f", _compose_file(), "up", "-d", _service()],
        check=True,
        capture_output=True,
    )


def ensure_up(timeout_s: float = 180.0, poll_s: float = 2.0) -> None:
    """Return once the container reports ready, or raise on timeout.

    When READER_KOKORO_MANAGED=1 (the reader runs inside docker compose, which
    owns the kokoro-tts service via depends_on + restart policy), we never shell
    out to docker — there's no docker in that container — and just poll /health.
    On the host, we start the container on demand.
    """
    if _health_ok():
        return
    if os.environ.get("READER_KOKORO_MANAGED") != "1":
        _start_container()
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _health_ok():
            return
        time.sleep(poll_s)
    raise RuntimeError(
        f"Kokoro container did not become ready within {timeout_s:.0f}s "
        f"(check: docker compose -f {_compose_file()} logs {_service()})"
    )
