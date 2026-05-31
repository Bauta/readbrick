from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_data_dir(monkeypatch, tmp_path):
    """Each test gets its own ~/.reader by pointing READER_DATA_DIR at tmp_path."""
    monkeypatch.setenv("READER_DATA_DIR", str(tmp_path))
    yield tmp_path


@pytest.fixture(autouse=True)
def _no_network_metadata(monkeypatch):
    """Tests must never hit OpenLibrary or Google Books.

    Strategy: replace `server.metadata.enrich` on the module itself
    with a no-op stub. Production callers (library, book_detail, and
    any future caller) reach `enrich` via
    `from . import metadata as md` and look up `md.enrich` at call
    time — they get the stub. Adding a new caller does NOT silently
    leak through to the real network: any `md.enrich(...)` is caught.

    tests/test_metadata.py does `from server.metadata import enrich`
    at import time, binding the original function in its own namespace.
    It mocks `server.metadata.httpx.get` to fake the network — that
    layer is below the patched `enrich`, so those tests are unaffected.

    Tests that want a controlled return value should override the
    stub via `monkeypatch.setattr(server.metadata, "enrich",
    lambda *a, **kw: {...})`.
    """
    from server import metadata
    monkeypatch.setattr(metadata, "enrich", lambda *a, **kw: None)
    yield


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"
