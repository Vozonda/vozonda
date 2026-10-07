"""dev.html is safe to publish and deterministic (VOZONDA-DEV-PAGE-PUBLIC).

The generator reads only public files of the repo: no network, no tokens, no
private paths, and no commit count or git rev, so scripts/verify.sh does not
leave the checkout dirty after every commit.
"""

import importlib.util
import socket
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
GEN = ROOT / "scripts" / "gen-dev-page.py"
# Built from parts so the public scan of this file stays clean.
PRIVATE = ("local" + "host", "127.0." + "0.1", ":30" + "02", "/da" + "ta/", "gitea" + "_token")


def _load():
    spec = importlib.util.spec_from_file_location("gen_dev_page", GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def no_network(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("gen-dev-page opened a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def test_output_is_public_safe_and_deterministic(tmp_path, no_network):
    gen = _load()
    a, b = tmp_path / "a.html", tmp_path / "b.html"
    assert gen.main(["--out", str(a)]) == 0
    assert gen.main(["--out", str(b)]) == 0
    text = a.read_text(encoding="utf-8")
    assert a.read_bytes() == b.read_bytes()
    for private in PRIVATE + ("cipher" + "fox",):
        assert private not in text, private
    assert "-dev." not in text, "no commit-count version in the page"


def test_generator_source_has_no_private_endpoints():
    src = GEN.read_text(encoding="utf-8")
    for private in PRIVATE + ("urllib",):
        assert private not in src, private

