import json
from pathlib import Path

import pytest

CATALOG = Path(__file__).resolve().parent.parent / "data" / "google-fonts-list.json"


def test_catalog_file_shape_and_known_families():
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    assert isinstance(data, list) and len(data) > 500
    assert all(set(e) == {"family", "category"} for e in data[:50])
    families = {e["family"] for e in data}
    assert {"Lora", "Bitter", "Atkinson Hyperlegible"} <= families


_FAKE_CSS = """
/* latin */
@font-face {
  font-family: 'Lora';
  font-style: normal;
  src: url(https://fonts.gstatic.com/s/lora/v1/lora-regular.woff2) format('woff2');
}
/* latin */
@font-face {
  font-family: 'Lora';
  font-style: italic;
  src: url(https://fonts.gstatic.com/s/lora/v1/lora-italic.woff2) format('woff2');
}
"""

_EVIL_CSS = """
/* latin */
@font-face {
  font-family: 'Evil';
  font-style: normal;
  src: url(https://evil.example.com/x.woff2) format('woff2');
}
"""


def _setup(tmp_path, monkeypatch):
    monkeypatch.setenv("READER_DATA_DIR", str(tmp_path))
    from server.config import ensure_dirs
    ensure_dirs()


def test_slugify():
    from server import fonts
    assert fonts.slugify("Atkinson Hyperlegible") == "atkinson-hyperlegible"
    assert fonts.slugify("EB Garamond") == "eb-garamond"
    assert fonts.slugify("Roboto  Slab!") == "roboto-slab"


def test_catalog_includes_bundled_and_families(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    from server import fonts
    cat = fonts.catalog()
    keys = {b["key"] for b in cat["bundled"]}
    assert {"sans", "serif", "slab", "hyperlegible", "dyslexic"} <= keys
    assert any(f["family"] == "Lora" for f in cat["families"])


def test_ensure_rejects_unknown_family_without_network(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    from server import fonts
    def _boom(*a, **k):
        raise AssertionError("network must not be called for a rejected family")
    monkeypatch.setattr(fonts.httpx, "get", _boom)
    with pytest.raises(ValueError):
        fonts.ensure("Definitely Not A Real Font 9000")


def test_ensure_downloads_caches_and_is_idempotent(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    from server import fonts

    calls = {"css": 0, "woff": 0}

    class _Resp:
        def __init__(self, text="", content=b""):
            self.text, self.content = text, content
        def raise_for_status(self):
            pass

    def _get(url, *a, **k):
        if "css2" in url:
            calls["css"] += 1
            return _Resp(text=_FAKE_CSS)
        calls["woff"] += 1
        return _Resp(content=b"WOFF2DATA")

    monkeypatch.setattr(fonts.httpx, "get", _get)

    out = fonts.ensure("Lora")
    assert out["family"] == "Lora" and out["slug"] == "lora"
    styles = {f["style"] for f in out["faces"]}
    assert styles == {"normal", "italic"}
    p = fonts.font_path("lora", "0.woff2")
    assert p is not None and p.read_bytes() == b"WOFF2DATA"

    calls_before = dict(calls)
    out2 = fonts.ensure("Lora")
    assert out2["cached"] is True
    assert calls == calls_before  # no re-fetch


def test_ensure_rejects_non_gstatic_host(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    from server import fonts

    class _Resp:
        text = _EVIL_CSS
        def raise_for_status(self):
            pass

    monkeypatch.setattr(fonts.httpx, "get", lambda *a, **k: _Resp())
    # 'Evil' isn't in the catalog, so it's rejected at the allowlist already;
    # force past the allowlist to prove the host check also rejects it.
    monkeypatch.setattr(fonts, "is_allowed", lambda fam: True)
    with pytest.raises(RuntimeError):
        fonts.ensure("Evil")


def test_font_path_rejects_traversal(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    from server import fonts
    assert fonts.font_path("lora", "../../secret") is None
    assert fonts.font_path("..", "0.woff2") is None


WEB_FONTS = Path(__file__).resolve().parent.parent / "web" / "fonts"

def test_bundled_font_files_present():
    expected = [
        "Lora-Regular.woff2", "Lora-Italic.woff2",
        "Bitter-Regular.woff2", "Bitter-Italic.woff2",
        "AtkinsonHyperlegible-Regular.woff2", "AtkinsonHyperlegible-Italic.woff2",
        "OpenDyslexic-Regular.woff2",
    ]
    for name in expected:
        p = WEB_FONTS / name
        assert p.is_file() and p.stat().st_size > 1000, f"missing/empty: {name}"


def test_delete_cached_removes_dir(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    from server import fonts
    d = fonts.fonts_cache_dir() / "merriweather"
    d.mkdir(parents=True)
    (d / "0.woff2").write_bytes(b"x")
    assert fonts.delete_cached("merriweather") is True
    assert not d.exists()


def test_delete_cached_idempotent_on_missing(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    from server import fonts
    assert fonts.delete_cached("never-downloaded") is False


def test_delete_cached_rejects_traversal_and_bad_slugs(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    from server import fonts
    # A sentinel OUTSIDE the fonts cache dir must survive every attempt.
    outside = fonts.fonts_cache_dir().parent.parent / "outside_secret"
    outside.mkdir(parents=True)
    (outside / "keep.txt").write_text("keep")
    for bad in ["..", "../..", "../../outside_secret", "a/b",
                "merriweather/../..", "/etc", "Merriweather", "foo.bar"]:
        assert fonts.delete_cached(bad) is False, bad
    assert (outside / "keep.txt").exists()
