"""Custom user styles: users pick a rhythm type and name their own roles.

Table `custom_styles` lives in the same SQLite DB as jobs (VOZONDA_DB) and
follows the watchlist migration pattern. Each row is a user style whose id
looks like ``custom_<slug>`` with slug ``[a-z0-9_]{2,30}``. Built-in style ids
can never be taken or overridden. The prompt template and rhythm profile of a
custom style are built at runtime from its roles plus its rhythm type
(see style_registry for the template, rhythm for the profile).
"""

from __future__ import annotations

import logging
import re
import sqlite3
import time

from .jobs import _conn  # reuse DB_PATH and connection helper

logger = logging.getLogger(__name__)

ID_RE = re.compile(r"^custom_[a-z0-9_]{2,30}$")

NAME_MAX = 40
DOC_MAX = 120
ROLE_MAX = 400
TONE_MAX = 300

CUSTOM_STYLES_SCHEMA = """
CREATE TABLE IF NOT EXISTS custom_styles (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  doc TEXT NOT NULL DEFAULT '',
  role_a TEXT NOT NULL,
  role_b TEXT NOT NULL,
  tone TEXT NOT NULL DEFAULT '',
  rhythm_type TEXT NOT NULL,
  created_at REAL NOT NULL
);
"""


def init_custom_styles_db() -> None:
    with _conn() as c:
        c.executescript(CUSTOM_STYLES_SCHEMA)


def _add_column(c: sqlite3.Connection, table: str, column_ddl: str) -> None:
    """ALTER TABLE ADD COLUMN that skips existing columns (watchlist pattern)."""
    try:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column_ddl}")
    except sqlite3.OperationalError as exc:
        if "duplicate column" in str(exc).lower():
            return
        logger.exception("custom styles migration failed adding %s to %s", column_ddl, table)
        raise


def validate_style_id(style_id: str) -> str:
    """Validate a custom style id, or raise ValueError with a clear message."""
    sid = (style_id or "").strip()
    if not sid:
        raise ValueError("id is required and must look like custom_<slug>")
    try:
        from .style_registry import STYLE_IDS
    except Exception:
        STYLE_IDS = []
    if sid in STYLE_IDS:
        raise ValueError(f"built-in style '{sid}' cannot be taken or overridden")
    if not ID_RE.match(sid):
        raise ValueError(
            f"invalid style id '{sid}': must look like custom_<slug> "
            "with slug [a-z0-9_]{2,30}"
        )
    return sid


def validate_rhythm_type(rhythm_type: str) -> str:
    from .rhythm import RHYTHM_TYPES

    rt = (rhythm_type or "").strip()
    if rt not in RHYTHM_TYPES:
        raise ValueError(
            f"unknown rhythm_type '{rhythm_type}': must be one of {sorted(RHYTHM_TYPES)}"
        )
    return rt


def validate_custom_fields(
    name: str | None,
    doc: str | None,
    role_a: str | None,
    role_b: str | None,
    tone: str | None,
) -> tuple[str, str, str, str, str]:
    """Validate text fields, or raise ValueError with a clear message."""
    n = (name or "").strip()
    if not n:
        raise ValueError("name is required")
    if len(n) > NAME_MAX:
        raise ValueError(f"name must be at most {NAME_MAX} characters")
    d = (doc or "").strip()
    if len(d) > DOC_MAX:
        raise ValueError(f"doc must be at most {DOC_MAX} characters")
    ra = (role_a or "").strip()
    if not ra:
        raise ValueError("role_a is required")
    if len(ra) > ROLE_MAX:
        raise ValueError(f"role_a must be at most {ROLE_MAX} characters")
    rb = (role_b or "").strip()
    if not rb:
        raise ValueError("role_b is required")
    if len(rb) > ROLE_MAX:
        raise ValueError(f"role_b must be at most {ROLE_MAX} characters")
    t = (tone or "").strip()
    if len(t) > TONE_MAX:
        raise ValueError(f"tone must be at most {TONE_MAX} characters")
    return n, d, ra, rb, t


def _row_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "doc": row["doc"] or "",
        "role_a": row["role_a"],
        "role_b": row["role_b"],
        "tone": row["tone"] or "",
        "rhythm_type": row["rhythm_type"],
        "created_at": float(row["created_at"]),
    }


def list_custom_styles() -> list[dict]:
    init_custom_styles_db()
    with _conn() as c:
        rows = c.execute("SELECT * FROM custom_styles ORDER BY created_at ASC").fetchall()
    return [_row_to_dict(r) for r in rows]


def get_custom_style(style_id: str) -> dict:
    init_custom_styles_db()
    with _conn() as c:
        row = c.execute("SELECT * FROM custom_styles WHERE id = ?", (style_id,)).fetchone()
    if row is None:
        raise KeyError(style_id)
    return _row_to_dict(row)


def create_custom_style(
    style_id: str,
    name: str,
    doc: str = "",
    role_a: str = "",
    role_b: str = "",
    tone: str = "",
    rhythm_type: str = "",
) -> dict:
    init_custom_styles_db()
    sid = validate_style_id(style_id)
    rt = validate_rhythm_type(rhythm_type)
    n, d, ra, rb, t = validate_custom_fields(name, doc, role_a, role_b, tone)
    try:
        with _conn() as c:
            c.execute(
                "INSERT INTO custom_styles (id, name, doc, role_a, role_b, tone, rhythm_type, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (sid, n, d, ra, rb, t, rt, time.time()),
            )
    except sqlite3.IntegrityError as exc:
        raise ValueError(f"style id '{sid}' is already taken") from exc
    return get_custom_style(sid)


def update_custom_style(
    style_id: str,
    name: str | None = None,
    doc: str | None = None,
    role_a: str | None = None,
    role_b: str | None = None,
    tone: str | None = None,
    rhythm_type: str | None = None,
) -> dict:
    init_custom_styles_db()
    current = get_custom_style(style_id)
    new_name = current["name"] if name is None else name
    new_doc = current["doc"] if doc is None else doc
    new_ra = current["role_a"] if role_a is None else role_a
    new_rb = current["role_b"] if role_b is None else role_b
    new_tone = current["tone"] if tone is None else tone
    new_rt = current["rhythm_type"] if rhythm_type is None else validate_rhythm_type(rhythm_type)
    n, d, ra, rb, t = validate_custom_fields(new_name, new_doc, new_ra, new_rb, new_tone)
    with _conn() as c:
        cur = c.execute(
            "UPDATE custom_styles SET name = ?, doc = ?, role_a = ?, role_b = ?, tone = ?, rhythm_type = ?"
            " WHERE id = ?",
            (n, d, ra, rb, t, new_rt, style_id),
        )
        if cur.rowcount == 0:
            raise KeyError(style_id)
    return get_custom_style(style_id)


def delete_custom_style(style_id: str) -> None:
    init_custom_styles_db()
    with _conn() as c:
        cur = c.execute("DELETE FROM custom_styles WHERE id = ?", (style_id,))
        if cur.rowcount == 0:
            raise KeyError(style_id)
