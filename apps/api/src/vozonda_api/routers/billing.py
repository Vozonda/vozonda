import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel

from ..env import env

router = APIRouter()
logger = logging.getLogger(__name__)


async def _require_write_auth(authorization: str | None = Header(None)) -> None:
    from ..main import require_write_auth

    await require_write_auth(authorization)


async def _require_read_access(
    user_id: str,
    request: Request | None = None,
    authorization: str | None = None,
) -> None:
    """Allow read access if operator write auth passes OR bearer token belongs to user_id.

    Reuses require_write_auth for the operator check (same logic, no duplication).
    Falls back to validating a Bearer / query-token and comparing the token's
    user_id to the path parameter.

    When no auth is provided at all (no header, no query token), return 401.
    When a valid token belongs to another user, return 403.
    """
    try:
        from ..main import _validate_access_token, require_write_auth
    except ImportError:
        raise HTTPException(503, "auth subsystem unavailable")

    # Try operator write auth first
    try:
        await require_write_auth(authorization)
        return
    except HTTPException:
        # Operator auth failed — fall back to access token
        pass

    # Check for access token (Bearer or query param)
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    if request and not token:
        token = request.query_params.get("token")
    if not token:
        # No auth provided at all — require authentication
        raise HTTPException(401, "missing or invalid token")

    # Validate the access token
    try:
        token_info = _validate_access_token(token, request)
    except HTTPException:
        # Invalid access token
        raise HTTPException(401, "missing or invalid token")

    if not token_info or token_info.get("user_id") != user_id:
        raise HTTPException(403, "forbidden")


class CreateTokenIn(BaseModel):
    user_id: str
    name: str | None = None


@router.post("/billing/tokens", dependencies=[Depends(_require_write_auth)])
async def create_token(body: CreateTokenIn) -> dict:
    """Create a new access token for a user."""
    if not env("ENABLE_BILLING", "false").lower() == "true":
        raise HTTPException(503, "billing disabled")
    try:
        from ..billing import create_access_token, create_user, get_user_balance

        balance = get_user_balance(body.user_id)
        if balance is None:
            create_user(body.user_id)
        token, info = create_access_token(body.user_id, name=body.name)
        return {"token": token, **info}
    except HTTPException:
        raise
    except Exception:
        logger.exception("token creation failed for user %s", body.user_id)
        raise HTTPException(500, "token creation failed")


@router.get("/billing/tokens/{user_id}")
async def list_tokens(
    user_id: str,
    request: Request = None,
    authorization: str | None = Header(None),
) -> dict:
    """List active access tokens for a user."""
    if not env("ENABLE_BILLING", "false").lower() == "true":
        raise HTTPException(503, "billing disabled")
    await _require_read_access(user_id, request, authorization)
    try:
        from ..billing import list_user_tokens

        tokens = list_user_tokens(user_id)
        return {"tokens": tokens}
    except HTTPException:
        raise
    except Exception:
        logger.exception("failed to list tokens for user %s", user_id)
        raise HTTPException(500, "failed to list tokens")


@router.post("/billing/tokens/{token_id}/revoke", dependencies=[Depends(_require_write_auth)])
async def revoke_token(token_id: str) -> dict:
    """Revoke an access token."""
    if not env("ENABLE_BILLING", "false").lower() == "true":
        raise HTTPException(503, "billing disabled")
    try:
        from ..billing import revoke_token

        revoke_token(token_id)
        return {"revoked": token_id}
    except HTTPException:
        raise
    except Exception:
        logger.exception("token revocation failed for token %s", token_id)
        raise HTTPException(500, "token revocation failed")


@router.get("/billing/balance/{user_id}")
async def get_balance(
    user_id: str,
    request: Request = None,
    authorization: str | None = Header(None),
) -> dict:
    """Get user's current balance in satoshis."""
    if not env("ENABLE_BILLING", "false").lower() == "true":
        raise HTTPException(503, "billing disabled")
    await _require_read_access(user_id, request, authorization)
    try:
        from ..billing import get_user_balance

        balance = get_user_balance(user_id)
        if balance is None:
            raise HTTPException(404, "user not found")
        return {"user_id": user_id, "balance_sats": balance}
    except HTTPException:
        raise
    except Exception:
        logger.exception("failed to get balance for user %s", user_id)
        raise HTTPException(500, "failed to get balance")


class AddBalanceIn(BaseModel):
    amount_sats: int


@router.post("/billing/balance/{user_id}", dependencies=[Depends(_require_write_auth)])
async def add_balance(user_id: str, body: AddBalanceIn) -> dict:
    """Add satoshis to a user's balance (top-up)."""
    if not env("ENABLE_BILLING", "false").lower() == "true":
        raise HTTPException(503, "billing disabled")
    if body.amount_sats <= 0:
        raise HTTPException(422, "amount must be positive")
    try:
        from ..billing import add_user_balance, create_user, get_user_balance

        if get_user_balance(user_id) is None:
            create_user(user_id, initial_balance_sats=body.amount_sats)
            return {"user_id": user_id, "balance_sats": body.amount_sats}
        new_balance = add_user_balance(user_id, body.amount_sats)
        return {"user_id": user_id, "balance_sats": new_balance}
    except HTTPException:
        raise
    except Exception:
        logger.exception("failed to add balance for user %s", user_id)
        raise HTTPException(500, "failed to add balance")


@router.get("/billing/charges/{user_id}")
async def list_charges(
    user_id: str,
    request: Request = None,
    authorization: str | None = Header(None),
    limit: int = Query(default=50),
) -> dict:
    """List recent job charges for a user."""
    if not env("ENABLE_BILLING", "false").lower() == "true":
        raise HTTPException(503, "billing disabled")
    await _require_read_access(user_id, request, authorization)
    try:
        from ..billing import list_user_charges

        charges = list_user_charges(user_id, limit=min(limit, 100))
        return {"user_id": user_id, "charges": charges}
    except HTTPException:
        raise
    except Exception:
        logger.exception("failed to list charges for user %s", user_id)
        raise HTTPException(500, "failed to list charges")