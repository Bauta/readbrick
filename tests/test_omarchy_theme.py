"""Reading the active Omarchy palette and serving it as CSS.

Readbrick must stay a standalone web app: on a machine with no Omarchy theme
present, the endpoints degrade quietly and the reader renders exactly as it
did before.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

COLORS_TOML = """\
mode = "dark"

accent = "#e68e0d"
selection = "#2a2a2a"
muted = "#333333"

background = "#121212"
lighter_background = "#1e1e1e"

foreground = "#bebebe"
light_foreground = "#8a8a8d"
"""


@pytest.fixture
def theme_dir(tmp_path, monkeypatch):
    d = tmp_path / "theme"
    d.mkdir()
    (d / "colors.toml").write_text(COLORS_TOML)
    (tmp_path / "theme.name").write_text("Matte Black\n")
    monkeypatch.setenv("READER_OMARCHY_THEME_DIR", str(d))
    return d


@pytest.fixture
def client():
    from server.app import create_app
    return TestClient(create_app())


# ───── palette parsing ─────

def test_reads_palette_from_colors_toml(theme_dir):
    from server.omarchy_theme import read_palette
    p = read_palette()
    assert p is not None
    assert p["accent"] == "#e68e0d"
    assert p["background"] == "#121212"
    assert p["mode"] == "dark"


def test_palette_is_none_when_no_theme_dir(monkeypatch, tmp_path):
    from server.omarchy_theme import read_palette
    monkeypatch.setenv("READER_OMARCHY_THEME_DIR", str(tmp_path / "nope"))
    assert read_palette() is None


def test_palette_is_none_when_colors_toml_is_malformed(tmp_path, monkeypatch):
    from server.omarchy_theme import read_palette
    d = tmp_path / "theme"
    d.mkdir()
    (d / "colors.toml").write_text("this is not = valid = toml [[[")
    monkeypatch.setenv("READER_OMARCHY_THEME_DIR", str(d))
    assert read_palette() is None


def test_palette_requires_the_colours_the_reader_actually_needs(tmp_path, monkeypatch):
    """A theme missing background/foreground/accent is unusable, not half-used."""
    from server.omarchy_theme import read_palette
    d = tmp_path / "theme"
    d.mkdir()
    (d / "colors.toml").write_text('mode = "dark"\nselection = "#111111"\n')
    monkeypatch.setenv("READER_OMARCHY_THEME_DIR", str(d))
    assert read_palette() is None


def test_theme_name_is_read_from_inside_an_override_dir(tmp_path, monkeypatch):
    """An override must not make us read theme.name out of its parent.

    Omarchy's own layout puts theme.name beside the theme directory, but with
    READER_OMARCHY_THEME_DIR=/omarchy-theme the parent is "/" — not ours.
    """
    from server.omarchy_theme import theme_name
    d = tmp_path / "mounted"
    d.mkdir()
    (tmp_path / "theme.name").write_text("Outside The Mount\n")   # must be ignored
    (d / "theme.name").write_text("Inside The Mount\n")
    monkeypatch.setenv("READER_OMARCHY_THEME_DIR", str(d))
    assert theme_name() == "Inside The Mount"


def test_theme_name_is_none_when_an_override_dir_has_no_name(tmp_path, monkeypatch):
    from server.omarchy_theme import theme_name
    d = tmp_path / "mounted"
    d.mkdir()
    (tmp_path / "theme.name").write_text("Outside The Mount\n")
    monkeypatch.setenv("READER_OMARCHY_THEME_DIR", str(d))
    assert theme_name() is None


def test_theme_name_uses_omarchy_layout_without_an_override(tmp_path, monkeypatch):
    """Default layout: theme.name really does sit beside the theme directory."""
    from server import omarchy_theme
    (tmp_path / "theme").mkdir()
    (tmp_path / "theme.name").write_text("Matte Black\n")
    monkeypatch.delenv("READER_OMARCHY_THEME_DIR", raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(omarchy_theme, "theme_dir", lambda: tmp_path / "theme")
    assert omarchy_theme.theme_name() == "Matte Black"


# ───── /api/theme ─────

def test_theme_endpoint_reports_availability(client, theme_dir):
    r = client.get("/api/theme")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["mode"] == "dark"


def test_theme_endpoint_reports_unavailable_without_omarchy(client, monkeypatch, tmp_path):
    monkeypatch.setenv("READER_OMARCHY_THEME_DIR", str(tmp_path / "nope"))
    r = client.get("/api/theme")
    assert r.status_code == 200
    assert r.json()["available"] is False


# ───── /api/theme.css ─────

def test_theme_css_scopes_to_the_omarchy_theme_attribute(client, theme_dir):
    r = client.get("/api/theme.css")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/css")
    css = r.text
    assert '[data-theme="omarchy"]' in css
    assert "--accent: #e68e0d" in css
    assert "--bg: #121212" in css
    assert "--fg: #bebebe" in css


def test_theme_css_is_empty_but_valid_without_omarchy(client, monkeypatch, tmp_path):
    """An empty stylesheet keeps the <link> harmless on non-Omarchy machines."""
    monkeypatch.setenv("READER_OMARCHY_THEME_DIR", str(tmp_path / "nope"))
    r = client.get("/api/theme.css")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/css")
    assert '[data-theme="omarchy"]' not in r.text


def test_theme_css_rejects_a_palette_with_injected_css(tmp_path, monkeypatch, client):
    """Colour values are interpolated into a stylesheet — they must be validated."""
    d = tmp_path / "theme"
    d.mkdir()
    (d / "colors.toml").write_text(
        'mode = "dark"\n'
        'background = "#121212"\n'
        'foreground = "#bebebe"\n'
        'accent = "red; } body { display: none; } .x {"\n'
    )
    monkeypatch.setenv("READER_OMARCHY_THEME_DIR", str(d))
    css = client.get("/api/theme.css").text
    assert "display: none" not in css
