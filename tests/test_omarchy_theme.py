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


def test_theme_name_prefers_a_name_inside_the_theme_dir(tmp_path, monkeypatch):
    from server.omarchy_theme import theme_name
    d = tmp_path / "theme"
    d.mkdir()
    (tmp_path / "theme.name").write_text("Beside\n")
    (d / "theme.name").write_text("Inside\n")
    monkeypatch.setenv("READER_OMARCHY_THEME_DIR", str(d))
    assert theme_name() == "Inside"


def test_theme_name_falls_back_to_the_omarchy_layout_beside_the_dir(tmp_path, monkeypatch):
    """Omarchy writes theme.name beside the theme directory, not inside it."""
    from server.omarchy_theme import theme_name
    d = tmp_path / "theme"
    d.mkdir()
    (tmp_path / "theme.name").write_text("Matte Black\n")
    monkeypatch.setenv("READER_OMARCHY_THEME_DIR", str(d))
    assert theme_name() == "Matte Black"


def test_theme_name_never_reads_out_of_the_filesystem_root(monkeypatch):
    """Mounting the theme dir at "/omarchy-theme" must not read "/theme.name"."""
    from server import omarchy_theme
    monkeypatch.setenv("READER_OMARCHY_THEME_DIR", "/omarchy-theme")
    reads = []
    real_read = Path.read_text

    def spy(self, *a, **kw):
        reads.append(str(self))
        return real_read(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", spy)
    omarchy_theme.theme_name()
    assert "/theme.name" not in reads
    assert reads == ["/omarchy-theme/theme.name"]


def test_theme_name_uses_omarchy_layout_without_an_override(tmp_path, monkeypatch):
    """Default layout: theme.name really does sit beside the theme directory."""
    from server import omarchy_theme
    (tmp_path / "theme").mkdir()
    (tmp_path / "theme.name").write_text("Matte Black\n")
    monkeypatch.delenv("READER_OMARCHY_THEME_DIR", raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(omarchy_theme, "theme_dir", lambda: tmp_path / "theme")
    assert omarchy_theme.theme_name() == "Matte Black"


# ───── legibility floor ─────
#
# A desktop theme is designed for panels and terminals, not for hours of body
# text. A palette that looks fine on a bar can be genuinely unreadable at
# length, so one that cannot carry body text is refused whole rather than
# half-applied.

def _palette(tmp_path, monkeypatch, **colors):
    from server.omarchy_theme import read_palette
    d = tmp_path / "theme"
    d.mkdir()
    body = "\n".join(f'{k} = "{v}"' for k, v in colors.items())
    (d / "colors.toml").write_text(f'mode = "dark"\n{body}\n')
    monkeypatch.setenv("READER_OMARCHY_THEME_DIR", str(d))
    return read_palette()


def test_accepts_a_readable_palette(tmp_path, monkeypatch):
    """Matte Black, the theme actually in use: near-white on near-black."""
    p = _palette(tmp_path, monkeypatch,
                 background="#121212", foreground="#bebebe", accent="#e68e0d")
    assert p is not None


def test_rejects_a_palette_whose_body_text_is_unreadable(tmp_path, monkeypatch):
    p = _palette(tmp_path, monkeypatch,
                 background="#121212", foreground="#1a1a1a", accent="#e68e0d")
    assert p is None


def test_rejects_mid_grey_on_mid_grey(tmp_path, monkeypatch):
    p = _palette(tmp_path, monkeypatch,
                 background="#808080", foreground="#8a8a8a", accent="#ff0000")
    assert p is None


def test_accepts_a_light_theme(tmp_path, monkeypatch):
    """The reverse case must work too — a light desktop yields a light reader."""
    p = _palette(tmp_path, monkeypatch,
                 background="#fbfaf7", foreground="#2a2520", accent="#b6541a")
    assert p is not None


def test_a_low_contrast_desktop_still_reports_which_side_it_is_on(client, tmp_path, monkeypatch):
    """The palette is unusable, but Auto still needs to know the desktop is dark.

    Tying the two together would hand a low-contrast user exactly the
    white-reader-on-a-dark-desktop bug the mode reporting exists to prevent.
    """
    d = tmp_path / "theme"
    d.mkdir()
    (d / "colors.toml").write_text(
        'mode = "dark"\nbackground = "#121212"\n'
        'foreground = "#1a1a1a"\naccent = "#e68e0d"\n'
    )
    monkeypatch.setenv("READER_OMARCHY_THEME_DIR", str(d))
    body = client.get("/api/theme").json()
    assert body["available"] is False    # colours refused
    assert body["mode"] == "dark"        # …but the side is still reported


def test_mode_is_none_when_there_is_no_theme_at_all(client, monkeypatch, tmp_path):
    monkeypatch.setenv("READER_OMARCHY_THEME_DIR", str(tmp_path / "nope"))
    assert client.get("/api/theme").json()["mode"] is None


def test_hex_with_alpha_is_treated_as_unmeasurable(tmp_path, monkeypatch):
    """A translucent colour's real contrast depends on what is behind it."""
    p = _palette(tmp_path, monkeypatch,
                 background="#12121200", foreground="#1a1a1a00", accent="#e68e0d")
    assert p is not None, "unmeasurable must fail open, not be guessed at"


def test_contrast_is_symmetric_and_bounded():
    from server.omarchy_theme import contrast_ratio
    assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21, abs=0.1)
    assert contrast_ratio("#ffffff", "#000000") == pytest.approx(21, abs=0.1)
    assert contrast_ratio("#777777", "#777777") == pytest.approx(1, abs=0.01)


def test_unparseable_colours_are_not_judged_on_contrast(tmp_path, monkeypatch):
    """Named colours are valid CSS; refusing them for being unmeasurable is wrong."""
    p = _palette(tmp_path, monkeypatch,
                 background="black", foreground="white", accent="orange")
    assert p is not None


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
