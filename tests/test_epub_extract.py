"""Paragraph extraction from EPUB document HTML.

Specifically: don't insert phantom spaces around inline elements like
<em>, <i>, <strong> that wrap parts of a word or sit next to punctuation.
That bug made the rendered reader text look like "Potters ." (space
before period) when the source markup was "<em>Potters</em>.".
"""
from __future__ import annotations

from server.library import _extract_paragraphs_from_html


def test_no_phantom_space_before_punctuation_after_inline_tag():
    html = (
        "<html><body>"
        "<p>They never thought they could survive it if anyone found out about "
        "<em>the Potters</em>.</p>"
        "</body></html>"
    )
    _title, paras, _imgs = _extract_paragraphs_from_html(html)
    assert len(paras) == 1
    # Critical: the period sits flush against "Potters", not " ."
    assert paras[0]["text"].endswith("Potters.")
    assert " ." not in paras[0]["text"]


def test_no_phantom_space_before_comma_after_inline_tag():
    html = "<p>found out that it <em>worked</em>, but not now.</p>"
    _t, paras, _imgs = _extract_paragraphs_from_html(html)
    assert paras[0]["text"] == "found out that it worked, but not now."


def test_preserves_legitimate_whitespace_between_words():
    html = "<p>found out that it <em>worked</em> just fine.</p>"
    _t, paras, _imgs = _extract_paragraphs_from_html(html)
    # Space between "worked" and "just" was a real space in source markup —
    # must survive.
    assert paras[0]["text"] == "found out that it worked just fine."


def test_preserves_guillemets_and_ellipsis():
    html = "<p>«That son of theirs … he must be about Dudley's age, no?»</p>"
    _t, paras, _imgs = _extract_paragraphs_from_html(html)
    assert paras[0]["text"] == "«That son of theirs … he must be about Dudley's age, no?»"


def test_quote_marks_around_inline_tag_keep_their_position():
    html = "<p>She said: «<em>I wonder</em>», then stopped.</p>"
    _t, paras, _imgs = _extract_paragraphs_from_html(html)
    assert paras[0]["text"] == "She said: «I wonder», then stopped."


def test_collapses_multiple_whitespace_chars():
    html = "<p>before\n\t  after</p>"
    _t, paras, _imgs = _extract_paragraphs_from_html(html)
    assert paras[0]["text"] == "before after"


def test_empty_paragraph_is_skipped():
    html = "<p></p><p>  </p><p>real content</p>"
    _t, paras, _imgs = _extract_paragraphs_from_html(html)
    assert len(paras) == 1
    assert paras[0]["text"] == "real content"


def test_chapter_title_extracted_from_first_heading():
    html = "<h1>The Beginning</h1><p>Introduction.</p>"
    title, paras, _imgs = _extract_paragraphs_from_html(html)
    assert title == "The Beginning"
    # Heading is ALSO a paragraph — current behaviour, preserved
    assert paras[0]["text"] == "The Beginning"
    assert paras[1]["text"] == "Introduction."


def test_blockquote_is_extracted_as_paragraph():
    html = "<p>before</p><blockquote>a quote with <em>emphasis</em>.</blockquote><p>after</p>"
    _t, paras, _imgs = _extract_paragraphs_from_html(html)
    assert [p["text"] for p in paras] == ["before", "a quote with emphasis.", "after"]


def test_image_after_paragraph_is_recorded():
    html = '<p>Intro</p><img src="pix/b.jpg" alt="a barn"/><p>After</p>'
    _t, paras, imgs = _extract_paragraphs_from_html(html)
    assert [p["text"] for p in paras] == ["Intro", "After"]
    assert len(imgs) == 1
    assert imgs[0] == {"src_base": "b.jpg", "alt": "a barn", "after_idx": 0}


def test_image_before_first_paragraph_anchors_at_minus_one():
    html = '<figure><img src="cover/a.png" alt="A"/><p>Caption</p></figure>'
    _t, paras, imgs = _extract_paragraphs_from_html(html)
    assert [p["text"] for p in paras] == ["Caption"]
    assert imgs[0]["after_idx"] == -1
    assert imgs[0]["src_base"] == "a.png"


def test_img_without_src_is_skipped():
    html = "<p>X</p><img alt='broken'/><p>Y</p>"
    _t, paras, imgs = _extract_paragraphs_from_html(html)
    assert imgs == []


def test_svg_image_href_is_recorded():
    html = '<p>X</p><svg><image xlink:href="art/c.svg"/></svg>'
    _t, paras, imgs = _extract_paragraphs_from_html(html)
    assert len(imgs) == 1
    assert imgs[0]["src_base"] == "c.svg"


def test_same_image_referenced_twice_yields_two_refs():
    html = '<img src="d.png"/><p>mid</p><img src="d.png"/>'
    _t, _paras, imgs = _extract_paragraphs_from_html(html)
    assert [i["src_base"] for i in imgs] == ["d.png", "d.png"]
    assert [i["after_idx"] for i in imgs] == [-1, 0]
