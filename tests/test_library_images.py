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


def _make_epub_with_chapters(tmp_path, chapters):
    """Build an EPUB from a list of (title, file_name, content, extra_items) tuples.
    chapters whose title is falsy are excluded from the TOC."""
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier("id-multi")
    book.set_title("Multi-chapter Book")
    book.set_language("en")
    book.add_author("Author")

    toc_items = []
    spine_items: list = ["nav"]
    for title, file_name, content, extra_items in chapters:
        for item in extra_items:
            book.add_item(item)
        chap = epub.EpubHtml(title=title, file_name=file_name, lang="en")
        chap.content = content
        book.add_item(chap)
        spine_items.append(chap)
        if title:
            toc_items.append(chap)

    book.toc = tuple(toc_items)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine_items

    path = tmp_path / "multi.epub"
    epub.write_epub(str(path), book)
    return path


def test_untitled_illustration_page_image_is_kept(tmp_path):
    """An untitled image-only doc whose filename is not front-matter should
    survive the kept filter and contribute its image to parsed['images'] (FIX 2)."""
    from ebooklib import epub
    from server import library

    png = _png_bytes()
    img_item = epub.EpubImage(
        uid="full", file_name="images/full.png",
        media_type="image/png", content=png,
    )

    path = _make_epub_with_chapters(tmp_path, [
        (
            "Chapter One",
            "chap01.xhtml",
            "<html><body><h1>Chapter One</h1><p>Prose here.</p></body></html>",
            [],
        ),
        (
            "",  # no title — untitled illustration page
            "plate.xhtml",
            '<html><body><img src="images/full.png"/></body></html>',
            [img_item],
        ),
    ])

    book_dir = tmp_path / "book"
    book_dir.mkdir()
    parsed = library.parse_epub(path, book_dir)

    # The plate page's image must appear in the book's image list.
    assert len(parsed["images"]) == 1, f"expected 1 image, got {parsed['images']}"


def test_frontmatter_image_only_page_is_dropped(tmp_path):
    """An untitled image-only doc whose filename is front-matter (cover.xhtml)
    should NOT contribute images (FIX 2 secondary assertion)."""
    from ebooklib import epub
    from server import library

    png = _png_bytes()
    img_item = epub.EpubImage(
        uid="cov", file_name="images/cover.png",
        media_type="image/png", content=png,
    )

    path = _make_epub_with_chapters(tmp_path, [
        (
            "Chapter One",
            "chap01.xhtml",
            "<html><body><h1>Chapter One</h1><p>Prose.</p></body></html>",
            [],
        ),
        (
            "",  # no title, but filename is front-matter
            "cover.xhtml",
            '<html><body><img src="images/cover.png"/></body></html>',
            [img_item],
        ),
    ])

    book_dir = tmp_path / "book2"
    book_dir.mkdir()
    parsed = library.parse_epub(path, book_dir)

    # cover.xhtml is front-matter — its image must NOT appear.
    assert parsed["images"] == [], f"unexpected images: {parsed['images']}"


def test_same_image_src_deduplicated_on_disk(tmp_path):
    """Two <img> refs to the same src produce two image entries in parsed['images']
    but only one file on disk under images/ (FIX 4)."""
    from ebooklib import epub
    from server import library

    png = _png_bytes()
    img_item = epub.EpubImage(
        uid="shared", file_name="images/shared.png",
        media_type="image/png", content=png,
    )

    chap_content = (
        "<html><body>"
        "<p>Para one.</p>"
        '<img src="images/shared.png" alt="first"/>'
        "<p>Para two.</p>"
        '<img src="images/shared.png" alt="second"/>'
        "<p>Para three.</p>"
        "</body></html>"
    )

    path = _make_epub_with_chapters(tmp_path, [
        ("Chapter", "chap.xhtml", chap_content, [img_item]),
    ])

    book_dir = tmp_path / "dedupbook"
    book_dir.mkdir()
    parsed = library.parse_epub(path, book_dir)

    assert len(parsed["images"]) == 2, f"expected 2 image entries, got {parsed['images']}"
    assert len(list((book_dir / "images").iterdir())) == 1, "expected exactly 1 file on disk"


def test_disallowed_image_extension_is_skipped(tmp_path):
    """An <img> pointing at an image with a disallowed extension (bmp) is ignored
    and no file is written (FIX 5)."""
    from ebooklib import epub
    from server import library

    bmp_item = epub.EpubImage(
        uid="bmpimg", file_name="images/art.bmp",
        media_type="image/bmp", content=b"BM\x00\x00",
    )

    chap_content = (
        "<html><body>"
        "<p>Some text.</p>"
        '<img src="images/art.bmp" alt="bmp art"/>'
        "</body></html>"
    )

    path = _make_epub_with_chapters(tmp_path, [
        ("Chapter", "chap.xhtml", chap_content, [bmp_item]),
    ])

    book_dir = tmp_path / "bmpbook"
    book_dir.mkdir()
    parsed = library.parse_epub(path, book_dir)

    assert parsed["images"] == [], f"unexpected images: {parsed['images']}"
    assert not (book_dir / "images").exists(), "no images dir should be created"


def test_parse_pdf_extracts_inline_image(tmp_path):
    from server import library

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hello world from page one.")
    png = _png_bytes()
    page.insert_image(pymupdf.Rect(72, 120, 172, 220), stream=png)
    src = tmp_path / "doc.pdf"
    doc.save(str(src))

    book_dir = tmp_path / "pdfbook"
    book_dir.mkdir()
    parsed = library.parse_pdf(src, book_dir)

    paras = [p["text"] for ch in parsed["chapters"] for p in ch["paragraphs"]]
    assert any("Hello world" in t for t in paras)

    assert len(parsed["images"]) >= 1
    img = parsed["images"][0]
    fname = img["src"].rsplit("/", 1)[-1]
    assert (book_dir / "images" / fname).is_file()
    # Anchored after the text that precedes it on the page (idx >= 0).
    assert img["after_idx"] >= 0
