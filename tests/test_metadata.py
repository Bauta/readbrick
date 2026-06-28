"""Metadata enrichment cascade tests."""
from unittest.mock import patch, MagicMock

import pytest

from server.metadata import enrich, clean_isbn


@pytest.fixture(autouse=True)
def _google_books_key(monkeypatch):
    """Most tests assume Google Books is callable. After Google removed
    anonymous quota in 2026, _try_google_books skips when GOOGLE_BOOKS_API_KEY
    is unset. Set a fake key so the cascade exercises the GB path. Tests
    that want to verify the no-key-skips-GB behavior unset it manually."""
    monkeypatch.setenv("GOOGLE_BOOKS_API_KEY", "test-key")


def _mock_ol_response(payload):
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = payload
    return r


def test_openlibrary_hit_returns_ol_fields_without_calling_google_books():
    ol_payload = {
        "ISBN:9788234567890": {
            "title": "Gutten og fjellet",
            "publish_date": "2018",
            "subjects": [{"name": "Fiction"}, {"name": "Norway"}],
            "notes": "A boy and his mountain.",
            "cover": {"medium": "https://covers.openlibrary.org/b/id/123-M.jpg"},
        }
    }
    with patch("server.metadata.httpx.get") as mock_get:
        mock_get.return_value = _mock_ol_response(ol_payload)
        result = enrich("Gutten og fjellet", "Aslaug Lien", "nb", "9788234567890")
    assert result is not None
    assert result["metadata_source"] == "openlibrary"
    assert result["published_year"] == 2018
    assert "fiction" in (result["genre"] or "")
    assert result["description"] == "A boy and his mountain."
    assert result["cover_url"] == "https://covers.openlibrary.org/b/id/123-M.jpg"
    # Should not have called Google Books
    assert mock_get.call_count == 1


def test_openlibrary_miss_falls_through_to_google_books():
    gb_payload = {
        "items": [{
            "volumeInfo": {
                "title": "Some Book",
                "publishedDate": "2020-03-01",
                "categories": ["Mystery"],
                "description": "A mystery novel.",
                "imageLinks": {"thumbnail": "https://books.google/cover.jpg"},
                "industryIdentifiers": [{"type": "ISBN_13", "identifier": "9781234567890"}],
            }
        }]
    }
    responses = iter([
        _mock_ol_response({}),                # OpenLibrary returns empty dict (no hits)
        _mock_ol_response(gb_payload),        # Google Books returns a hit
    ])
    with patch("server.metadata.httpx.get") as mock_get:
        mock_get.side_effect = lambda *a, **kw: next(responses)
        result = enrich("Some Book", "Some Author", "en", None)
    assert result is not None
    assert result["metadata_source"] == "google_books"
    assert result["published_year"] == 2020
    assert result["description"] == "A mystery novel."
    assert result["isbn"] == "9781234567890"


def test_both_miss_returns_none():
    responses = iter([_mock_ol_response({}), _mock_ol_response({"items": []})])
    with patch("server.metadata.httpx.get") as mock_get:
        mock_get.side_effect = lambda *a, **kw: next(responses)
        result = enrich("Unknown title", "Unknown author", None, None)
    assert result is None


def test_openlibrary_timeout_falls_through_to_google_books():
    import httpx
    gb_payload = {
        "items": [{
            "volumeInfo": {
                "title": "X", "publishedDate": "1999",
                "description": "Found by GB after OL timeout",
            }
        }]
    }
    call = [0]
    def side(*a, **kw):
        call[0] += 1
        if call[0] == 1:
            raise httpx.TimeoutException("ol slow")
        return _mock_ol_response(gb_payload)
    with patch("server.metadata.httpx.get", side_effect=side):
        result = enrich("X", "Y", None, None)
    assert result is not None
    assert result["metadata_source"] == "google_books"


def test_google_books_skipped_without_api_key(monkeypatch):
    """Without GOOGLE_BOOKS_API_KEY, _try_google_books returns None
    immediately — no HTTP request is made (it would 429). Cascade then
    falls back to None overall when OpenLibrary also misses."""
    monkeypatch.delenv("GOOGLE_BOOKS_API_KEY", raising=False)
    responses = iter([_mock_ol_response({})])
    with patch("server.metadata.httpx.get") as mock_get:
        mock_get.side_effect = lambda *a, **kw: next(responses)
        result = enrich("Some Book", "Some Author", "en", "9781234567890")
    assert result is None
    # OpenLibrary called once; Google Books NOT called.
    assert mock_get.call_count == 1


def test_openlibrary_search_fetches_works_description():
    """A title+author search hit has no description in the search record — we
    fetch the /works record for it (handling the {value} shape)."""
    search = _mock_ol_response({"docs": [{
        "key": "/works/OL1W", "title": "T", "first_publish_year": 2021,
        "cover_i": 555, "subject": ["Fiction"],
    }]})
    works = _mock_ol_response({"description": {"value": "From the works record."}})
    responses = iter([search, works])
    with patch("server.metadata.httpx.get") as mock_get:
        mock_get.side_effect = lambda *a, **kw: next(responses)
        result = enrich("T", "A", "en", None)  # no ISBN -> search path
    assert result["metadata_source"] == "openlibrary"
    assert result["description"] == "From the works record."
    assert result["cover_url"].endswith("555-M.jpg")
    assert mock_get.call_count == 2  # search + /works (Google Books not needed)


def test_openlibrary_cover_no_description_merges_google_books():
    """Jocko case: OpenLibrary has a cover but no description anywhere; the
    Google Books description is merged onto the OpenLibrary result (cover kept)."""
    search = _mock_ol_response({"docs": [{
        "key": "/works/OL2W", "title": "Leadership", "first_publish_year": 2020,
        "cover_i": 9380709,
    }]})
    works = _mock_ol_response({"title": "Leadership"})  # no description field
    gb = _mock_ol_response({"items": [{"volumeInfo": {
        "description": "Field manual for leaders.", "publishedDate": "2020",
    }}]})
    responses = iter([search, works, gb])
    with patch("server.metadata.httpx.get") as mock_get:
        mock_get.side_effect = lambda *a, **kw: next(responses)
        result = enrich("Leadership Strategy and Tactics", "Jocko Willink", "en", None)
    assert result["metadata_source"] == "openlibrary"          # OL stays the source
    assert result["cover_url"].endswith("9380709-M.jpg")        # OL cover kept
    assert result["description"] == "Field manual for leaders."  # GB description merged
    assert mock_get.call_count == 3  # search + /works + Google Books


def test_clean_isbn_strips_hyphens_and_validates_length():
    assert clean_isbn("978-82-3456-789-0") == "9788234567890"
    assert clean_isbn("0-306-40615-2") == "0306406152"
    assert clean_isbn("not-an-isbn") is None
    assert clean_isbn("123") is None  # too short
    assert clean_isbn(None) is None
