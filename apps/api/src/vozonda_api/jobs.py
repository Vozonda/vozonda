import asyncio
import json
import logging
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# listener focus: one or two sentences, kept short so it cannot swamp the prompt
FOCUS_MAX = 300

from .env import env
from .envfile import load_env_file

load_env_file()

DB_PATH = Path(env("DB") or Path(__file__).resolve().parents[3] / "data" / "jobs.db")


def _is_url_rendered(url: str) -> bool:
    """Check if a URL has been rendered as a job (direct or via digest_sources)."""
    with _conn() as c:
        # Check direct job URL
        row = c.execute("SELECT id FROM jobs WHERE url = ?", (url,)).fetchone()
        if row:
            return True
        # Check if URL is in any job's digest_sources via json_each TVF
        row = c.execute(
            "SELECT jobs.id FROM jobs, json_each(digest_sources) WHERE json_each.value = ?",
            (url,),
        ).fetchone()
        return bool(row)

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  url TEXT NOT NULL,
  title TEXT DEFAULT '',
  state TEXT NOT NULL DEFAULT 'queued',
  current_stage TEXT,
  stages TEXT NOT NULL DEFAULT '[]',
  script TEXT,
  error TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
"""


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as c:
        c.executescript(SCHEMA)
        for col, ddl in [
            ("style", "TEXT DEFAULT 'default'"),
            ("format", "TEXT DEFAULT 'dialog'"),
            ("tone", "TEXT DEFAULT 'neutral'"),
            ("language", "TEXT DEFAULT 'auto'"),
            ("started_at", "REAL"),
            ("finished_at", "REAL"),
            ("duration_ms", "INTEGER"),
            ("description", "TEXT DEFAULT ''"),
            ("watchlist_id", "TEXT"),
            ("hosts", "INTEGER DEFAULT 2"),
            ("explicit", "INTEGER DEFAULT 0"),
            ("voice_profile", "TEXT"),
            # digest (#122): flag + source list + chapter metadata
            ("digest", "INTEGER DEFAULT 0"),
            ("digest_sources", "TEXT"),
            ("chapters", "TEXT"),
            ("research_mode", "INTEGER DEFAULT 0"),
            ("research_sources", "TEXT"),
            ("og_image", "TEXT"),
            # length of the finished audio; duration_ms is the render time (2026-10-02:
            # the library showed render time as episode length)
            ("audio_seconds", "REAL"),
            # Billing support (DUE-067)
            ("access_token_id", "TEXT"),
            ("user_id", "TEXT"),
            ("provider", "TEXT DEFAULT 'qwen'"),
            ("charge_id", "TEXT"),
            # Podcast show identity (#232)
            ("show_name", "TEXT DEFAULT ''"),
            ("show_author", "TEXT DEFAULT ''"),
            ("show_category", "TEXT DEFAULT ''"),
            # VOZONDA-LEN-1: precise episode length target in minutes
            ("target_minutes", "REAL"),
            # UX phase 2: what the listener wants the hosts to dig into
            ("focus", "TEXT DEFAULT ''"),
            # UX phase 2: pause after the script so the listener can edit it
            ("review_script", "INTEGER DEFAULT 0"),
            ("script_approved", "INTEGER DEFAULT 0"),
            # 2+ sources as ONE conversation (compose default) instead of a digest
            ("combine", "INTEGER DEFAULT 0"),
            # VOZONDA-AGENT-3: public base URL for absolute webhook audio_url
            ("public_base", "TEXT"),
            # Insights - Hallucination-Guard & Source-Grounded Blinkist-grade (DUE-077 / #262)
            ("executive_summary", "TEXT DEFAULT ''"),
            ("executive_quote", "TEXT DEFAULT ''"),
            ("key_takeaways", "TEXT"),
            ("factuality_score", "REAL"),
            # VOZONDA-AGENT-2: callback webhook and delivery tracking
            ("callback_url", "TEXT"),
            ("webhook_fired", "INTEGER DEFAULT 0"),
            # VOZONDA-NOSTR-1: reference to the show this job belongs to
            ("show_slug", "TEXT DEFAULT ''"),
            # VOZONDA-NOSTR: show slug for Nostr publishing linkage
            ("show_slug", "TEXT DEFAULT ''"),
            # VOZONDA-TRAY-PRIVACY: uploads stay on the local model unless allowed to cloud
            ("local_only", "INTEGER DEFAULT 0"),
        ]:
            try:
                c.execute(f"ALTER TABLE jobs ADD COLUMN {col} {ddl}")
            except sqlite3.OperationalError:
                pass
        # watchlist lives in same DB; ensure its table exists
        try:
            c.executescript(
                "CREATE TABLE IF NOT EXISTS watchlist (id TEXT PRIMARY KEY, feed_url TEXT NOT NULL UNIQUE, style TEXT NOT NULL DEFAULT 'balanced', format TEXT NOT NULL DEFAULT 'dialog', language TEXT NOT NULL DEFAULT 'auto', hosts INTEGER NOT NULL DEFAULT 2, created_at REAL NOT NULL, last_checked REAL, enabled INTEGER NOT NULL DEFAULT 1);"
            )
            try:
                c.execute("ALTER TABLE watchlist ADD COLUMN explicit INTEGER NOT NULL DEFAULT 0")
            except sqlite3.OperationalError:
                pass
        except sqlite3.OperationalError:
            pass
        # Idempotency keys live in same DB (VOZONDA-AGENT-2)
        try:
            c.executescript(
                "CREATE TABLE IF NOT EXISTS idempotency_keys ("
                "  key TEXT PRIMARY KEY,"
                "  job_id TEXT NOT NULL,"
                "  created_at REAL NOT NULL"
                ");"
            )
        except sqlite3.OperationalError:
            pass


def _row_to_job(row: sqlite3.Row) -> dict[str, Any]:
    row = {k: v for k, v in zip(row.keys(), tuple(row))}
    # executive_summary / key_takeaways are nullable text/json columns
    try:
        kt_raw = row.get("key_takeaways") if "key_takeaways" in row.keys() else None  # noqa: SIM118
        kt = json.loads(kt_raw) if kt_raw else None
    except Exception:
        kt = None
    return {
        "id": row["id"],
        "url": row["url"],
        "title": row["title"],
        "state": row["state"],
        "current_stage": row["current_stage"],
        "stages": json.loads(row["stages"]),
        "script": json.loads(row["script"]) if row["script"] else None,
        "error": row["error"],
        "style": row.get("style", "default"),
        "format": row.get("format", "dialog"),
        "tone": row.get("tone", "neutral"),
        "language": row.get("language", "auto"),
        "created_at": row.get("created_at"),
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
        "duration_ms": row.get("duration_ms"),
        "description": row.get("description") or "",
        "watchlist_id": row.get("watchlist_id"),
        "hosts": row.get("hosts", 2) if row.get("hosts") is not None else 2,
        "explicit": bool(row["explicit"]) if "explicit" in row else False,
        "voice_profile": json.loads(row["voice_profile"]) if row.get("voice_profile") else None,
        # digest (#122)
        "digest": bool(row.get("digest", 0)),
        "digest_sources": json.loads(row["digest_sources"]) if row.get("digest_sources") else None,
        "chapters": json.loads(row["chapters"]) if row.get("chapters") else None,
        "research_mode": bool(row.get("research_mode", 0)),
        "research_sources": json.loads(row["research_sources"]) if row.get("research_sources") else None,
        "og_image": row.get("og_image"),
        "audio_seconds": row.get("audio_seconds"),
        # Billing support (DUE-067)
        "access_token_id": row.get("access_token_id"),
        "user_id": row.get("user_id"),
        "provider": row.get("provider", "qwen"),
        "charge_id": row.get("charge_id"),
        # VOZONDA-LEN-1
        "target_minutes": row.get("target_minutes"),
        # Podcast show identity (#232)
        "show_name": row.get("show_name") or "",
        "focus": row.get("focus") or "",
        "review_script": bool(row.get("review_script")),
        "script_approved": bool(row.get("script_approved")),
        "combine": bool(row.get("combine")),
        "show_author": row.get("show_author") or "",
        "show_category": row.get("show_category") or "",
        "local_only": bool(row.get("local_only", 0)),
        # Insights - Hallucination-Guard (DUE-077 / #262)
        "executive_summary": row.get("executive_summary") or "" if "executive_summary" in row.keys() else "",  # noqa: SIM118
        "executive_quote": row.get("executive_quote") or "" if "executive_quote" in row.keys() else "",  # noqa: SIM118
        "key_takeaways": kt,
        "factuality_score": row.get("factuality_score") if "factuality_score" in row.keys() else None,  # noqa: SIM118
        "callback_url": row.get("callback_url") if "callback_url" in row.keys() else None,  # noqa: SIM118
        "show_slug": row.get("show_slug") or "",
        "public_base": row.get("public_base"),
        "audio_url": f"/audio/{row['id']}.mp3" if row.get("state") == "done" else None,
    }


STAGES = ["fetch", "discover", "triage", "sub-fetch", "extract", "script", "voice", "master"]

DEFAULT_ESTIMATED_DURATION_MS = 90_000


def _avg_duration_ms(conn: sqlite3.Connection) -> int:
    try:
        rows = conn.execute(
            "SELECT duration_ms FROM jobs WHERE state='done' AND duration_ms IS NOT NULL ORDER BY finished_at DESC LIMIT 10"
        ).fetchall()
        vals = [int(r[0]) for r in rows if r[0] and int(r[0]) > 0]
        if vals:
            return sum(vals) // len(vals)
    except Exception:
        logger.debug("average duration lookup failed, using default", exc_info=True)
    return DEFAULT_ESTIMATED_DURATION_MS


def _queue_snapshot(conn: sqlite3.Connection, job_id: str, job_state: str) -> dict[str, Any]:
    if job_state not in ("queued", "running"):
        return {"queue_position": None, "queue_length": 0, "estimated_wait_ms": None, "estimated_wait_seconds": None, "ahead_title": None, "ahead_count": 0}
    if job_state == "running":
        try:
            cur = conn.execute("SELECT COUNT(*) FROM jobs WHERE state='queued'")
            qlen = int(cur.fetchone()[0])
        except Exception:
            qlen = 0
        return {"queue_position": 0, "queue_length": qlen, "estimated_wait_ms": 0, "estimated_wait_seconds": 0, "ahead_title": None, "ahead_count": 0}
    # queued: ordered by created_at
    try:
        rows = conn.execute(
            "SELECT id FROM jobs WHERE state='queued' ORDER BY created_at ASC"
        ).fetchall()
        ids = [r[0] for r in rows]
        qlen = len(ids)
        try:
            pos = ids.index(job_id) + 1
        except ValueError:
            pos = None
        if pos is None:
            return {"queue_position": None, "queue_length": qlen, "estimated_wait_ms": None, "estimated_wait_seconds": None, "ahead_title": None, "ahead_count": 0}
        avg = _avg_duration_ms(conn)
        est = avg * pos

        # Find the job currently running (state='running')
        ahead_title = None
        ahead_count = max(0, pos - 1)
        try:
            run_row = conn.execute(
                "SELECT title, url, user_id FROM jobs WHERE state='running' ORDER BY started_at ASC LIMIT 1"
            ).fetchone()
            if run_row:
                # In billing mode, hide other users' titles
                billing_enabled = env("ENABLE_BILLING", "false").lower() == "true"
                if billing_enabled:
                    # Get the queued job's user_id
                    q_row = conn.execute("SELECT user_id FROM jobs WHERE id = ?", (job_id,)).fetchone()
                    queued_user_id = q_row["user_id"] if q_row else None
                    run_user_id = run_row["user_id"]
                    if queued_user_id != run_user_id:
                        ahead_title = None
                    else:
                        ahead_title = run_row["title"] or run_row["url"] or "another episode"
                else:
                    ahead_title = run_row["title"] or run_row["url"] or "another episode"
        except Exception:
            logger.debug("queue ahead-title lookup failed for job %s", job_id, exc_info=True)

        return {
            "queue_position": pos,
            "queue_length": qlen,
            "estimated_wait_ms": est,
            "estimated_wait_seconds": est // 1000,
            "ahead_title": ahead_title,
            "ahead_count": ahead_count,
        }
    except Exception:
        return {"queue_position": None, "queue_length": 0, "estimated_wait_ms": None, "estimated_wait_seconds": None, "ahead_title": None, "ahead_count": 0}


def fresh_stages() -> list[dict[str, Any]]:
    return [{"name": s, "status": "pending"} for s in STAGES]


def human_error(raw: str) -> str:
    """Reduce a traceback-ish failure blob to one plain sentence."""
    clean = re.sub(r"<[^>]+>", "", raw or "").strip()
    if not clean:
        return "a pipeline stage failed"
    if "\n" not in clean and len(clean) <= 200:
        return clean
    lines = [ln.strip() for ln in clean.splitlines() if ln.strip()]
    for ln in reversed(lines):
        if re.search(r"(?:Error|Exception|failed)\b", ln) and not ln.startswith(("File", 'File "')):
            return ln[:200]
    return (lines[-1] if lines else "a pipeline stage failed")[:200]


class JobStore:
    def __init__(self) -> None:
        init_db()

    def create(
        self,
        job_id: str,
        url: str,
        style: str = "default",
        fmt: str = "dialog",
        tone: str = "neutral",
        language: str = "auto",
        watchlist_id: str | None = None,
        hosts: int = 2,
        explicit: bool = False,
        voice: dict[str, Any] | None = None,
        digest: bool = False,
        digest_sources: list[str] | None = None,
        research_mode: bool = False,
        research_sources: list[str] | None = None,
        user_id: str | None = None,
        access_token_id: str | None = None,
        provider: str = "qwen",
        show_name: str | None = None,
        show_author: str | None = None,
        show_category: str | None = None,
        show_slug: str | None = None,
        target_minutes: float | None = None,
        focus: str | None = None,
        review_script: bool = False,
        combine: bool = False,
        callback_url: str | None = None,
        public_base: str | None = None,
        local_only: bool = False,
    ) -> dict[str, Any]:
        now = time.time()
        with _conn() as c:
            c.execute(
                "INSERT INTO jobs (id, url, style, format, tone, language, watchlist_id, hosts, explicit, voice_profile, digest, digest_sources, research_mode, research_sources, state, stages, created_at, updated_at, user_id, access_token_id, provider, show_name, show_author, show_category, show_slug, target_minutes, focus, review_script, combine, callback_url, public_base, local_only) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (job_id, url, style, fmt, tone, language, watchlist_id, int(hosts), int(bool(explicit)), json.dumps(voice) if voice else None, int(bool(digest)), json.dumps(digest_sources) if digest_sources else None, int(bool(research_mode)), json.dumps(research_sources) if research_sources else None, json.dumps(fresh_stages()), now, now, user_id, access_token_id, provider, (show_name or "")[:80], (show_author or "")[:80], (show_category or "")[:60], (show_slug or "")[:80], target_minutes, (focus or "").strip()[:FOCUS_MAX], int(bool(review_script)), int(bool(combine)), callback_url.strip() if callback_url else None, (public_base or "").rstrip("/") if public_base else None, int(bool(local_only))),
            )
        return self.get(job_id)

    def get(self, job_id: str) -> dict[str, Any]:
        with _conn() as c:
            row = c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            job = _row_to_job(row)
            qs = _queue_snapshot(c, job_id, str(job.get("state", "")))
            job.update(qs)
            return job

    def queue_info(self, job_id: str) -> dict[str, Any]:
        """Public helper for queue position without full job fetch overhead."""
        with _conn() as c:
            row = c.execute("SELECT state FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            return _queue_snapshot(c, job_id, str(row[0]))

    def update(
        self,
        job_id: str,
        *,
        state: str | None = None,
        stage: str | None = None,
        status: str | None = None,
        detail: str | None = None,
        title: str | None = None,
        script: list[dict[str, Any]] | None = None,
        error: str | None = None,
        started_at: float | None = None,
        finished_at: float | None = None,
        duration_ms: int | None = None,
        description: str | None = None,
        chapters: list[dict[str, Any]] | None = None,
        research_sources: list[str] | None = None,
        executive_summary: str | None = None,
        executive_quote: str | None = None,
        key_takeaways: list[dict[str, Any]] | None = None,
        factuality_score: float | None = None,
        script_approved: bool | None = None,
        callback_url: str | None = None,
        og_image: str | None = None,
        audio_seconds: float | None = None,
    ) -> dict[str, Any]:
        job = self.get(job_id)
        if stage and status:
            for s in job["stages"]:
                if s["name"] == stage:
                    s["status"] = status
                    if status == "running":
                        s["_t0"] = time.time()
                    elif status == "done":
                        t0 = s.pop("_t0", None)
                        if t0:
                            s["ms"] = int((time.time() - t0) * 1000)
                    elif status == "failed":
                        s.pop("_t0", None)
                        if detail:
                            s["detail"] = detail
        sets = ["updated_at = ?"]
        args: list[Any] = [time.time()]
        if state is not None:
            sets.append("state = ?")
            args.append(state)
        if stage:
            sets.append("current_stage = ?")
            args.append(stage)
        if title is not None:
            sets.append("title = ?")
            args.append(title)
        if script is not None:
            sets.append("script = ?")
            args.append(json.dumps(script))
        if script_approved is not None:
            sets.append("script_approved = ?")
            args.append(int(script_approved))
        if description is not None:
            sets.append("description = ?")
            args.append(description)
        if audio_seconds is not None:
            sets.append("audio_seconds = ?")
            args.append(audio_seconds)
        if og_image is not None:
            # since 2026-08-25 five callers passed og_image and every call raised a TypeError
            # (logged only): no episode ever stored its cover (coordinator, 2026-10-02)
            sets.append("og_image = ?")
            args.append(og_image)
        if error is not None:
            sets.append("error = ?")
            args.append(error)
        if started_at is not None:
            sets.append("started_at = ?")
            args.append(started_at)
        if finished_at is not None:
            sets.append("finished_at = ?")
            args.append(finished_at)
        if duration_ms is not None:
            sets.append("duration_ms = ?")
            args.append(duration_ms)
        if chapters is not None:
            sets.append("chapters = ?")
            args.append(json.dumps(chapters))
        if research_sources is not None:
            sets.append("research_sources = ?")
            args.append(json.dumps(research_sources))
        if executive_summary is not None:
            sets.append("executive_summary = ?")
            args.append(executive_summary)
        if executive_quote is not None:
            sets.append("executive_quote = ?")
            args.append(executive_quote)
        if key_takeaways is not None:
            sets.append("key_takeaways = ?")
            args.append(json.dumps(key_takeaways))
        if factuality_score is not None:
            sets.append("factuality_score = ?")
            args.append(float(factuality_score))
        if callback_url is not None:
            sets.append("callback_url = ?")
            args.append(callback_url.strip() if callback_url else None)
        sets.append("stages = ?")
        args.append(json.dumps(job["stages"]))
        args.append(job_id)
        with _conn() as c:
            c.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id = ?", args)
        updated = self.get(job_id)
        if state in ("done", "failed"):
            self._schedule_webhook_delivery(updated)
        return updated

    def set_stage_running(self, job_id: str, stage: str, detail: str = "") -> dict[str, Any]:
        job = self.get(job_id)
        extra: dict[str, Any] = {}
        if job.get("started_at") is None:
            extra["started_at"] = time.time()
        return self.update(
            job_id, state="running", stage=stage, status="running", detail=detail, **extra
        )

    def set_stage_done(self, job_id: str, stage: str) -> dict[str, Any]:
        return self.update(job_id, stage=stage, status="done")

    def fail(self, job_id: str, stage: str, error: str) -> dict[str, Any]:
        clean = human_error(error)
        job = self.get(job_id)
        finished: dict[str, Any] = {}
        if job.get("finished_at") is None:
            now = time.time()
            finished["finished_at"] = now
            if job.get("started_at") is not None:
                finished["duration_ms"] = int((now - job["started_at"]) * 1000)
        
        # Refund if billing was charged (DUE-067)
        if job.get("charge_id") and env("ENABLE_BILLING", "false").lower() == "true":
            try:
                from .billing import refund_charge
                refund_charge(job_id)
                print(f"Billing: refunded job {job_id} after failure in stage {stage}")
            except Exception as e:
                print(f"Billing: refund failed for job {job_id}: {e}")
        
        return self.update(
            job_id,
            state="failed",
            stage=stage,
            status="failed",
            detail=clean,
            error=clean,
            **finished,
        )

    def add_stage_meta(self, job_id: str, stage: str, **meta: Any) -> dict[str, Any]:
        """Attach extra data (e.g. script lint) to a stage without touching status."""
        now = time.time()
        with _conn() as c:
            row = c.execute("SELECT stages FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            stages = json.loads(row["stages"])
            for s in stages:
                if s["name"] == stage:
                    s.setdefault("meta", {}).update(meta)
            c.execute(
                "UPDATE jobs SET stages = ?, updated_at = ? WHERE id = ?",
                (json.dumps(stages), now, job_id),
            )
        return self.get(job_id)

    def delete(self, job_id: str) -> None:
        """Remove a job row entirely (cancel first if still pending)."""
        with _conn() as c:
            cur = c.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            if cur.rowcount == 0:
                raise KeyError(job_id)

    def finish(self, job_id: str) -> dict[str, Any]:
        job = self.get(job_id)
        now = time.time()
        started = job.get("started_at")
        
        # Confirm charge on successful completion (DUE-067)
        if job.get("charge_id") and env("ENABLE_BILLING", "false").lower() == "true":
            try:
                from .billing import confirm_charge
                confirm_charge(job_id)
                print(f"Billing: confirmed charge for completed job {job_id}")
            except Exception as e:
                print(f"Billing: charge confirmation failed for job {job_id}: {e}")
        
        return self.update(
            job_id,
            state="done",
            finished_at=now,
            duration_ms=int((now - started) * 1000) if started is not None else None,
        )

    def fail_interrupted(self, error: str = "interrupted") -> list[dict[str, Any]]:
        with _conn() as c:
            rows = c.execute(
                "SELECT id, current_stage FROM jobs WHERE state IN ('queued','running')"
            ).fetchall()
        out = []
        for row in rows:
            if row["current_stage"]:
                out.append(self.fail(row["id"], row["current_stage"], error))
            else:
                out.append(self.update(row["id"], state="failed", error=error))
        return out

    def _schedule_webhook_delivery(self, job: dict[str, Any]) -> None:
        """Schedule background webhook delivery if callback_url is set and not yet fired."""
        callback_url = job.get("callback_url")
        if not callback_url:
            return
        job_id = job.get("id")
        if not job_id:
            return
        state = job.get("state")
        if state not in ("done", "failed"):
            return
        with _conn() as c:
            cur = c.execute(
                "UPDATE jobs SET webhook_fired = 1 WHERE id = ? AND (webhook_fired IS NULL OR webhook_fired = 0)",
                (job_id,),
            )
            if cur.rowcount == 0:
                return

        try:
            loop = asyncio.get_running_loop()
            from .webhooks import deliver

            loop.create_task(deliver(job))
        except RuntimeError:
            pass

    def get_idempotent_job(self, key: str) -> dict[str, Any] | None:
        """Return the existing job if key was registered within 24 hours.

        Different request bodies with the same key within 24 hours return the existing
        job to prevent duplicate rendering and billing.
        """
        now = time.time()
        with _conn() as c:
            row = c.execute(
                "SELECT job_id, created_at FROM idempotency_keys WHERE key = ?",
                (key,),
            ).fetchone()
            if row:
                job_id = row["job_id"]
                created_at = float(row["created_at"])
                if (now - created_at) < 86400:  # 24 hours
                    try:
                        return self.get(job_id)
                    except KeyError:
                        return None
        return None

    def set_idempotent_key(self, key: str, job_id: str) -> None:
        """Associate an idempotency key with a job id."""
        now = time.time()
        with _conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO idempotency_keys (key, job_id, created_at) VALUES (?, ?, ?)",
                (key, job_id, now),
            )

