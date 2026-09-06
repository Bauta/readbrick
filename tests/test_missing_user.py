"""A user that no longer exists must be a 404, never a 500.

A browser holds the chosen user in localStorage. Remove that user (or rebuild
the library) and every page still asks for their preferences on load. That
answer used to be a foreign-key IntegrityError surfacing as a 500, which the
reader page could not tell apart from the server being broken.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("READER_DATA_DIR", str(tmp_path))
    from server.app import create_app
    return TestClient(create_app())


def test_prefs_for_a_missing_user_is_404(client):
    r = client.get("/api/users/999/prefs")
    assert r.status_code == 404


def test_prefs_for_a_removed_user_is_404_not_500(client):
    user = client.post("/api/users", json={"name": "Ghost"}).json()
    assert client.get(f"/api/users/{user['id']}/prefs").status_code == 200
    client.delete(f"/api/users/{user['id']}")
    r = client.get(f"/api/users/{user['id']}/prefs")
    assert r.status_code == 404


def test_patching_prefs_for_a_missing_user_is_404(client):
    r = client.patch("/api/users/999/prefs", json={"theme": "sepia"})
    assert r.status_code == 404
