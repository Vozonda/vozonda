"""No silent exceptions: every swallowed error logs a line (VOZONDA-SILENT-EXCEPTIONS).

Covers:
- AST scan of vozonda_api finds zero `except Exception/BaseException/bare`
  handlers whose body is only `pass` (unless marked `# silent:`).
- Schema migration helpers skip duplicate-column errors and re-raise others.
- A failing cover/og-image step emits a WARNING and the job still completes.
"""

import ast
import logging
import sqlite3
from pathlib import Path

import pytest


def _handler_is_broad(node: ast.ExceptHandler) -> bool:
    if node.type is None:
        return True
    if isinstance(node.type, ast.Name):
        return node.type.id in ("Exception", "BaseException")
    return False


def _handler_is_silent(node: ast.ExceptHandler) -> bool:
    body = [
        n
        for n in node.body
        if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str))
    ]
    return len(body) == 1 and isinstance(body[0], ast.Pass)


def _handler_is_excused(lines: list[str], node: ast.ExceptHandler) -> bool:
    own = lines[node.lineno - 1] if 0 <= node.lineno - 1 < len(lines) else ""
    above = lines[node.lineno - 2] if node.lineno - 2 >= 0 else ""
    return "# silent:" in own or "# silent:" in above


def test_no_silent_exceptions():
    root = Path(__file__).resolve().parents[1] / "src" / "vozonda_api"
    offenders = []
    for path in sorted(root.rglob("*.py")):
        lines = path.read_text().splitlines()
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ExceptHandler)
                and _handler_is_broad(node)
                and _handler_is_silent(node)
                and not _handler_is_excused(lines, node)
            ):
                offenders.append(f"{path.relative_to(root)}:{node.lineno}")
    assert offenders == [], f"silent except-pass handlers: {offenders}"


@pytest.mark.parametrize("module_name", ["vozonda_api.watchlist", "vozonda_api.billing", "vozonda_api.nostr_auth"])
def test_add_column_skips_duplicate_and_reraises(module_name):
    import importlib

    mod = importlib.import_module(module_name)
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t (a TEXT)")
    mod._add_column(conn, "t", "b TEXT")
    # second run is a duplicate column: skipped, not raised
    mod._add_column(conn, "t", "b TEXT")
    cols = [r[1] for r in conn.execute("PRAGMA table_info(t)").fetchall()]
    assert "b" in cols
    # a different OperationalError (no such table) must propagate
    with pytest.raises(sqlite3.OperationalError):
        mod._add_column(conn, "no_such_table", "b TEXT")


def test_og_image_failure_warns_and_job_completes(monkeypatch, caplog):
    import vozonda_api.cover as cover
    from vozonda_api import pipeline
    from vozonda_api.jobs import JobStore

    store = JobStore()
    job_id = "test-og-warns"
    try:
        store.get(job_id)
    except KeyError:
        store.create(job_id, url="https://example.com/article")

    monkeypatch.setattr("vozonda_api.doctor.blocking_problem", lambda: None)

    async def fake_fetch(url):
        return "<html><body>hello</body></html>"

    async def fake_extract(url, html=None, depth="direct", **kw):
        return ("Example title", "some body text for the episode", "https://example.com/og.png")

    async def boom(url, dest):
        raise RuntimeError("og boom")

    async def fake_tail(store_, job_id_, job_, body_, title_, lang_):
        yield store_.finish(job_id_)

    monkeypatch.setattr(pipeline, "fetch_article", fake_fetch)
    monkeypatch.setattr(pipeline, "_extract", fake_extract)
    monkeypatch.setattr(cover, "download_og_image", boom)
    monkeypatch.setattr(pipeline, "_run_from_body", fake_tail)

    async def _drain():
        return [u async for u in pipeline.run_job(store, job_id)]

    import asyncio

    with caplog.at_level(logging.WARNING, logger="vozonda_api.pipeline"):
        updates = asyncio.run(_drain())

    assert updates, "job produced no updates"
    assert any(
        r.levelno >= logging.WARNING and "og-image" in r.getMessage() for r in caplog.records
    ), f"no og-image WARNING, records: {[r.getMessage() for r in caplog.records]}"
    assert store.get(job_id)["state"] == "done"
