import re

from vozonda_api.main import _readable_id


def test_format_is_slug_plus_short_hex() -> None:
    rid = _readable_id("https://example.com/blog/my-post")
    assert re.fullmatch(r"[a-z0-9-]+-[0-9a-f]{4}", rid)


def test_slugifies_path_tail() -> None:
    rid = _readable_id("https://Example.com/My_Article?q=1")
    assert rid.rsplit("-", 1)[0] == "my-article"


def test_empty_path_falls_back_to_episode() -> None:
    rid = _readable_id("https://example.com/")
    assert rid.startswith("episode-")


def test_long_tail_truncated_to_40_chars() -> None:
    rid = _readable_id("https://example.com/" + "a" * 80)
    assert len(rid.rsplit("-", 1)[0]) == 40


def test_ids_differ_for_same_url() -> None:
    url = "https://example.com/same"
    assert _readable_id(url) != _readable_id(url)
