"""Tests for billing and access token gate system (DUE-067)."""

import json
import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def billing_db():
    """Temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        os.environ["VOZONDA_DB"] = str(db_path)
        yield db_path


def test_token_generation():
    """Test access token generation."""
    from vozonda_api.billing import generate_token, hash_token

    token = generate_token()
    assert len(token) > 32
    assert isinstance(token, str)

    token_hash = hash_token(token)
    assert len(token_hash) == 64  # SHA256 hex
    assert token_hash != token  # Hash should differ from token


def test_create_user(billing_db):
    """Test user account creation."""
    from vozonda_api.billing import create_user, get_user_balance, init_billing_db

    init_billing_db()

    user = create_user("test-user-1", initial_balance_sats=5000)
    assert user["user_id"] == "test-user-1"
    assert user["balance_sats"] == 5000

    balance = get_user_balance("test-user-1")
    assert balance == 5000


def test_create_duplicate_user(billing_db):
    """Test that duplicate user creation fails."""
    from vozonda_api.billing import create_user, init_billing_db

    init_billing_db()
    create_user("test-user-2")

    with pytest.raises(ValueError, match="already exists"):
        create_user("test-user-2")


def test_add_balance(billing_db):
    """Test adding balance to user."""
    from vozonda_api.billing import add_user_balance, create_user, get_user_balance, init_billing_db

    init_billing_db()
    create_user("test-user-3", initial_balance_sats=1000)

    new_balance = add_user_balance("test-user-3", 500)
    assert new_balance == 1500
    assert get_user_balance("test-user-3") == 1500


def test_create_access_token(billing_db):
    """Test access token creation."""
    from vozonda_api.billing import create_access_token, create_user, init_billing_db

    init_billing_db()
    create_user("test-user-4")

    token, info = create_access_token("test-user-4", name="my-token")
    assert len(token) > 32
    assert info["user_id"] == "test-user-4"
    assert info["name"] == "my-token"


def test_validate_token(billing_db):
    """Test token validation."""
    from vozonda_api.billing import (
        TokenValidationError,
        create_access_token,
        create_user,
        init_billing_db,
        validate_token,
    )

    init_billing_db()
    create_user("test-user-5")
    token, _ = create_access_token("test-user-5")

    info = validate_token(token)
    assert info["user_id"] == "test-user-5"

    # Invalid token
    with pytest.raises(TokenValidationError):
        validate_token("invalid-token")


def test_revoke_token(billing_db):
    """Test token revocation."""
    from vozonda_api.billing import (
        TokenValidationError,
        create_access_token,
        create_user,
        init_billing_db,
        revoke_token,
        validate_token,
    )

    init_billing_db()
    create_user("test-user-6")
    token, info = create_access_token("test-user-6")

    # Should work before revoke
    validate_token(token)

    # Revoke token
    revoke_token(info["id"])

    # Should fail after revoke
    with pytest.raises(TokenValidationError, match="inactive"):
        validate_token(token)


def test_charge_job(billing_db):
    """Test job charging."""
    from vozonda_api.billing import charge_job, create_user, get_user_balance, init_billing_db

    init_billing_db()
    create_user("test-user-7", initial_balance_sats=5000)

    charge = charge_job("job-1", "test-user-7", "qwen", "standard")
    assert charge["amount_sats"] == 1000  # Default Qwen standard cost
    assert charge["status"] == "pending"

    # Balance should be reduced
    balance = get_user_balance("test-user-7")
    assert balance == 4000


def test_insufficient_balance(billing_db):
    """Test charging when balance is insufficient."""
    from vozonda_api.billing import InsufficientBalanceError, charge_job, create_user, init_billing_db

    init_billing_db()
    create_user("test-user-8", initial_balance_sats=500)

    with pytest.raises(InsufficientBalanceError):
        charge_job("job-2", "test-user-8", "qwen", "standard")


def test_confirm_charge(billing_db):
    """Test charge confirmation."""
    from vozonda_api.billing import (
        charge_job,
        confirm_charge,
        create_user,
        init_billing_db,
    )

    init_billing_db()
    create_user("test-user-9", initial_balance_sats=5000)

    charge = charge_job("job-3", "test-user-9", "qwen", "standard")
    assert charge["status"] == "pending"

    confirm_charge("job-3")

    # Status should be updated (would need to query DB to verify)


def test_refund_charge(billing_db):
    """Test charge refund."""
    from vozonda_api.billing import (
        charge_job,
        create_user,
        get_user_balance,
        init_billing_db,
        refund_charge,
    )

    init_billing_db()
    create_user("test-user-10", initial_balance_sats=5000)

    charge_job("job-4", "test-user-10", "qwen", "standard")
    assert get_user_balance("test-user-10") == 4000

    amount = refund_charge("job-4")
    assert amount == 1000
    assert get_user_balance("test-user-10") == 5000


def test_cost_matrix(billing_db, monkeypatch):
    """Test cost calculation."""
    from vozonda_api.billing import get_cost, init_billing_db

    init_billing_db()

    # Default costs
    assert get_cost("qwen", "standard") == 1000
    assert get_cost("qwen", "digest") == 2000
    assert get_cost("nemo", "standard") == 1500

    # Custom costs via environment
    custom_costs = {"qwen": {"standard": 500, "digest": 1000}, "nemo": {"standard": 1000}}
    monkeypatch.setenv("VOZONDA_COSTS", json.dumps(custom_costs))

    # Note: get_cost reads from env each time, so custom should work
    assert get_cost("qwen", "standard") == 500


def test_list_charges(billing_db):
    """Test listing user charges."""
    from vozonda_api.billing import (
        charge_job,
        create_user,
        init_billing_db,
        list_user_charges,
    )

    init_billing_db()
    create_user("test-user-11", initial_balance_sats=10000)

    charge_job("job-5", "test-user-11", "qwen", "standard")
    charge_job("job-6", "test-user-11", "nemo", "digest")

    charges = list_user_charges("test-user-11")
    assert len(charges) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
