"""PDFs get their own read limit: the Attention paper (~2.2 MB) was cut at the
2 MB HTML limit and failed as 'scanned without text layer' (bench s3)."""

import httpx

from vozonda_api import fetcher


def _resp(n: int) -> httpx.Response:
    return httpx.Response(200, content=b"%PDF-" + b"x" * n, headers={"content-type": "application/pdf"})


def test_pdf_limit_is_larger_than_the_html_limit():
    assert fetcher.PDF_MAX_BYTES >= 10 * fetcher.FETCH_MAX_BYTES


def test_read_bytes_bounded_honours_the_given_limit():
    big = 3_000_000
    assert len(fetcher._read_bytes_bounded(_resp(big))) == fetcher.FETCH_MAX_BYTES
    assert len(fetcher._read_bytes_bounded(_resp(big), fetcher.PDF_MAX_BYTES)) == big + 5
