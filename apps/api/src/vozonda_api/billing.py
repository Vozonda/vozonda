"""Billing and access token gate for pay-per-job model.

Manages user accounts, access tokens, balances, and job charges.
"""

import hashlib
import json
import logging
import secrets
import sqlite3
import time
from typing import Any

from .env import env
from .envfile import load_env_file
from .jobs import DB_PATH

logger = logging.getLogger(__name__)

load_env_file()


def _add_column(c: sqlite3.Connection, table: str, column_ddl: str) -> None:
    """ALTER TABLE ADD COLUMN that skips existing columns.

    Only a duplicate-column OperationalError is swallowed; any other
    error is logged and re-raised so a broken schema fails at startup.
    """
    try:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column_ddl}")
    except sqlite3.OperationalError as exc:
        if "duplicate column" in str(exc).lower():
            return
        logger.exception("billing migration failed adding %s to %s", column_ddl, table)
        raise

VOZONDA_TIER_THRESHOLD = int(env("TIER_THRESHOLD", "1000"))

# Cost matrix: provider -> job type -> cost in satoshis
DEFAULT_COSTS = {
    "qwen": {"standard": 1000, "digest": 2000, "research": 3000},
    "nemo": {"standard": 1500, "digest": 2500, "research": 3500},
    "voxtral": {"standard": 800, "digest": 1500, "research": 2500},
    "piper": {"standard": 500, "digest": 1000, "research": 1500},
}

BILLING_SCHEMA = """
CREATE TABLE IF NOT EXISTS access_tokens (
  id TEXT PRIMARY KEY,
  token_hash TEXT NOT NULL UNIQUE,
  user_id TEXT NOT NULL,
  created_at REAL NOT NULL,
  last_used REAL,
  active INTEGER NOT NULL DEFAULT 1,
  name TEXT,
  metadata TEXT
);

  CREATE TABLE IF NOT EXISTS user_accounts (
    user_id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    balance_sats INTEGER NOT NULL DEFAULT 0,
    tier TEXT NOT NULL DEFAULT 'free',
    metadata TEXT
  );

CREATE TABLE IF NOT EXISTS job_charges (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  job_type TEXT NOT NULL,
  amount_sats INTEGER NOT NULL,
  charged_at REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  notes TEXT,
  UNIQUE(job_id)
);

CREATE INDEX IF NOT EXISTS idx_access_tokens_user_id ON access_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_access_tokens_token_hash ON access_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_access_tokens_active ON access_tokens(active);
CREATE INDEX IF NOT EXISTS idx_job_charges_user_id ON job_charges(user_id);
CREATE INDEX IF NOT EXISTS idx_job_charges_job_id ON job_charges(job_id);
CREATE INDEX IF NOT EXISTS idx_job_charges_status ON job_charges(status);
"""


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_billing_db() -> None:
    """Initialize billing tables and indexes."""
    with _conn() as c:
        c.executescript(BILLING_SCHEMA)
        # migrate tier column if missing (#DUE-watchlist-paid)
        _add_column(c, "user_accounts", "tier TEXT NOT NULL DEFAULT 'free'")


def hash_token(token: str) -> str:
    """Hash access token for storage (never store plaintext)."""
    return hashlib.sha256(token.encode()).hexdigest()


def generate_token() -> str:
    """Generate a secure random access token."""
    return secrets.token_urlsafe(32)


class TokenValidationError(Exception):
    """Raised when token validation fails."""



class InsufficientBalanceError(Exception):
    """Raised when user balance is insufficient."""



def create_user(user_id: str, initial_balance_sats: int = 0, tier: str = "free") -> dict[str, Any]:
    """Create a new user account with initial balance and tier."""
    now = time.time()
    with _conn() as c:
        try:
            c.execute(
                "INSERT INTO user_accounts (user_id, created_at, updated_at, balance_sats, tier) VALUES (?, ?, ?, ?, ?)",
                (user_id, now, now, initial_balance_sats, tier),
            )
        except sqlite3.IntegrityError:
            raise ValueError(f"User {user_id} already exists")
        return {
            "user_id": user_id,
            "created_at": now,
            "updated_at": now,
            "balance_sats": initial_balance_sats,
            "tier": tier,
        }


def get_user_balance(user_id: str) -> int | None:
    """Get user's current balance in satoshis. Returns None if user doesn't exist."""
    with _conn() as c:
        row = c.execute("SELECT balance_sats FROM user_accounts WHERE user_id = ?", (user_id,)).fetchone()
        return int(row[0]) if row else None


def get_user_tier(user_id: str) -> str | None:
    """Get user's tier ('free' or 'hosted'). Returns None if user doesn't exist."""
    with _conn() as c:
        row = c.execute("SELECT tier FROM user_accounts WHERE user_id = ?", (user_id,)).fetchone()
        return row["tier"] if row else None


def set_user_tier(user_id: str, tier: str) -> bool:
    """Set user's tier ('free' or 'hosted'). Returns True on success."""
    now = time.time()
    with _conn() as c:
        c.execute(
            "UPDATE user_accounts SET tier = ?, updated_at = ? WHERE user_id = ?",
            (tier, now, user_id),
        )
        return c.total_changes > 0


def add_user_balance(user_id: str, amount_sats: int) -> int:
    """Add satoshis to user balance. Returns new balance."""
    now = time.time()
    with _conn() as c:
        c.execute(
            "UPDATE user_accounts SET balance_sats = balance_sats + ?, updated_at = ? WHERE user_id = ?",
            (amount_sats, now, user_id),
        )
        if c.total_changes == 0:
            raise ValueError(f"User {user_id} not found")
        row = c.execute("SELECT balance_sats FROM user_accounts WHERE user_id = ?", (user_id,)).fetchone()
        return int(row[0])


def create_access_token(
    user_id: str, name: str | None = None, metadata: dict | None = None
) -> tuple[str, dict[str, Any]]:
    """Create and return a new access token.

    Returns (plaintext_token, token_record).
    Token is only returned once - store it immediately.
    """
    token = generate_token()
    token_hash = hash_token(token)
    now = time.time()
    token_id = secrets.token_hex(8)

    with _conn() as c:
        c.execute(
            """INSERT INTO access_tokens
               (id, token_hash, user_id, created_at, name, metadata, active)
               VALUES (?, ?, ?, ?, ?, ?, 1)""",
            (
                token_id,
                token_hash,
                user_id,
                now,
                name,
                json.dumps(metadata) if metadata else None,
            ),
        )

    return token, {
        "id": token_id,
        "user_id": user_id,
        "name": name,
        "created_at": now,
    }


def validate_token(token: str) -> dict[str, Any]:
    """Validate access token and return token record.

    Raises TokenValidationError if invalid or inactive.
    Updates last_used timestamp.
    """
    token_hash = hash_token(token)
    now = time.time()

    with _conn() as c:
        row = c.execute(
            "SELECT id, user_id, created_at, name, active FROM access_tokens WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()

        if not row:
            raise TokenValidationError("invalid token")

        if not row["active"]:
            raise TokenValidationError("token is inactive")

        # Update last_used
        c.execute("UPDATE access_tokens SET last_used = ? WHERE id = ?", (now, row["id"]))

        return {
            "token_id": row["id"],
            "user_id": row["user_id"],
            "name": row["name"],
            "created_at": row["created_at"],
        }


def get_cost(provider: str, job_type: str) -> int:
    """Get cost for a job in satoshis."""
    costs = json.loads(env("COSTS", json.dumps(DEFAULT_COSTS)))
    return costs.get(provider, {}).get(job_type, DEFAULT_COSTS.get(provider, {}).get(job_type, 1000))


def charge_job(job_id: str, user_id: str, provider: str, job_type: str) -> dict[str, Any]:
    """Charge user for a job.

    Raises InsufficientBalanceError if balance is insufficient.
    Raises ValueError if user does not exist.
    Returns charge record.
    """
    amount = get_cost(provider, job_type)

    with _conn() as c:
        # Verify user exists and has sufficient balance
        balance_row = c.execute("SELECT balance_sats FROM user_accounts WHERE user_id = ?", (user_id,)).fetchone()
        if not balance_row:
            raise ValueError(f"User {user_id} not found")

        balance = int(balance_row[0])
        if balance < amount:
            raise InsufficientBalanceError(
                f"insufficient balance: {balance} sats < {amount} sats required"
            )

        # Create charge record
        now = time.time()
        charge_id = secrets.token_hex(8)
        try:
            c.execute(
                """INSERT INTO job_charges
                   (id, job_id, user_id, provider, job_type, amount_sats, charged_at, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')""",
                (charge_id, job_id, user_id, provider, job_type, amount, now),
            )

            # Deduct from balance
            c.execute(
                "UPDATE user_accounts SET balance_sats = balance_sats - ?, updated_at = ? WHERE user_id = ?",
                (amount, now, user_id),
            )
        except sqlite3.IntegrityError as e:
            # Handle potential race conditions or duplicate job_ids
            raise ValueError(f"Failed to charge job {job_id}: {e}")

        return {
            "charge_id": charge_id,
            "job_id": job_id,
            "user_id": user_id,
            "provider": provider,
            "job_type": job_type,
            "amount_sats": amount,
            "charged_at": now,
            "status": "pending",
        }


def confirm_charge(job_id: str) -> None:
    """Mark charge as confirmed (job completed successfully)."""
    now = time.time()
    with _conn() as c:
        c.execute(
            "UPDATE job_charges SET status = 'confirmed', charged_at = ? WHERE job_id = ? AND status = 'pending'",
            (now, job_id),
        )


def refund_charge(job_id: str) -> int | None:
    """Refund a charge (job failed). Returns refunded amount or None if not found."""
    with _conn() as c:
        row = c.execute("SELECT user_id, amount_sats FROM job_charges WHERE job_id = ?", (job_id,)).fetchone()

        if not row:
            return None

        user_id = row["user_id"]
        amount = int(row["amount_sats"])

        # Mark charge as refunded
        c.execute(
            "UPDATE job_charges SET status = 'refunded' WHERE job_id = ?",
            (job_id,),
        )

        # Restore balance
        now = time.time()
        c.execute(
            "UPDATE user_accounts SET balance_sats = balance_sats + ?, updated_at = ? WHERE user_id = ?",
            (amount, now, user_id),
        )

        return amount


def list_user_charges(user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """List recent charges for a user."""
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM job_charges WHERE user_id = ? ORDER BY charged_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]


def revoke_token(token_id: str) -> None:
    """Deactivate an access token."""
    with _conn() as c:
        c.execute("UPDATE access_tokens SET active = 0 WHERE id = ?", (token_id,))


def list_user_tokens(user_id: str) -> list[dict[str, Any]]:
    """List active access tokens for a user."""
    with _conn() as c:
        rows = c.execute(
            "SELECT id, name, created_at, last_used FROM access_tokens WHERE user_id = ? AND active = 1",
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def user_has_watchlist_access(user_id: str) -> bool:
    """Check if user has 'hosted' tier for watchlist access.
    
    Watchlist is a paid feature in the Hosted tier.
    Returns True if user tier is 'hosted', False otherwise.
    """
    tier = get_user_tier(user_id)
    return tier == "hosted"
