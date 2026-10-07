"""Plain-text titles skip licence boilerplate (bench s3 was titled
'Provided proper attribution is provided, Google hereby grant...')."""

from vozonda_api.pipeline import _guess_text_title

ATTENTION_HEAD = """Provided proper attribution is provided, Google hereby grants permission to
reproduce the tables and figures in this paper solely for use in journalistic or
scholarly works.

Attention Is All You Need
arXiv:1706.03762v7 [cs.CL] 2 Aug 2023

Ashish Vaswani
"""


def test_skips_licence_lines_to_the_real_title():
    assert _guess_text_title(ATTENTION_HEAD) == "Attention Is All You Need"


def test_plain_notes_keep_their_first_line():
    assert _guess_text_title("My weekly notes\nSome text follows here.") == "My weekly notes"


def test_empty_text_has_no_title():
    assert _guess_text_title("   ") == ""
