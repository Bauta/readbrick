"""EPUB image extraction → images/ files + book.json sidecar."""
from __future__ import annotations

import pymupdf  # used only to mint a valid PNG for the fixture


def _png_bytes() -> bytes:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 8))
    pix.clear_with(128)
    return pix.tobytes("png")


def _make_epub_with_image(tmp_path, *, src_attr="images/pic.png"):
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier("id-img")
    book.set_title("Picture Book")
    book.set_language("en")
    book.add_author("Author")

    png = _png_bytes()
    book.add_item(epub.EpubImage(
        uid="pic", file_name="images/pic.png",
        media_type="image/png", content=png,
    ))

    chap = epub.EpubHtml(title="One", file_name="chap.xhtml", lang="en")
    chap.content = (
        "<html><body>"
        "<p>Before the picture.</p>"
        f'<img src="{src_attr}" alt="a picture"/>'
        "<p>After the picture.</p>"
        "</body></html>"
    )
    book.add_item(chap)
    book.toc = (chap,)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chap]

    path = tmp_path / "pic.epub"
    epub.write_epub(str(path), book)
    return path, png


def test_parse_epub_extracts_image_and_anchors_it(tmp_path):
    from server import library

    src, png = _make_epub_with_image(tmp_path)
    book_dir = tmp_path / "book"
    book_dir.mkdir()

    parsed = library.parse_epub(src, book_dir)
    imgs = parsed["images"]
    assert len(imgs) == 1
    assert imgs[0]["alt"] == "a picture"
    # paragraphs: "Before…"(0), "After…"(1); image sits after idx 0
    assert imgs[0]["after_idx"] == 0
    assert imgs[0]["src"].startswith(f"/api/books/{book_dir.name}/images/")

    fname = imgs[0]["src"].rsplit("/", 1)[-1]
    assert (book_dir / "images" / fname).read_bytes() == png


def test_parse_epub_missing_image_resource_is_skipped(tmp_path):
    from server import library

    src, _png = _make_epub_with_image(tmp_path, src_attr="images/does-not-exist.png")
    book_dir = tmp_path / "book"
    book_dir.mkdir()

    parsed = library.parse_epub(src, book_dir)
    assert parsed["images"] == []
    assert not (book_dir / "images").exists()
